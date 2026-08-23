"""
proper_backtest_dual_momentum.py
Backtest DualMomentumEngine on QQQ/GLD/TLT/SHY across three cross-market windows.

- Monthly rebalancing only.
- 0.10% transaction cost per side.
- Honest 1-day lag: signal at month-end close, execute at next trading day close.
- Lookback history fetched from yfinance so 12-month signals are available from the
  first month of each window.
- Reports window metrics, position log, equity curves, and deploy-worthiness vs MacroAllocator.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np

try:
    import yfinance as yf
except ImportError:
    yf = None

from dual_momentum_engine import DualMomentumEngine


WINDOWS = {
    "2022 bear": {
        "start": "2022-01-03",
        "end": "2022-12-30",
    },
    "2023–Aug 2024": {
        "start": "2023-01-03",
        "end": "2024-08-30",
    },
    "Aug 2024–Aug 2026": {
        "start": "2024-08-01",
        "end": "2026-08-21",
    },
}

MACRO_ALLOCATOR_RETURNS = {
    "2022 bear": -0.0168,
    "2023–Aug 2024": 0.4375,
    "Aug 2024–Aug 2026": 0.5369,
}

DATA_DIR = "/opt/stonk-ai/v3_rebuild/data"
REPORTS_DIR = "/opt/stonk-ai/reports"
COST_PER_SIDE = 0.001
TICKERS = ["QQQ", "GLD", "TLT", "SHY"]


def fetch_prices(ticker: str, start: str, end: str) -> Tuple[List[datetime], List[float]]:
    if yf is None:
        raise RuntimeError("yfinance not installed")
    hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
    dates = [d.to_pydatetime() for d in hist.index]
    closes = [float(v) for v in hist["Close"]]
    return dates, closes


def load_local_window_data(window_key: str) -> Dict[str, Any]:
    bars_path = os.path.join(DATA_DIR, f"{window_key}_bars.json")
    regime_path = os.path.join(DATA_DIR, f"{window_key}_regime_etfs.json")
    with open(bars_path) as fh:
        bars = json.load(fh)
    with open(regime_path) as fh:
        regime = json.load(fh)
    result: Dict[str, Any] = {}
    for sym in bars:
        result[sym] = {
            "closes": bars[sym]["closes"],
            "dates": [datetime.fromisoformat(d.replace("Z", "+00:00")) for d in bars[sym]["timestamps"]],
        }
    for sym in regime:
        result[sym] = {
            "closes": regime[sym]["prices"],
            "dates": [datetime.fromisoformat(d.replace("Z", "+00:00")) for d in regime[sym]["dates"]],
        }
    return result


def build_data_for_window(window_name: str) -> Tuple[List[datetime], Dict[str, List[float]]]:
    cfg = WINDOWS[window_name]
    start_dt = datetime.strptime(cfg["start"], "%Y-%m-%d") - timedelta(days=400)
    end_dt = datetime.strptime(cfg["end"], "%Y-%m-%d") + timedelta(days=5)

    all_dates: Dict[str, List[datetime]] = {}
    all_closes: Dict[str, List[float]] = {}
    for ticker in TICKERS:
        dates, closes = fetch_prices(ticker, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
        all_dates[ticker] = dates
        all_closes[ticker] = closes

    master_dates = all_dates["QQQ"]
    prices: Dict[str, List[float]] = {}
    for ticker in TICKERS:
        ticker_map = {d.date(): c for d, c in zip(all_dates[ticker], all_closes[ticker])}
        aligned = []
        last = None
        for d in master_dates:
            key = d.date()
            if key in ticker_map:
                last = ticker_map[key]
            aligned.append(last)
        prices[ticker] = aligned

    if window_name == "2022 bear":
        local_key = "bear_2022"
    elif window_name == "2023–Aug 2024":
        local_key = "oos_2023_2024"
    else:
        local_key = "forward_2024_2026"
    local = load_local_window_data(local_key)
    verification = {}
    for ticker in ["QQQ", "TLT", "SHY"]:
        if ticker not in local:
            continue
        local_map = {d.date(): c for d, c in zip(local[ticker]["dates"], local[ticker]["closes"])}
        max_dev = 0.0
        for d, c in zip(master_dates, prices[ticker]):
            key = d.date()
            if key in local_map:
                lc = local_map[key]
                dev = abs(c - lc) / lc * 100 if lc else 0
                max_dev = max(max_dev, dev)
        verification[ticker] = round(max_dev, 4)
    print(f"  {window_name} local verification max deviation vs yfinance: {verification}")

    return master_dates, prices


def run_window(window_name: str, lookback_months: int) -> Dict[str, Any]:
    master_dates, master_prices = build_data_for_window(window_name)
    cfg = WINDOWS[window_name]
    window_start = datetime.strptime(cfg["start"], "%Y-%m-%d").date()
    window_end = datetime.strptime(cfg["end"], "%Y-%m-%d").date()

    engine = DualMomentumEngine(lookback_months=lookback_months)
    signals = engine.compute_signals(master_prices, master_dates)

    position_by_day: Dict[int, str] = {}
    for i, sig in enumerate(signals):
        try:
            start_idx = master_dates.index(sig.execution_date)
        except ValueError:
            continue
        if i + 1 < len(signals):
            try:
                end_idx = master_dates.index(signals[i + 1].execution_date)
            except ValueError:
                end_idx = len(master_dates)
        else:
            end_idx = len(master_dates)
        for j in range(start_idx, end_idx):
            position_by_day[j] = sig.selected

    equity = 1.0
    current_position: Any = None
    full_equity_curve: List[Tuple[datetime, float, str, float]] = []
    for j in range(len(master_dates)):
        target = position_by_day.get(j, "SHY")
        if target != current_position:
            equity *= 1.0 - COST_PER_SIDE
            current_position = target
        daily_ret = 0.0 if j == 0 else master_prices[current_position][j] / master_prices[current_position][j - 1] - 1.0
        equity *= 1.0 + daily_ret
        full_equity_curve.append((master_dates[j], equity, current_position, daily_ret))

    window_curve = [(d, e, pos, dr) for d, e, pos, dr in full_equity_curve if window_start <= d.date() <= window_end]
    if not window_curve:
        raise ValueError(f"No data in window {window_name}")
    base_equity = window_curve[0][1]
    rebased_curve = [(d.isoformat(), e / base_equity, pos, dr) for d, e, pos, dr in window_curve]

    dates = [d for d, _, _, _ in window_curve]
    equity_arr = np.array([e for _, e, _, _ in rebased_curve])
    running_max = np.maximum.accumulate(equity_arr)
    drawdowns = (equity_arr - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    qqq_full = np.array(master_prices["QQQ"])
    qqq_window_start_idx = next(i for i, d in enumerate(master_dates) if d.date() >= window_start)
    qqq_window_end_idx = next(i for i in range(len(master_dates) - 1, -1, -1) if master_dates[i].date() <= window_end)
    qqq_return = qqq_full[qqq_window_end_idx] / qqq_full[qqq_window_start_idx] - 1.0

    position_log = []
    prev_pos = None
    for d, e, pos, dr in window_curve:
        if pos != prev_pos:
            sig_reason = next((s.reason for s in signals if s.execution_date == d), "initial/no signal")
            position_log.append({
                "date": d.isoformat(),
                "position": pos,
                "reason": sig_reason,
                "equity_after_cost": e / base_equity,
            })
            prev_pos = pos

    rebalances = sum(1 for i in range(1, len(window_curve)) if window_curve[i][2] != window_curve[i-1][2])

    return {
        "window": window_name,
        "lookback_months": lookback_months,
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "strategy_return": float(rebased_curve[-1][1] - 1.0),
        "qqq_return": float(qqq_return),
        "max_drawdown": max_dd,
        "rebalances": rebalances,
        "trades": rebalances,
        "equity_curve": rebased_curve,
        "position_log": position_log,
    }


def assess_deploy_worthiness(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stop condition:
    Deploy-worthy if best variant: beats macro allocator in >=2 of 3 windows,
    max DD <= -20% everywhere, 2022 >= -10%.
    """
    lb = results["best_variant_lookback"]
    key = f"{lb}_month"
    beats_macro = 0
    max_dd_ok = True
    return_2022_ok = True
    per_window = {}
    for label in WINDOWS:
        w = results["windows"][label][key]
        macro_ret = MACRO_ALLOCATOR_RETURNS[label]
        beat = w["strategy_return"] > macro_ret
        beats_macro += int(beat)
        dd_ok = w["max_drawdown"] >= -0.20
        if not dd_ok:
            max_dd_ok = False
        if label == "2022 bear" and w["strategy_return"] < -0.10:
            return_2022_ok = False
        per_window[label] = {
            "dual_momentum_return": w["strategy_return"],
            "macro_allocator_return": macro_ret,
            "beats_macro": beat,
            "max_drawdown": w["max_drawdown"],
            "max_dd_ok": dd_ok,
        }

    deploy_worthy = (beats_macro >= 2) and max_dd_ok and return_2022_ok
    return {
        "deploy_worthy": deploy_worthy,
        "best_variant_lookback": lb,
        "beats_macro_allocator_count": beats_macro,
        "max_drawdown_ok": max_dd_ok,
        "return_2022_ok": return_2022_ok,
        "per_window": per_window,
    }


