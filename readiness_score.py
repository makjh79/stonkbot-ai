"""
STONK.AI Readiness Score Engine

Composite 0-100 readiness score per stock that drives tier assignment
AND entry decisions.  This is the new "brain" of the watchlist.

Factors (weighted) — 10 factors, sum normalised to 100%:
  - Signal engine total_score (momentum+quality+risk+regime): 20%
  - RSI proximity to sweet spot (50-65 = 100): 10%
  - Volume confirmation (recent 5d vs 20d avg; directional): 5%
  - MACD histogram turning positive: 8%
  - Distance to 20d EMA (price above EMA = trend confirm): 12%
  - Sector relative strength: 30% (best non-price predictor)
  - Intraday momentum: 10%
  - Options IV sentiment: 5%
  - Relative volume confirmation: boolean chip only (weight 0% to avoid double-counting volume)
  - VWAP deviation momentum signal: 5%

Tiers:
  STRONG_NOW readiness >= 78
  NOW      readiness >= 72
  WATCH    readiness >= 55
  MONITOR  readiness < 55

Entry eligible: readiness >= 75 AND >= 5 confirmations AND >= 1 hard confirmation AND above_ema.
"""


import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from signal_rules import (
    compute_backend_tier,
    compute_confirmation_count,
    ENTRY_MIN_CONFIRMATIONS,
    ENTRY_MIN_HARD_CONFIRMATIONS,
    ENTRY_READINESS_MIN,
    HARD_CONFIRMATION_KEYS,
    has_required_positive_edge,
    TIER_NOW_MIN,
    TIER_STRONG_NOW_MIN,
    TIER_WATCH_MIN,
)

# PEAD removed — Alpaca has no earnings API, factor dropped for zero external deps

logger = logging.getLogger(__name__)

# 2026-09-05 signal redesign: go live with candidate score based on factor attribution.
# Only factors with positive live edge are kept in the score; toxic factors are removed.
# Positive-edge factors: above_ema (+16.3pp), rsi_signal (+16.3pp), momentum_score (+10.0pp).
# Toxic/removed: volume_confirmed (-20.7pp), vwap_confirmed (-27.8pp), options_confirmed (-37.5pp),
# macd_turning (-46.9pp), near_term_bullish_flow (-46.9pp), bid_ask_bullish (-7.6pp), sector_strong (-9.4pp).
# Three-pillar candidate score: 40% trend quality, 40% momentum strength, 20% execution/risk filters.
# Feature flag: set False to revert instantly to pre-redesign composite.
USE_CANDIDATE_SCORE: bool = True

# Candidate-score constants (pillar weights add to 1.0)
CANDIDATE_WEIGHT_TREND = 0.40
CANDIDATE_WEIGHT_MOMENTUM = 0.40
CANDIDATE_WEIGHT_RISK = 0.20

# Legacy weights kept for instant rollback. DO NOT rely on these when USE_CANDIDATE_SCORE=True.
WEIGHT_SIGNAL = 0.25
WEIGHT_RSI = 0.06
WEIGHT_VOLUME = 0.10
WEIGHT_MACD = 0.05
WEIGHT_EMA = 0.10
WEIGHT_SECTOR = 0.25
WEIGHT_INTRADAY = 0.05
WEIGHT_OPTIONS = 0.14
WEIGHT_REL_VOLUME = 0.00
WEIGHT_VWAP_DEV = 0.15
WEIGHT_RELATIVE_STRENGTH = 0.04
WEIGHT_5M_MOMENTUM = 0.0075
WEIGHT_5M_VOLUME_SURGE = 0.0025
WEIGHT_5M_VWAP = 0.0025
WEIGHT_OPTIONS_FLOW = 0.005
WEIGHT_SPREAD_OK = 0.005
WEIGHT_NO_CORPORATE_ACTION = 0.005
WEIGHT_BID_ASK_IMBALANCE = 0.005

# Tier and entry constants now live in signal_rules.py (single source of truth).
# Any local overrides here are bugs; change them in signal_rules.py instead.



@dataclass
class ReadinessResult:
    symbol: str
    readiness_score: float
    tier: str
    confirmations: Dict
    confirmation_count: int
    entry_eligible: bool
    tier_reason: str

    factor_breakdown: Optional[Dict] = field(default=None)

def _rsi_component_score(rsi: float) -> float:
    """
    v3 2026-08-08: RSI is a negative contributor when overbought (>70),
    neutral/small positive in the 40-60 range, and otherwise muted.

    Attribution shows the old "sweet spot" RSI signal had no edge; we now
    use it only as a risk veto.  The neutral band (40-60) avoids penalizing
    stocks that are not extended.  Missing RSI returns neutral to avoid
    discarding valid setups when data is absent.
    """
    if rsi <= 0:
        return 50.0  # missing = neutral (no information)
    if rsi > 80:
        return 0.0   # very overbought, full veto
    if rsi > 70:
        # 70-80 maps 30 -> 0 (strong negative)
        return max(0.0, 30.0 - (rsi - 70) * 3.0)
    if rsi > 65:
        # 65-70 maps 70 -> 30 (modest negative)
        return 70.0 - (rsi - 65) * 8.0
    if rsi >= 60:
        # 60-65 maps 85 -> 70 (slightly warm)
        return 85.0 - (rsi - 60) * 3.0
    if rsi >= 40:
        # 40-60 ideal zone (neutral-small positive)
        return 50.0 + (rsi - 50) * 1.5
    if rsi >= 30:
        # 30-40 oversold but not panic: small positive
        return 35.0 + (rsi - 30) * 1.5
    # Below 30: falling knife risk, mild negative
    return 20.0 + rsi * 0.5


