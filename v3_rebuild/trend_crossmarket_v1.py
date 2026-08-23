#!/usr/bin/env python3
"""
STONK.AI v3 Trend Engine cross-market validation.

Runs the top N configurations from the primary sweep across:
  - 2022 bear market (Jan-Dec 2022)
  - 2023 - Aug 2024
  - Aug 2024 - Aug 2026

Does not re-optimise per window.

Author: OpenClaw subagent
Date: 2026-08-23
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

import pandas as pd

from proper_backtest_trend_v1 import run_backtest, fetch_benchmark_series
from trend_engine_v1 import load_bars

DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
REPORT_DIR = Path("/opt/stonk-ai/reports")
DATE_TAG = "20260823"

WINDOWS: List[Tuple[str, Path]] = [
    ("bear_2022", DATA_DIR / "daily_bars_2022_2023.json"),
    ("oos_2023_2024", DATA_DIR / "daily_bars_2022_2023.json"),
    ("forward_2024_2026", DATA_DIR / "daily_bars_2yr.json"),
]


def load_window_bars(window: str, path: Path) -> Dict[str, Dict[str, List]]:
    raw = load_bars(path)
    if window == "bear_2022" and "2022_bear" in raw:
        return raw["2022_bear"]
    if window == "oos_2023_2024" and "2023_trans" in raw:
        return raw["2023_trans"]
    return raw


def fetch_bench_for_window(dates: List[str]) -> tuple:
    start_dt = pd.to_datetime(dates[0], utc=True) - pd.Timedelta(days=300)
    end_dt = pd.to_datetime(dates[-1], utc=True) + pd.Timedelta(days=5)
    spy = fetch_benchmark_series("SPY", start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    qqq = fetch_benchmark_series("QQQ", start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    return spy, qqq


def meets_stop(metrics: Dict[str, float], qqq_ret: float) -> bool:
    return (metrics["total_return"] >= qqq_ret and
            metrics["max_drawdown"] <= 0.20 and
            metrics["sharpe_ratio"] >= 0.8)


def window_score(metrics: Dict[str, float]) -> float:
    return metrics["total_return"] - 1.5 * metrics["max_drawdown"] + metrics["sharpe_ratio"]


def run_crossmarket(configs: List[Dict[str, Any]], top_codes: List[str]) -> Dict[str, Any]:
    summary = {
        "date_tag": DATE_TAG,
        "variants": {},
        "windows": {},
    }

    for code, cfg in zip(top_codes, configs):
        variant_results = {}
        window_scores = []
        stop_met_all = True

        for window, path in WINDOWS:
            bars = load_window_bars(window, path)
            spy, qqq = fetch_bench_for_window(bars["QQQ"]["timestamps"])
            out = run_backtest(deepcopy(cfg), bars=bars, variant=f"{code}_{window}",
                               spy_series=spy, qqq_series=qqq, date_tag=DATE_TAG)
            r = out["result"]
            variant_results[window] = {
                "metrics": {k: r[k] for k in [
                    "total_return", "annualized_return", "sharpe_ratio", "max_drawdown",
                    "win_rate", "profit_factor", "number_of_trades", "avg_holding_days",
                    "avg_gross_exposure_pct", "avg_net_exposure_pct",
                    "qqq_total_return", "qqq_sharpe_ratio", "qqq_max_drawdown",
                ]},
                "report_path": r.get("report_path", str(out["report_path"])),
            }
            window_scores.append(window_score(r))
            if not meets_stop(r, r["qqq_total_return"]):
                stop_met_all = False

        summary["variants"][code] = {
            "config": cfg,
            "window_results": variant_results,
            "average_window_score": sum(window_scores) / len(window_scores),
            "stop_condition_met": stop_met_all,
        }

    # Rank by average window score
    ranked = sorted(summary["variants"].items(), key=lambda kv: -kv[1]["average_window_score"])
    summary["ranking"] = [
        {
            "variant": code,
            "average_window_score": data["average_window_score"],
            "stop_condition_met": data["stop_condition_met"],
        }
        for code, data in ranked
    ]
    summary["best_variant"] = ranked[0][0]
    summary["best_config"] = ranked[0][1]["config"]

    cross_path = REPORT_DIR / f"v3_trend_v1_crossmarket_{DATE_TAG}.json"
    with open(cross_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Cross-market summary written to {cross_path}")
    return summary


if __name__ == "__main__":
    with open(REPORT_DIR / f"v3_trend_v1_summary_{DATE_TAG}.json") as f:
        sweep = json.load(f)

    top3 = sweep["ranking"][:3]
    configs = [x["config"] for x in top3]
    codes = [x["variant"] for x in top3]
    print("Cross-market validating:", codes)
    summary = run_crossmarket(configs, codes)
    print("Best variant:", summary["best_variant"])
    for code, data in summary["variants"].items():
        print(f"\n{code}: avg score {data['average_window_score']:.3f}, stop={data['stop_condition_met']}")
        for w, res in data["window_results"].items():
            m = res["metrics"]
            print(f"  {w}: ret={m['total_return']:.2%} dd={m['max_drawdown']:.2%} sharpe={m['sharpe_ratio']:.2f} vs_qqq={m['total_return']-m['qqq_total_return']:.2%}")
