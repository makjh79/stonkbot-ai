#!/usr/bin/env python3
"""
STONK.AI v3 Trend Engine execution realism test.

For the single best config, run Aug 2024 - Aug 2026 with:
  - idealised t+1 close
  - next-open execution + slippage 0.05% + 0.1 x daily_volatility

Reports both curves and the degradation.

Author: OpenClaw subagent
Date: 2026-08-23
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import pandas as pd

from proper_backtest_trend_v1 import run_backtest, fetch_benchmark_series
from trend_engine_v1 import load_bars

DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
REPORT_DIR = Path("/opt/stonk-ai/reports")
DATE_TAG = "20260823"


def run_realism(best_config: Dict[str, Any]):
    bars = load_bars(DATA_DIR / "daily_bars_2yr.json")
    spy, qqq = fetch_benchmark_series("SPY",
        (pd.to_datetime(bars["QQQ"]["timestamps"][0], utc=True) - pd.Timedelta(days=300)).strftime("%Y-%m-%d"),
        (pd.to_datetime(bars["QQQ"]["timestamps"][-1], utc=True) + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    ), fetch_benchmark_series("QQQ",
        (pd.to_datetime(bars["QQQ"]["timestamps"][0], utc=True) - pd.Timedelta(days=300)).strftime("%Y-%m-%d"),
        (pd.to_datetime(bars["QQQ"]["timestamps"][-1], utc=True) + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    )

    ideal = run_backtest(deepcopy(best_config), bars=bars, variant="v08_ideal", execution_mode="t1_close",
                         spy_series=spy, qqq_series=qqq, date_tag=DATE_TAG)
    realistic = run_backtest(deepcopy(best_config), bars=bars, variant="v08_realistic", execution_mode="next_open",
                             spy_series=spy, qqq_series=qqq, date_tag=DATE_TAG)

    ir = ideal["result"]
    rr = realistic["result"]

    report = {
        "date_tag": DATE_TAG,
        "config": best_config,
        "ideal": {
            "execution_mode": "t1_close",
            "metrics": {k: ir[k] for k in [
                "total_return", "annualized_return", "sharpe_ratio", "max_drawdown",
                "win_rate", "profit_factor", "number_of_trades", "avg_holding_days",
                "avg_gross_exposure_pct", "avg_net_exposure_pct",
                "final_equity", "final_qqq_equity",
            ]},
        },
        "realistic": {
            "execution_mode": "next_open",
            "metrics": {k: rr[k] for k in [
                "total_return", "annualized_return", "sharpe_ratio", "max_drawdown",
                "win_rate", "profit_factor", "number_of_trades", "avg_holding_days",
                "avg_gross_exposure_pct", "avg_net_exposure_pct",
                "final_equity", "final_qqq_equity",
            ]},
        },
        "degradation": {
            "total_return_delta": rr["total_return"] - ir["total_return"],
            "sharpe_delta": rr["sharpe_ratio"] - ir["sharpe_ratio"],
            "max_drawdown_delta": rr["max_drawdown"] - ir["max_drawdown"],
            "final_equity_delta": rr["final_equity"] - ir["final_equity"],
            "return_pct_degradation": (rr["total_return"] - ir["total_return"]) / abs(ir["total_return"]) if ir["total_return"] != 0 else None,
        },
    }

    out_path = REPORT_DIR / f"v3_trend_v1_realistic_{DATE_TAG}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Realism report written to {out_path}")
    print(json.dumps(report["degradation"], indent=2))
    return report


if __name__ == "__main__":
    with open(REPORT_DIR / f"v3_trend_v1_crossmarket_{DATE_TAG}.json") as f:
        cross = json.load(f)
    best_config = cross["best_config"]
    print("Running execution realism for best variant", cross["best_variant"])
    run_realism(best_config)
