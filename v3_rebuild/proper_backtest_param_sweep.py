#!/usr/bin/env python3
"""
STONK.AI v3 Deployed Strategy — Four-Lever Parameter Sweep
==========================================================

Wraps the existing harness proper_backtest_deployed.py (commit e645b41)
and runs the requested lever combinations:

  max_positions        : [15, 18, 20, 22, 25]
  cash_floor_pct       : [0.05, 0.10, 0.15]
  entry_buffer_pct     : [0.0, 0.06, 0.12]
  allow_caution_entries: [False, True]

Outputs:
  - JSON report: /opt/stonk-ai/reports/v3_param_sweep_YYYYMMDD.json
  - Summary CSV: /opt/stonk-ai/reports/v3_param_sweep_YYYYMMDD.csv (sorted by Sharpe desc)
  - PNG charts:  /opt/stonk-ai/reports/v3_param_sweep_return_vs_dd.png
                 /opt/stonk-ai/reports/v3_param_sweep_sharpe_vs_invested.png

Implementation note: The harness's backtest() function source is read
at runtime, patched to accept the four levers as arguments, and executed
in the harness's namespace. This keeps the backtest logic identical to
the base harness while allowing fast, non-destructive parameter sweeps.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

V3_DIR = Path("/opt/stonk-ai/v3_rebuild")
REPORT_DIR = Path("/opt/stonk-ai/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(V3_DIR))

import proper_backtest_deployed as harness

# Levers
MAX_POSITIONS_LEVELS = [15, 18, 20, 22, 25]
CASH_FLOOR_LEVELS = [0.05, 0.10, 0.15]
ENTRY_BUFFER_LEVELS = [0.0, 0.06, 0.12]
CAUTION_LEVELS = [False, True]

BASELINE = {
    "max_positions": 15,
    "cash_floor_pct": 0.10,
    "entry_buffer_pct": 0.12,
    "allow_caution_entries": False,
}

DATE_TAG = "20260823"
JSON_PATH = REPORT_DIR / f"v3_param_sweep_{DATE_TAG}.json"
CSV_PATH = REPORT_DIR / f"v3_param_sweep_{DATE_TAG}.csv"
PNG_RETURN_DD = REPORT_DIR / "v3_param_sweep_return_vs_dd.png"
PNG_SHARPE_INV = REPORT_DIR / "v3_param_sweep_sharpe_vs_invested.png"


def build_parameterized_backtest():
    """
    Read the harness's backtest() source, patch in lever arguments, disable
    per-run disk writes, and compile a new function in the harness namespace.
    """
    src = inspect.getsource(harness.backtest)

    # Change signature to accept levers
    src = src.replace(
        "def backtest() -> Dict:",
        "def _sweep_backtest(max_positions: int, cash_floor_pct: float, entry_buffer_pct: float, allow_caution_entries: bool) -> Dict:",
        1,
    )

    # Replace the three constant references with the corresponding parameters
    src = src.replace("V3_MAX_POSITIONS", "max_positions", 1)
    src = src.replace("V3_CASH_FLOOR_PCT", "cash_floor_pct", 1)
    src = src.replace("V3_ENTRY_CASH_BUFFER_PCT", "entry_buffer_pct", 1)

    # Replace tier assignment to respect allow_caution_entries
    old_tier_block = '''ranked = []
                for rank, (score, sym, feat) in enumerate(day_scores, 1):
                    if rank <= max(1, n // 3):
                        tier = "STRONG_NOW"
                    elif rank <= max(1, 2 * n // 3):
                        tier = "NOW"
                    else:
                        tier = "WATCH"
                    ranked.append((score, sym, feat, tier))'''

    new_tier_block = '''ranked = []
                for rank, (score, sym, feat) in enumerate(day_scores, 1):
                    if rank <= max(1, n // 3):
                        tier = "STRONG_NOW"
                    elif rank <= max(1, 2 * n // 3):
                        tier = "NOW"
                    else:
                        if allow_caution_entries:
                            tier = "WATCH"
                        else:
                            continue
                    ranked.append((score, sym, feat, tier))'''

    if old_tier_block not in src:
        raise RuntimeError("Could not locate tier assignment block in harness source.")
    src = src.replace(old_tier_block, new_tier_block, 1)

    # Disable per-run disk writes (we keep only our own aggregated outputs)
    old_save_block = '''    # Save outputs
    date_tag = datetime.now().strftime("%Y%m%d")
    report_path = REPORT_DIR / f"v3_proper_backtest_{date_tag}.json"
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2)

    equity_csv_path = REPORT_DIR / "v3_proper_backtest_equity.csv"
    pd.DataFrame(equity_curve).to_csv(equity_csv_path, index=False)'''

    new_save_block = '''    # Save outputs disabled during sweep
    report_path = REPORT_DIR / "sweep_run.json"
    equity_csv_path = REPORT_DIR / "sweep_run_equity.csv"'''

    if old_save_block not in src:
        raise RuntimeError("Could not locate save-output block in harness source.")
    src = src.replace(old_save_block, new_save_block, 1)

    local_ns = {}
    exec(src, harness.__dict__, local_ns)
    return local_ns["_sweep_backtest"]


SWEEP_BACKTEST = build_parameterized_backtest()


def compute_avg_invested(equity_curve: List[Dict]) -> Dict[str, float]:
    invested = []
    for row in equity_curve:
        equity = row["equity"]
        cash = row["cash"]
        if equity > 0:
            invested.append((equity - cash) / equity)
        else:
            invested.append(0.0)
    arr = np.array(invested)
    return {
        "avg_invested_pct": float(np.mean(arr)),
        "max_invested_pct": float(np.max(arr)),
    }


def run_one(levers: Dict) -> Dict:
    out = SWEEP_BACKTEST(
        max_positions=levers["max_positions"],
        cash_floor_pct=levers["cash_floor_pct"],
        entry_buffer_pct=levers["entry_buffer_pct"],
        allow_caution_entries=levers["allow_caution_entries"],
    )
    result = out["result"]
    equity_curve = out["equity_curve"]
    invested_stats = compute_avg_invested(equity_curve)

    return {
        "max_positions": levers["max_positions"],
        "cash_floor_pct": levers["cash_floor_pct"],
        "entry_buffer_pct": levers["entry_buffer_pct"],
        "allow_caution_entries": levers["allow_caution_entries"],
        "total_return": result["total_return"],
        "annualized_return": result["annualized_return"],
        "sharpe": result["sharpe_ratio"],
        "max_drawdown": result["max_drawdown"],
        "win_rate": result["win_rate"],
        "profit_factor": result["profit_factor"],
        "trades": result["number_of_trades"],
        "avg_invested_pct": invested_stats["avg_invested_pct"],
        "max_invested_pct": invested_stats["max_invested_pct"],
        "vs_qqq_return": result["total_return"] - result["qqq_total_return"],
    }


def make_charts(df: pd.DataFrame):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Chart 1: total_return vs max_drawdown, color by sharpe
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter = ax.scatter(
        df["max_drawdown"] * 100,
        df["total_return"] * 100,
        c=df["sharpe"],
        cmap="viridis",
        s=80,
        edgecolors="black",
        linewidths=0.5,
    )
    ax.axvline(-10, color="red", linestyle="--", alpha=0.5, label="DD limit (-10%)")
    ax.axhline(20, color="green", linestyle="--", alpha=0.5, label="Return floor (+20%)")
    ax.set_xlabel("Max Drawdown (%)")
    ax.set_ylabel("Total Return (%)")
    ax.set_title("v3 Parameter Sweep: Return vs Max Drawdown (color = Sharpe)")
    cb = fig.colorbar(scatter, ax=ax)
    cb.set_label("Sharpe")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(PNG_RETURN_DD, dpi=150)
    plt.close(fig)

    # Chart 2: sharpe vs avg_invested_pct
    fig, ax = plt.subplots(figsize=(10, 7))
    scatter2 = ax.scatter(
        df["avg_invested_pct"] * 100,
        df["sharpe"],
        c=df["total_return"] * 100,
        cmap="plasma",
        s=80,
        edgecolors="black",
        linewidths=0.5,
    )
    ax.set_xlabel("Average Invested %")
    ax.set_ylabel("Sharpe")
    ax.set_title("v3 Parameter Sweep: Sharpe vs Average Invested % (color = Total Return)")
    cb2 = fig.colorbar(scatter2, ax=ax)
    cb2.set_label("Total Return (%)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(PNG_SHARPE_INV, dpi=150)
    plt.close(fig)


def main():
    combos = list(product(
        MAX_POSITIONS_LEVELS,
        CASH_FLOOR_LEVELS,
        ENTRY_BUFFER_LEVELS,
        CAUTION_LEVELS,
    ))
    print(f"Running {len(combos)} parameter combinations...")

    results = []
    for idx, (mp, cf, eb, ac) in enumerate(combos, 1):
        levers = {
            "max_positions": mp,
            "cash_floor_pct": cf,
            "entry_buffer_pct": eb,
            "allow_caution_entries": ac,
        }
        print(f"[{idx}/{len(combos)}] {levers}")
        try:
            record = run_one(levers)
            results.append(record)
        except Exception as e:
            print(f"ERROR running combo {levers}: {e}")
            import traceback
            traceback.print_exc()
            results.append({**levers, "error": str(e)})

    df = pd.DataFrame([r for r in results if "error" not in r])
    df = df.sort_values(by="sharpe", ascending=False)

    # Recommended: highest Sharpe with total_return >= +20% and max_drawdown <= -10%
    # Note: harness stores max_drawdown as a positive fraction (0.10 == 10%).
    constrained = df[(df["total_return"] >= 0.20) & (df["max_drawdown"] <= 0.10)]
    recommended = {}
    if not constrained.empty:
        rec_row = constrained.iloc[0]
        recommended = {
            "max_positions": int(rec_row["max_positions"]),
            "cash_floor_pct": float(rec_row["cash_floor_pct"]),
            "entry_buffer_pct": float(rec_row["entry_buffer_pct"]),
            "allow_caution_entries": bool(rec_row["allow_caution_entries"]),
            "sharpe": float(rec_row["sharpe"]),
            "total_return": float(rec_row["total_return"]),
            "max_drawdown": float(rec_row["max_drawdown"]),
            "reason": "Highest Sharpe with total_return >= +20% and max_drawdown <= -10%",
        }
    else:
        # No combo satisfies both constraints; document the empty set.
        recommended = {
            "reason": "No combination satisfies total_return >= +20% and max_drawdown <= -10% simultaneously in this sweep.",
            "constraint_results": {
                "return_ge_20pct_count": int((df["total_return"] >= 0.20).sum()),
                "dd_le_10pct_count": int((df["max_drawdown"] <= 0.10).sum()),
                "both_count": 0,
            },
        }

    # Nearest practical recommendation: highest Sharpe among DD <= -10%
    dd_ok = df[df["max_drawdown"] <= 0.10]
    nearest_recommended = {}
    if not dd_ok.empty:
        nr_row = dd_ok.sort_values(by="sharpe", ascending=False).iloc[0]
        nearest_recommended = {
            "max_positions": int(nr_row["max_positions"]),
            "cash_floor_pct": float(nr_row["cash_floor_pct"]),
            "entry_buffer_pct": float(nr_row["entry_buffer_pct"]),
            "allow_caution_entries": bool(nr_row["allow_caution_entries"]),
            "sharpe": float(nr_row["sharpe"]),
            "total_return": float(nr_row["total_return"]),
            "max_drawdown": float(nr_row["max_drawdown"]),
            "reason": "Highest Sharpe among combos satisfying max_drawdown <= -10% (constraint return >= +20% was unsatisfied)",
        }

    # Best total return within DD <= -10%
    dd_ok = df[df["max_drawdown"] <= 0.10]
    best_return = {}
    if not dd_ok.empty:
        br_row = dd_ok.sort_values(by="total_return", ascending=False).iloc[0]
        best_return = {
            "max_positions": int(br_row["max_positions"]),
            "cash_floor_pct": float(br_row["cash_floor_pct"]),
            "entry_buffer_pct": float(br_row["entry_buffer_pct"]),
            "allow_caution_entries": bool(br_row["allow_caution_entries"]),
            "sharpe": float(br_row["sharpe"]),
            "total_return": float(br_row["total_return"]),
            "max_drawdown": float(br_row["max_drawdown"]),
        }

    # Baseline record
    baseline_mask = (
        (df["max_positions"] == BASELINE["max_positions"]) &
        (df["cash_floor_pct"] == BASELINE["cash_floor_pct"]) &
        (df["entry_buffer_pct"] == BASELINE["entry_buffer_pct"]) &
        (df["allow_caution_entries"] == BASELINE["allow_caution_entries"])
    )
    baseline_record = df[baseline_mask].iloc[0].to_dict() if baseline_mask.any() else {}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "baseline_config": BASELINE,
        "baseline_metrics": baseline_record,
        "recommended_config": recommended,
        "nearest_recommended": nearest_recommended,
        "best_return_within_dd_limit": best_return,
        "lever_ranges": {
            "max_positions": MAX_POSITIONS_LEVELS,
            "cash_floor_pct": CASH_FLOOR_LEVELS,
            "entry_buffer_pct": ENTRY_BUFFER_LEVELS,
            "allow_caution_entries": CAUTION_LEVELS,
        },
        "results": results,
    }

    with open(JSON_PATH, "w") as f:
        json.dump(report, f, indent=2)

    df.to_csv(CSV_PATH, index=False)
    make_charts(df)

    print(f"\nJSON: {JSON_PATH}")
    print(f"CSV:  {CSV_PATH}")
    print(f"PNG:  {PNG_RETURN_DD}")
    print(f"PNG:  {PNG_SHARPE_INV}")

    if recommended:
        print("\nRecommended config (highest Sharpe, return>=+20%, DD<=-10%):")
        print(json.dumps(recommended, indent=2))
    if best_return:
        print("\nBest total return within DD<=-10%:")
        print(json.dumps(best_return, indent=2))


if __name__ == "__main__":
    main()
