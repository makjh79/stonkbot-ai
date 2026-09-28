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

# v3 2026-08-01: single source of truth for strategy parameters
from strategy_config import (
    ENTRY_READINESS_MIN,
    ENTRY_MIN_CONFIRMATIONS,
    ENTRY_MIN_HARD_CONFIRMATIONS,
    HARD_CONFIRMATION_KEYS,
    REQUIRED_POSITIVE_HARD_KEYS,
    REQUIRED_POSITIVE_FALLBACK_BUNDLES,
)


# -----------------------------------------------------------------------------
# Positive-edge entry gate with fallbacks
# -----------------------------------------------------------------------------
def has_required_positive_edge(confirmations):
    """V3 positive-edge gate with fallback paths.

    2026-09-05 redesign: if both REQUIRED_POSITIVE_HARD_KEYS and fallback bundles
    are empty in strategy_config, this requirement is disabled and the function
    returns True.  This lets the candidate score's own entry gate control entries
    without duplicating logic here.

    Legacy behavior: primary VWAP, or volume+options, or intraday+relvol+above_ema.
    """
    if not confirmations:
        return False
    # Candidate-mode short-circuit: no positive-edge requirement configured.
    if not REQUIRED_POSITIVE_HARD_KEYS and not REQUIRED_POSITIVE_FALLBACK_BUNDLES:
        return True
    if any(confirmations.get(k) for k in REQUIRED_POSITIVE_HARD_KEYS):
        return True
    for bundle in REQUIRED_POSITIVE_FALLBACK_BUNDLES:
        if all(confirmations.get(k) for k in bundle):
            return True
    return False

# -----------------------------------------------------------------------------
# Tier thresholds (backend names)
# -----------------------------------------------------------------------------
# 2026-09-05: raised for candidate signal redesign — fewer, higher-conviction tiers.
TIER_STRONG_NOW_MIN = 80.0
TIER_NOW_MIN = 75.0
TIER_WATCH_MIN = 65.0        # raised from 50

# Minimum readiness for any "scored" frontend visibility (BUILDING/READY)
TIER_BUILDING_MIN = TIER_WATCH_MIN

# Entry gate — imported from strategy_config (single source of truth)
# ENTRY_READINESS_MIN, ENTRY_MIN_CONFIRMATIONS, ENTRY_MIN_HARD_CONFIRMATIONS
# are now defined in strategy_config.py and imported above.

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

# HARD_CONFIRMATION_KEYS and V3_REQUIRED_POSITIVE_KEYS imported from strategy_config

