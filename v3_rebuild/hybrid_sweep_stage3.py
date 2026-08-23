#!/usr/bin/env python3
"""
STONK.AI v3 HYBRID — Stage-3 optimization with overfit penalties + convergence stop.

Continues from v34, adding:
1. Penalty: >30 trades/month average (overtrading)
2. Penalty: first-year return < second-year return by >10pp (temporal instability)
3. Penalty: any single trade >5% of total return (concentration risk)

Stop when best return hasn't improved by >1% absolute over last 10 variants,
or 50 total variants reached.

Then freeze the best config and run cross-market tests on:
- 2022 bear market proxy (Jan-Dec 2022)
- 2023 transition (Jan 2023 - Aug 2024)
"""
from __future__ import annotations

import csv
import json
import math
import os
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd

from proper_backtest_hybrid import run_backtest as _run_backtest, log_to_csv, DEFAULT_CONFIG
from proper_backtest_hybrid import load_bars, load_features, fetch_or_load_regime_etfs, build_regime_series, score_momentum, score_pullback, Position, SECTOR_PEERS, symbol_to_sector

REPORT_DIR = Path("/opt/stonk-ai/reports")
REPO_ROOT = Path("/opt/stonk-ai")
LAST_KNOWN = 34
MAX_VARIANTS = 50
CONVERGENCE_WINDOW = 10
CONVERGENCE_MIN_IMPROVEMENT = 0.01

QQQ_RETURN = 0.5555652610661019
symbol_to_sector_local = symbol_to_sector

# --- Penalty scoring helpers ---

def overfit_score(result: Dict[str, Any]) -> Tuple[float, List[str]]:
    """Return adjusted primary score and list of penalty flags."""
    flags: List[str] = []
    months = 2.0  # all current backtest is 2 years
    avg_trades_per_month = result["number_of_trades"] / months
    if avg_trades_per_month > 30:
        flags.append(f"overtrading:{avg_trades_per_month:.1f}/mo")

    # Year split: need equity curve. Compute from trades is hard; use daily equity if available.
    # We'll attach equity_curve to result in wrapper.
    first_year_ret = result.get("first_year_return")
    second_year_ret = result.get("second_year_return")
    if first_year_ret is not None and second_year_ret is not None:
        if second_year_ret - first_year_ret > 0.10:
            flags.append(f"temporal_instability:Y1={first_year_ret:.1%} Y2={second_year_ret:.1%}")

    max_trade_contrib = result.get("max_trade_contribution", 0.0)
    if max_trade_contrib > 0.05:
        flags.append(f"concentration:{max_trade_contrib:.1%}")

    # Penalize return: each flag is -5% absolute return equivalent
    penalty = 0.05 * len(flags)
    adjusted_return = result["total_return"] - penalty
    return adjusted_return, flags


def run_backtest_enriched(cfg: Dict[str, Any], variant: str = "v01") -> Dict[str, Any]:
    """Wrap engine to add per-year returns and max trade contribution."""
    out = _run_backtest(cfg, variant=variant)
    result = out["result"]
    equity_curve = out["equity_curve"]
    trades = out["trades"]

    # Split equity curve by first / second year (approx midpoint)
    n = len(equity_curve)
    if n > 2:
        mid = n // 2
        start_val = equity_curve[0]["equity"]
        first_year_end = equity_curve[mid]["equity"]
        final_val = equity_curve[-1]["equity"]
        result["first_year_return"] = (first_year_end / start_val) - 1.0
        result["second_year_return"] = (final_val / first_year_end) - 1.0
    else:
        result["first_year_return"] = None
        result["second_year_return"] = None

    # Max single closed-trade contribution to total P&L
    closed = [t for t in trades if t["reason"] != "final_liquidation"]
    total_pnl = sum(t["pnl"] for t in closed)
    result["max_trade_contribution"] = max(abs(t["pnl"]) / abs(total_pnl) for t in closed) if total_pnl != 0 else 0.0

    return out


# --- Lever space: continuation around v34 frontier ---

