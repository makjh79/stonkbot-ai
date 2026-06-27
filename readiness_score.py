"""
STONK.AI Readiness Score Engine

Composite 0-100 readiness score per stock that drives tier assignment
AND entry decisions.  This is the new "brain" of the watchlist.

Factors (weighted):
  - Signal engine total_score (momentum+quality+risk+regime): 40%
  - RSI proximity to sweet spot (50-65 = 100, tapering both sides): 15%
  - Volume confirmation (recent 5d vs 20d avg; >1.2x = high): 15%
  - MACD histogram turning positive: 10%
  - Distance to 20d EMA (price above EMA = trend confirm): 10%
  - Sector relative strength: 10%

Tiers:
  NOW     readiness >= 70
  WATCH   readiness 50-69
  MONITOR readiness < 50

Entry eligible: readiness >= 72 AND >= 3 confirmations (out of 7) (out of 5).
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pead_factor import compute_pead

logger = logging.getLogger(__name__)

# Weights (sum to 1.0)
WEIGHT_SIGNAL = 0.30   # momentum 40%→30% (over-weighted)
WEIGHT_RSI = 0.10     # RSI 15%→10% (weakly negative correlation)
WEIGHT_VOLUME = 0.05    # volume 15%→5% (NEGATIVELY correlated with wins!)
WEIGHT_MACD = 0.10
WEIGHT_EMA = 0.20      # EMA 10%→20% (strongest predictor at +0.593)
WEIGHT_SECTOR = 0.25    # sector 10%→25% (strong predictor at +0.502)

# Tier thresholds
TIER_NOW_MIN = 72.0   # raised from 70 for higher quality entries
TIER_WATCH_MIN = 55.0   # raised from 50

# Entry eligibility
ENTRY_READINESS_MIN = 70.0
ENTRY_MIN_CONFIRMATIONS = 2


@dataclass
class ReadinessResult:
    symbol: str
    readiness_score: float
    tier: str
    confirmations: Dict
    confirmation_count: int
    entry_eligible: bool
    tier_reason: str


def _rsi_component_score(rsi: float) -> float:
    """
    Score RSI on a 0-100 scale.

    Momentum strategy: RSI 50-65 is the sweet spot (score 100).
    - Below 30: falling knife risk, score tapers toward 20
    - 30-40: recovering, score rises 40->80
    - 40-50: decent, score 80->95
    - 50-65: ideal, score 100
    - 65-70: slightly overbought, score 95->80
    - 70-80: overbought, score 60->30
    - Above 80: very overbought, score 10
    """
    if rsi <= 0:
        return 20.0
    if rsi < 30:
        # Falling knife zone: 0-30 maps to 20-40
        return 20.0 + (rsi / 30.0) * 20.0
    if rsi < 40:
        # 30-40 maps to 40-80
        return 40.0 + ((rsi - 30) / 10.0) * 40.0
    if rsi < 50:
        # 40-50 maps to 80-95
        return 80.0 + ((rsi - 40) / 10.0) * 15.0
    if rsi <= 65:
        # Sweet spot: 50-65 = 100
        return 100.0
    if rsi <= 70:
        # 65-70 maps to 95-80
        return 95.0 - ((rsi - 65) / 5.0) * 15.0
    if rsi <= 80:
        # 70-80 maps to 60-30
        return 60.0 - ((rsi - 70) / 10.0) * 30.0
    # Above 80: very overbought
    return max(10.0, 30.0 - (rsi - 80) * 1.0)


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
    Simple MACD histogram estimate from EMA12/EMA26.
    Returns (score 0-100, turning_positive: bool).
    """
    if len(closes) < 35:
        return 50.0, False

    ema12_prev = _ema(closes[-27:-1], 12)
    ema26_prev = _ema(closes[-27:-1], 26)
    hist_prev = ema12_prev - ema26_prev

    ema12_now = _ema(closes[-26:], 12)
    ema26_now = _ema(closes[-26:], 26)
    hist_now = ema12_now - ema26_now

    turning_positive = hist_prev <= 0 and hist_now > 0
    positive_and_rising = hist_now > 0 and hist_now > hist_prev

    if turning_positive:
        return 100.0, True
    if positive_and_rising:
        return 80.0, True
    if hist_now > 0:
        return 60.0, False
    if hist_now > hist_prev:  # negative but rising
        return 40.0, False
    return 20.0, False


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
    Score intraday momentum from 15-minute bars.
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