def _rsi_signal_label(rsi: float) -> str:
    if rsi < 30:
        return "oversold"
    if rsi > 70:
        return "overbought"
    return "neutral"


def _volume_component_score(recent_vol: float, avg_vol: float,
                             price_change: float = 0.0) -> Tuple[float, bool]:
    """
    Score volume confirmation on 0-100.
    FIXED: Volume spikes are NEGATIVELY correlated with wins (-0.231).
    High volume on falling price = selling pressure (bearish).
    High volume on rising price = buying pressure (bullish).
    Low volume = neutral.

    recent_vol = 5d average; avg_vol = 20d average.
    price_change = 5d price change (decimal, e.g. 0.03 = +3%).
    Returns (score, confirmed: bool).
    """
    if avg_vol <= 0:
        return 50.0, False
    ratio = recent_vol / avg_vol

    # Base score from volume ratio
    if ratio >= 1.5:
        base_score = 90.0
    elif ratio >= 1.2:
        base_score = 75.0
    elif ratio >= 1.0:
        base_score = 55.0
    elif ratio >= 0.8:
        base_score = 40.0
    else:
        base_score = 25.0

    # Adjust for price direction: volume + rising price = bullish, volume + falling price = bearish
    if ratio >= 1.2 and price_change < -0.02:
        # High volume on a drop = selling pressure → reduce score
        base_score -= 30
    elif ratio >= 1.2 and price_change > 0.02:
        # High volume on a rally = buying pressure → increase score
        base_score += 10

    score = max(0.0, min(100.0, base_score))
    confirmed = score >= 65 and ratio >= 1.0 and price_change > 0
    return score, confirmed


def _macd_component_score(closes: List[float]) -> Tuple[float, bool]:
    """
    v3 2026-08-08: MACD is negative in late-stage strongly-positive histogram
    territory, and positive only on a fresh cross from negative to positive.
    The old "positive and rising" bucket had negative live edge, so it is
    removed.  Missing/bare data returns neutral to avoid discarding setups.
    """
    if len(closes) < 35:
        return 50.0, False  # missing = neutral

    ema12_prev = _ema(closes[-27:-1], 12)
    ema26_prev = _ema(closes[-27:-1], 26)
    hist_prev = ema12_prev - ema26_prev

    ema12_now = _ema(closes[-26:], 12)
    ema26_now = _ema(closes[-26:], 26)
    hist_now = ema12_now - ema26_now

    turning_positive = hist_prev <= 0 and hist_now > 0
    strongly_positive = hist_now > 0 and hist_now > abs(hist_prev) * 0.5
    still_positive = hist_now > 0

    if turning_positive:
        return 100.0, True
    if strongly_positive:
        # late-stage momentum, mean-reversion risk — negative
        return 20.0, False
    if still_positive:
        # positive but not strongly extended — neutral/slightly negative
        return 40.0, False
    if hist_now > hist_prev:
        # negative but improving — neutral
        return 50.0, False
    return 30.0, False


def _ema(values: List[float], period: int) -> float:
    """Compute EMA for a list of values."""
    if not values or len(values) < period:
        if not values:
            return 0.0
        return sum(values) / len(values)
    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for val in values[period:]:
        ema = (val - ema) * multiplier + ema
    return ema


def _ema_distance_score(price: float, closes: List[float]) -> Tuple[float, bool]:
    """
    Score distance to 20d EMA. Price above EMA = trend confirmation.
    Returns (score 0-100, above_ema: bool).
    """
    if len(closes) < 20 or price <= 0:
        return 50.0, False
    ema20 = _ema(closes[-20:], 20)
    above = price > ema20
    distance_pct = (price - ema20) / ema20 * 100 if ema20 > 0 else 0.0

    if above:
        if distance_pct <= 5:
            return 100.0, True   # nicely above, not overextended
        elif distance_pct <= 10:
            return 85.0, True
        elif distance_pct <= 15:
            return 65.0, True
        else:
            return 40.0, True    # overextended above EMA
    else:
        if distance_pct >= -2:
            return 70.0, False   # just below EMA, might reclaim
        elif distance_pct >= -5:
            return 45.0, False
        else:
            return 25.0, False   # well below EMA


