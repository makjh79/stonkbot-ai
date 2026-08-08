"""strategy_config.py — Single source of truth for all strategy parameters.

Every module that needs a strategy constant MUST import from here.
Never hardcode strategy values in individual files.

When you change a strategy parameter, change it HERE and only here.
Then run: python3 -c "import strategy_config; strategy_config.validate()"
"""
from typing import Dict, Any, Set, List

# =============================================================================
# Entry Gate
# =============================================================================
ENTRY_READINESS_MIN: float = 75.0
ENTRY_MIN_CONFIRMATIONS: int = 5
ENTRY_MIN_HARD_CONFIRMATIONS: int = 1
ENTRY_HARD_CONFIRMATIONS_STRICT: int = 2  # when total chips < 7
ENTRY_HARD_CONFIRMATIONS_STRICT_BELOW: int = 7  # threshold for strict mode
ENTRY_ABOVE_EMA_REQUIRED: bool = True
ENTRY_TRADEABLE_TIER: str = "STRONG_NOW"

# =============================================================================
# Hard Confirmation Keys (v3 2026-08-08)
# Evidence-based: only factors with positive live edge are hard confirmations.
# REMOVED: macd_turning (live edge -15.5pp), intraday_confirmed (-8.9pp)
# REQUIRED: both vwap_confirmed AND options_confirmed (the two strongest live edges).
# volume_confirmed and relvol_confirmed remain positive chips but are no longer
# sufficient on their own for the positive-edge gate.
# =============================================================================
HARD_CONFIRMATION_KEYS: Set[str] = {
    "volume_confirmed",
    "options_confirmed",
    "vwap_confirmed",
    "relvol_confirmed",
}

# ALL of these MUST be True for entry.  v3 evidence: VWAP (+28pp) and options
# flow (+11pp) are the only confirmed positive-edge hard confirmations.
REQUIRED_POSITIVE_HARD_KEYS: Set[str] = {
    "vwap_confirmed",
    "options_confirmed",
}

# Display-only keys: still computed and shown in UI, but NOT used for entry
DISPLAY_ONLY_CONFIRMATION_KEYS: Set[str] = {
    "macd_turning",
    "intraday_confirmed",
}

# =============================================================================
# Position Caps by Tier
# =============================================================================
TIER_MAX_POSITION_PCT: Dict[str, float] = {
    "STRONG_NOW": 0.12,
    "NOW": 0.08,
    "WATCH": 0.08,
    "MONITOR": 0.08,
}
MAX_SINGLE_POSITION_PCT: float = 0.12
MAX_SECTOR_PCT: float = 0.25

# =============================================================================
# Stop Parameters
# =============================================================================
HARD_STOP_ATR_MULTIPLIER: float = 1.5
HARD_STOP_MIN_PCT: float = 0.05       # v3: widened from 3% to 5% on 2026-08-01
HARD_STOP_MAX_PCT: float = 0.11
TRAILING_STOP_PCT: float = -0.10
TRAILING_STOP_ATR_MULTIPLIER: float = 2.0
TRAILING_STOP_MIN_PCT: float = 0.05   # v3: widened from 3% to 5%
TRAILING_STOP_MAX_PCT: float = 0.14
ABS_HARD_CUT_PCT: float = -0.05      # v3: widened from -3% to -5%
VWAP_STOP_MAX_PCT: float = 0.02
VWAP_STOP_ATR_MULTIPLIER: float = 1.0

# =============================================================================
# Profit-Taking (v3 ATR Scale-Out)
# =============================================================================
V3_SCALEOUT_ENABLED: bool = True
V3_SCALEOUT_T1_ATR: float = 1.0       # first scale-out: +1x ATR, sell 1/3
V3_SCALEOUT_T2_ATR: float = 2.0       # second scale-out: +2x ATR, sell 1/3
V3_SCALEOUT_FRACTION: float = 0.33    # fraction to sell at each level
TRIM_PROFIT_PCT: float = 0.25          # legacy trim at +25%
FULL_EXIT_PROFIT_PCT: float = 0.50     # full exit at +50%

# =============================================================================
# Position Management
# =============================================================================
MIN_HOLD_DAYS: Dict[str, int] = {
    "RISK_ON": 5,
    "RISK_OFF": 3,
    "CRISIS": 0,
}
ROTATION_ENABLED: bool = False          # disabled 2026-08-01
THESIS_BROKEN_GATED_BY_MIN_HOLD: bool = True

# =============================================================================
# Cash & Risk Guardrails
# =============================================================================
CASH_FLOOR_PCT: float = 0.10
ENTRY_CASH_BUFFER_PCT: float = 0.12
HIGH_BETA_BASKET_CAP_PCT: float = 0.35
PORTFOLIO_DD_HALT_PCT: float = -0.10

# =============================================================================
# Gates
# =============================================================================
EARNINGS_BLACKOUT_DAYS: int = 2
IMPLIED_MOVE_MAX_ATR_MULT: float = 1.5
IMPLIED_MOVE_WINDOW_DAYS: tuple = (3, 7)
REENTRY_COOLDOWN_DAYS: int = 7
ATR_ENTRY_MAX_PCT: float = 0.07

