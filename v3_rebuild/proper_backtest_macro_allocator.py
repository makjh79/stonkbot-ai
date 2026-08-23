"""
proper_backtest_macro_allocator.py
Backtest MacroAllocator on SPY/QQQ across three cross-market windows.

- Monthly rebalancing only.
- 0.10% transaction cost per side (two sides per rebalance = 0.20% round-trip).
- Reports window metrics and writes equity curves.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import numpy as np

from macro_allocator import MacroAllocator, build_macro_features, load_window_data


WINDOWS = {
    "2022 bear": "bear_2022",
    "2023–Aug 2024": "oos_2023_2024",
    "Aug 2024–Aug 2026": "forward_2024_2026",
}

COST_PER_SIDE = 0.001  # 0.10%
QQQ_BENCHMARK_TICKER = "QQQ"
SPY_BENCHMARK_TICKER = "SPY"


def month_end_indices(dates: List[datetime]) -> List[int]:
    """Return indices of the last trading day of each calendar month."""
    if not dates:
        return []
    idxs: List[int] = []
    last_month = (dates[0].year, dates[0].month)
    for i, d in enumerate(dates):
        this_month = (d.year, d.month)
        if this_month != last_month:
            idxs.append(i - 1)
            last_month = this_month
    idxs.append(len(dates) - 1)
    return idxs


def run_window(data_dir: str, window_key: str) -> Dict[str, Any]:
    raw = load_window_data(data_dir, window_key)

    spy = raw["SPY"]
    qqq = raw["QQQ"]

    feats = build_macro_features(
        spy_closes=spy["closes"],
        qqq_closes=qqq["closes"],
        lqd_closes=raw["LQD"]["closes"],
        hyg_closes=raw["HYG"]["closes"],
        vixy_closes=raw["VIXY"]["closes"],
        tlt_closes=raw["TLT"]["closes"],
        shy_closes=raw["SHY"]["closes"],
        dates=spy["timestamps"],
    )

    # Map date -> feature for quick lookup
    feat_by_date = {f.date.date(): f for f in feats}

    allocator = MacroAllocator()

    dates = spy["timestamps"]
    spy_prices = np.array(spy["closes"], dtype=float)
    qqq_prices = np.array(qqq["closes"], dtype=float)

    equity = 1.0
    exposure = 0.0
    equity_curve: List[Tuple[str, float, float, float, float]] = []
    trades = 0
    exposure_sum = 0.0
    exposure_count = 0

    rebalance_indices = month_end_indices(dates)

    # First valid feature date
    first_feat_date = min(feat_by_date.keys()) if feat_by_date else None

    prev_i = None
    for i in rebalance_indices:
        d = dates[i].date()
        # If we don't have macro features for this date yet, stay flat.
        if d not in feat_by_date:
            target = 0.0
        else:
            target = allocator.decide_equity_exposure(dates[i], feat_by_date[d].to_dict())

        # Determine period: from current rebalance day close through next rebalance day close
        period_start = i
        period_end = i if prev_i is None else i
        if prev_i is not None:
            period_start = prev_i + 1  # trade at close following rebalance decision
            period_end = i

        # Transaction cost on change
        if target != exposure:
            turnover = abs(target - exposure)
            equity *= 1.0 - turnover * COST_PER_SIDE
            exposure = target
            trades += 1

        # Mark-to-market daily in the period
        for j in range(period_start, period_end + 1):
            if j == period_start:
                daily_ret = 0.0
            else:
                # Use QQQ as the equity sleeve return; SPY alternative included for diagnostics.
                daily_ret = (qqq_prices[j] / qqq_prices[j - 1]) - 1.0
            equity *= 1.0 + exposure * daily_ret
            equity_curve.append((
                dates[j].isoformat(),
                float(equity),
                float(exposure),
                float(qqq_prices[j]),
                float(spy_prices[j]),
            ))
            exposure_sum += exposure
            exposure_count += 1

        prev_i = i

    equity_curve_arr = np.array([e[1] for e in equity_curve])
    running_max = np.maximum.accumulate(equity_curve_arr)
    drawdowns = (equity_curve_arr - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    # Benchmark buy-and-hold QQQ returns over the window using first/last closes
    qqq_return = (qqq_prices[-1] / qqq_prices[0]) - 1.0
    spy_return = (spy_prices[-1] / spy_prices[0]) - 1.0
    allocator_return = equity - 1.0

    return {
        "window": window_key,
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "allocator_return": allocator_return,
        "spy_return": spy_return,
        "qqq_return": qqq_return,
        "max_drawdown": max_dd,
        "avg_equity_exposure": exposure_sum / exposure_count if exposure_count else 0.0,
        "rebalances": trades,
        "equity_curve": equity_curve,
        "first_feature_date": first_feat_date.isoformat() if first_feat_date else None,
    }


def write_equity_csv(path: str, window_results: List[Dict[str, Any]]) -> None:
    """Combine equity curves for all windows into a single CSV."""
    with open(path, "w") as fh:
        fh.write("date,equity,exposure,qqq_close,spy_close,window\n")
        for res in window_results:
            for row in res["equity_curve"]:
                fh.write(
                    f"{row[0]},{row[1]:.6f},{row[2]:.2f},{row[3]:.4f},{row[4]:.4f},{res['window']}\n"
                )


def write_summary_json(path: str, summary_rows: List[Dict[str, Any]], allocator_rules: str) -> None:
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allocator_rules": allocator_rules,
        "cost_per_side": COST_PER_SIDE,
        "windows": summary_rows,
    }
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)


def main() -> None:
    base_dir = os.path.dirname(__file__)
    data_dir = os.path.join(base_dir, "data")
    reports_dir = os.path.join(os.path.dirname(base_dir), "reports")
    os.makedirs(reports_dir, exist_ok=True)

    allocator = MacroAllocator()
    rules = allocator.rule_summary()

    window_results: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    for label, key in WINDOWS.items():
        res = run_window(data_dir, key)
        window_results.append(res)
        summary_rows.append(
            {
                "window": label,
                "allocator_equity_return": res["allocator_return"],
                "qqq_return": res["qqq_return"],
                "spy_return": res["spy_return"],
                "max_drawdown": res["max_drawdown"],
                "avg_equity_exposure": res["avg_equity_exposure"],
                "trades_rebalances": res["rebalances"],
                "first_date": res["first_date"],
                "last_date": res["last_date"],
            }
        )

    write_equity_csv(
        os.path.join(reports_dir, "macro_allocator_equity_20260823.csv"),
        window_results,
    )
    write_summary_json(
        os.path.join(reports_dir, "macro_allocator_backtest_20260823.json"),
        summary_rows,
        rules,
    )

    # Print concise report
    print("\n" + "=" * 80)
    print("MACRO ALLOCATOR BACKTEST REPORT")
    print("=" * 80)
    print(f"Cost per side: {COST_PER_SIDE:.2%}")
    print("\nWindow Results:")
    print(
        f"{'Window':<20} {'Alloc Ret':>12} {'QQQ Ret':>12} {'Max DD':>12} "
        f"{'Avg Exp':>10} {'Rebal':>8}"
    )
    print("-" * 80)
    for row in summary_rows:
        print(
            f"{row['window']:<20} "
            f"{row['allocator_equity_return']:>11.2%} "
            f"{row['qqq_return']:>11.2%} "
            f"{row['max_drawdown']:>11.2%} "
            f"{row['avg_equity_exposure']:>9.2%} "
            f"{row['trades_rebalances']:>7d}"
        )
    print("\nFiles written:")
    print(f"  {os.path.join(reports_dir, 'macro_allocator_backtest_20260823.json')}")
    print(f"  {os.path.join(reports_dir, 'macro_allocator_equity_20260823.csv')}")
    print("\n" + rules)


if __name__ == "__main__":
    main()
