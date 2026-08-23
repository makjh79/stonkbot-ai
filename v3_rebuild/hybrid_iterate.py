#!/usr/bin/env python3
"""
Autonomous iteration driver for the v3 HYBRID engine.
Runs up to 20 distinct variants and stops immediately when a success
threshold is met.

Each successful variant is committed to git with a message containing the
variant number and headline return.
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any

from proper_backtest_hybrid import DEFAULT_CONFIG, run_variant, meets_threshold

V3_DIR = Path("/opt/stonk-ai/v3_rebuild")
REPORT_DIR = Path("/opt/stonk-ai/reports")


def git_commit(variant: str, ret: float, sharpe: float, dd: float):
    """Commit the variant report and chart."""
    try:
        subprocess.run(
            ["git", "-C", str(V3_DIR.parent), "add", f"reports/v3_hybrid_{variant}_backtest_*.json"],
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(V3_DIR.parent), "add", f"reports/v3_hybrid_{variant}_equity_*.png"],
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(V3_DIR.parent), "add", "reports/hybrid_iteration_log.csv"],
            check=False,
        )
        msg = f"hybrid variant {variant}: ret {ret:.2%}, sharpe {sharpe:.2f}, maxdd {-dd:.2%}"
        r = subprocess.run(
            ["git", "-C", str(V3_DIR.parent), "commit", "-m", msg],
            capture_output=True,
            text=True,
        )
        print(r.stdout)
        if r.returncode != 0:
            print("git commit warning:", r.stderr)
    except Exception as e:
        print(f"git commit failed: {e}")


def make_config(
    base: Dict,
    mom_trend_filter: str = None,
    mom_entry_timing: str = None,
    mom_base_pct: float = None,
    mom_strong_cap_pct: float = None,
    mom_profit_take: str = None,
    mom_regimes: List[str] = None,
    mom_rsi_band: Tuple[int, int] = None,
    mom_min_ret20d: float = None,
    mom_max_positions: int = None,
    pb_regimes: List[str] = None,
    pb_threshold: float = None,
    pb_base_pct: float = None,
    pb_strong_cap_pct: float = None,
    pb_max_positions: int = None,
    cash_floor_pct: float = None,
    entry_buffer_pct: float = None,
    drawdown_halt_pct: float = None,
) -> Dict:
    cfg = deepcopy(base)
    if mom_trend_filter is not None:
        cfg["mom_trend_filter"] = mom_trend_filter
    if mom_entry_timing is not None:
        cfg["mom_entry_timing"] = mom_entry_timing
    if mom_base_pct is not None:
        cfg["mom_base_pct"] = mom_base_pct
    if mom_strong_cap_pct is not None:
        cfg["mom_strong_cap_pct"] = mom_strong_cap_pct
    if mom_profit_take is not None:
        cfg["mom_profit_take"] = mom_profit_take
    if mom_regimes is not None:
        cfg["mom_regimes"] = mom_regimes
    if mom_rsi_band is not None:
        cfg["mom_rsi_low"] = mom_rsi_band[0]
        cfg["mom_rsi_high"] = mom_rsi_band[1]
    if mom_min_ret20d is not None:
        cfg["mom_min_ret20d"] = mom_min_ret20d
    if mom_max_positions is not None:
        cfg["mom_max_positions"] = mom_max_positions
    if pb_regimes is not None:
        cfg["pb_regimes"] = pb_regimes
    if pb_threshold is not None:
        cfg["pb_threshold"] = pb_threshold
    if pb_base_pct is not None:
        cfg["pb_base_pct"] = pb_base_pct
    if pb_strong_cap_pct is not None:
        cfg["pb_strong_cap_pct"] = pb_strong_cap_pct
    if pb_max_positions is not None:
        cfg["pb_max_positions"] = pb_max_positions
    if cash_floor_pct is not None:
        cfg["cash_floor_pct"] = cash_floor_pct
    if entry_buffer_pct is not None:
        cfg["entry_buffer_pct"] = entry_buffer_pct
    if drawdown_halt_pct is not None:
        cfg["drawdown_halt_pct"] = drawdown_halt_pct
    return cfg


def build_variant_list() -> List[Tuple[str, Dict, str]]:
    """Return ordered list of (variant, config, notes)."""
    base = DEFAULT_CONFIG
    variants: List[Tuple[str, Dict, str]] = []

    # v01 baseline already run; include it for completeness if needed
    # v02: more aggressive sizing on baseline
    variants.append(("v02", make_config(
        base,
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        pb_base_pct=0.05,
        pb_strong_cap_pct=0.12,
        mom_max_positions=20,
        pb_max_positions=20,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "aggressive sizing 5%/15%, 20 max pos, small buffers"))

    # v03: looser entry timing (breakout)
    variants.append(("v03", make_config(
        base,
        mom_entry_timing="breakout",
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=20,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "breakout timing, aggressive sizing"))

    # v04: also allow momentum in RISK_OFF/CAUTION-ish (regime usage)
    variants.append(("v04", make_config(
        base,
        mom_entry_timing="breakout",
        mom_regimes=["RISK_ON", "RISK_OFF"],
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "momentum in RISK_ON+RISK_OFF, breakout, 5%/15%"))

    # v05: lower min ret20 + breakout
    variants.append(("v05", make_config(
        base,
        mom_entry_timing="breakout",
        mom_min_ret20d=0.0,
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "breakout, min ret20 0%, 5%/15%"))

    # v06: wider RSI band + breakout
    variants.append(("v06", make_config(
        base,
        mom_entry_timing="breakout",
        mom_rsi_band=(45, 80),
        mom_min_ret20d=0.0,
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "breakout, rsi 45-80, min ret20 0%, 5%/15%"))

    # v07: pullback to 10d low instead of breakout
    variants.append(("v07", make_config(
        base,
        mom_entry_timing="pullback_10d_low",
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "pullback to 10d low, 5%/15%, loose buffers"))

    # v08: ema20/ema200 trend filter + breakout
    variants.append(("v08", make_config(
        base,
        mom_trend_filter="ema20_ema200",
        mom_entry_timing="breakout",
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "ema20/ema200 filter, breakout, 5%/15%"))

    # v09: price vs 52w high + breakout
    variants.append(("v09", make_config(
        base,
        mom_trend_filter="price_52w_high",
        mom_entry_timing="breakout",
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "price vs 52w high, breakout, 5%/15%"))

    # v10: trailing only profit taking
    variants.append(("v10", make_config(
        base,
        mom_entry_timing="breakout",
        mom_profit_take="trailing_only",
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "trailing only, breakout, 5%/15%"))

    # v11: combine best sizing + breakout + 0 min ret + wider RSI
    variants.append(("v11", make_config(
        base,
        mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50",
        mom_min_ret20d=0.0,
        mom_rsi_band=(45, 80),
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.20,
        mom_max_positions=25,
        pb_max_positions=15,
        cash_floor_pct=0.02,
        entry_buffer_pct=0.02,
        mom_regimes=["RISK_ON", "RISK_OFF"],
    ), "kitchen sink A: breakout, 0 ret, rsi45-80, 5%/20%, 25 mom slots, momentum in RISK_OFF"))

    # v12: kitchen sink B with pullback_10d_low
    variants.append(("v12", make_config(
        base,
        mom_entry_timing="pullback_10d_low",
        mom_min_ret20d=0.0,
        mom_rsi_band=(45, 80),
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.20,
        mom_max_positions=25,
        pb_max_positions=15,
        cash_floor_pct=0.02,
        entry_buffer_pct=0.02,
    ), "kitchen sink B: pullback 10d low, 0 ret, rsi45-80, 5%/20%, 25 slots"))

    # v13: very aggressive: no cash floor, no buffer, max 30 positions
    variants.append(("v13", make_config(
        base,
        mom_entry_timing="breakout",
        mom_min_ret20d=0.0,
        mom_rsi_band=(45, 80),
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.20,
        mom_max_positions=30,
        pb_max_positions=30,
        cash_floor_pct=0.0,
        entry_buffer_pct=0.0,
        drawdown_halt_pct=1.0,  # effectively disable
        pb_threshold=0.45,
    ), "very aggressive: no buffers, 30 slots, 5%/20%, lower pb threshold"))

    # v14: moderate: 4% base, 12% cap, 18 positions
    variants.append(("v14", make_config(
        base,
        mom_entry_timing="breakout",
        mom_base_pct=0.04,
        mom_strong_cap_pct=0.12,
        mom_max_positions=18,
        pb_max_positions=18,
        cash_floor_pct=0.05,
        entry_buffer_pct=0.05,
    ), "moderate breakout 4%/12%, 18 slots, normal buffers"))

    # v15: pullback module only in RISK_ON, momentum everywhere
    variants.append(("v15", make_config(
        base,
        mom_entry_timing="breakout",
        mom_regimes=["RISK_ON", "RISK_OFF", "CRISIS"],
        pb_regimes=["RISK_ON"],
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=25,
        pb_max_positions=10,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "momentum everywhere, pullback only RISK_ON, 5%/15%"))

    # v16: scaleout 1/4 at +1 ATR
    variants.append(("v16", make_config(
        base,
        mom_entry_timing="breakout",
        mom_profit_take="scaleout_1_4",
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
    ), "scaleout 1/4 at +1 ATR, breakout, 5%/15%"))

    # v17: ema20/ema50 (baseline filter) but no pullback filter = pure breakout
    variants.append(("v17", make_config(
        base,
        mom_trend_filter="ema20_ema50",
        mom_entry_timing="breakout",
        mom_min_ret20d=0.0,
        mom_rsi_band=(50, 75),
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=22,
        pb_max_positions=15,
        cash_floor_pct=0.02,
        entry_buffer_pct=0.02,
    ), "ema20/ema50 pure breakout, 0 ret, 5%/15%, 22 slots"))

    # v18: pullback in CAUTION (RISK_OFF) only, momentum in RISK_ON
    variants.append(("v18", make_config(
        base,
        mom_entry_timing="breakout",
        mom_regimes=["RISK_ON"],
        pb_regimes=["RISK_OFF"],
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=20,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
        pb_threshold=0.45,
    ), "momentum RISK_ON, pullback RISK_OFF, 5%/15%"))

    # v19: highest allocation tested
    variants.append(("v19", make_config(
        base,
        mom_entry_timing="breakout",
        mom_min_ret20d=0.0,
        mom_rsi_band=(45, 80),
        mom_base_pct=0.06,
        mom_strong_cap_pct=0.20,
        mom_max_positions=30,
        pb_max_positions=20,
        cash_floor_pct=0.0,
        entry_buffer_pct=0.0,
        drawdown_halt_pct=1.0,
        mom_profit_take="trailing_only",
    ), "max allocation: 6%/20%, 30 slots, no buffers, trailing only"))

    # v20: final balanced attempt
    variants.append(("v20", make_config(
        base,
        mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50",
        mom_min_ret20d=0.05,
        mom_rsi_band=(55, 80),
        mom_base_pct=0.05,
        mom_strong_cap_pct=0.15,
        mom_max_positions=20,
        pb_max_positions=15,
        cash_floor_pct=0.03,
        entry_buffer_pct=0.03,
        mom_profit_take="scaleout_1_3",
    ), "balanced: breakout, ema20/ema50, ret20>=5%, rsi55-80, 5%/15%"))

    return variants


def main():
    variants = build_variant_list()
    print(f"Prepared {len(variants)} variants. Running until threshold met or budget exhausted.")

    best = None
    best_out = None
    for idx, (variant, cfg, notes) in enumerate(variants, start=2):
        try:
            out = run_variant(cfg, variant, notes=notes)
            result = out["result"]
            git_commit(variant, result["total_return"], result["sharpe_ratio"], result["max_drawdown"])

            if best is None or result["total_return"] > best["total_return"]:
                best = result
                best_out = out

            met, threshold = meets_threshold(result)
            if met:
                print(f"\n🎯 SUCCESS: variant {variant} meets {threshold}")
                print(json.dumps({k: result[k] for k in [
                    "variant", "total_return", "sharpe_ratio", "max_drawdown",
                    "win_rate", "profit_factor", "number_of_trades", "avg_invested_pct"
                ]}, indent=2))
                return result, out
        except Exception as e:
            print(f"ERROR in variant {variant}: {e}")
            import traceback
            traceback.print_exc()

    print("\nBudget exhausted. No variant met threshold.")
    return best, best_out


if __name__ == "__main__":
    best_result, best_out = main()
    if best_result:
        print("\n=== Best variant overall ===")
        print(json.dumps({k: best_result[k] for k in [
            "variant", "total_return", "sharpe_ratio", "max_drawdown",
            "win_rate", "profit_factor", "number_of_trades", "avg_invested_pct"
        ]}, indent=2))