# -----------------------------------------------------------------------------
# Tier naming
# -----------------------------------------------------------------------------
TIER_DISPLAY_MAP: Dict[str, str] = {
    "STRONG_NOW": "PRIME",
    "NOW": "BUILDING",
    "WATCH": "READY",
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
    """Return short labels of active chips, matching the UI factor chips.
    v3 2026-08-01: MACD and INT are display-only (not used for entry gate).
    They are marked with * in narrative text.

    2026-09-05: for entry-gate language use entry_confirmation_labels()."""
    labels = {
        "momentum_score": "MOM",
        "rsi_signal": "RSI",
        "volume_confirmed": "VOL",
        "macd_turning": "MACD*",   # display-only, not used for entry (v3)
        "above_ema": "EMA",
        "sector_strong": "SEC",
        "intraday_confirmed": "INT*",  # display-only, not used for entry (v3)
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


# 2026-09-05: labels that are actual pillars of the candidate-score entry gate.
ENTRY_CONFIRMATION_LABELS: Dict[str, str] = {
    "momentum_score": "MOM",
    "rsi_signal": "RSI",
    "above_ema": "EMA",
    "spread_ok": "SPR",
    "no_corporate_action_risk": "CA",
}

# 2026-09-05: labels that are display-only (tracked for transparency but removed from entry gate).
DISPLAY_ONLY_CONFIRMATION_LABELS: Dict[str, str] = {
    "volume_confirmed": "VOL",
    "macd_turning": "MACD",
    "sector_strong": "SEC",
    "intraday_confirmed": "INT",
    "options_confirmed": "OPT",
    "relvol_confirmed": "RVOL",
    "vwap_confirmed": "VWAP",
    "momentum_5m_up": "5M",
    "near_term_bullish_flow": "OF",
    "bid_ask_bullish": "QBI",
}


def _chip_active(test, value) -> bool:
    try:
        return bool(test(value))
    except Exception:
        return False


def entry_confirmation_labels(confirmations: Optional[Dict[str, Any]]) -> list[str]:
    """Return labels of confirmation chips that are active entry pillars."""
    if not confirmations:
        return []
    return [
        label
        for key, label in ENTRY_CONFIRMATION_LABELS.items()
        if key in confirmations and key in CONFIRMATION_CHIPS
        and _chip_active(CONFIRMATION_CHIPS[key], confirmations[key])
    ]


def display_only_confirmation_labels(confirmations: Optional[Dict[str, Any]]) -> list[str]:
    """Return labels of active display-only chips (not used for entry gate)."""
    if not confirmations:
        return []
    return [
        label
        for key, label in DISPLAY_ONLY_CONFIRMATION_LABELS.items()
        if key in confirmations and key in CONFIRMATION_CHIPS
        and _chip_active(CONFIRMATION_CHIPS[key], confirmations[key])
    ]


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
    confirmations: Optional[Dict[str, Any]] = None,
) -> bool:
    """Canonical entry eligibility gate.

    Matches the logic in readiness_score.py / trading_bot.py.
    When a symbol has very strong confirmation breadth (>=7), we relax the hard-
    confirm requirement to 1.
    v3 2026-08-01: requires at least one positive-edge hard confirmation
    bundle (VWAP, or volume+trend+options/relvol, or intraday+relvol+trend)
    when confirmations dict is available.
    """
    min_hard = 1 if confirmation_count >= 7 else ENTRY_MIN_HARD_CONFIRMATIONS
    # v3: use the same positive-edge helper as readiness_score.py/trading_bot.py
    _has_positive = True  # default True for backward compat when confirmations not provided
    if confirmations is not None:
        _has_positive = has_required_positive_edge(confirmations)
    return (
        above_ema
        and readiness >= ENTRY_READINESS_MIN
        and confirmation_count >= ENTRY_MIN_CONFIRMATIONS
        and hard_confirmations >= min_hard
        and _has_positive
    )


def tier_reason_prefix(backend_tier: str) -> str:
    """Return the frontend display prefix used in tier_reason strings."""
    return assign_tier(backend_tier) + ":"


def expected_display_tier_for_signal(signal: Dict[str, Any]) -> str:
    """Given a signal dict, return the expected frontend display tier."""
    backend_tier = signal.get("tier") or compute_backend_tier(signal.get("readiness_score", 0))
    return assign_tier(backend_tier, signal.get("entry_eligible", False))


# -----------------------------------------------------------------------------
# Canonical sector taxonomy (2026-07-18)
# -----------------------------------------------------------------------------
# Split the overloaded "Consumer/Platform" bucket (was ~34% of the book, which
# made sector trims fire constantly) into coherent groups. Also deduplicated:
# every symbol appears in exactly one bucket (previously UBER/ABNB/EXPE/SPOT/
# ROKU/PINS/SHOP were in both Technology and Consumer/Platform).
_SECTOR_BUCKETS: Dict[str, Iterable[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "CRM", "ORCL", "ADBE", "INTU", "IBM", "INTC", "SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW", "NET", "DDOG", "OKTA", "PATH", "PLTR"],
    "Semiconductors": ["AMD", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON", "AVGO", "TXN"],
    "Cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "CYBR", "S"],
    "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY", "PYPL", "FIS", "V", "GS", "MS", "BLK", "SCHW"],
    "Travel/Mobility": ["UBER", "ABNB", "EXPE"],
    "E-Commerce": ["SHOP", "ETSY", "CHWY"],
    "Media/Entertainment": ["ROKU", "SPOT", "PINS", "SNAP", "TTD", "APP", "DKNG", "NFLX", "DUOL"],
    "Consumer Brands": ["ELF", "LULU", "NKE", "COST", "WMT", "HD"],
    "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
    "Healthcare": ["UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "VRTX", "BMY", "REGN", "GILD", "ISRG", "ZBH", "ILMN", "SGEN"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY"],
    "Industrials": ["GE", "CAT", "UNP", "HON", "UPS", "RTX", "LMT", "DE"],
    "Financials": ["JPM", "BAC", "WFC"],
    "Communications/Media": ["DIS", "CMCSA", "TMUS", "CHTR", "WBD", "PARA"],
}

SECTOR_MAP: Dict[str, str] = {}
for _sector_name, _symbols in _SECTOR_BUCKETS.items():
    for _sym in _symbols:
        SECTOR_MAP[_sym] = _sector_name


def sector_for(symbol: str) -> str:
    """Canonical sector lookup. All sector resolution must go through here."""
    return SECTOR_MAP.get(symbol, "Other")
