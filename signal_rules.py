"""Canonical signal/tier/entry rules shared across the StonkBOT.AI pipeline.

This module is the single source of truth for:
  - readiness tier thresholds
  - backend -> frontend tier mapping
  - entry eligibility gate
  - confirmation counting helpers

Any script that needs to know "what tier is this?" or "is this entry eligible?"
should import from here, not re-derive locally.
"""

from typing import Any, Dict, Iterable, Optional

# -----------------------------------------------------------------------------
# Tier thresholds (backend names)
# -----------------------------------------------------------------------------
TIER_STRONG_NOW_MIN = 77.0   # lowered from 78.0 2026-07-13; keeps PRIME reachable
TIER_NOW_MIN = 72.0          # raised from 70 for higher-quality entries
TIER_WATCH_MIN = 55.0        # raised from 50

# Minimum readiness for any "scored" frontend visibility (BUILDING/WATCHING)
TIER_BUILDING_MIN = TIER_WATCH_MIN

# -----------------------------------------------------------------------------
# Entry gate
# -----------------------------------------------------------------------------
ENTRY_READINESS_MIN = 75.0
ENTRY_MIN_CONFIRMATIONS = 5
ENTRY_MIN_HARD_CONFIRMATIONS = 1

# Which confirmation keys count as "hard" for the entry gate.
# These match the hard-confirmation set used by readiness_score.py.
HARD_CONFIRMATION_KEYS = {
    "volume_confirmed",
    "macd_turning",
    "intraday_confirmed",
    "options_confirmed",
    "relvol_confirmed",
}

# -----------------------------------------------------------------------------
# Tier naming
# -----------------------------------------------------------------------------
TIER_DISPLAY_MAP: Dict[str, str] = {
    "STRONG_NOW": "PRIME",
    "NOW": "BUILDING",
    "WATCH": "WATCHING",
    "MONITOR": "TRACKING",
}

DISPLAY_TIER_MAP = {v: k for k, v in TIER_DISPLAY_MAP.items()}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def compute_confirmation_count(confirmations: Optional[Dict[str, Any]]) -> int:
    """Count active boolean confirmations from the canonical confirmations dict.

    Notes:
      - Excludes numeric *_score fields and momentum_score.
      - rsi_signal is a string label; only neutral or oversold count as a confirmation.
      - All other truthy values count as confirmations.
    """
    if not confirmations:
        return 0
    exclude = {"momentum_score", "intraday_score", "options_score", "relvol_score", "vwap_score"}
    count = 0
    for key, value in confirmations.items():
        if key == "momentum_score":
            if value is not None and value >= 50:
                count += 1
            continue
        if key in exclude:
            continue
        if key == "rsi_signal":
            if value in ("neutral", "oversold"):
                count += 1
            continue
        if value:
            count += 1
    return count


def hard_confirmation_count(confirmations: Optional[Dict[str, Any]], hard_keys: Optional[Iterable[str]] = None) -> int:
    """Count hard confirmations used for the entry gate.

    The default hard keys match the canonical intraday/technical confirmations
    emitted by the readiness engine.
    """
    keys = set(hard_keys) if hard_keys is not None else HARD_CONFIRMATION_KEYS
    return sum(1 for k, v in (confirmations or {}).items() if k in keys and v)


def compute_backend_tier(readiness: float) -> str:
    """Return canonical backend tier for a readiness score."""
    if readiness >= TIER_STRONG_NOW_MIN:
        return "STRONG_NOW"
    if readiness >= TIER_NOW_MIN:
        return "NOW"
    if readiness >= TIER_WATCH_MIN:
        return "WATCH"
    return "MONITOR"


def assign_tier(backend_tier: str, entry_eligible: bool = False) -> str:
    """Map backend tier to frontend display tier.

    `entry_eligible` is accepted for API compatibility but no longer changes the
    display tier; tier reflects model conviction, while `entry_eligible` / buy
    status reflect trading intent.
    """
    return TIER_DISPLAY_MAP.get(backend_tier, "TRACKING")


def display_tier_to_backend(display_tier: str) -> str:
    """Reverse frontend display tier to backend tier."""
    return DISPLAY_TIER_MAP.get(display_tier, "MONITOR")


def is_entry_eligible(
    readiness: float,
    confirmation_count: int,
    above_ema: bool,
    hard_confirmations: int = 0,
) -> bool:
    """Canonical entry eligibility gate.

    Matches the logic in readiness_score.py / trading_bot.py.
    When a symbol has very strong confirmation breadth (>=7), we relax the hard-
    confirm requirement to 1.
    """
    min_hard = 1 if confirmation_count >= 7 else ENTRY_MIN_HARD_CONFIRMATIONS
    return (
        above_ema
        and readiness >= ENTRY_READINESS_MIN
        and confirmation_count >= ENTRY_MIN_CONFIRMATIONS
        and hard_confirmations >= min_hard
    )


def tier_reason_prefix(backend_tier: str) -> str:
    """Return the frontend display prefix used in tier_reason strings."""
    return assign_tier(backend_tier) + ":"


def expected_display_tier_for_signal(signal: Dict[str, Any]) -> str:
    """Given a signal dict, return the expected frontend display tier."""
    backend_tier = signal.get("tier") or compute_backend_tier(signal.get("readiness_score", 0))
    return assign_tier(backend_tier, signal.get("entry_eligible", False))
