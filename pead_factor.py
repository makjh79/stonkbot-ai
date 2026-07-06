"""PEAD factor — DROPPED.

Alpaca has no earnings data API. Factor removed for zero external dependencies.
Sector strength (30% weight) replaces this factor — it had higher correlation with P&L anyway.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class PEADResult:
    symbol: str = ""
    days_since_earnings: Optional[int] = None
    earnings_direction: Optional[str] = None
    earnings_surprise_pct: Optional[float] = None
    post_earnings_window: bool = False
    pead_score: float = 0.0
    pead_boost: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "days_since_earnings": None,
            "earnings_direction": None,
            "earnings_surprise_pct": None,
            "post_earnings_window": False,
            "pead_score": 0.0,
            "pead_boost": 0.0,
        }


def compute_pead(symbol=None, enrichment_data=None, closes=None):
    """DEPRECATED: PEAD dropped. Returns zero result."""
    return PEADResult(symbol=symbol or "")


def compute_pead_batch(symbols=None, enrichment_path=None):
    """DEPRECATED: PEAD dropped. Returns empty results."""
    return {}
