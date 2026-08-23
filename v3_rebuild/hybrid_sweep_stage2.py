#!/usr/bin/env python3
"""
STONK.AI v3 HYBRID — Stage-2 focused optimization sweep.

Uses proper_backtest_hybrid.run_backtest as the engine.
Generates up to 30 variants, logs them, saves JSON/CSV/PNG, and commits successes.

Selection rule:
  Primary: maximize total_return subject to
    sharpe >= 1.0, max_drawdown <= 0.15, trades >= 200
  Fallback (no variant beats QQQ +55.56%): maximize sharpe subject to same constraints.

Early stop if any variant reaches total_return >= 0.80 AND sharpe >= 1.2 AND max_dd <= 0.15.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any

from proper_backtest_hybrid import run_backtest, log_to_csv, DEFAULT_CONFIG

REPORT_DIR = Path("/opt/stonk-ai/reports")
REPO_ROOT = Path("/opt/stonk-ai")

LAST_KNOWN = 25
MAX_VARIANTS = LAST_KNOWN + 30
EARLY_STOP_RETURN = 0.80
EARLY_STOP_SHARPE = 1.20
EARLY_STOP_DD = 0.15

QQQ_RETURN = 0.5555652610661019

# Frontier starting configs
V19 = {
    "mom_trend_filter": "ema20_ema50",
    "mom_entry_timing": "breakout",
    "mom_base_pct": 0.06,
    "mom_strong_cap_pct": 0.20,
    "mom_profit_take": "trailing_only",
    "mom_regimes": ["RISK_ON"],
    "mom_rsi_low": 45,
    "mom_rsi_high": 80,
    "mom_min_ret20d": 0.0,
    "mom_max_positions": 30,
    "pb_threshold": 0.50,
    "pb_max_positions": 20,
    "pb_base_pct": 0.03,
    "pb_strong_cap_pct": 0.12,
    "pb_regimes": ["RISK_ON"],
    "cash_floor_pct": 0.0,
    "entry_buffer_pct": 0.0,
    "drawdown_halt_pct": 1.0,
    "hard_stop_atr_mult": 1.5,
    "trailing_stop_atr_mult": 2.0,
}

V13 = {
    "mom_trend_filter": "ema20_ema50",
    "mom_entry_timing": "breakout",
    "mom_base_pct": 0.05,
    "mom_strong_cap_pct": 0.20,
    "mom_profit_take": "scaleout_1_3",
    "mom_regimes": ["RISK_ON"],
    "mom_rsi_low": 45,
    "mom_rsi_high": 80,
    "mom_min_ret20d": 0.0,
    "mom_max_positions": 30,
    "pb_threshold": 0.45,
    "pb_max_positions": 30,
    "pb_base_pct": 0.03,
    "pb_strong_cap_pct": 0.12,
    "pb_regimes": ["RISK_ON"],
    "cash_floor_pct": 0.0,
    "entry_buffer_pct": 0.0,
    "drawdown_halt_pct": 1.0,
    "hard_stop_atr_mult": 1.5,
    "trailing_stop_atr_mult": 2.0,
}

V24 = {
    "mom_trend_filter": "ema20_ema50",
    "mom_entry_timing": "breakout",
    "mom_base_pct": 0.05,
    "mom_strong_cap_pct": 0.15,
    "mom_profit_take": "trailing_only",
    "mom_regimes": ["RISK_ON"],
    "mom_rsi_low": 45,
    "mom_rsi_high": 80,
    "mom_min_ret20d": 0.0,
    "mom_max_positions": 30,
    "pb_threshold": 0.45,
    "pb_max_positions": 20,
    "pb_base_pct": 0.03,
    "pb_strong_cap_pct": 0.12,
    "pb_regimes": ["RISK_ON"],
    "cash_floor_pct": 0.05,
    "entry_buffer_pct": 0.05,
    "drawdown_halt_pct": 0.10,
    "hard_stop_atr_mult": 1.2,
    "trailing_stop_atr_mult": 1.5,
}

# Shared static levers not directly varied
STATIC = {
    "mom_use_rank": True,
    "pb_use_rank": True,
    "pb_rsi_max": 75,
    "pb_dist_ema200_min": -0.15,
    "sector_cap_pct": 0.25,
    "hard_stop_min_pct": 0.05,
    "hard_stop_max_pct": 0.11,
    "trailing_stop_min_pct": 0.05,
    "trailing_stop_max_pct": 0.14,
    "scaleout_t1_atr": 0.5,
    "scaleout_t2_atr": 1.0,
    "scaleout_frac": 1 / 3.0,
    "full_exit_profit_pct": 0.30,
}

LEVER_OPTIONS = {
    "mom_base_pct": [0.04, 0.05, 0.06, 0.07],
    "mom_strong_cap_pct": [0.15, 0.18, 0.20, 0.25],
    "mom_max_positions": [20, 25, 30, 40],
    "pb_max_positions": [10, 15, 20, 25],
    "cash_floor_pct": [0.00, 0.03, 0.05],
    "entry_buffer_pct": [0.00, 0.03, 0.05],
    "mom_entry_timing": ["breakout", "pullback_5ema", "pullback_10d_low"],
    "mom_trend_filter": ["ema20_ema50", "ema20_ema200", "price_52w_high"],
    "mom_profit_take": ["trailing_only", "scaleout_1_4_at_1_0_2_0_atr", "scaleout_1_3_at_0_5_1_0_atr"],
    "mom_rsi_band": [(45, 80), (50, 80), (50, 75), (55, 80)],
    "pb_threshold": [0.45, 0.50, 0.60],
    "hard_stop_atr_mult": [1.0, 1.1, 1.2, 1.3],
    "trailing_stop_atr_mult": [1.3, 1.5, 1.8, 2.0],
    "mom_min_ret20d": [0.0, 0.05, 0.10],
}

PROFIT_TAKE_MAP = {
    "trailing_only": "trailing_only",
    "scaleout_1_4_at_1_0_2_0_atr": "scaleout_1_4",
    "scaleout_1_3_at_0_5_1_0_atr": "scaleout_1_3",
}


def make_config(template: Dict[str, Any], levers: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg.update(deepcopy(STATIC))
    cfg.update(deepcopy(template))

    for k, v in levers.items():
        if k == "mom_rsi_band":
            cfg["mom_rsi_low"] = v[0]
            cfg["mom_rsi_high"] = v[1]
        elif k == "mom_profit_take":
            cfg["mom_profit_take"] = PROFIT_TAKE_MAP[v]
        else:
            cfg[k] = v

    # Sensible caps and floors dependent on other choices
    # If trailing_only and scaleout thresholds don't apply, keep defaults.
    if cfg["mom_profit_take"] == "scaleout_1_4":
        cfg["scaleout_t1_atr"] = 1.0
        cfg["scaleout_t2_atr"] = 2.0
        cfg["scaleout_frac"] = 0.25
    elif cfg["mom_profit_take"] == "scaleout_1_3":
        cfg["scaleout_t1_atr"] = 0.5
        cfg["scaleout_t2_atr"] = 1.0
        cfg["scaleout_frac"] = 1 / 3.0

    # Adjust stop bounds for tighter/looser hard stop so the ATR multiple actually matters
    cfg["hard_stop_max_pct"] = max(cfg["hard_stop_max_pct"], cfg["hard_stop_atr_mult"] * 0.05 + 0.01)
    cfg["trailing_stop_max_pct"] = max(cfg["trailing_stop_max_pct"], cfg["trailing_stop_atr_mult"] * 0.05 + 0.01)

    # If strong cap is close to base, promote strong cap to at least base + 3%
    if cfg["mom_strong_cap_pct"] <= cfg["mom_base_pct"]:
        cfg["mom_strong_cap_pct"] = cfg["mom_base_pct"] + 0.03

    return cfg


def config_fingerprint(cfg: Dict[str, Any]) -> str:
    keys = sorted(k for k in cfg if k not in ("methodology",))
    return json.dumps({k: cfg[k] for k in keys}, sort_keys=True)


def focused_combinations():
    """Return an ordered list of lever combinations that explore the frontier."""
    combos: List[Dict[str, Any]] = []

    def add(**levers):
        combos.append(levers)

    # Start from v19: the high-return candidate. Try to fix its 15.2% DD while keeping alpha.
    # 1-8: strong cap / sizing / stops around v19
    add(mom_base_pct=0.05, mom_strong_cap_pct=0.18, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.03, entry_buffer_pct=0.03, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.18, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.03, entry_buffer_pct=0.03, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)
    add(mom_base_pct=0.05, mom_strong_cap_pct=0.20, mom_max_positions=40, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)

    # v13 route: more trades, better Sharpe. Loosen/tighten thresholds and sizing.
    add(mom_base_pct=0.05, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=25,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=25,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)
    add(mom_base_pct=0.05, mom_strong_cap_pct=0.18, mom_max_positions=30, pb_max_positions=25,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(50, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)

    # v24 route: safer DD, lower return. Push sizing/cap up while keeping 5% cash/buffer.
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.18, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.07, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)

    # Trend filter experiments on v19 backbone
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema200", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="price_52w_high", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)

    # Entry timing experiments (requires base sizing tuned down a bit because timing reduces entries)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="pullback_5ema",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="pullback_10d_low",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)

    # Profit-taking / stop mixes
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_4_at_1_0_2_0_atr", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)

    # RSI band / min ret20d experiments
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(50, 75),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.05)

    # Mixed v19+v24 with moderate cash and looser pullback
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=25,
        cash_floor_pct=0.03, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)
    add(mom_base_pct=0.07, mom_strong_cap_pct=0.25, mom_max_positions=30, pb_max_positions=25,
        cash_floor_pct=0.03, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)

    # Tight risk v24-style but with higher base sizing
    add(mom_base_pct=0.07, mom_strong_cap_pct=0.18, mom_max_positions=25, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(50, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.0, trailing_stop_atr_mult=1.3, mom_min_ret20d=0.05)

    # Aggressive v19 with 40 slots
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.25, mom_max_positions=40, pb_max_positions=25,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.45, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)

    # Best-of-both attempt: v19 sizing + v24 risk controls + scaleouts
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.03, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(45, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)

    # Additional frontier combos
    add(mom_base_pct=0.05, mom_strong_cap_pct=0.25, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45, 80),
        pb_threshold=0.60, hard_stop_atr_mult=1.5, trailing_stop_atr_mult=2.0, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=25, pb_max_positions=15,
        cash_floor_pct=0.03, entry_buffer_pct=0.03, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(50, 80),
        pb_threshold=0.50, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)

    # De-duplicate by fingerprint while preserving order
    seen = set()
    unique = []
    for levers in combos:
        # Determine implied base template (v19 default unless tight risk controls)
        cfg = make_config(V19, levers)
        fp = config_fingerprint(cfg)
        if fp not in seen:
            seen.add(fp)
            unique.append(levers)
    return unique[:30]


def notes_from_levers(levers: Dict[str, Any]) -> str:
    parts = []
    for k in ["mom_base_pct", "mom_strong_cap_pct", "mom_max_positions", "pb_max_positions",
              "cash_floor_pct", "entry_buffer_pct", "mom_entry_timing", "mom_trend_filter",
              "mom_profit_take", "mom_rsi_band", "pb_threshold", "hard_stop_atr_mult",
              "trailing_stop_atr_mult", "mom_min_ret20d"]:
        v = levers.get(k)
        if v is None:
            continue
        if k == "mom_rsi_band":
            parts.append(f"rsi{v[0]}-{v[1]}")
        elif k == "mom_profit_take":
            parts.append(v.replace("_", " "))
        elif k == "mom_entry_timing":
            parts.append(v)
        elif k == "mom_trend_filter":
            parts.append(v.replace("_", "/"))
        else:
            if isinstance(v, float):
                parts.append(f"{k}={v:.0%}" if v < 1 else f"{k}={v:.1f}")
            else:
                parts.append(f"{k}={v}")
    return " | ".join(parts)


def commit_variant(variant: str, result: Dict[str, Any]):
    msg = (
        f"hybrid variant {variant}: ret {result['total_return']:.2%}, "
        f"sharpe {result['sharpe_ratio']:.2f}, maxdd {-result['max_drawdown']:.2%}, "
        f"trades {result['number_of_trades']}"
    )
    files = [
        str(REPORT_DIR / f"v3_hybrid_{variant}_backtest_20260823.json"),
        str(REPORT_DIR / f"v3_hybrid_{variant}_equity_20260823.csv"),
        str(REPORT_DIR / f"v3_hybrid_{variant}_equity_20260823.png"),
        str(REPORT_DIR / "hybrid_iteration_log.csv"),
    ]
    try:
        subprocess.run(["git", "-C", str(REPO_ROOT), "add"] + files, check=True)
        subprocess.run(["git", "-C", str(REPO_ROOT), "commit", "-m", msg], check=True)
        print(f"Committed {variant}")
    except subprocess.CalledProcessError as e:
        print(f"Git commit failed for {variant}: {e}")


def score_variant(result: Dict[str, Any]) -> float:
    """Higher is better under primary objective (return within constraints)."""
    ret = result["total_return"]
    sharpe = result["sharpe_ratio"]
    dd = result["max_drawdown"]
    trades = result["number_of_trades"]
    feasible = sharpe >= 1.0 and dd <= 0.15 and trades >= 200
    if not feasible:
        # Heavily penalize infeasible; but still keep track for fallback Sharpe sorting
        return -1e6 + sharpe * 100 - dd * 1000 + trades / 100
    return ret  # feasible -> raw return is the objective


def main():
    combos = focused_combinations()
    print(f"Running up to {len(combos)} focused combinations (variants v{LAST_KNOWN+1:02d} ... v{MAX_VARIANTS:02d})")

    results: List[Dict[str, Any]] = []
    seen_fingerprints: set = set()

    # Load existing fingerprints to avoid re-running
    for v in range(1, LAST_KNOWN + 1):
        path = REPORT_DIR / f"v3_hybrid_v{v:02d}_backtest_20260823.json"
        if path.exists():
            with open(path) as f:
                existing = json.load(f)
            seen_fingerprints.add(config_fingerprint(existing["config"]))

    variant_num = LAST_KNOWN
    early_stop = False

    for levers in combos:
        variant_num += 1
        if variant_num > MAX_VARIANTS:
            break
        variant = f"v{variant_num:02d}"

        cfg = make_config(V19, levers)
        fp = config_fingerprint(cfg)
        if fp in seen_fingerprints:
            print(f"Skipping duplicate {variant}")
            variant_num -= 1
            continue
        seen_fingerprints.add(fp)

        notes = notes_from_levers(levers)
        try:
            out = run_backtest(cfg, variant=variant)
            result = out["result"]
        except Exception as e:
            print(f"Variant {variant} FAILED: {e}")
            continue

        # Append to log
        log_to_csv(result, notes=notes)
        results.append(result)

        # Commit
        commit_variant(variant, result)

        # Early stop check
        if (result["total_return"] >= EARLY_STOP_RETURN and
                result["sharpe_ratio"] >= EARLY_STOP_SHARPE and
                result["max_drawdown"] <= EARLY_STOP_DD):
            print(f"EARLY STOP: {variant} meets all stretch goals")
            early_stop = True
            break

    # Also read in all previous variants for final ranking
    all_results: List[Dict[str, Any]] = []
    for v in range(1, variant_num + 1):
        path = REPORT_DIR / f"v3_hybrid_v{v:02d}_backtest_20260823.json"
        if path.exists():
            with open(path) as f:
                all_results.append(json.load(f))

    feasible = [r for r in all_results if r["sharpe_ratio"] >= 1.0 and r["max_drawdown"] <= 0.15 and r["number_of_trades"] >= 200]

    # Primary target
    if feasible:
        feasible.sort(key=lambda r: -r["total_return"])
        best_return = feasible[0]
    else:
        best_return = None

    # Sharpe within constraints
    if feasible:
        sharpe_sorted = sorted(feasible, key=lambda r: -r["sharpe_ratio"])
        best_sharpe = sharpe_sorted[0]
    else:
        best_sharpe = None

    # Beats QQQ check
    beats_qqq = [r for r in feasible if r["total_return"] > QQQ_RETURN]
    if not beats_qqq:
        # fallback: maximize sharpe across feasible already computed
        pass

    # Pareto frontier: not dominated by another feasible variant on return, sharpe, and DD
    def dominates(a, b):
        return (a["total_return"] >= b["total_return"] and
                a["sharpe_ratio"] >= b["sharpe_ratio"] and
                a["max_drawdown"] <= b["max_drawdown"] and
                (a["total_return"] > b["total_return"] or
                 a["sharpe_ratio"] > b["sharpe_ratio"] or
                 a["max_drawdown"] < b["max_drawdown"]))

    pareto = [r for r in feasible if not any(dominates(other, r) for other in feasible if other["variant"] != r["variant"])]
    pareto.sort(key=lambda r: -r["total_return"])

    summary = {
        "total_variants_run": len(results),
        "early_stopped": early_stop,
        "best_by_return": best_return,
        "best_by_sharpe": best_sharpe,
        "pareto_frontier": pareto,
        "all_feasible": feasible,
    }

    summary_path = REPORT_DIR / "hybrid_stage2_summary_20260823.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== STAGE 2 SUMMARY ===")
    print(f"Variants run this stage: {len(results)}")
    if best_return:
        print(f"Best return (feasible): {best_return['variant']} -> {best_return['total_return']:.2%} ret, {best_return['sharpe_ratio']:.3f} sharpe, {-best_return['max_drawdown']:.2%} dd, {best_return['number_of_trades']} trades")
    if best_sharpe:
        print(f"Best sharpe (feasible): {best_sharpe['variant']} -> {best_sharpe['total_return']:.2%} ret, {best_sharpe['sharpe_ratio']:.3f} sharpe, {-best_sharpe['max_drawdown']:.2%} dd, {best_sharpe['number_of_trades']} trades")
    print(f"Pareto frontier variants: {[r['variant'] for r in pareto]}")

    # Recommend: if a feasible variant beats QQQ, pick the feasible best-by-return; else pick best sharpe.
    if best_return and best_return["total_return"] > QQQ_RETURN:
        recommended = best_return
    elif best_sharpe:
        recommended = best_sharpe
    else:
        recommended = None

    if recommended:
        print(f"\nRECOMMENDED ALPHA SETUP: {recommended['variant']}")
        print(json.dumps(recommended["config"], indent=2))

    return summary


if __name__ == "__main__":
    main()