def main() -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)

    all_results: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_per_side": COST_PER_SIDE,
        "execution": "signal at month-end close, execute at next trading day close",
        "macro_allocator_returns": MACRO_ALLOCATOR_RETURNS,
        "windows": {},
    }

    csv_rows: List[str] = []
    csv_rows.append("date,equity,position,daily_return,window,lookback_months")

    print("\n" + "=" * 100)
    print("DUAL MOMENTUM BACKTEST REPORT")
    print("=" * 100)
    print(f"Cost per side: {COST_PER_SIDE:.2%}")
    print(f"Execution: {all_results['execution']}")

    summary_rows = []
    for label in WINDOWS:
        res12 = run_window(label, 12)
        res6 = run_window(label, 6)

        all_results["windows"][label] = {
            "12_month": {
                "strategy_return": res12["strategy_return"],
                "qqq_return": res12["qqq_return"],
                "max_drawdown": res12["max_drawdown"],
                "rebalances": res12["rebalances"],
                "trades": res12["trades"],
                "first_date": res12["first_date"],
                "last_date": res12["last_date"],
            },
            "6_month": {
                "strategy_return": res6["strategy_return"],
                "qqq_return": res6["qqq_return"],
                "max_drawdown": res6["max_drawdown"],
                "rebalances": res6["rebalances"],
                "trades": res6["trades"],
                "first_date": res6["first_date"],
                "last_date": res6["last_date"],
            },
            "position_log_12m": res12["position_log"],
            "position_log_6m": res6["position_log"],
        }

        for res in [res12, res6]:
            for row in res["equity_curve"]:
                csv_rows.append(f"{row[0]},{row[1]:.6f},{row[2]},{row[3]:.6f},{label},{res['lookback_months']}")

        summary_rows.append({
            "window": label,
            "dm_12m": res12["strategy_return"],
            "dm_6m": res6["strategy_return"],
            "qqq": res12["qqq_return"],
            "max_dd_12m": res12["max_drawdown"],
            "max_dd_6m": res6["max_drawdown"],
            "rebal_12m": res12["rebalances"],
            "rebal_6m": res6["rebalances"],
        })

    oos12 = all_results["windows"]["2023–Aug 2024"]["12_month"]["strategy_return"]
    oos6 = all_results["windows"]["2023–Aug 2024"]["6_month"]["strategy_return"]
    best_lookback = 12 if oos12 >= oos6 else 6
    all_results["best_variant_lookback"] = best_lookback

    all_results["deploy_worthiness"] = assess_deploy_worthiness(all_results)

    with open(os.path.join(REPORTS_DIR, "dual_momentum_backtest_20260823.json"), "w") as fh:
        json.dump(all_results, fh, indent=2)
    with open(os.path.join(REPORTS_DIR, "dual_momentum_equity_20260823.csv"), "w") as fh:
        fh.write("\n".join(csv_rows) + "\n")

    print("\nWindow Results:")
    print(f"{'Window':<20} {'DM 12m':>10} {'DM 6m':>10} {'QQQ':>10} {'DD 12m':>10} {'DD 6m':>10} {'Rebal12':>8} {'Rebal6':>8}")
    print("-" * 100)
    for row in summary_rows:
        print(
            f"{row['window']:<20} "
            f"{row['dm_12m']:>9.2%} "
            f"{row['dm_6m']:>9.2%} "
            f"{row['qqq']:>9.2%} "
            f"{row['max_dd_12m']:>9.2%} "
            f"{row['max_dd_6m']:>9.2%} "
            f"{row['rebal_12m']:>7d} "
            f"{row['rebal_6m']:>7d} "
        )

    dw = all_results["deploy_worthiness"]
    print(f"\nBest variant (chosen on 2023–Aug 2024): {best_lookback}-month lookback")
    print(f"Deploy-worthy: {dw['deploy_worthy']}")
    print(f"  Beats macro allocator in {dw['beats_macro_allocator_count']}/3 windows")
    print(f"  Max drawdown <= -20% everywhere: {dw['max_drawdown_ok']}")
    print(f"  2022 return >= -10%: {dw['return_2022_ok']}")
    print("\nFiles written:")
    print(f"  /opt/stonk-ai/v3_rebuild/dual_momentum_engine.py")
    print(f"  /opt/stonk-ai/v3_rebuild/proper_backtest_dual_momentum.py")
    print(f"  {os.path.join(REPORTS_DIR, 'dual_momentum_backtest_20260823.json')}")
    print(f"  {os.path.join(REPORTS_DIR, 'dual_momentum_equity_20260823.csv')}")


if __name__ == "__main__":
    main()
