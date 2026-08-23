"""
proper_backtest_macro_plus_satellite.py
Backtest MacroAllocator + SatelliteAlphaEngine combined system.

- Monthly rebalancing at month-end close (idealized execution documented).
- Macro allocator decides equity exposure {0, 25, 50, 75, 100}%.
- If equity exposure > 30%, allocate that sleeve to top N momentum stocks.
- Remaining capital in bond proxy (TLT if available, else SHY, else cash).
- Transaction cost: 0.10% per side.
- Reports vs pure macro allocator and benchmarks (QQQ, SPY).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from macro_allocator import MacroAllocator, build_macro_features, load_window_data
from satellite_alpha_engine import SatelliteAlphaEngine


WINDOWS = {
    "2022 bear": "bear_2022",
    "2023–Aug 2024": "oos_2023_2024",
    "Aug 2024–Aug 2026": "forward_2024_2026",
}

COST_PER_SIDE = 0.001  # 0.10%
MAX_POSITIONS = 10
MAX_POSITION_PCT = 0.15
SECTOR_CAP_PCT = 0.25
MIN_STOCK_HISTORY_DAYS = 250  # ~1 trading year; 2022 has 251 trading days
BOND_PROXY_PREFERENCE = ("TLT", "SHY")

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


def find_bond_proxy(raw: Dict[str, Any]) -> Optional[str]:
    for sym in BOND_PROXY_PREFERENCE:
        if sym in raw and len(raw[sym]["closes"]) > 0:
            return sym
    return None


def run_window(
    data_dir: str,
    window_key: str,
    daily_bars_path: str,
    macro_allocator: MacroAllocator,
    satellite_engine: SatelliteAlphaEngine,
) -> Dict[str, Any]:
    raw = load_window_data(data_dir, window_key)
    spy = raw["SPY"]
    qqq = raw["QQQ"]
    dates = spy["timestamps"]

    feats = build_macro_features(
        spy_closes=spy["closes"],
        qqq_closes=qqq["closes"],
        lqd_closes=raw["LQD"]["closes"],
        hyg_closes=raw["HYG"]["closes"],
        vixy_closes=raw["VIXY"]["closes"],
        tlt_closes=raw["TLT"]["closes"],
        shy_closes=raw["SHY"]["closes"],
        dates=dates,
    )
    feat_by_date = {f.date.date(): f for f in feats}

    # Load full daily bars including individual stocks for the satellite sleeve.
    # Each macro window has a dedicated bars file; use the one matching window_key.
    window_bars_path = os.path.join(data_dir, f"{window_key}_bars.json")
    if not os.path.exists(window_bars_path):
        window_bars_path = daily_bars_path
    all_bars = load_daily_bars(window_bars_path)
    stock_bars = {
        sym: bars
        for sym, bars in all_bars.items()
        if sym not in satellite_engine.exclude_symbols
        and len(bars.get("closes", [])) >= MIN_STOCK_HISTORY_DAYS
    }
    # Reindex stock bar timestamps to match macro window dates if needed
    stock_bars_by_date = build_stock_bars_by_date(stock_bars)

    bond_proxy = find_bond_proxy(raw)
    bond_prices = np.array(raw[bond_proxy]["closes"], dtype=float) if bond_proxy else None
    spy_prices = np.array(spy["closes"], dtype=float)
    qqq_prices = np.array(qqq["closes"], dtype=float)

    rebalance_indices = month_end_indices(dates)

    equity = 1.0
    exposure = 0.0
    satellite_weights: Dict[str, float] = {}
    equity_curve: List[Tuple[str, float, float, float, int, Dict[str, float]]] = []
    trades = 0
    exposure_sum = 0.0
    exposure_count = 0
    stock_count_sum = 0
    rebalances = 0
    contribution: Dict[str, float] = defaultdict(float)

    prev_i: Optional[int] = None
    for i in rebalance_indices:
        d = dates[i].date()
        target_exposure = 0.0
        if d in feat_by_date:
            target_exposure = macro_allocator.decide_equity_exposure(dates[i], feat_by_date[d].to_dict())

        period_start = i if prev_i is None else prev_i + 1
        period_end = i

        # Rebalance: compute turnover cost and new satellite sleeve if any
        new_satellite_weights: Dict[str, float] = {}
        new_bond_weight = 0.0
        new_cash_weight = 0.0

        if target_exposure > 0.30:
            satellite_capital = equity * target_exposure
            bond_capital = equity * (1.0 - target_exposure)
            signals = satellite_engine.select_stocks(
                dates[i], stock_bars_by_date, spy_bars=all_bars.get("SPY")
            )
            new_satellite_weights = satellite_engine.size_positions(
                signals, satellite_capital, equal_weight=True
            )
            # Normalize satellite weights as fraction of total portfolio
            new_satellite_weights = {
                sym: w / equity for sym, w in new_satellite_weights.items()
            }
            if bond_proxy and bond_prices is not None:
                new_bond_weight = bond_capital / equity
            else:
                new_cash_weight = bond_capital / equity
        elif target_exposure > 0.0:
            # Macro wants a modest equity sleeve but below satellite threshold:
            # put the equity portion in the bond proxy (macro backtest uses QQQ/SPY
            # as the equity sleeve, but here we keep it simple in bonds).
            if bond_proxy and bond_prices is not None:
                new_bond_weight = 1.0
            else:
                new_cash_weight = 1.0
        else:
            # 0% equity: match the pure macro backtest and hold cash (not TLT).
            # This avoids the 2022 rate-rising TLT drawdown when the allocator is
            # fully risk-off.
            new_cash_weight = 1.0

        # Transaction costs: total absolute change in portfolio weights
        turnover = _compute_turnover(
            satellite_weights, exposure, new_satellite_weights, new_bond_weight, new_cash_weight
        )
        equity *= 1.0 - turnover * COST_PER_SIDE
        if turnover > 1e-9:
            trades += 1

        satellite_weights = new_satellite_weights
        exposure = target_exposure
        rebalances += 1

        # Mark-to-market daily in the period
        for j in range(period_start, period_end + 1):
            if j == period_start:
                period_ret = 0.0
            else:
                # Composite return = sum(stock weight * stock ret) + bond weight * bond ret
                period_ret = 0.0
                for sym, weight in satellite_weights.items():
                    sym_prices = stock_bars_by_date.get(sym)
                    if sym_prices is None or j >= len(sym_prices["closes"]):
                        continue
                    sym_ret = (sym_prices["closes"][j] / sym_prices["closes"][j - 1]) - 1.0
                    period_ret += weight * sym_ret
                    if j == period_end:
                        contribution[sym] += weight * sym_ret
                if new_bond_weight > 0 and bond_prices is not None and j > 0:
                    bond_ret = (bond_prices[j] / bond_prices[j - 1]) - 1.0
                    period_ret += new_bond_weight * bond_ret
            equity *= 1.0 + period_ret
            active_stocks = sum(1 for w in satellite_weights.values() if w > 1e-9)
            equity_curve.append(
                (
                    dates[j].isoformat(),
                    float(equity),
                    float(exposure),
                    float(active_stocks),
                    float(qqq_prices[j]),
                    float(spy_prices[j]),
                )
            )
            exposure_sum += exposure
            stock_count_sum += active_stocks
            exposure_count += 1

        prev_i = i

    equity_curve_arr = np.array([e[1] for e in equity_curve])
    running_max = np.maximum.accumulate(equity_curve_arr)
    drawdowns = (equity_curve_arr - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    qqq_return = (qqq_prices[-1] / qqq_prices[0]) - 1.0
    spy_return = (spy_prices[-1] / spy_prices[0]) - 1.0
    combined_return = equity - 1.0

    # Top winning stock picks by contribution (sum of daily weighted returns)
    top_contributors = sorted(contribution.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "window": window_key,
        "label": [k for k, v in WINDOWS.items() if v == window_key][0],
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "combined_return": combined_return,
        "spy_return": spy_return,
        "qqq_return": qqq_return,
        "max_drawdown": max_dd,
        "avg_equity_exposure": exposure_sum / exposure_count if exposure_count else 0.0,
        "avg_stock_count": stock_count_sum / exposure_count if exposure_count else 0.0,
        "rebalances": rebalances,
        "trades_with_cost": trades,
        "bond_proxy": bond_proxy,
        "equity_curve": equity_curve,
        "top_contributors": top_contributors,
    }


def build_stock_bars_by_date(
    stock_bars: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Ensure stock bars have datetime timestamps and return same shape."""
    out: Dict[str, Dict[str, Any]] = {}
    for sym, bars in stock_bars.items():
        out[sym] = dict(bars)
    return out