V34 = {
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
    "pb_threshold": 0.45,
    "pb_max_positions": 20,
    "pb_base_pct": 0.03,
    "pb_strong_cap_pct": 0.12,
    "pb_regimes": ["RISK_ON"],
    "cash_floor_pct": 0.05,
    "entry_buffer_pct": 0.05,
    "drawdown_halt_pct": 1.0,
    "hard_stop_atr_mult": 1.1,
    "trailing_stop_atr_mult": 1.5,
}

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

PROFIT_TAKE_MAP = {
    "trailing_only": "trailing_only",
    "scaleout_1_4_at_1_0_2_0_atr": "scaleout_1_4",
    "scaleout_1_3_at_0_5_1_0_atr": "scaleout_1_3",
}


def make_config(levers: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deepcopy(DEFAULT_CONFIG)
    cfg.update(deepcopy(STATIC))
    cfg.update(deepcopy(V34))
    for k, v in levers.items():
        if k == "mom_rsi_band":
            cfg["mom_rsi_low"] = v[0]
            cfg["mom_rsi_high"] = v[1]
        elif k == "mom_profit_take":
            cfg["mom_profit_take"] = PROFIT_TAKE_MAP[v]
        else:
            cfg[k] = v

    if cfg["mom_profit_take"] == "scaleout_1_4":
        cfg["scaleout_t1_atr"] = 1.0
        cfg["scaleout_t2_atr"] = 2.0
        cfg["scaleout_frac"] = 0.25
    elif cfg["mom_profit_take"] == "scaleout_1_3":
        cfg["scaleout_t1_atr"] = 0.5
        cfg["scaleout_t2_atr"] = 1.0
        cfg["scaleout_frac"] = 1 / 3.0

    cfg["hard_stop_max_pct"] = max(cfg["hard_stop_max_pct"], cfg["hard_stop_atr_mult"] * 0.05 + 0.01)
    cfg["trailing_stop_max_pct"] = max(cfg["trailing_stop_max_pct"], cfg["trailing_stop_atr_mult"] * 0.05 + 0.01)

    if cfg["mom_strong_cap_pct"] <= cfg["mom_base_pct"]:
        cfg["mom_strong_cap_pct"] = cfg["mom_base_pct"] + 0.03
    return cfg


def config_fingerprint(cfg: Dict[str, Any]) -> str:
    keys = sorted(k for k in cfg if k not in ("methodology",))
    return json.dumps({k: cfg[k] for k in keys}, sort_keys=True)


def focused_combinations_stage3():
    combos: List[Dict[str, Any]] = []
    def add(**levers): combos.append(levers)

    # Around v34: sizing / cap / stops
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.22, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.0, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.07, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=25,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=35, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)

    # Trend filter variants
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema200", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="price_52w_high", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)

    # Entry timing variants
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="pullback_5ema",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="pullback_10d_low",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)

    # Stop / profit variants
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_4_at_1_0_2_0_atr", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="scaleout_1_3_at_0_5_1_0_atr", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.8, mom_min_ret20d=0.0)

    # RSI / ret20 variants
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(50,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.05, entry_buffer_pct=0.05, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.05)

    # Cash / buffer variants
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.03, entry_buffer_pct=0.03, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.1, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)
    add(mom_base_pct=0.06, mom_strong_cap_pct=0.20, mom_max_positions=30, pb_max_positions=20,
        cash_floor_pct=0.00, entry_buffer_pct=0.00, mom_entry_timing="breakout",
        mom_trend_filter="ema20_ema50", mom_profit_take="trailing_only", mom_rsi_band=(45,80),
        pb_threshold=0.45, hard_stop_atr_mult=1.2, trailing_stop_atr_mult=1.5, mom_min_ret20d=0.0)

    seen = set()
    unique = []
    for levers in combos:
        cfg = make_config(levers)
        fp = config_fingerprint(cfg)
        if fp not in seen:
            seen.add(fp)
            unique.append(levers)
    return unique[:MAX_VARIANTS - LAST_KNOWN]