def _relative_strength_score(
    symbol: str,
    all_bars: Dict[str, Dict],
) -> float:
    """
    Stock vs SPY 20-day relative strength (alpha).
    Score 0-100 based on how much the stock is outperforming the market.
    """
    stock_bars = all_bars.get(symbol, {}) if all_bars else {}
    stock_closes = stock_bars.get("closes", []) if isinstance(stock_bars, dict) else []
    spy_bars = all_bars.get("SPY", {}) if all_bars else {}
    spy_closes = spy_bars.get("closes", []) if isinstance(spy_bars, dict) else []

    if len(stock_closes) < 21 or len(spy_closes) < 21:
        return 50.0

    stock_roc = (stock_closes[-1] - stock_closes[-21]) / stock_closes[-21]
    spy_roc = (spy_closes[-1] - spy_closes[-21]) / spy_closes[-21]
    alpha = stock_roc - spy_roc

    # Score: outperforming by 5%+ = 100, tracking = 60, underperforming by 5%+ = 0
    if alpha >= 0.10:
        return 100.0
    if alpha >= 0.05:
        return 80.0 + (alpha - 0.05) / 0.05 * 20.0
    if alpha >= 0.02:
        return 60.0 + (alpha - 0.02) / 0.03 * 20.0
    if alpha >= -0.02:
        return 60.0 + alpha / 0.02 * 20.0
    if alpha >= -0.05:
        return 30.0 + (alpha + 0.02) / 0.03 * 30.0
    return max(0.0, 30.0 + (alpha + 0.05) / 0.05 * 30.0)


def _sector_relative_strength(
    symbol: str,
    all_bars: Dict[str, Dict],
    sector_symbols: List[str],
) -> Tuple[float, bool]:
    """
    Compare sector momentum vs market (SPY).
    Returns (score 0-100, sector_strong: bool).
    """
    spy_bars = all_bars.get("SPY", {})
    spy_closes = spy_bars.get("closes", [])
    spy_roc = 0.0
    if len(spy_closes) >= 20:
        spy_roc = (spy_closes[-1] - spy_closes[-20]) / spy_closes[-20]

    # Average 20d momentum for sector peers
    sector_rocs = []
    for s in sector_symbols:
        bars = all_bars.get(s)
        if not bars:
            continue
        sc = bars.get("closes", [])
        if len(sc) >= 20:
            sector_rocs.append((sc[-1] - sc[-20]) / sc[-20])

    if not sector_rocs:
        return 50.0, False

    avg_sector_roc = sum(sector_rocs) / len(sector_rocs)
    relative = avg_sector_roc - spy_roc

    # Score: sector outperforming SPY by 2%+ = 100, tracking = 60, lagging = 20
    if relative >= 0.03:
        return 100.0, True
    if relative >= 0.01:
        return 80.0, True
    if relative >= 0.0:
        return 60.0, False
    if relative >= -0.02:
        return 40.0, False
    return 20.0, False


def _intraday_momentum_score(intraday_bars: List[Dict], daily_vwap: Optional[float] = None) -> Tuple[float, bool]:
    """
    Score intraday momentum from 5-minute bars.
    Returns (score 0-100, confirmed: bool).

    Boosts readiness when:
    - Price trending up in last 3-5 bars (intraday momentum)
    - Volume accelerating in recent bars
    - Price above daily VWAP
    """
    if not intraday_bars or len(intraday_bars) < 3:
        return 50.0, False  # neutral when no intraday data (market closed)

    # Intraday price momentum: compare last close to 3 bars ago
    recent_bars = intraday_bars[-5:] if len(intraday_bars) >= 5 else intraday_bars
    first_close = recent_bars[0].get("c", 0)
    last_close = recent_bars[-1].get("c", 0)
    if first_close <= 0:
        return 50.0, False

    intraday_return = (last_close - first_close) / first_close

    # Volume acceleration: compare last 3 bars avg vol to overall avg vol
    recent_vol = sum(b.get("v", 0) for b in intraday_bars[-3:]) / min(3, len(intraday_bars))
    overall_vol = sum(b.get("v", 0) for b in intraday_bars) / len(intraday_bars)
    vol_ratio = recent_vol / overall_vol if overall_vol > 0 else 1.0

    # VWAP confirmation
    vwap_confirmed = False
    if daily_vwap and daily_vwap > 0:
        vwap_confirmed = last_close > daily_vwap

    # Score: combine intraday return, volume ratio, and VWAP
    score = 50.0
    # Intraday return: +1% = +30, -1% = -30
    score += max(-30, min(30, intraday_return * 3000))
    # Volume ratio: >1.5x = +15, <0.5x = -10
    if vol_ratio >= 1.5:
        score += 15
    elif vol_ratio >= 1.2:
        score += 10
    elif vol_ratio < 0.5:
        score -= 10
    # VWAP confirmation
    if vwap_confirmed:
        score += 5

    score = max(0.0, min(100.0, score))
    confirmed = score >= 65 and vol_ratio >= 1.0

    return score, confirmed