# =============================================================================
# Validation
# =============================================================================
def validate() -> List[str]:
    """Check that all parameters are internally consistent. Returns list of issues."""
    issues = []
    if HARD_STOP_MIN_PCT > HARD_STOP_MAX_PCT:
        issues.append(f"HARD_STOP_MIN_PCT ({HARD_STOP_MIN_PCT}) > HARD_STOP_MAX_PCT ({HARD_STOP_MAX_PCT})")
    if TRAILING_STOP_MIN_PCT > TRAILING_STOP_MAX_PCT:
        issues.append(f"TRAILING_STOP_MIN_PCT ({TRAILING_STOP_MIN_PCT}) > TRAILING_STOP_MAX_PCT ({TRAILING_STOP_MAX_PCT})")
    if not REQUIRED_POSITIVE_HARD_KEYS.issubset(HARD_CONFIRMATION_KEYS):
        issues.append(f"REQUIRED_POSITIVE_HARD_KEYS {REQUIRED_POSITIVE_HARD_KEYS} not subset of HARD_CONFIRMATION_KEYS {HARD_CONFIRMATION_KEYS}")
    if DISPLAY_ONLY_CONFIRMATION_KEYS & HARD_CONFIRMATION_KEYS:
        issues.append(f"DISPLAY_ONLY keys overlap with HARD keys: {DISPLAY_ONLY_CONFIRMATION_KEYS & HARD_CONFIRMATION_KEYS}")
    for regime, days in MIN_HOLD_DAYS.items():
        if days < 0:
            issues.append(f"MIN_HOLD_DAYS[{regime}] is negative: {days}")
    if V3_SCALEOUT_T1_ATR >= V3_SCALEOUT_T2_ATR:
        issues.append(f"V3_SCALEOUT_T1_ATR ({V3_SCALEOUT_T1_ATR}) >= V3_SCALEOUT_T2_ATR ({V3_SCALEOUT_T2_ATR})")
    if not (0 < V3_SCALEOUT_FRACTION < 1):
        issues.append(f"V3_SCALEOUT_FRACTION ({V3_SCALEOUT_FRACTION}) not in (0, 1)")
    return issues


def export_for_website() -> Dict[str, Any]:
    """Export strategy parameters as a dict suitable for config_truth.json."""
    return {
        "entry_gate": {
            "readiness_min": ENTRY_READINESS_MIN,
            "confirmations_min": ENTRY_MIN_CONFIRMATIONS,
            "hard_confirmations_min": ENTRY_MIN_HARD_CONFIRMATIONS,
            "hard_confirmations_min_strict": ENTRY_HARD_CONFIRMATIONS_STRICT,
            "hard_confirmations_strict_when_below": ENTRY_HARD_CONFIRMATIONS_STRICT_BELOW,
            "above_ema": ENTRY_ABOVE_EMA_REQUIRED,
            "tradeable_tier": ENTRY_TRADEABLE_TIER,
            "hard_confirmation_keys": sorted(HARD_CONFIRMATION_KEYS),
            "hard_confirmation_note": "v3: macd_turning and intraday_confirmed REMOVED (negative live edge). At least one of volume OR vwap required.",
        },
        "position_management": {
            "rotation_enabled": ROTATION_ENABLED,
            "min_hold_days": MIN_HOLD_DAYS,
            "thesis_broken_exit": "gated by min_hold_days" if THESIS_BROKEN_GATED_BY_MIN_HOLD else "immediate",
            "profit_taking": f"v3 ATR scale-out: 1/3 at +{V3_SCALEOUT_T1_ATR:.0f}x ATR, 1/3 at +{V3_SCALEOUT_T2_ATR:.0f}x ATR, then trim at +{TRIM_PROFIT_PCT:.0%}; full exit at +{FULL_EXIT_PROFIT_PCT:.0%}",
            "v3_scaleout": {
                "enabled": V3_SCALEOUT_ENABLED,
                "tier_1": f"+{V3_SCALEOUT_T1_ATR:.0f}x ATR, sell {V3_SCALEOUT_FRACTION:.0%}",
                "tier_2": f"+{V3_SCALEOUT_T2_ATR:.0f}x ATR, sell {V3_SCALEOUT_FRACTION:.0%}",
            },
        },
        "caps": TIER_MAX_POSITION_PCT,
        "stops": {
            "trailing": f"{TRAILING_STOP_ATR_MULTIPLIER}x ATR from peak",
            "hard": f"{HARD_STOP_ATR_MULTIPLIER}x ATR",
            "abs_cut": f"max({ABS_HARD_CUT_PCT:.0%}, 1x ATR)",
            "vwap": f"max({VWAP_STOP_MAX_PCT:.0%}, 1x ATR) below VWAP",
        },
        # Raw values for the website Risk Guardrails panel — the panel renders
        # from these so it can never drift from strategy_config.py.
        "guardrails": {
            "hard_stop_atr_mult": HARD_STOP_ATR_MULTIPLIER,
            "hard_stop_min_pct": HARD_STOP_MIN_PCT,
            "hard_stop_max_pct": HARD_STOP_MAX_PCT,
            "trailing_stop_atr_mult": TRAILING_STOP_ATR_MULTIPLIER,
            "trailing_stop_min_pct": TRAILING_STOP_MIN_PCT,
            "trailing_stop_max_pct": TRAILING_STOP_MAX_PCT,
            "max_sector_pct": MAX_SECTOR_PCT,
            "cash_floor_pct": CASH_FLOOR_PCT,
            "entry_cash_buffer_pct": ENTRY_CASH_BUFFER_PCT,
            "atr_entry_max_pct": ATR_ENTRY_MAX_PCT,
            "earnings_blackout_days": EARNINGS_BLACKOUT_DAYS,
            "implied_move_max_atr_mult": IMPLIED_MOVE_MAX_ATR_MULT,
            "high_beta_basket_cap_pct": HIGH_BETA_BASKET_CAP_PCT,
        },
    }


if __name__ == "__main__":
    issues = validate()
    if issues:
        print("VALIDATION FAILED:")
        for i in issues:
            print(f"  - {i}")
        raise SystemExit(1)
    else:
        print("strategy_config.py: all validations passed")
        import json
        print(json.dumps(export_for_website(), indent=2))