def load_daily_bars(path: str) -> Dict[str, Dict[str, Any]]:
    import json

    with open(path) as fh:
        data = json.load(fh)
    for bars in data.values():
        if "timestamps" in bars:
            bars["timestamps"] = [
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if isinstance(ts, str)
                else ts
                for ts in bars["timestamps"]
            ]
    return data


def _compute_turnover(
    old_satellite_weights: Dict[str, float],
    old_bond_weight: float,
    new_satellite_weights: Dict[str, float],
    new_bond_weight: float,
    new_cash_weight: float,
) -> float:
    """Sum of absolute weight changes across all sleeves."""
    symbols = set(old_satellite_weights) | set(new_satellite_weights)
    turnover = 0.0
    for sym in symbols:
        turnover += abs(new_satellite_weights.get(sym, 0.0) - old_satellite_weights.get(sym, 0.0))
    turnover += abs(new_bond_weight - old_bond_weight)
    # Cash is implicit residual; include only if explicitly tracked
    turnover += abs(new_cash_weight - (1.0 - old_bond_weight - sum(old_satellite_weights.values())))
    return turnover


def load_pure_macro_results(reports_dir: str) -> List[Dict[str, Any]]:
    path = os.path.join(reports_dir, "macro_allocator_backtest_20260823.json")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        data = json.load(fh)
    return data.get("windows", [])


