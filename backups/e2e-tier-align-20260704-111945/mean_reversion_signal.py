"""
Mean Reversion Signal Engine

Scans the stock universe for oversold conditions with volume capitulation.
Uncorrelated to momentum — finds bounce candidates when momentum is weak.

Entry criteria (all must be true):
  - RSI < 35 (oversold)
  - Price > 5% below 20d EMA (stretched)
  - Volume spike: recent 5d avg > 1.3x 20d avg (capitulation/buying interest)
  - NOT structural decline: 50d EMA must be flat or rising (not declining)

Score (0-100):
  - RSI component (40%): lower RSI = higher score
  - EMA distance (25%): further below EMA = higher score
  - Volume spike (20%): bigger spike = higher score
  - Trend filter (15%): above 50d EMA = higher score
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Entry thresholds
RSI_OVERSOLD_MAX = 35.0
EMA_DISCOUNT_MIN = 0.05  # price must be at least 5% below 20d EMA
VOLUME_SPIKE_MIN = 1.3   # recent 5d vol must be 1.3x the 20d avg

# Score weights
WEIGHT_RSI = 0.40
WEIGHT_EMA = 0.25
WEIGHT_VOLUME = 0.20
WEIGHT_TREND = 0.15


@dataclass
class MeanReversionSignal:
    symbol: str
    reversion_score: float
    rsi14: float
    ema_distance_pct: float
    volume_ratio: float
    above_50d_ema: bool
    entry_eligible: bool
    strategy_type: str = "mean_reversion"
    readiness_score: float = 0.0  # mapped from reversion_score for bot compatibility
    tier: str = "MONITOR"
    confirmations: Dict = None
    confirmation_count: int = 0
    entry_eligible_mr: bool = False
    tier_reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "strategy_type": "mean_reversion",
            "reversion_score": round(self.reversion_score, 2),
            "total_score": round(self.reversion_score, 2),  # for bot compatibility
            "readiness_score": round(self.readiness_score, 2),
            "rsi14": round(self.rsi14, 2),
            "ema_distance_pct": round(self.ema_distance_pct, 4),
            "volume_ratio": round(self.volume_ratio, 2),
            "above_50d_ema": self.above_50d_ema,
            "entry_eligible": self.entry_eligible,
            "tier": self.tier,
            "confirmations": self.confirmations or {},
            "confirmation_count": self.confirmation_count,
            "tier_reason": self.tier_reason,
            "momentum_score": 0.0,  # placeholder for bot compatibility
            "quality_score": 0.0,
            "risk_score": 0.0,
            "regime_score": 0.0,
            "macd_hist": 0.0,
            "above_ema20": False,  # MR signals are below EMA by design
            "sector_strong": False,
            "volume_confirmed": self.volume_ratio >= VOLUME_SPIKE_MIN,
        }


def compute_mean_reversion(
    symbol: str,
    closes: List[float],
    volumes: List[float],
    price: float,
    rsi14: float,
) -> Optional[MeanReversionSignal]:
    """
    Compute mean reversion signal for a single stock.
    Returns None if the stock doesn't meet minimum criteria.
    """
    if len(closes) < 50 or len(volumes) < 20 or price <= 0:
        return None

    # 1. RSI check
    if rsi14 >= RSI_OVERSOLD_MAX:
        return None  # not oversold enough

    # 2. EMA distance
    ema20 = _ema(closes[-20:], 20)
    if ema20 <= 0:
        return None
    ema_distance_pct = (ema20 - price) / ema20  # positive = below EMA
    if ema_distance_pct < EMA_DISCOUNT_MIN:
        return None  # not stretched enough below EMA

    # 3. Volume spike
    if len(volumes) >= 20:
        recent_vol = sum(volumes[-5:]) / 5
        avg_vol_20 = sum(volumes[-20:]) / 20
    else:
        recent_vol = avg_vol_20 = sum(volumes) / max(len(volumes), 1)
    volume_ratio = recent_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0
    if volume_ratio < VOLUME_SPIKE_MIN:
        return None  # no volume capitulation

    # 4. Trend filter — don't catch falling knives
    ema50 = _ema(closes[-50:], 50)
    ema50_prev = _ema(closes[-51:-1], 50) if len(closes) >= 51 else ema50
    above_50d_ema = price > ema50
    ema50_declining = ema50 < ema50_prev

    # If price is below 50d EMA AND 50d EMA is declining — structural decline, skip
    if not above_50d_ema and ema50_declining:
        return None

    # --- Score components ---

    # RSI component (40%): RSI 0-35 maps to score 100-50
    # Lower RSI = higher score
    rsi_component = max(0.0, min(100.0, 100 - (rsi14 / RSI_OVERSOLD_MAX) * 50))

    # EMA distance component (25%): 5-15% below = 50-100
    # Further below = higher score (more stretched)
    ema_component = max(0.0, min(100.0, (ema_distance_pct - EMA_DISCOUNT_MIN) / 0.10 * 50 + 50))

    # Volume spike component (20%): 1.3x = 50, 2.0x = 100
    vol_component = max(0.0, min(100.0, (volume_ratio - 1.0) / 1.0 * 50 + 25))
    if volume_ratio >= 2.0:
        vol_component = 100.0

    # Trend filter component (15%): above 50d EMA = 100, below but EMA flat = 60
    if above_50d_ema:
        trend_component = 100.0
    else:
        trend_component = 60.0  # below 50d EMA but not declining

    # Weighted score
    reversion_score = (
        WEIGHT_RSI * rsi_component
        + WEIGHT_EMA * ema_component
        + WEIGHT_VOLUME * vol_component
        + WEIGHT_TREND * trend_component
    )
    reversion_score = round(max(0.0, min(100.0, reversion_score)), 2)

    # Map to readiness_score for bot compatibility
    readiness_score = reversion_score

    # Entry eligible: mean reversion is NOT a live entry trigger.
    # It flags oversold bounce candidates for the watchlist only.
    # The canonical entry_eligible flag comes from the momentum readiness gate (77/5/above_ema).
    entry_eligible = False
    entry_eligible_mr = reversion_score >= 65.0 and volume_ratio >= VOLUME_SPIKE_MIN

    # Tier
    if readiness_score >= 70:
        tier = "NOW"
    elif readiness_score >= 50:
        tier = "WATCH"
    else:
        tier = "MONITOR"

    # Confirmations
    confirmations = {
        "rsi_oversold": rsi14 < RSI_OVERSOLD_MAX,
        "below_ema_stretched": ema_distance_pct >= EMA_DISCOUNT_MIN,
        "volume_capitulation": volume_ratio >= VOLUME_SPIKE_MIN,
        "not_structural_decline": above_50d_ema or not ema50_declining,
        "above_ema50": above_50d_ema,
    }
    confirmation_count = sum(1 for v in confirmations.values() if v)

    # Tier reason
    reasons = []
    if confirmations["rsi_oversold"]:
        reasons.append(f"RSI oversold ({rsi14:.1f})")
    if confirmations["below_ema_stretched"]:
        reasons.append(f"{ema_distance_pct*100:.1f}% below 20d EMA")
    if confirmations["volume_capitulation"]:
        reasons.append(f"volume spike {volume_ratio:.1f}x")
    if confirmations["not_structural_decline"]:
        reasons.append("not in structural decline")
    tier_reason = "Mean reversion: " + ", ".join(reasons) + "."

    return MeanReversionSignal(
        symbol=symbol,
        reversion_score=reversion_score,
        rsi14=rsi14,
        ema_distance_pct=ema_distance_pct,
        volume_ratio=volume_ratio,
        above_50d_ema=above_50d_ema,
        entry_eligible=entry_eligible,
        readiness_score=readiness_score,
        tier=tier,
        confirmations=confirmations,
        confirmation_count=confirmation_count,
        tier_reason=tier_reason,
        entry_eligible_mr=entry_eligible_mr,
    )


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