def _options_sentiment_score(
    iv_summary: Optional[Dict],
    options_flow: Optional[Dict] = None,
    minute_vwap: Optional[float] = None,
    price: Optional[float] = None,
) -> Tuple[float, bool]:
    """
    Score options sentiment from IV summary dict and options flow data.
    Uses 30d ATM IV and IV rank if available; falls back to raw implied_vol field.
    Incorporates options flow (call/put ratio, near-term bullish flow, unusual volume).
    v3 2026-08-08: options flow score now gets amplified when near-term bullish
    flow is confirmed AND the price is above intraday VWAP, reducing false
    positives from contrarian/hedge flow.
    Returns (score 0-100, confirmed: bool).

    Logic:
      - IV rank > 0.80 (high percentile) = expensive options, event fear → lower score
      - IV rank > 0.60 = elevated → slightly lower
      - IV rank 0.30-0.60 = normal → neutral
      - IV rank < 0.30 = low IV, bullish complacency → higher
      - If no rank, fall back to absolute 30d IV thresholds
    """
    # Start with IV-based score
    if iv_summary is None:
        iv_score = 50.0
    elif isinstance(iv_summary, dict):
        iv_30d = iv_summary.get("iv_30d")
        iv_rank = iv_summary.get("iv_rank")
        if iv_rank is not None and 0 <= iv_rank <= 1:
            if iv_rank > 0.80:
                iv_score = 20.0
            elif iv_rank > 0.60:
                iv_score = 40.0
            elif iv_rank > 0.30:
                iv_score = 60.0
            elif iv_rank > 0.10:
                iv_score = 75.0
            else:
                iv_score = 85.0
        elif iv_30d is not None and iv_30d > 0:
            if iv_30d > 0.8:
                iv_score = 20.0
            elif iv_30d > 0.6:
                iv_score = 35.0
            elif iv_30d > 0.4:
                iv_score = 60.0
            elif iv_30d > 0.25:
                iv_score = 75.0
            else:
                iv_score = 85.0
        else:
            iv_score = 50.0
    else:
        iv_score = 50.0

    # Adjust by options flow if available
    if not options_flow:
        return iv_score, iv_score >= 65

    flow_score = iv_score
    if options_flow.get("options_unusual_volume"):
        # Unusual volume with bullish near-term flow is a strong confirmation
        if options_flow.get("near_term_bullish_flow"):
            flow_score = min(100.0, flow_score + 10.0)
            # v3: add extra lift when price is above intraday VWAP (momentum
            # alignment) so options flow amplifies rather than contradicts
            # the live technical picture.
            if minute_vwap and price and price > minute_vwap:
                flow_score = min(100.0, flow_score + 8.0)
        else:
            flow_score = max(0.0, flow_score - 10.0)

    put_call_ratio = options_flow.get("put_call_ratio")
    if put_call_ratio is not None:
        if put_call_ratio < 0.5 and options_flow.get("near_term_bullish_flow"):
            flow_score = min(100.0, flow_score + 5.0)
        elif put_call_ratio > 1.5:
            flow_score = max(0.0, flow_score - 10.0)

    return round(max(0.0, min(100.0, flow_score)), 1), flow_score >= 65




# compute_confirmation_count now imported from signal_rules.py.

# Sector peer mapping for relative strength
SECTOR_PEERS: Dict[str, List[str]] = {
    "AI/Growth": ["PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "PATH", "PANW", "APP", "GTLB", "ELF", "DUOL", "ESTC", "CFLT", "S"],
    "Semiconductors": ["AMD", "NVDA", "AVGO", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON"],
    "Tech Giants": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "NOW", "TEAM", "VEEV", "DOCN"],
    "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY"],
    "Consumer/Platform": ["UBER", "DKNG", "SHOP", "ROKU", "TTD", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "CHWY", "ETSY"],
    "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
    "Retail/Lifestyle": ["LULU", "NKE", "COST", "WMT", "HD", "ELF"],
    "Cloud/Data": ["SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW"],
}



def _relative_volume_score(recent_vol: float, avg_vol: float) -> float:
    """Score relative volume: >2.0x average = strong confirmation (100), 1.5x = good (75), else taper."""
    if avg_vol <= 0:
        return 0.0
    ratio = recent_vol / avg_vol
    if ratio >= 2.0:
        return 100.0
    if ratio >= 1.5:
        return 75.0 + (ratio - 1.5) * 50.0  # 75→100 across 1.5→2.0
    if ratio >= 1.0:
        return 40.0 + (ratio - 1.0) * 70.0   # 40→75 across 1.0→1.5
    return max(0.0, ratio * 40.0)  # taper to 0


def _vwap_deviation_score(price: float, daily_vwap: Optional[float]) -> float:
    """Score VWAP deviation: price >> VWAP = buyers in control (momentum), below = distribution."""
    if not daily_vwap or daily_vwap <= 0:
        return 50.0  # neutral when no data
    deviation = (price - daily_vwap) / daily_vwap * 100
    if deviation >= 2.0:
        return 100.0
    if deviation >= 0.5:
        return 70.0 + (deviation - 0.5) * 20.0
    if deviation >= -0.5:
        return 50.0 + deviation * 40.0
    if deviation >= -2.0:
        return 30.0 + (deviation + 0.5) * 13.33
    return max(0.0, 10.0 + (deviation + 2.0) * 10.0)