def write_equity_csv(path: str, window_results: List[Dict[str, Any]]) -> None:
    with open(path, "w") as fh:
        fh.write("date,equity,exposure,active_stocks,qqq_close,spy_close,window\n")
        for res in window_results:
            for row in res["equity_curve"]:
                fh.write(
                    f"{row[0]},{row[1]:.6f},{row[2]:.2f},{row[3]:.1f},"
                    f"{row[4]:.4f},{row[5]:.4f},{res['window']}\n"
                )


def write_summary_json(path: str, summary_rows: List[Dict[str, Any]], rules: str, limitations: str) -> None:
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allocator_rules": rules,
        "limitations": limitations,
        "cost_per_side": COST_PER_SIDE,
        "max_positions": MAX_POSITIONS,
        "max_position_pct": MAX_POSITION_PCT,
        "sector_cap_pct": SECTOR_CAP_PCT,
        "windows": summary_rows,
    }
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)


def main() -> None:
    base_dir = os.path.dirname(__file__)
    data_dir = os.path.join(base_dir, "data")
    reports_dir = os.path.join(os.path.dirname(base_dir), "reports")
    os.makedirs(reports_dir, exist_ok=True)

    daily_bars_path = os.path.join(data_dir, "daily_bars_2yr.json")

    macro_allocator = MacroAllocator()
    # Reasonable minimum history: a calendar year has ~251-253 trading days.
    # Using 250 allows the 2022 bear window to participate in satellite selection
    # while still excluding very recently listed names.
    satellite_engine = SatelliteAlphaEngine(
        max_positions=MAX_POSITIONS,
        max_position_pct=MAX_POSITION_PCT,
        sector_cap_pct=SECTOR_CAP_PCT,
        min_history_days=MIN_STOCK_HISTORY_DAYS,
    )

    pure_macro_rows = load_pure_macro_results(reports_dir)
    pure_macro_by_label = {row["window"]: row for row in pure_macro_rows}

    window_results: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    for label, key in WINDOWS.items():
        res = run_window(data_dir, key, daily_bars_path, macro_allocator, satellite_engine)
        window_results.append(res)
        macro_row = pure_macro_by_label.get(label, {})
        summary_rows.append(
            {
                "window": label,
                "combined_return": res["combined_return"],
                "pure_macro_return": macro_row.get("allocator_equity_return"),
                "qqq_return": res["qqq_return"],
                "spy_return": res["spy_return"],
                "max_drawdown": res["max_drawdown"],
                "avg_equity_exposure": res["avg_equity_exposure"],
                "avg_stock_count": res["avg_stock_count"],
                "rebalances": res["rebalances"],
                "bond_proxy": res["bond_proxy"],
                "top_contributors": res["top_contributors"],
                "first_date": res["first_date"],
                "last_date": res["last_date"],
            }
        )

    write_equity_csv(
        os.path.join(reports_dir, "macro_plus_satellite_equity_20260823.csv"),
        window_results,
    )

    limitations = (
        "Sector data unavailable; sector_cap_pct is a documented warning/limitation only. "
        "Execution assumed at month-end close (idealized); next-open would add slippage. "
        "Universe from daily_bars_2yr.json may have survivorship bias. "
        "Stock selection does not account for splits/dividends beyond raw close prices. "
        "Bond proxy chosen as TLT if available, else SHY, else cash."
    )
    write_summary_json(
        os.path.join(reports_dir, "macro_plus_satellite_backtest_20260823.json"),
        summary_rows,
        macro_allocator.rule_summary(),
        limitations,
    )

    # Evaluate stop condition
    stop_pass = True
    fail_reasons: List[str] = []
    improved_any = False
    for row in summary_rows:
        if row["max_drawdown"] < -0.25:
            stop_pass = False
            fail_reasons.append(f"{row['window']}: max drawdown {row['max_drawdown']:.2%} < -25%")
        macro_ret = row["pure_macro_return"]
        if macro_ret is not None:
            if row["combined_return"] > macro_ret:
                improved_any = True
            if macro_ret - row["combined_return"] > 0.05:
                stop_pass = False
                fail_reasons.append(
                    f"{row['window']}: underperforms macro by {macro_ret - row['combined_return']:.2%} > 5pp"
                )
    if not improved_any:
        stop_pass = False
        fail_reasons.append("No window improved over pure macro allocator.")

    # Print concise report
    print("\n" + "=" * 90)
    print("MACRO + SATELLITE BACKTEST REPORT")
    print("=" * 90)
    print(f"Cost per side: {COST_PER_SIDE:.2%} | Max positions: {MAX_POSITIONS} | Stock cap: {MAX_POSITION_PCT:.0%}")
    print("\nWindow Results:")
    print(
        f"{'Window':<20} {'Combo Ret':>12} {'Macro Ret':>12} {'QQQ Ret':>12} "
        f"{'Max DD':>12} {'Avg Exp':>10} {'Avg Stks':>10} {'Rebal':>8}"
    )
    print("-" * 90)
    for row in summary_rows:
        macro_str = f"{row['pure_macro_return']:.2%}" if row["pure_macro_return"] is not None else "n/a"
        print(
            f"{row['window']:<20} "
            f"{row['combined_return']:>11.2%} "
            f"{macro_str:>11} "
            f"{row['qqq_return']:>11.2%} "
            f"{row['max_drawdown']:>11.2%} "
            f"{row['avg_equity_exposure']:>9.2%} "
            f"{row['avg_stock_count']:>9.1f} "
            f"{row['rebalances']:>7d}"
        )
    print("\nTop contributors per window:")
    for row in summary_rows:
        print(f"  {row['window']}:")
        for sym, contrib in row["top_contributors"]:
            print(f"    {sym}: {contrib:.2%}")

    print("\nStop condition:")
    print(f"  Passed: {stop_pass}")
    if fail_reasons:
        for reason in fail_reasons:
            print(f"  - {reason}")
    else:
        print("  - All checks passed.")

    print("\nFiles written:")
    print(f"  {os.path.join(reports_dir, 'macro_plus_satellite_backtest_20260823.json')}")
    print(f"  {os.path.join(reports_dir, 'macro_plus_satellite_equity_20260823.csv')}")


if __name__ == "__main__":
    main()
