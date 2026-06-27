#!/usr/bin/env python3
"""
STONK.AI Regime Detection Module

Reads market_indices.json (or fetches fresh data from Alpaca data hub)
and determines the current market regime to override risk parameters.

Regime states:
  RISK_ON  — Normal. Full position sizes (8% max), 5% cash floor, NOW+ entries
  RISK_OFF — Defensive. 4% max position, 15% cash floor, STRONG_NOW entries only
  CRISIS   — Extreme. No new entries, 30% cash floor, halve existing position sizes

Trigger conditions:
  RISK_OFF if ANY:
    - Credit spreads widening: LQD/HYG ratio > 1.45
    - SPY closes below its 50-day EMA
    - VIXY change_pct > 5%
    - Yield curve steepening AND credit_signal widening simultaneously

  CRISIS if ANY:
    - VIXY change_pct > 15%
    - Credit spreads (LQD/HYG) > 1.60
    - SPY below 50-day EMA AND credit spreads widening
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MARKET_INDICES_FILE = Path("/opt/stonk-ai/market_indices.json")
REGIME_STATUS_FILE = Path("/var/www/hedge-fund-website/regime_status.json")

# Regime thresholds
CREDIT_SPREAD_RISK_OFF = 1.45
CREDIT_SPREAD_CRISIS = 1.60
VIXY_CHANGE_RISK_OFF = 5.0
VIXY_CHANGE_CRISIS = 15.0
EMA_PERIOD = 50


def _load_market_indices() -> Dict:
    """Load market_indices.json from disk."""
    try:
        if MARKET_INDICES_FILE.exists():
            with open(MARKET_INDICES_FILE) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load market_indices.json: {e}")
    return {}


def _fetch_fresh_regime_data() -> Dict:
    """Fetch fresh regime data from Alpaca data hub."""
    try:
        from alpaca_data import get_data_hub
        hub = get_data_hub()
        snaps = hub.get_snapshots(["VIXY", "SHY", "TLT", "LQD", "HYG"])
        regime = {}
        for sym, snap in snaps.items():
            price = snap.get("price") or 0
            prev_close = snap.get("prev_close") or 0
            regime[sym] = {
                "price": price,
                "prev_close": prev_close,
                "change_pct": ((price - prev_close) / prev_close * 100) if prev_close else 0,
            }
        # Yield curve proxy: SHY/TLT ratio
        shy = regime.get("SHY", {}).get("price", 0)
        tlt = regime.get("TLT", {}).get("price", 0)
        if tlt > 0:
            regime["yield_curve_ratio"] = round(shy / tlt, 4)
            regime["yield_curve_signal"] = "steepening" if (shy / tlt) > 0.3 else "normal"
        # Credit spread proxy: LQD/HYG ratio
        lqd = regime.get("LQD", {}).get("price", 0)
        hyg = regime.get("HYG", {}).get("price", 0)
        if hyg > 0:
            ratio = lqd / hyg
            regime["credit_spread_ratio"] = round(ratio, 4)
            regime["credit_signal"] = "widening" if ratio > 1.3 else "improving"
        return regime
    except Exception as e:
        logger.warning(f"Fresh regime data fetch failed: {e}")
        return {}


def _compute_spy_ema50() -> Tuple[Optional[float], Optional[float]]:
    """
    Fetch SPY daily bars and compute 50-day EMA.
    Returns (current_spy_price, ema50) or (None, None) on failure.
    """
    try:
        from alpaca_data import get_data_hub
        hub = get_data_hub()
        bars = hub.get_daily_bars(["SPY"], days=EMA_PERIOD + 30)
        closes = bars.get("SPY", {}).get("closes", [])
        if len(closes) < EMA_PERIOD:
            logger.warning(f"Not enough SPY closes for EMA{EMA_PERIOD}: {len(closes)}")
            return None, None
        # EMA calculation
        multiplier = 2 / (EMA_PERIOD + 1)
        ema = closes[0]
        for c in closes[1:]:
            ema = (c - ema) * multiplier + ema
        return closes[-1], ema
    except Exception as e:
        logger.warning(f"SPY EMA50 computation failed: {e}")
        return None, None


def _spy_vs_ema50() -> Tuple[str, Optional[float], Optional[float]]:
    """Returns ('above'/'below', spy_price, ema50)."""
    spy_price, ema50 = _compute_spy_ema50()
    if spy_price is None or ema50 is None:
        return "unknown", None, None
    return ("above" if spy_price >= ema50 else "below", spy_price, ema50)


def _regime_params(banner):
    """Map a regime name to risk parameters used by the trading loop."""
    return {
        "RISK_ON":  {"max_position_pct": 8,  "cash_floor_pct": 10,  "min_tier_for_entry": "NOW",       "label": "Normal",    "description": "Full position sizes, normal entry"},
        "RISK_OFF": {"max_position_pct": 4,  "cash_floor_pct": 15, "min_tier_for_entry": "STRONG_NOW", "label": "Defensive", "description": "Reduced position sizes, STRONG_NOW entries only"},
        "CRISIS":   {"max_position_pct": 4,  "cash_floor_pct": 30, "min_tier_for_entry": None,          "label": "Crisis",    "description": "No new entries, high cash floor"},
    }[banner]


def _write_regime_status(regime: str, triggers: List[str], indicators: Dict):
    """Write regime_status.json for website display."""
    params = _regime_params(regime)
    status = {
        "regime": regime,
        "regime_label": params["label"],
        "description": params["description"],
        "max_position_pct": params["max_position_pct"],
        "cash_floor_pct": params["cash_floor_pct"],
        "min_tier_for_entry": params["min_tier_for_entry"],
        "triggers": triggers,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "indicators": indicators,
    }
    try:
        REGIME_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(REGIME_STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not write regime_status.json: {e}")
    return status


def get_regime() -> Dict:
    """
    Determine current market regime.

    Returns dict:
      {
        "regime": "RISK_ON"|"RISK_OFF"|"CRISIS",
        "triggers": [...],
        "indicators": {...},
        "params": {max_position_pct, cash_floor_pct, min_tier_for_entry},
        "timestamp": "...",
      }
    """
    # Try disk first, fall back to fresh fetch
    market_data = _load_market_indices()
    regime_data = market_data.get("regime", {})
    if not regime_data:
        regime_data = _fetch_fresh_regime_data()

    triggers: List[str] = []
    regime = "RISK_ON"

    # --- Extract indicators ---
    credit_spread = regime_data.get("credit_spread_ratio")
    credit_signal = regime_data.get("credit_signal", "")
    vixy_change = regime_data.get("VIXY", {}).get("change_pct", 0)
    yield_curve_signal = regime_data.get("yield_curve_signal", "")

    # SPY vs EMA50
    spy_vs_ema, spy_price, ema50 = _spy_vs_ema50()

    # --- CRISIS checks (highest priority) ---
    if vixy_change > VIXY_CHANGE_CRISIS:
        regime = "CRISIS"
        triggers.append(f"VIXY change {vixy_change:.1f}% > {VIXY_CHANGE_CRISIS}%")

    if credit_spread and credit_spread > CREDIT_SPREAD_CRISIS:
        regime = "CRISIS"
        triggers.append(f"Credit spread {credit_spread:.2f} > {CREDIT_SPREAD_CRISIS}")

    if spy_vs_ema == "below" and credit_signal == "widening":
        regime = "CRISIS"
        triggers.append("SPY below EMA50 AND credit spreads widening")

    # --- RISK_OFF checks (only if not already CRISIS) ---
    if regime != "CRISIS":
        if credit_spread and credit_spread > CREDIT_SPREAD_RISK_OFF:
            regime = "RISK_OFF"
            triggers.append(f"Credit spread {credit_spread:.2f} > {CREDIT_SPREAD_RISK_OFF}")

        if spy_vs_ema == "below":
            regime = "RISK_OFF"
            triggers.append("SPY below 50-day EMA")

        if vixy_change > VIXY_CHANGE_RISK_OFF:
            regime = "RISK_OFF"
            triggers.append(f"VIXY change {vixy_change:.1f}% > {VIXY_CHANGE_RISK_OFF}%")

        if yield_curve_signal == "steepening" and credit_signal == "widening":
            regime = "RISK_OFF"
            triggers.append("Yield curve steepening AND credit spreads widening")

    indicators = {
        "spy_vs_ema50": spy_vs_ema,
        "credit_spread": credit_spread,
        "vixy_change": round(vixy_change, 2),
        "yield_curve": yield_curve_signal,
    }
    if spy_price is not None:
        indicators["spy_price"] = round(spy_price, 2)
    if ema50 is not None:
        indicators["spy_ema50"] = round(ema50, 2)

    params = _regime_params(regime)
    status = _write_regime_status(regime, triggers, indicators)

    result = {
        "regime": regime,
        "triggers": triggers,
        "indicators": indicators,
        "params": {
            "max_position_pct": params["max_position_pct"],
            "cash_floor_pct": params["cash_floor_pct"],
            "min_tier_for_entry": params["min_tier_for_entry"],
        },
        "timestamp": status["timestamp"],
    }
    return result