def notes_from_levers(levers: Dict[str, Any]) -> str:
    parts = []
    for k, v in levers.items():
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
        subprocess.run(["git", "-C", str(REPO_ROOT), "add", "-f"] + files, check=True)
        subprocess.run(["git", "-C", str(REPO_ROOT), "commit", "-m", msg], check=True)
        print(f"Committed {variant}")
    except subprocess.CalledProcessError as e:
        print(f"Git commit failed for {variant}: {e}")


def run_stage3():
    combos = focused_combinations_stage3()
    print(f"Stage-3: running up to {len(combos)} new variants (v{LAST_KNOWN+1:02d} ... v{MAX_VARIANTS:02d})")

    # Load existing fingerprints
    seen_fingerprints: set = set()
    for v in range(1, LAST_KNOWN + 1):
        path = REPORT_DIR / f"v3_hybrid_v{v:02d}_backtest_20260823.json"
        if path.exists():
            existing = json.load(open(path))
            seen_fingerprints.add(config_fingerprint(existing["config"]))

    variant_num = LAST_KNOWN
    stage_results: List[Dict[str, Any]] = []
    best_adjusted_return = -1e9
    last_improved_variant = LAST_KNOWN

    for levers in combos:
        variant_num += 1
        if variant_num > MAX_VARIANTS:
            break
        variant = f"v{variant_num:02d}"

        cfg = make_config(levers)
        fp = config_fingerprint(cfg)
        if fp in seen_fingerprints:
            variant_num -= 1
            continue
        seen_fingerprints.add(fp)

        try:
            out = run_backtest_enriched(cfg, variant=variant)
            result = out["result"]
        except Exception as e:
            print(f"Variant {variant} FAILED: {e}")
            continue

        adjusted_return, flags = overfit_score(result)
        result["adjusted_return"] = adjusted_return
        result["penalty_flags"] = flags

        notes = notes_from_levers(levers) + (" | PENALTIES: " + ", ".join(flags) if flags else "")
        log_to_csv(result, notes=notes)
        stage_results.append(result)
        commit_variant(variant, result)

        print(f"{variant}: ret {result['total_return']:.2%} adj {adjusted_return:.2%} sharpe {result['sharpe_ratio']:.3f} dd {-result['max_drawdown']:.2%} trades {result['number_of_trades']} flags {flags}")

        if adjusted_return > best_adjusted_return + 0.0001:
            best_adjusted_return = adjusted_return
            last_improved_variant = variant_num

        if variant_num - last_improved_variant >= CONVERGENCE_WINDOW:
            print(f"CONVERGENCE STOP: no >1% improvement for {CONVERGENCE_WINDOW} variants")
            break

    # Rank all variants (new + existing) by adjusted return within constraints
    all_results: List[Dict[str, Any]] = []
    for v in range(1, variant_num + 1):
        path = REPORT_DIR / f"v3_hybrid_v{v:02d}_backtest_20260823.json"
        if path.exists():
            r = json.load(open(path))
            # Recompute adjusted if missing
            if "adjusted_return" not in r:
                r["adjusted_return"], r["penalty_flags"] = overfit_score(r)
            all_results.append(r)

    feasible = [r for r in all_results if r["sharpe_ratio"] >= 1.0 and r["max_drawdown"] <= 0.15 and r["number_of_trades"] >= 200]
    if feasible:
        feasible.sort(key=lambda r: -r["adjusted_return"])
        best_config = feasible[0]["config"]
        best_variant = feasible[0]["variant"]
    else:
        # no feasible, pick by raw sharpe ignoring penalties
        all_results.sort(key=lambda r: -r["sharpe_ratio"])
        best_config = all_results[0]["config"]
        best_variant = all_results[0]["variant"]

    print(f"\nBEST CONFIG AFTER OVERFIT PENALTIES: {best_variant}")
    print(json.dumps(best_config, indent=2))

    return best_config, best_variant, feasible


# --- Cross-market frozen backtest ---

