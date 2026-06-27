"""
Post-Earnings Announcement Drift (PEAD) Factor

Captures the well-documented anomaly: stocks that beat earnings estimates
drift higher for 30-60 days post-announcement. This is real alpha that
pure momentum strategies miss.

Score decay:
  Days 1-10 post-beat:  score 80-100 (strong drift window)
  Days 11-20 post-beat: score 50-80  (drift continues, tapering)
  Days 21-30 post-beat: score 20-50  (diminishing edge)
  Days 30+ post-beat:   score 0      (edge expired)

If earnings surprise data is unavailable, price reaction is used as proxy:
stock rose >2% on earnings day → treated as "beat".

Data source: signal_enrichment.json earnings field, populated by signal_enricher.py
Format per symbol:
  {
    "period": "2026-03-31",
    "quarter": 2,
    "year": 2026,
    "estimate": 1.9884,
    "actual": 2.01,
    "surprise": 0.0216,
    "surprise_pct": 1.0863,
    "direction": "beat"   # "beat" | "miss" | "inline"
  }
"""

import json
import logging
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

ENRICHMENT_PATH = Path("/opt/stonk-ai/signal_enrichment.json")
MAX_WINDOW_DAYS = 30


from dataclasses import dataclass


@dataclass
class PEADResult:
    """PEAD factor result for a single symbol."""
    symbol: str
    days_since_earnings: Optional[int]
    earnings_direction: Optional[str]  # "beat" | "miss" | "inline" | None
    earnings_surprise_pct: Optional[float]
    post_earnings_window: bool  # within 30 days of a beat
    pead_score: float  # 0-100
    pead_boost: float  # readiness points to add (0 if no boost)

    def to_dict(self) -> Dict:
        return {
            "days_since_earnings": self.days_since_earnings,
            "earnings_direction": self.earnings_direction,
            "earnings_surprise_pct": round(self.earnings_surprise_pct, 2) if self.earnings_surprise_pct is not None else None,
            "post_earnings_window": self.post_earnings_window,
            "pead_score": round(self.pead_score, 2),
            "pead_boost": round(self.pead_boost, 2),
        }


def _load_enrichment(path: Path = ENRICHMENT_PATH) -> Dict:
    """Load signal_enrichment.json and return the data dict."""
    try:
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f).get("data", {})
    except Exception as e:
        logger.warning(f"Could not load enrichment for PEAD: {e}")
        return {}


def _days_since_period(period_str: str) -> Optional[int]:
    """Estimate days since earnings announcement.

    Finnhub provides fiscal quarter end date, not actual announcement date.
    Most US companies report 30-45 days after quarter end.
    We use period + 35 days as estimated announcement date.
    """
    try:
        from datetime import timedelta as _td
        period_date = datetime.strptime(period_str, "%Y-%m-%d").date()
        estimated_announcement = period_date + _td(days=35)
        today = date.today()
        delta = (today - estimated_announcement).days
        return max(0, delta) if delta >= 0 else None
    except Exception:
        return None


def _pead_score_for_beat(days: int) -> float:
    """
    Compute PEAD score for a confirmed beat, decaying over 30 days.

    Days 1-10:  100 → 80  (strong drift, linear taper)
    Days 11-20: 80  → 50  (drift continues, tapering)
    Days 21-30: 50  → 10  (diminishing edge)
    Days 30+:   0          (edge expired)
    """
    if days <= 0 or days > MAX_WINDOW_DAYS:
        return 0.0
    if days <= 10:
        # 100 at day 1, 80 at day 10 — linear taper
        return 100.0 - (days - 1) * 2.0
    if days <= 20:
        # 80 at day 10, 50 at day 20
        return 80.0 - (days - 10) * 3.0
    # days 21-30: 50 → 10
    return max(0.0, 50.0 - (days - 20) * 4.0)


def _pead_boost_from_score(score: float) -> float:
    """
    Map PEAD score to readiness boost points.
    Boost range: 0-10 points added to readiness score.
    Score 100 → +10 boost
    Score 80  → +8 boost
    Score 50  → +5 boost
    Score 20  → +2 boost
    Score 0   → 0 boost
    """
    return max(0.0, min(10.0, score * 0.10))


def compute_pead(
    symbol: str,
    enrichment_data: Optional[Dict] = None,
    closes: Optional[list] = None,
) -> PEADResult:
    """
    Compute PEAD factor for a single symbol.

    Parameters
    ----------
    symbol : str
        Stock ticker.
    enrichment_data : dict, optional
        Enrichment entry for this symbol (from signal_enrichment.json).
        If None, will load from disk.
    closes : list, optional
        Daily close prices for price-reaction proxy (used if earnings
        direction is not available from enrichment data).
    """
    if enrichment_data is None:
        all_data = _load_enrichment()
        enrichment_data = all_data.get(symbol, {})

    earnings = enrichment_data.get("earnings", {}) if enrichment_data else {}
    if not earnings:
        # No earnings data — check if we have closes for price-reaction proxy
        if closes and len(closes) >= 2:
            # Can't determine earnings day without the period; return zero
            pass
        return PEADResult(
            symbol=symbol,
            days_since_earnings=None,
            earnings_direction=None,
            earnings_surprise_pct=None,
            post_earnings_window=False,
            pead_score=0.0,
            pead_boost=0.0,
        )

    direction = earnings.get("direction")
    surprise_pct = earnings.get("surprise_pct", 0)
    period = earnings.get("period", "")

    days_since = _days_since_period(period)

    if days_since is None:
        return PEADResult(
            symbol=symbol,
            days_since_earnings=None,
            earnings_direction=direction,
            earnings_surprise_pct=surprise_pct,
            post_earnings_window=False,
            pead_score=0.0,
            pead_boost=0.0,
        )

    # Determine if this was a "beat" — either from API or price reaction proxy
    is_beat = False

    if direction == "beat":
        is_beat = True
    elif direction == "miss":
        is_beat = False
    elif closes and len(closes) >= 2 and days_since <= 5:
        # Price reaction proxy: if stock rose >2% on earnings day (approximated
        # by looking at the most recent closes), treat as beat
        # This is a rough proxy — we check 1-day return
        recent_return = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
        if recent_return > 0.02:
            is_beat = True

    # Compute score
    if is_beat and days_since <= MAX_WINDOW_DAYS:
        score = _pead_score_for_beat(days_since)
        boost = _pead_boost_from_score(score)
    elif not is_beat and days_since <= MAX_WINDOW_DAYS:
        # Miss → negative drift: no boost, slight penalty won't be applied here
        # (the readiness score naturally handles this via lower momentum)
        score = 0.0
        boost = 0.0
    else:
        score = 0.0
        boost = 0.0

    post_window = is_beat and days_since <= MAX_WINDOW_DAYS

    return PEADResult(
        symbol=symbol,
        days_since_earnings=days_since,
        earnings_direction=direction,
        earnings_surprise_pct=surprise_pct,
        post_earnings_window=post_window,
        pead_score=score,
        pead_boost=boost,
    )


def compute_pead_batch(
    symbols: list,
    enrichment_path: Path = ENRICHMENT_PATH,
) -> Dict[str, PEADResult]:
    """
    Compute PEAD factor for a batch of symbols.
    Loads enrichment data once and computes for all symbols.

    Returns dict: {symbol: PEADResult}
    """
    all_data = _load_enrichment(enrichment_path)
    results = {}
    for sym in symbols:
        e = all_data.get(sym, {})
        results[sym] = compute_pead(sym, e)
    return results