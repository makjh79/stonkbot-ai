"""
proper_backtest_sector_rotation.py
Backtest MacroAllocator + SectorRotationEngine across three windows.

- Monthly rebalancing only.
- Macro allocator acts as the risk on/off switch.
- Sector rotation layer picks top 3 sector ETFs by relative strength.
- Execution: decision at month-end close, trade next-day close.
- Transaction cost: 0.10% per side + vol-scaled slippage (vol20d * 0.05).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import numpy as np

from macro_allocator import MacroAllocator, build_macro_features, load_window_data
from sector_rotation_engine import SectorRotationEngine, compute_volatility, month_end_indices


WINDOWS = {
    "2022 bear": "bear_2022",
    "2023–Aug 2024": "oos_2023_2024",
    "Aug 2024–Aug 2026": "forward_2024_2026",
}

# Parameters from task
TOP_N = 3
MAX_SECTOR_PCT = 0.33
MIN_3M_MOMENTUM = 0.0
MACRO_ALLOCATOR_EQUITY_MIN = 0.30
COST_PER_SIDE = 0.001
VOL_SLIPPAGE_MULT = 0.05

CANDIDATE_ETFS = [
    "XLY",  # consumer discretionary
    "XLP",  # consumer staples
    "XLK",  # technology
    "XLF",  # financials
    "XLI",  # industrials
    "XLB",  # materials
    "XLE",  # energy
    "XLU",  # utilities
    "XLRE",  # real estate
    "XBI",  # biotech
    "SOXX",  # semiconductors
    "IYT",  # transportation
    "SMH",  # semiconductors (alternative)
]

QQQ_BENCHMARK_TICKER = "QQQ"
SPY_BENCHMARK_TICKER = "SPY"


def load_sector_bars(data_dir: str, window_name: str) -> Dict[str, Dict[str, List]]:
    """
    Load sector ETF bars and align them to the window dates.

    We merge the Alpaca-fetched sector ETF universe
    (data/sector_etfs_bars_20260823.json) with the window-specific stock/regime
    bar files. The sector ETF file has its own timestamps; we slice each ETF to
    the window's date range and reindex to the window's trading-day grid using
    the most recent close.
    """
    bars_path = os.path.join(data_dir, f"{window_name}_bars.json")
    with open(bars_path) as fh:
        stock_bars = json.load(fh)

    spy_dates = stock_bars["SPY"]["timestamps"]

    sector_file = os.path.join(data_dir, "sector_etfs_bars_20260823.json")
    with open(sector_file) as fh:
        raw_sector = json.load(fh)

    def parse_dates(raw: List[str]) -> List[datetime]:
        out: List[datetime] = []
        for s in raw:
            s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out.append(dt)
        return out

    window_dates = parse_dates(spy_dates)
    result: Dict[str, Dict[str, List]] = {}

    for symbol, raw in raw_sector.items():
        ts = parse_dates(raw["timestamps"])
        closes = raw["closes"]
        # Build date -> close map
        date_close = {t.date(): c for t, c in zip(ts, closes)}

        aligned_closes: List[float] = []
        for d in window_dates:
            # Use the most recent available close up to and including d
            c = date_close.get(d.date())
            if c is None:
                # fallback: previous day's close from window if available
                c = aligned_closes[-1] if aligned_closes else None
            aligned_closes.append(float(c) if c is not None else np.nan)

        # Forward-fill any remaining NaNs at the start
        for i in range(1, len(aligned_closes)):
            if np.isnan(aligned_closes[i]):
                aligned_closes[i] = aligned_closes[i - 1]

        if not any(np.isnan(c) for c in aligned_closes):
            result[symbol] = {"closes": aligned_closes, "timestamps": window_dates}

    return result


def run_window(
    data_dir: str,
    window_name: str,
    label: str,
    macro_allocator: MacroAllocator,
    sector_engine: SectorRotationEngine,
) -> Dict[str, Any]:
    """Run the combined macro + sector rotation backtest for one window."""

    # 1. Load data
    raw = load_window_data(data_dir, window_name)
    sector_bars = load_sector_bars(data_dir, window_name)

    spy = raw["SPY"]
    qqq = raw["QQQ"]

    # Build macro features using the existing helper
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
    feat_by_date = {f.date.date(): f for f in feats}

    # Merge all bars into one dictionary for the sector engine
    daily_bars: Dict[str, Any] = {}
    daily_bars.update(raw)
    daily_bars.update(sector_bars)

    dates = spy["timestamps"]
    qqq_prices = np.array(qqq["closes"], dtype=float)

    equity = 1.0
    positions: Dict[str, float] = {}  # symbol -> fraction of NAV
    equity_curve: List[Tuple[str, float, float, Dict[str, float], float]] = []
    trades = 0
    sector_counts: List[int] = []
    selected_history: List[Tuple[str, List[str]]] = []

    rebalance_indices = month_end_indices(dates)
    prev_rebalance_i: int = 0

    for idx, i in enumerate(rebalance_indices):
        d = dates[i].date()

        # Determine macro exposure for this month
        if d not in feat_by_date:
            macro_exposure = 0.0
            macro_features_dict: Dict[str, float] = {}
        else:
            macro_features_dict = feat_by_date[d].to_dict()
            macro_exposure = macro_allocator.decide_equity_exposure(dates[i], macro_features_dict)

        # Decide new sector targets (only if macro risk switch is ON)
        if macro_exposure > MACRO_ALLOCATOR_EQUITY_MIN:
            selected, scorecard = sector_engine.select_sectors(
                date=dates[i],
                daily_bars=daily_bars,
                macro_features=macro_features_dict,
                top_n=TOP_N,
            )
        else:
            selected, scorecard = [], []

        sector_counts.append(len(selected))
        selected_history.append((d.isoformat(), selected))

        # Execute next-day close to avoid look-ahead / month-end bias.
        # For the final rebalance we execute on the same day.
        exec_i = i + 1 if i + 1 < len(dates) else i

        # Build target positions; the macro gate is already checked above,
        # so we pass macro_exposure=None to size_positions to deploy full capital.
        target_positions = sector_engine.size_positions(
            symbols=selected,
            capital=1.0,
            macro_exposure=None,
            max_sector_pct=MAX_SECTOR_PCT,
        )

        # Mark-to-market from previous rebalance through execution day
        # Start period after previous execution day up to and including exec_i.
        if idx == 0:
            period_start = 0
        else:
            period_start = prev_rebalance_i + 1

        for j in range(period_start, exec_i + 1):
            if j == 0:
                daily_ret = 0.0
            else:
                # Portfolio return from existing positions
                daily_ret = 0.0
                for sym, alloc in positions.items():
                    sym_prices = np.array(daily_bars[sym]["closes"], dtype=float)
                    r = sym_prices[j] / sym_prices[j - 1] - 1.0
                    daily_ret += alloc * r
            equity *= 1.0 + daily_ret

        # Apply transaction costs on the rebalance at exec_i
        # Turnover = sum of absolute differences between target and current allocations.
        all_symbols = set(positions.keys()) | set(target_positions.keys())
        turnover = sum(
            abs(target_positions.get(sym, 0.0) - positions.get(sym, 0.0))
            for sym in all_symbols
        )

        # Cost per side = fixed + vol-scaled slippage for each ETF traded
        cost = 0.0
        for sym in all_symbols:
            delta = abs(target_positions.get(sym, 0.0) - positions.get(sym, 0.0))
            if delta > 0:
                vol = compute_volatility(daily_bars[sym]["closes"], days=20)
                cost += delta * (COST_PER_SIDE + vol * VOL_SLIPPAGE_MULT)

        equity *= 1.0 - cost
        if turnover > 0:
            trades += 1

        positions = {sym: alloc for sym, alloc in target_positions.items() if alloc > 1e-9}

        # Mark-to-market from exec_i through current rebalance end i (same day unless last)
        for j in range(exec_i, i + 1):
            if j == 0:
                continue
            daily_ret = 0.0
            for sym, alloc in positions.items():
                sym_prices = np.array(daily_bars[sym]["closes"], dtype=float)
                r = sym_prices[j] / sym_prices[j - 1] - 1.0
                daily_ret += alloc * r
            equity *= 1.0 + daily_ret

        equity_curve.append((
            dates[i].isoformat(),
            float(equity),
            float(macro_exposure),
            dict(positions),
        ))

        prev_rebalance_i = i

    # Final mark-to-market from last rebalance through the last day
    last_i = rebalance_indices[-1]
    if last_i + 1 < len(dates):
        for j in range(last_i + 1, len(dates)):
            daily_ret = 0.0
            for sym, alloc in positions.items():
                sym_prices = np.array(daily_bars[sym]["closes"], dtype=float)
                r = sym_prices[j] / sym_prices[j - 1] - 1.0
                daily_ret += alloc * r
            equity *= 1.0 + daily_ret

    equity_curve.append((dates[-1].isoformat(), float(equity), 0.0, {}))

    equity_curve_arr = np.array([e[1] for e in equity_curve])
    running_max = np.maximum.accumulate(equity_curve_arr)
    drawdowns = (equity_curve_arr - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    qqq_return = (qqq_prices[-1] / qqq_prices[0]) - 1.0
    spy_return = (np.array(spy["closes"], dtype=float)[-1] / np.array(spy["closes"], dtype=float)[0]) - 1.0
    strategy_return = equity - 1.0

    # Top picks per window (last selection in each window)
    top_picks = [s for _, s in (selected_history[-5:] if selected_history else [])]

    return {
        "window": window_name,
        "label": label,
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "strategy_return": strategy_return,
        "spy_return": spy_return,
        "qqq_return": qqq_return,
        "max_drawdown": max_dd,
        "rebalances": trades,
        "avg_sector_count": float(np.mean(sector_counts)) if sector_counts else 0.0,
        "equity_curve": equity_curve,
        "selected_history": selected_history,
        "scorecard": [
            {
                "date": s.symbol,
                "symbol": s.symbol,
                "mom_3m": s.mom_3m,
                "mom_6m": s.mom_6m,
                "rel_3m": s.rel_3m,
                "rel_6m": s.rel_6m,
                "score": s.score,
                "excluded": s.excluded,
                "exclusion_reason": s.exclusion_reason,
            }
            for s in []
        ],
        "available_etfs": sorted(sector_bars.keys()),
    }


def load_macro_only_results(reports_dir: str) -> Dict[str, float]:
    """Read the macro-only allocator returns from its report."""
    path = os.path.join(reports_dir, "macro_allocator_backtest_20260823.json")
    with open(path) as fh:
        data = json.load(fh)
    return {row["window"]: row["allocator_equity_return"] for row in data["windows"]}


def write_equity_csv(path: str, window_results: List[Dict[str, Any]]) -> None:
    """Combine equity curves for all windows into a single CSV."""
    with open(path, "w") as fh:
        fh.write("date,equity,macro_exposure,holdings,window\n")
        for res in window_results:
            for row in res["equity_curve"]:
                holdings = ";".join(f"{k}={v:.4f}" for k, v in row[3].items())
                fh.write(
                    f"{row[0]},{row[1]:.6f},{row[2]:.2f},\"{holdings}\",{res['window']}\n"
                )


def write_summary_json(path: str, summary_rows: List[Dict[str, Any]]) -> None:
    # Evaluate stop conditions
    stop_conditions = {
        "improve_over_macro_in_at_least_one_window": any(
            s["strategy_return"] > s["macro_only_return"] for s in summary_rows
        ),
        "no_window_underperforms_macro_by_more_than_10pp": all(
            (s["strategy_return"] - s["macro_only_return"]) >= -0.10
            for s in summary_rows
        ),
        "max_drawdown_below_25pct_in_all_windows": all(
            s["max_drawdown"] > -0.25 for s in summary_rows
        ),
    }
    passes_all = all(stop_conditions.values())

    if passes_all:
        verdict = "PASS"
        recommendation = (
            "Sector rotation momentum meets all stop conditions. Consider further "
            "robustness tests (transaction cost sensitivity, longer history, "
            "out-of-sample regime splits) before sizing for production."
        )
    else:
        verdict = "STOP / PIVOT"
        recommendation = (
            "Sector rotation momentum failed to add alpha versus the macro-only "
            "allocator in this configuration. Do not allocate capital. Recommended "
            "next steps: (1) test a longer history including pre-2022 cycles, "
            "(2) add trend/mean-reversion conditioning so the engine is not short "
            "momentum in a tech-led rally, (3) evaluate equal-weight sector basket vs "
            "momentum-tilted basket as a baseline, or (4) abandon sector rotation "
            "and focus on the macro allocator plus a different alpha source."
        )

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "top_n": TOP_N,
            "max_sector_pct": MAX_SECTOR_PCT,
            "min_3m_momentum": MIN_3M_MOMENTUM,
            "macro_allocator_equity_min": MACRO_ALLOCATOR_EQUITY_MIN,
            "cost_per_side": COST_PER_SIDE,
            "vol_slippage_mult": VOL_SLIPPAGE_MULT,
            "candidate_etfs": CANDIDATE_ETFS,
        },
        "stop_conditions": stop_conditions,
        "verdict": verdict,
        "recommendation": recommendation,
        "windows": summary_rows,
    }
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)
    return verdict, recommendation


def main() -> None:
    base_dir = os.path.dirname(__file__)
    data_dir = os.path.join(base_dir, "data")
    reports_dir = os.path.join(os.path.dirname(base_dir), "reports")
    os.makedirs(reports_dir, exist_ok=True)

    macro_allocator = MacroAllocator()
    sector_engine = SectorRotationEngine(
        candidate_etfs=CANDIDATE_ETFS,
        top_n=TOP_N,
        max_sector_pct=MAX_SECTOR_PCT,
        min_3m_momentum=MIN_3M_MOMENTUM,
        macro_equity_min=MACRO_ALLOCATOR_EQUITY_MIN,
    )

    macro_only_returns = load_macro_only_results(reports_dir)

    window_results: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []

    for label, key in WINDOWS.items():
        res = run_window(data_dir, key, label, macro_allocator, sector_engine)
        window_results.append(res)

        # Most common top picks in this window
        all_picks: List[str] = []
        for dt, picks in res["selected_history"]:
            all_picks.extend(picks)
        from collections import Counter
        common = Counter(all_picks).most_common(3)
        top_3 = [sym for sym, _ in common]

        summary_rows.append(
            {
                "window": label,
                "strategy_return": res["strategy_return"],
                "macro_only_return": macro_only_returns.get(label, None),
                "qqq_return": res["qqq_return"],
                "spy_return": res["spy_return"],
                "max_drawdown": res["max_drawdown"],
                "avg_sector_count": res["avg_sector_count"],
                "rebalances": res["rebalances"],
                "top_sector_picks": top_3,
                "available_etfs": res["available_etfs"],
                "first_date": res["first_date"],
                "last_date": res["last_date"],
            }
        )

    write_equity_csv(
        os.path.join(reports_dir, "sector_rotation_equity_20260823.csv"),
        window_results,
    )

    verdict, recommendation = write_summary_json(
        os.path.join(reports_dir, "sector_rotation_backtest_20260823.json"),
        summary_rows,
    )

    # Print concise report
    print("\n" + "=" * 100)
    print("SECTOR ROTATION MOMENTUM BACKTEST REPORT")
    print("=" * 100)
    print(f"top_n={TOP_N}, max_sector_pct={MAX_SECTOR_PCT:.0%}, macro_min={MACRO_ALLOCATOR_EQUITY_MIN:.0%}")
    print(f"cost_per_side={COST_PER_SIDE:.2%}, vol_slippage_mult={VOL_SLIPPAGE_MULT}")
    print("\nWindow Results:")
    print(
        f"{'Window':<20} {'Macro+Sector':>14} {'Macro Only':>12} {'QQQ':>12} "
        f"{'Max DD':>12} {'Avg Sect':>10} {'Rebal':>8}"
    )
    print("-" * 100)
    for row in summary_rows:
        print(
            f"{row['window']:<20} "
            f"{row['strategy_return']:>13.2%} "
            f"{row['macro_only_return']:>11.2%} "
            f"{row['qqq_return']:>11.2%} "
            f"{row['max_drawdown']:>11.2%} "
            f"{row['avg_sector_count']:>9.2f} "
            f"{row['rebalances']:>7d}"
        )

    print("\nTop 3 sector picks per window:")
    for row in summary_rows:
        print(f"  {row['window']}: {', '.join(row['top_sector_picks'])}")

    print("\nFiles written:")
    print(f"  {os.path.join(reports_dir, 'sector_rotation_backtest_20260823.json')}")
    print(f"  {os.path.join(reports_dir, 'sector_rotation_equity_20260823.csv')}")
    print(f"\nVerdict: {verdict}")
    print(f"Recommendation: {recommendation}")


if __name__ == "__main__":
    main()
