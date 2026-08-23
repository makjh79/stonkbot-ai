#!/usr/bin/env python3
"""
STONK.AI v3 Trend Engine focused parameter sweep + cross-market validation.

Author: OpenClaw subagent
Date: 2026-08-23
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd
import yfinance as yf

from proper_backtest_trend_v1 import run_backtest, fetch_benchmark_series
from trend_engine_v1 import load_bars

DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
REPORT_DIR = Path("/opt/stonk-ai/reports")

DATE_TAG = "20260823"

BASE_CONFIG: Dict[str, Any] = {
    "benchmark": "SPY",
    "trend_ema_fast": 50,
    "trend_ema_slow": 200,
    "top_n": 10,
    "base_size_pct": 0.05,
    "max_position_pct": 0.15,
    "max_gross_exposure_pct": 1.50,
    "max_net_long_pct": 1.00,
    "max_net_short_pct": 0.50,
    "max_sector_pct": 0.25,
    "drawdown_halt_pct": 0.15,
    "short_alloc_pct": 0.25,
    "tactical_weight_pct": 0.20,
    "lookback_mom12": 252,
    "lookback_mom3": 63,
    "borrow_cost_annual": 0.02,
    "execution_mode": "t1_close",
    "vol_slippage_mult": 0.1,
    "rebalance_freq_days": 10,
}


def make_variant(cfg: Dict[str, Any], overrides: Dict[str, Any], code: str) -> Dict[str, Any]:
    v = deepcopy(cfg)
    v.update(overrides)
    v["variant_code"] = code
    return v


# Focused grid: 20 variants
VARIANTS: List[Dict[str, Any]] = []
counter = 1
for ema_slow in [150, 200]:
    for top_n in [5, 10, 15]:
        for short in [0.0, 0.25, 0.50]:
            # tactical and base size tied to top_n to keep the grid tight
            tactical = 0.0 if top_n == 5 else (0.2 if top_n == 10 else 0.4)
            base = 0.04 if top_n == 5 else (0.06 if top_n == 10 else 0.08)
            code = f"v{counter:02d}"
            VARIANTS.append(make_variant(BASE_CONFIG, {
                "trend_ema_slow": ema_slow,
                "top_n": top_n,
                "short_alloc_pct": short,
                "tactical_weight_pct": tactical,
                "base_size_pct": base,
            }, code))
            counter += 1


def fetch_bench_for_window(dates: List[str]) -> tuple:
    start_dt = pd.to_datetime(dates[0], utc=True) - pd.Timedelta(days=300)
    end_dt = pd.to_datetime(dates[-1], utc=True) + pd.Timedelta(days=5)
    spy = fetch_benchmark_series("SPY", start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    qqq = fetch_benchmark_series("QQQ", start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    return spy, qqq


def primary_score(result: Dict[str, Any]) -> float:
    """Composite score used to rank variants on the primary window."""
    ret = result["total_return"]
    dd = result["max_drawdown"]
    sharpe = result["sharpe_ratio"]
    vs_qqq = ret - result["qqq_total_return"]
    return ret - 1.5 * dd + sharpe + 0.5 * vs_qqq


def run_sweep():
    bars = load_bars(DATA_DIR / "daily_bars_2yr.json")
    spy, qqq = fetch_bench_for_window(bars["QQQ"]["timestamps"])

    results = []
    for v in VARIANTS:
        code = v.pop("variant_code")
        print(f"\n=== {code} ===")
        out = run_backtest(v, bars=bars, variant=code, spy_series=spy, qqq_series=qqq, date_tag=DATE_TAG)
        r = out["result"]
        score = primary_score(r)
        results.append({"variant": code, "score": score, "result": r, "config": v})
        print(json.dumps({k: r[k] for k in [
            "variant", "total_return", "sharpe_ratio", "max_drawdown",
            "number_of_trades", "avg_gross_exposure_pct", "avg_net_exposure_pct",
            "qqq_total_return"
        ]}, indent=2))

    results.sort(key=lambda x: -x["score"])
    summary = {
        "date_tag": DATE_TAG,
        "primary_window": f"{bars['QQQ']['timestamps'][0]} to {bars['QQQ']['timestamps'][-1]}",
        "ranking": [
            {
                "variant": x["variant"],
                "score": x["score"],
                "config": x["config"],
                "metrics": {k: x["result"][k] for k in [
                    "total_return", "annualized_return", "sharpe_ratio", "max_drawdown",
                    "win_rate", "profit_factor", "number_of_trades", "avg_holding_days",
                    "avg_gross_exposure_pct", "avg_net_exposure_pct",
                    "qqq_total_return", "qqq_sharpe_ratio", "qqq_max_drawdown"
                ]},
            }
            for x in results
        ],
    }
    summary_path = REPORT_DIR / f"v3_trend_v1_summary_{DATE_TAG}.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary written to {summary_path}")
    return results[:3]


if __name__ == "__main__":
    top3 = run_sweep()
    print("\nTop 3 variants for cross-market validation:")
    for x in top3:
        print(x["variant"], x["score"], x["config"])
