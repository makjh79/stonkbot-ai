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
TIER_STRONG_NOW_MIN = 76.0   # lowered from 77.0 2026-07-14; PRIME cohort too thin at 77
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

# -----------------------------------------------------------------------------
# Confirmation chips
# -----------------------------------------------------------------------------
# Canonical set of 15 boolean/indicator chips shown in the UI and used by the
# readiness engine.  The confirmation count should reflect *active chips* from
# this set, not every truthy field in the confirmations dict.
CONFIRMATION_CHIPS: Dict[str, Any] = {
    "momentum_score": lambda v: v is not None and v >= 50,
    "rsi_signal": lambda v: v in ("neutral", "oversold"),
    "volume_confirmed": bool,
    "macd_turning": bool,
    "above_ema": bool,
    "sector_strong": bool,
    "intraday_confirmed": bool,
    "options_confirmed": bool,
    "relvol_confirmed": bool,
    "vwap_confirmed": bool,
    "momentum_5m_up": bool,
    "near_term_bullish_flow": bool,
    "spread_ok": bool,
    "bid_ask_bullish": bool,
    "no_corporate_action_risk": bool,
}

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
    """Count active confirmation *chips* from the canonical 15-chip set.

    This intentionally ignores numeric ratio fields like options_call_put_ratio
    or bid_ask_spread_pct that live in the same dict but are not green chips.
    """
    if not confirmations:
        return 0
    count = 0
    for key, test in CONFIRMATION_CHIPS.items():
        if key not in confirmations:
            continue
        value = confirmations[key]
        try:
            if test(value):
                count += 1
        except Exception:
            pass
    return count


def active_confirmation_labels(confirmations: Optional[Dict[str, Any]]) -> list[str]:
    """Return short labels of active chips, matching the UI factor chips."""
    labels = {
        "momentum_score": "MOM",
        "rsi_signal": "RSI",
        "volume_confirmed": "VOL",
        "macd_turning": "MACD",
        "above_ema": "EMA",
        "sector_strong": "SEC",
        "intraday_confirmed": "INT",
        "options_confirmed": "OPT",
        "relvol_confirmed": "RVOL",
        "vwap_confirmed": "VWAP",
        "momentum_5m_up": "5M",
        "near_term_bullish_flow": "OF",
        "spread_ok": "SPR",
        "bid_ask_bullish": "QBI",
        "no_corporate_action_risk": "CA",
    }
    return [labels[k] for k in CONFIRMATION_CHIPS if k in (confirmations or {}) and CONFIRMATION_CHIPS[k](confirmations[k])]


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