def compute_readiness(
    symbol: str,
    total_score: float,
    rsi14: float,
    closes: List[float],
    volumes: List[float],
    price: float,
    sector: str,
    all_bars: Optional[Dict[str, Dict]] = None,
    intraday_bars: Optional[List[Dict]] = None,
    daily_vwap: Optional[float] = None,
    prev_close: Optional[float] = None,
    options_implied_vol: Optional[Union[float, Dict]] = None,
    minute_vwap: Optional[float] = None,
    vs_qqq_5d_return_delta: Optional[float] = None,
    **kwargs,
) -> ReadinessResult:
    """
    Compute the composite readiness score for a single stock.

    Parameters
    ----------
    symbol : str
    total_score : float
        The signal engine's 0-100 total score (momentum+quality+risk+regime).
    rsi14 : float
        14-period RSI.
    closes : List[float]
        Daily close prices (at least 26 for MACD).
    volumes : List[float]
        Daily volumes (at least 20 for volume ratio).
    price : float
        Current/latest price.
    sector : str
        Sector label from signal_engine.
    all_bars : Dict[str, Dict], optional
        All symbol bars for sector relative strength calculation.
    """
    # v3 2026-08-08: enriched fields that must be present for the new signal
    # are explicitly listed here.  Missing values fall back cleanly to
    # neutral/old behavior, so the engine never breaks on partial data.
    daily_vwap = daily_vwap or kwargs.get("daily_vwap")
    minute_vwap = minute_vwap or kwargs.get("minute_vwap") or daily_vwap
    vs_qqq_5d_return_delta = vs_qqq_5d_return_delta or kwargs.get("vs_qqq_5d_return_delta")
    all_bars = all_bars or {}

    # 1. Signal engine total_score component (40%)
    signal_component = max(0.0, min(100.0, total_score))

    # 2. RSI component (15%)
    rsi_component = _rsi_component_score(rsi14)
    rsi_signal = _rsi_signal_label(rsi14)

    # 3. Volume confirmation (15%)
    if len(volumes) >= 20:
        recent_vol = sum(volumes[-5:]) / 5
        avg_vol = sum(volumes[-20:]) / 20
    else:
        recent_vol = avg_vol = sum(volumes) / max(len(volumes), 1)
    # Compute 5d price change for volume direction context
    price_change_5d = 0.0
    if len(closes) >= 6:
        price_change_5d = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0.0
    vol_component, volume_confirmed = _volume_component_score(recent_vol, avg_vol, price_change_5d)

    # 4. MACD histogram (10%)
    macd_component, macd_turning = _macd_component_score(closes)

    # 5. EMA distance (4%)
    ema_component, above_ema = _ema_distance_score(price, closes)

    # 5b. Relative strength vs SPY (8%)
    rs_component = _relative_strength_score(symbol, all_bars)

    # 6. Sector relative strength (10%)
    sector_peers = SECTOR_PEERS.get(sector, [])
    sector_component, sector_strong = _sector_relative_strength(
        symbol, all_bars, sector_peers,
    )

    # 7. Intraday momentum (bonus confirmation, not weighted in composite)
    intraday_component, intraday_confirmed = _intraday_momentum_score(
        intraday_bars or [], daily_vwap
    )

    # 8. Options sentiment (from IV term structure / rank / 30d IV + options flow)
    options_flow = kwargs.get("options_flow") or {
        "put_call_ratio": kwargs.get("options_call_put_ratio"),
        "options_unusual_volume": kwargs.get("options_unusual_volume", False),
        "near_term_bullish_flow": kwargs.get("near_term_bullish_flow", False),
    }
    options_component, options_confirmed = _options_sentiment_score(options_implied_vol, options_flow, minute_vwap, price)

    # 9. Relative volume confirmation (already have recent_vol / avg_vol from volume step)
    relvol_component = _relative_volume_score(recent_vol, avg_vol)
    relvol_confirmed = relvol_component >= 60.0  # >1.0x avg volume

    # 10. VWAP deviation (momentum signal)
    vwap_component = _vwap_deviation_score(price, daily_vwap)
    vwap_confirmed = vwap_component >= 60.0  # price above VWAP or close

    # v3 2026-08-08: QQQ relative-strength gate.  If the symbol's 5-day return
    # is below QQQ's 5-day return, it is underperforming the growth benchmark;
    # reduce readiness by at least 15 points.  A positive delta is rewarded
    # modestly; a zero/missing delta is neutral.
    qqq_gate_penalty = 0.0
    if vs_qqq_5d_return_delta is not None and vs_qqq_5d_return_delta < 0:
        qqq_gate_penalty = 15.0 + min(10.0, abs(vs_qqq_5d_return_delta) * 500.0)

    # Pull explicit 5-minute / options / spread / corporate-action chips from kwargs (populated by signal_engine)
    momentum_5m_up = kwargs.get("momentum_5m_up", False)
    volume_5m_surge = kwargs.get("volume_5m_surge", False)
    price_above_5m_vwap = kwargs.get("price_above_5m_vwap", False)
    near_term_bullish_flow = options_flow.get("near_term_bullish_flow", False)
    spread_ok = kwargs.get("spread_ok", True)
    bid_ask_bullish = kwargs.get("bid_ask_bullish", False)
    corporate_action_risk = kwargs.get("corporate_action_risk", False)

    # Confirmations dict (canonical boolean signals) — built once, used by both candidate and legacy paths.
    confirmations = {
        "momentum_score": round(signal_component, 1),
        "rsi_signal": rsi_signal,
        "volume_confirmed": volume_confirmed,
        "macd_turning": macd_turning,
        "above_ema": above_ema,
        "sector_strong": sector_strong,
        "intraday_confirmed": intraday_confirmed,
        "intraday_score": round(intraday_component, 1),
        "momentum_5m_up": bool(momentum_5m_up),
        "volume_5m_surge": bool(volume_5m_surge),
        "price_above_5m_vwap": bool(price_above_5m_vwap),
        "options_confirmed": options_confirmed,
        "options_score": round(options_component, 1),
        "options_call_put_ratio": options_flow.get("put_call_ratio"),
        "options_unusual_volume": options_flow.get("options_unusual_volume", False),
        "near_term_bullish_flow": options_flow.get("near_term_bullish_flow", False),
        "bid_ask_spread_pct": kwargs.get("bid_ask_spread_pct"),
        "wide_spread": kwargs.get("wide_spread", False),
        "spread_ok": kwargs.get("spread_ok", True),
        "bid_ask_imbalance": kwargs.get("bid_ask_imbalance"),
        "bid_ask_bullish": kwargs.get("bid_ask_bullish", False),
        "has_upcoming_dividend": kwargs.get("has_upcoming_dividend", False),
        "has_upcoming_split": kwargs.get("has_upcoming_split", False),
        "has_upcoming_merger": kwargs.get("has_upcoming_merger", False),
        "has_upcoming_spinoff": kwargs.get("has_upcoming_spinoff", False),
        "corporate_action_risk": kwargs.get("corporate_action_risk", False),
        "no_corporate_action_risk": not kwargs.get("corporate_action_risk", False),
        "relvol_confirmed": relvol_confirmed,
        "relvol_score": round(relvol_component, 1),
        "vwap_confirmed": vwap_confirmed,
        "vwap_score": round(vwap_component, 1),
    }

    if USE_CANDIDATE_SCORE:
        # Candidate redesign score (2026-09-05): three-pillar model based on live attribution.
        # Positive-edge factors retained: above_ema, rsi neutral, signal_component.
        # Pillar 1: trend quality (40%)
        trend_score = 0.0
        if above_ema:
            trend_score += 0.25
        if rsi_signal == "neutral":
            trend_score += 0.10
        if signal_component >= 60:
            trend_score += 0.05

        # Pillar 2: momentum strength (40%) — raw signal-engine total score
        momentum_score_norm = min(max(signal_component / 100.0, 0.0), 1.0)
        momentum_pillar = momentum_score_norm * CANDIDATE_WEIGHT_MOMENTUM

        # Pillar 3: execution / risk filters (20%)
        risk_score = 0.0
        if spread_ok:
            risk_score += 0.10
        if not corporate_action_risk:
            risk_score += 0.10

        readiness = (trend_score + momentum_pillar + risk_score) * 100.0
        readiness = round(max(0.0, min(100.0, readiness)), 1)

        confirmation_count = compute_confirmation_count(confirmations)

        # Entry gate: strong trend + momentum + clean execution. No toxic hard keys.
        entry_eligible = (
            readiness >= ENTRY_READINESS_MIN
            and above_ema
            and spread_ok
            and not corporate_action_risk
            and signal_component >= 55
            and rsi_signal != "overbought"
        )

        tier = compute_backend_tier(readiness)
        tier_reason = _build_tier_reason(
            tier, readiness, confirmations, confirmation_count,
        )
        return ReadinessResult(
            symbol=symbol,
            readiness_score=readiness,
            tier=tier,
            confirmations=confirmations,
            confirmation_count=confirmation_count,
            entry_eligible=entry_eligible,
            tier_reason=tier_reason,
            factor_breakdown=None,  # legacy breakdown not meaningful for candidate model
        )

    # Weighted composite (11 factors + 6 new confirmation chips; sum-of-weights normalised to avoid inflation)
    total_weight = (
        WEIGHT_SIGNAL + WEIGHT_RSI + WEIGHT_VOLUME + WEIGHT_MACD + WEIGHT_EMA
        + WEIGHT_SECTOR + WEIGHT_INTRADAY + WEIGHT_OPTIONS
        + WEIGHT_REL_VOLUME + WEIGHT_VWAP_DEV + WEIGHT_RELATIVE_STRENGTH
        + WEIGHT_5M_MOMENTUM + WEIGHT_5M_VOLUME_SURGE + WEIGHT_5M_VWAP
        + WEIGHT_OPTIONS_FLOW + WEIGHT_SPREAD_OK + WEIGHT_NO_CORPORATE_ACTION + WEIGHT_BID_ASK_IMBALANCE
    )
    factor_breakdown = {
        "signal":    {"raw": round(signal_component, 2),    "weight_pct": round(WEIGHT_SIGNAL/total_weight*100, 1),    "contribution": round(WEIGHT_SIGNAL    * signal_component / total_weight, 2)},
        "rsi":       {"raw": round(rsi_component, 2),       "weight_pct": round(WEIGHT_RSI/total_weight*100, 1),       "contribution": round(WEIGHT_RSI       * rsi_component / total_weight, 2)},
        "volume":    {"raw": round(vol_component, 2),       "weight_pct": round(WEIGHT_VOLUME/total_weight*100, 1),    "contribution": round(WEIGHT_VOLUME    * vol_component / total_weight, 2)},
        "macd":      {"raw": round(macd_component, 2),       "weight_pct": round(WEIGHT_MACD/total_weight*100, 1),      "contribution": round(WEIGHT_MACD      * macd_component / total_weight, 2)},
        "ema":       {"raw": round(ema_component, 2),       "weight_pct": round(WEIGHT_EMA/total_weight*100, 1),       "contribution": round(WEIGHT_EMA       * ema_component / total_weight, 2)},
        "sector":    {"raw": round(sector_component, 2),     "weight_pct": round(WEIGHT_SECTOR/total_weight*100, 1),    "contribution": round(WEIGHT_SECTOR    * sector_component / total_weight, 2)},
        "intraday":  {"raw": round(intraday_component, 2),   "weight_pct": round(WEIGHT_INTRADAY/total_weight*100, 1),  "contribution": round(WEIGHT_INTRADAY  * intraday_component / total_weight, 2)},
        "options":   {"raw": round(options_component, 2),   "weight_pct": round(WEIGHT_OPTIONS/total_weight*100, 1),   "contribution": round(WEIGHT_OPTIONS   * options_component / total_weight, 2)},
        "rel_volume":{"raw": round(relvol_component, 2),   "weight_pct": round(WEIGHT_REL_VOLUME/total_weight*100, 1),"contribution": round(WEIGHT_REL_VOLUME* relvol_component / total_weight, 2)},
        "vwap":      {"raw": round(vwap_component, 2),       "weight_pct": round(WEIGHT_VWAP_DEV/total_weight*100, 1),  "contribution": round(WEIGHT_VWAP_DEV  * vwap_component / total_weight, 2)},
        "relative_strength": {"raw": round(rs_component, 2),   "weight_pct": round(WEIGHT_RELATIVE_STRENGTH/total_weight*100, 1), "contribution": round(WEIGHT_RELATIVE_STRENGTH * rs_component / total_weight, 2)},
        "momentum_5m":        {"raw": bool(momentum_5m_up),        "weight_pct": round(WEIGHT_5M_MOMENTUM/total_weight*100, 1),       "contribution": round(WEIGHT_5M_MOMENTUM       * (100 if momentum_5m_up else 0) / total_weight, 2)},
        "volume_5m_surge":    {"raw": bool(volume_5m_surge),    "weight_pct": round(WEIGHT_5M_VOLUME_SURGE/total_weight*100, 1),   "contribution": round(WEIGHT_5M_VOLUME_SURGE   * (100 if volume_5m_surge else 0) / total_weight, 2)},
        "price_above_5m_vwap":{"raw": bool(price_above_5m_vwap),"weight_pct": round(WEIGHT_5M_VWAP/total_weight*100, 1),           "contribution": round(WEIGHT_5M_VWAP          * (100 if price_above_5m_vwap else 0) / total_weight, 2)},
        "options_flow":       {"raw": bool(near_term_bullish_flow),"weight_pct": round(WEIGHT_OPTIONS_FLOW/total_weight*100, 1),     "contribution": round(WEIGHT_OPTIONS_FLOW     * (100 if near_term_bullish_flow else 0) / total_weight, 2)},
        "spread_ok":          {"raw": bool(spread_ok),          "weight_pct": round(WEIGHT_SPREAD_OK/total_weight*100, 1),        "contribution": round(WEIGHT_SPREAD_OK        * (100 if spread_ok else 0) / total_weight, 2)},
        "no_corporate_action":{"raw": not corporate_action_risk,"weight_pct": round(WEIGHT_NO_CORPORATE_ACTION/total_weight*100, 1),"contribution": round(WEIGHT_NO_CORPORATE_ACTION * (100 if not corporate_action_risk else 0) / total_weight, 2)},
        "bid_ask_bullish":    {"raw": bool(bid_ask_bullish),    "weight_pct": round(WEIGHT_BID_ASK_IMBALANCE/total_weight*100, 1), "contribution": round(WEIGHT_BID_ASK_IMBALANCE * (100 if bid_ask_bullish else 0) / total_weight, 2)},
    }
    readiness = (
        WEIGHT_SIGNAL * signal_component
        + WEIGHT_RSI * rsi_component
        + WEIGHT_VOLUME * vol_component
        + WEIGHT_MACD * macd_component
        + WEIGHT_EMA * ema_component
        + WEIGHT_SECTOR * sector_component
        + WEIGHT_INTRADAY * intraday_component
        + WEIGHT_OPTIONS * options_component
        + WEIGHT_REL_VOLUME * relvol_component
        + WEIGHT_VWAP_DEV * vwap_component
        + WEIGHT_RELATIVE_STRENGTH * rs_component
        + WEIGHT_5M_MOMENTUM * (100 if momentum_5m_up else 0)
        + WEIGHT_5M_VOLUME_SURGE * (100 if volume_5m_surge else 0)
        + WEIGHT_5M_VWAP * (100 if price_above_5m_vwap else 0)
        + WEIGHT_OPTIONS_FLOW * (100 if near_term_bullish_flow else 0)
        + WEIGHT_SPREAD_OK * (100 if spread_ok else 0)
        + WEIGHT_NO_CORPORATE_ACTION * (100 if not corporate_action_risk else 0)
        + WEIGHT_BID_ASK_IMBALANCE * (100 if bid_ask_bullish else 0)
    ) / total_weight
    readiness = readiness - qqq_gate_penalty
    readiness = round(max(0.0, min(100.0, readiness)), 1)

    # Confirmations dict already built above for candidate path; legacy path builds from the same variables.

    # Confirmation count: canonical boolean count (single source of truth via signal_rules)
    confirmation_count = compute_confirmation_count(confirmations)

    # v3: hard keys imported from strategy_config via signal_rules (single source of truth)
    hard_confirmations = sum(
        1 for k in HARD_CONFIRMATION_KEYS
        if confirmations.get(k)
    )

    # Entry gate: high-quality setup + trend confirm.
    # Relaxed 2026-07-13: 1 hard confirmation is enough if total chips are strong (>=7),
    # otherwise require 2 hard confirmations as before.
    effective_hard_min = (
        1 if confirmation_count >= 7 else ENTRY_MIN_HARD_CONFIRMATIONS
    )

    # Market-dip opportunity override: during broad pullbacks, allow high-quality
    # names above their 20d EMA with at least 1 hard confirmation to qualify.
    dip_override = (
        kwargs.get("dip_opportunity", False)
        and confirmations.get("above_ema", False)
        and hard_confirmations >= DIP_HARD_CONF_MIN
        and readiness >= ENTRY_READINESS_MIN + qqq_gate_penalty  # pre-penalty readiness would have cleared
        and confirmation_count >= ENTRY_MIN_CONFIRMATIONS
    )

    # v3: positive-edge hard confirmations with fallbacks
    _has_positive_hard = has_required_positive_edge(confirmations)

    entry_eligible = (
        readiness >= ENTRY_READINESS_MIN
        and confirmation_count >= ENTRY_MIN_CONFIRMATIONS
        and hard_confirmations >= effective_hard_min
        and confirmations.get("above_ema", False)  # strongest live predictor (+0.572 correlation)
        and _has_positive_hard  # v3: volume or VWAP required
    ) or dip_override

    # Tier: decoupled from entry eligibility (2026-07-13).
    # STRONG_NOW is the top readiness tier; entry_eligible is a separate trading gate.
    tier = compute_backend_tier(readiness)

    # Tier reason
    tier_reason = _build_tier_reason(
        tier, readiness, confirmations, confirmation_count,
    )

    return ReadinessResult(
        symbol=symbol,
        readiness_score=readiness,
        tier=tier,
        confirmations=confirmations,
        confirmation_count=confirmation_count,
        entry_eligible=entry_eligible,
        tier_reason=tier_reason,
        factor_breakdown=factor_breakdown,
    )