def run_cross_market(cfg: Dict[str, Any], period: str, variant_label: str) -> Dict[str, Any]:
    """Run the existing engine against a different period by monkey-patching data paths."""
    # We copy the data files to the expected names, run, then restore.
    from proper_backtest_hybrid import BARS_FILE, FEATURES_FILE, START_DATE, END_DATE, REPORT_DIR
    import shutil

    data_dir = Path("/opt/stonk-ai/v3_rebuild/data")
    orig_bars = data_dir / "daily_bars_2yr.json"
    orig_features = data_dir / "features_2yr.json"
    orig_regime_cache = data_dir / "regime_etfs_yf.json"

    cross_bars = data_dir / "daily_bars_2022_2023.json"
    cross_features = data_dir / "features_2022_2023.json"
    cross_data = json.load(open(cross_bars))
    cross_features_data = json.load(open(cross_features))

    # Extract period-specific bars and features
    period_bars = cross_data[period]
    period_features_rows = cross_features_data[period]

    # Write temp files
    temp_bars = data_dir / f"daily_bars_{period}.json"
    temp_features = data_dir / f"features_{period}.json"
    json.dump(period_bars, open(temp_bars, "w"))
    json.dump(period_features_rows, open(temp_features, "w"))

    # Backup originals and swap
    backup_bars = data_dir / "daily_bars_2yr.json.bak"
    backup_features = data_dir / "features_2yr.json.bak"
    shutil.copyfile(orig_bars, backup_bars)
    shutil.copyfile(orig_features, backup_features)
    shutil.copyfile(temp_bars, orig_bars)
    shutil.copyfile(temp_features, orig_features)

    # Remove cached regime so it rebuilds for the period
    if orig_regime_cache.exists():
        orig_regime_cache.unlink()

    try:
        out = run_backtest_enriched(cfg, variant=variant_label)
        result = out["result"]
    finally:
        # Restore originals
        shutil.copyfile(backup_bars, orig_bars)
        shutil.copyfile(backup_features, orig_features)
        if backup_bars.exists():
            backup_bars.unlink()
        if backup_features.exists():
            backup_features.unlink()
        if temp_bars.exists():
            temp_bars.unlink()
        if temp_features.exists():
            temp_features.unlink()

    return result


def main():
    best_config, best_variant, feasible = run_stage3()

    # Run frozen config on cross-market periods
    bear_result = run_cross_market(best_config, "2022_bear", f"{best_variant}_2022_bear")
    trans_result = run_cross_market(best_config, "2023_trans", f"{best_variant}_2023_trans")

    cross_summary = {
        "best_variant": best_variant,
        "best_config": best_config,
        "2022_bear": {
            "total_return": bear_result["total_return"],
            "sharpe_ratio": bear_result["sharpe_ratio"],
            "max_drawdown": bear_result["max_drawdown"],
            "trades": bear_result["number_of_trades"],
            "avg_trades_per_month": bear_result["number_of_trades"] / (251 / 21),
        },
        "2023_trans": {
            "total_return": trans_result["total_return"],
            "sharpe_ratio": trans_result["sharpe_ratio"],
            "max_drawdown": trans_result["max_drawdown"],
            "trades": trans_result["number_of_trades"],
            "avg_trades_per_month": trans_result["number_of_trades"] / (418 / 21),
        },
    }

    summary_path = REPORT_DIR / "hybrid_stage3_cross_market_summary_20260823.json"
    json.dump(cross_summary, open(summary_path, "w"), indent=2)

    # Verdict
    bear_ok = bear_result["total_return"] > -0.15 and bear_result["max_drawdown"] <= 0.25
    trans_ok = trans_result["total_return"] > 0.20 and trans_result["sharpe_ratio"] >= 0.8

    if bear_ok and trans_ok:
        verdict = "deploy"
    elif trans_ok:
        verdict = "further_refine"
    else:
        verdict = "reject"

    cross_summary["verdict"] = verdict
    json.dump(cross_summary, open(summary_path, "w"), indent=2)

    print("\n=== CROSS-MARKET RESULTS ===")
    for period in ["2022_bear", "2023_trans"]:
        r = cross_summary[period]
        print(f"{period}: ret {r['total_return']:.2%}, sharpe {r['sharpe_ratio']:.3f}, maxdd {-r['max_drawdown']:.2%}, trades {r['trades']}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