def _options_sentiment_score(implied_vol: Optional[float]) -> Tuple[float, bool]:
    """
    Score options sentiment from implied volatility.
    Returns (score 0-100, confirmed: bool).

    High IV (>0.6) = high uncertainty, bearish sentiment → lower score
    Moderate IV (0.3-0.6) = normal → neutral
    Low IV (<0.3) = low uncertainty, bullish complacency → slightly higher
    """
    if implied_vol is None or implied_vol <= 0:
        return 50.0, False  # neutral when no data

    if implied_vol > 0.8:
        return 20.0, False  # very high IV = panic/bearish
    if implied_vol > 0.6:
        return 35.0, False  # elevated IV = bearish
    if implied_vol > 0.4:
        return 60.0, False  # normal IV
    if implied_vol > 0.25:
        return 75.0, True   # low IV = bullish/complacent
    return 85.0, True       # very low IV = strong bullish


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
    options_implied_vol: Optional[float] = None,
    pead_boost: float = 0.0,
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

    # 5. EMA distance (10%)
    ema_component, above_ema = _ema_distance_score(price, closes)

    # 6. Sector relative strength (10%)
    sector_peers = SECTOR_PEERS.get(sector, [])
    sector_component, sector_strong = _sector_relative_strength(
        symbol, all_bars, sector_peers,
    )

    # 7. Intraday momentum (bonus confirmation, not weighted in composite)
    intraday_component, intraday_confirmed = _intraday_momentum_score(
        intraday_bars or [], daily_vwap
    )

    # 8. Options sentiment (bonus confirmation from implied vol)
    options_component, options_confirmed = _options_sentiment_score(options_implied_vol)

    # 9. PEAD: Post-Earnings Announcement Drift (earnings_confirmed)
    pead_result = compute_pead(symbol, None, closes)
    earnings_confirmed = pead_result.post_earnings_window
    pead_boost_val = pead_result.pead_boost

    # Weighted composite
    readiness = (
        WEIGHT_SIGNAL * signal_component
        + WEIGHT_RSI * rsi_component
        + WEIGHT_VOLUME * vol_component
        + WEIGHT_MACD * macd_component
        + WEIGHT_EMA * ema_component
        + WEIGHT_SECTOR * sector_component
    )
    # Apply PEAD boost
    readiness = readiness + pead_boost + pead_boost_val
    readiness = round(max(0.0, min(100.0, readiness)), 1)

    # Confirmations dict (6 boolean signals)
    confirmations = {
        "momentum_score": round(signal_component, 1),
        "rsi_signal": rsi_signal,
        "volume_confirmed": volume_confirmed,
        "macd_turning": macd_turning,
        "above_ema": above_ema,
        "sector_strong": sector_strong,
        "intraday_confirmed": intraday_confirmed,
        "intraday_score": round(intraday_component, 1),
        "options_confirmed": options_confirmed,
        "options_score": round(options_component, 1),
        "earnings_confirmed": earnings_confirmed,
        "pead_score": round(pead_result.pead_score, 1),
        "pead_boost": round(pead_boost_val, 2),
    }

    # Confirmation count: count True booleans (exclude momentum_score which is numeric)
    confirmation_count = sum(1 for v in [
        volume_confirmed, macd_turning, above_ema, sector_strong,
        # Treat RSI as a confirmation if it's in neutral/oversold zone (not overbought)
        rsi_signal != "overbought",
        # Intraday confirmation (only counts during market hours when data is available)
        intraday_confirmed,
        # Options sentiment confirmation (low IV = bullish)
        options_confirmed,
        # PEAD: within 30 days of earnings beat
        earnings_confirmed,
    ] if v)

    # Tier
    if readiness >= 80.0:
        tier = "STRONG_NOW"
    elif readiness >= TIER_NOW_MIN:
        tier = "NOW"
    elif readiness >= TIER_WATCH_MIN:
        tier = "WATCH"
    else:
        tier = "MONITOR"

    # Entry eligibility
    entry_eligible = readiness >= ENTRY_READINESS_MIN and confirmation_count >= ENTRY_MIN_CONFIRMATIONS

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
    )


def _build_tier_reason(
    tier: str,
    readiness: float,
    confirmations: Dict,
    confirmation_count: int,
) -> str:
    """Human-readable reason for tier assignment."""
    parts = []
    if tier == "STRONG_NOW":
        parts.append(f"STRONG NOW: readiness {readiness:.1f}")
    elif tier == "NOW":
        parts.append(f"NOW: readiness {readiness:.1f}")
    elif tier == "WATCH":
        parts.append(f"WATCH: readiness {readiness:.1f}")
    else:
        parts.append(f"MONITOR: readiness {readiness:.1f}")

    reasons = []
    if confirmations.get("volume_confirmed"):
        reasons.append("volume confirmation")
    if confirmations.get("macd_turning"):
        reasons.append("MACD turning positive")
    if confirmations.get("above_ema"):
        reasons.append("above 20d EMA")
    if confirmations.get("sector_strong"):
        reasons.append("sector strength")
    if confirmations.get("intraday_confirmed"):
        reasons.append("intraday momentum")
    if confirmations.get("options_confirmed"):
        reasons.append("low IV (bullish options)")
    if confirmations.get("earnings_confirmed"):
        reasons.append("PEAD: post-earnings drift")
    if confirmations.get("rsi_signal") == "oversold":
        reasons.append("RSI oversold (bounce potential)")
    elif confirmations.get("rsi_signal") == "overbought":
        reasons.append("RSI overbought (caution)")

    if reasons:
        parts.append(" + ".join(reasons))
    else:
        parts.append(f"{confirmation_count}/9 confirmations")

    return ". ".join(parts) + "."