def _build_tier_reason(
    tier: str,
    readiness: float,
    confirmations: Dict,
    confirmation_count: int,
) -> str:
    """Human-readable reason for tier assignment (candidate-score redesign)."""
    parts = []
    if tier == "STRONG_NOW":
        parts.append(f"PRIME: readiness {readiness:.1f} — highest-conviction entry tier")
    elif tier == "NOW":
        parts.append(f"BUILDING: readiness {readiness:.1f} — entry-ready if hard filters pass")
    elif tier == "WATCH":
        parts.append(f"WATCHING: readiness {readiness:.1f} — on watch, not yet entry-ready")
    else:
        parts.append(f"TRACKING: readiness {readiness:.1f} — monitoring")

    reasons = []
    # Candidate-score pillars only
    if confirmations.get("above_ema"):
        reasons.append("above 20d EMA")
    momentum_score = confirmations.get("momentum_score")
    if momentum_score is not None and momentum_score >= 55:
        reasons.append(f"momentum score {momentum_score:.0f}")
    rsi = confirmations.get("rsi_signal")
    if rsi in ("bullish", "neutral", "oversold"):
        reasons.append(f"RSI {rsi}")
    elif rsi == "overbought":
        reasons.append("RSI overbought (caution)")
    if confirmations.get("spread_ok"):
        reasons.append("spread OK")
    if confirmations.get("no_corporate_action_risk"):
        reasons.append("no corporate-action risk")

    # Display-only context (kept for transparency, but not entry factors)
    display_reasons = []
    if confirmations.get("volume_confirmed"):
        display_reasons.append("volume (display-only)")
    if confirmations.get("vwap_confirmed"):
        display_reasons.append("VWAP (display-only)")
    if confirmations.get("macd_turning"):
        display_reasons.append("MACD (display-only)")
    if confirmations.get("sector_strong"):
        display_reasons.append("sector (display-only)")
    if confirmations.get("intraday_confirmed"):
        display_reasons.append("intraday (display-only)")
    if confirmations.get("options_confirmed"):
        display_reasons.append("options (display-only)")
    if confirmations.get("relvol_confirmed"):
        display_reasons.append("relvol (display-only)")
    if confirmations.get("near_term_bullish_flow"):
        display_reasons.append("options flow (display-only)")
    if confirmations.get("bid_ask_bullish"):
        display_reasons.append("bid/ask (display-only)")

    if reasons:
        parts.append("entry pillars: " + ", ".join(reasons))
    if display_reasons:
        parts.append("context: " + ", ".join(display_reasons))
    if not reasons and not display_reasons:
        parts.append(f"{confirmation_count}/10 confirmation chips active")

    return ". ".join(parts) + "."