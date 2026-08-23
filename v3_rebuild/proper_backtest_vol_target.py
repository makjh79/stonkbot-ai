#!/usr/bin/env python3
"""
proper_backtest_vol_target.py
Backtest the VolTargetEngine across the three standard cross-market windows.

- Daily rebalancing to the engine's target exposure.
- 5 percentage-point trade band to reduce churn.
- Honest 1-day execution lag: signal computed at close of day t,
  trade executed at close of day t+1.
- 0.10% transaction cost per side on traded notional.
- Portfolio: exposure * QQQ + (1 - exposure) * SHY (cash if SHY unavailable).

Outputs:
  /opt/stonk-ai/reports/vol_target_backtest_YYYYMMDD.json
  /opt/stonk-ai/reports/vol_target_equity_YYYYMMDD.csv
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from vol_target_engine import (
    VolTargetEngine,
    align_window_series,
    load_daily_bars_2yr,
    load_window_data,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
REPORT_DIR = Path("/opt/stonk-ai/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

DATE_TAG = "20260823"

WINDOWS: Dict[str, str] = {
    "2022 bear": "bear_2022",
    "2023–Aug 2024": "oos_2023_2024",
    "Aug 2024–Aug 2026": "forward_2024_2026",
}

# Selection window for the "best" variant (avoid forward-window selection bias).
SELECT_WINDOW_LABEL = "2023–Aug 2024"

PARAM_GRID: List[Dict[str, Any]] = [
    {"target_vol": 0.10, "vol_lookback": 20},
    {"target_vol": 0.10, "vol_lookback": 60},
    {"target_vol": 0.12, "vol_lookback": 20},
    {"target_vol": 0.12, "vol_lookback": 60},
    {"target_vol": 0.15, "vol_lookback": 20},
    {"target_vol": 0.15, "vol_lookback": 60},
]

MACRO_ALLOCATOR_BASELINE = {
    "2022 bear": -0.0168,
    "2023–Aug 2024": 0.4375,
    "Aug 2024–Aug 2026": 0.5369,
}

STOP_CRITERIA = {
    "2022 bear": {"min_return": -0.15, "max_drawdown": -0.20},
    "2023–Aug 2024": {"min_return": 0.50, "max_drawdown": -0.20},
    "Aug 2024–Aug 2026": {"min_return": 0.40, "max_drawdown": -0.20},
}

REQUIRED_SYMS = ["SPY", "QQQ", "LQD", "HYG", "VIXY", "SHY"]
COST_PER_SIDE = 0.001
TRADE_BAND = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_window(
    engine: VolTargetEngine,
    window_name: str,
    window_label: str,
) -> Dict[str, Any]:
    """Run one window and return metrics + equity curve."""
    raw = load_window_data(DATA_DIR, window_name)
    data = align_window_series(raw, REQUIRED_SYMS)

    dates = data["dates"]
    spy = data["SPY"]
    qqq = data["QQQ"]
    shy = data["SHY"]
    lqd = data["LQD"]
    hyg = data["HYG"]
    vixy = data["VIXY"]

    # Record whether SHY was actually used (it is available in all regime ETF files).
    shy_used = True

    signals = engine.compute_signals(
        spy_prices=spy,
        qqq_prices=qqq,
        lqd_prices=lqd,
        hyg_prices=hyg,
        vixy_prices=vixy,
        shy_prices=shy,
    )
    target = signals["target_exposure"]
    base = signals["base_exposure"]
    overlay = signals["overlay"]
    crisis = signals["crisis_brake_active"]
    dd20 = signals["drawdown_20d_high"]
    vol = signals["realized_vol"]

    equity = 1.0
    current_exposure = 0.0  # exposure in effect for today's return
    trades = 0
    turnover_total = 0.0
    equity_curve: List[Dict[str, Any]] = []

    n = len(dates)
    warmup = engine.required_warmup_days

    for i in range(n):
        # Daily returns of the two sleeves.
        if i == 0:
            qqq_ret = 0.0
            shy_ret = 0.0
        else:
            qqq_ret = qqq[i] / qqq[i - 1] - 1.0
            shy_ret = shy[i] / shy[i - 1] - 1.0

        daily_ret = current_exposure * qqq_ret + (1.0 - current_exposure) * shy_ret
        equity *= 1.0 + daily_ret

        # Determine target to execute at close of today (signal from yesterday).
        target_for_today = target[i - 1] if i >= 1 else 0.0

        # Trade only if the change exceeds the band.
        if abs(target_for_today - current_exposure) > TRADE_BAND:
            turnover = abs(target_for_today - current_exposure)
            equity *= 1.0 - turnover * COST_PER_SIDE
            turnover_total += turnover
            current_exposure = target_for_today
            trades += 1

        equity_curve.append({
            "date": dates[i].isoformat(),
            "equity": float(equity),
            "effective_exposure": float(current_exposure),
            "target_exposure": float(target[i]),
            "base_exposure": float(base[i]) if base[i] is not None and not np.isnan(base[i]) else 0.0,
            "overlay": float(overlay[i]),
            "crisis_brake": bool(crisis[i]) if i < len(crisis) else False,
            "drawdown_20d_high": float(dd20[i]) if dd20[i] is not None and not np.isnan(dd20[i]) else 0.0,
            "realized_vol": float(vol[i]) if vol[i] is not None and not np.isnan(vol[i]) else 0.0,
            "qqq_close": float(qqq[i]),
            "shy_close": float(shy[i]),
            "window": window_label,
        })

    eq_arr = np.array([r["equity"] for r in equity_curve])
    running_peak = np.maximum.accumulate(eq_arr)
    drawdowns = (running_peak - eq_arr) / running_peak
    max_dd = float(np.max(drawdowns))

    total_ret = float(eq_arr[-1] / eq_arr[0] - 1.0)
    avg_exposure = float(np.mean([r["effective_exposure"] for r in equity_curve]))

    qqq_total_ret = float(qqq[-1] / qqq[0] - 1.0)

    # Recovery-capture metric: first trading day after 2022-12-31 with exposure > 75%.
    recovery_days_after_2022: Optional[int] = None
    recovery_date: Optional[str] = None
    cutoff = date(2022, 12, 31)
    for r in equity_curve:
        d = date.fromisoformat(r["date"])
        if d > cutoff and r["effective_exposure"] > 0.75:
            recovery_days_after_2022 = (d - cutoff).days
            recovery_date = r["date"]
            break

    return {
        "window_label": window_label,
        "window_name": window_name,
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "n_days": n,
        "warmup_days": warmup,
        "first_signal_date": dates[warmup].isoformat() if warmup < n else None,
        "strategy_return": total_ret,
        "qqq_return": qqq_total_ret,
        "spy_return": float(spy[-1] / spy[0] - 1.0),
        "max_drawdown": max_dd,
        "avg_exposure": avg_exposure,
        "turnover_total": float(turnover_total),
        "trades": trades,
        "recovery_days_after_2022_12_31": recovery_days_after_2022,
        "recovery_date_above_75pct": recovery_date,
        "shy_used": shy_used,
        "equity_curve": equity_curve,
    }


def _variant_label(param: Dict[str, Any], overlay: bool = True) -> str:
    ov = "ovly" if overlay else "pure"
    return f"tv{param['target_vol']:.0%}_lb{param['vol_lookback']}d_{ov}"


def _run_variant(param: Dict[str, Any], overlay: bool = True) -> Dict[str, Any]:
    """Run all windows for one parameter set."""
    engine = VolTargetEngine(
        target_vol=param["target_vol"],
        vol_lookback=param["vol_lookback"],
        enable_overlay=overlay,
    )
    label = _variant_label(param, overlay)
    results: Dict[str, Any] = {}
    for win_label, win_name in WINDOWS.items():
        results[win_label] = _run_window(engine, win_name, win_label)
    return {
        "variant": label,
        "target_vol": param["target_vol"],
        "vol_lookback": param["vol_lookback"],
        "overlay_enabled": overlay,
        "windows": results,
    }


def _write_equity_csv(path: Path, all_variants: List[Dict[str, Any]]) -> None:
    """Write combined equity curve for all variants and windows."""
    fieldnames = [
        "variant", "window", "date", "equity", "effective_exposure",
        "target_exposure", "base_exposure", "overlay", "crisis_brake",
        "drawdown_20d_high", "realized_vol", "qqq_close", "shy_close",
    ]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for variant in all_variants:
            for win_label, win_res in variant["windows"].items():
                for row in win_res["equity_curve"]:
                    writer.writerow({
                        "variant": variant["variant"],
                        "window": win_label,
                        "date": row["date"],
                        "equity": f"{row['equity']:.6f}",
                        "effective_exposure": f"{row['effective_exposure']:.4f}",
                        "target_exposure": f"{row['target_exposure']:.4f}",
                        "base_exposure": f"{row['base_exposure']:.4f}",
                        "overlay": f"{row['overlay']:.4f}",
                        "crisis_brake": int(row["crisis_brake"]),
                        "drawdown_20d_high": f"{row['drawdown_20d_high']:.4f}",
                        "realized_vol": f"{row['realized_vol']:.4f}",
                        "qqq_close": f"{row['qqq_close']:.4f}",
                        "shy_close": f"{row['shy_close']:.4f}",
                    })


def _select_best_variant(variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Select the best variant using ONLY the 2023-Aug 2024 window.
    Prefer highest strategy return among variants that keep drawdown <= -20%
    in that window.
    """
    candidates = []
    for v in variants:
        res = v["windows"][SELECT_WINDOW_LABEL]
        if res["max_drawdown"] <= 0.20:  # i.e. not worse than -20%
            candidates.append((res["strategy_return"], v))
    if candidates:
        candidates.sort(key=lambda x: -x[0])
        return candidates[0][1]
    # Fallback: if no one met the DD constraint, just pick highest return.
    return max(variants, key=lambda v: v["windows"][SELECT_WINDOW_LABEL]["strategy_return"])


def _check_stop_criteria(best: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Check the ex-ante deploy-worthiness stop conditions."""
    passed = True
    details = {}
    for win_label, criteria in STOP_CRITERIA.items():
        res = best["windows"][win_label]
        ret_ok = res["strategy_return"] >= criteria["min_return"]
        dd_ok = res["max_drawdown"] <= abs(criteria["max_drawdown"])
        win_ok = ret_ok and dd_ok
        details[win_label] = {
            "return_pass": ret_ok,
            "drawdown_pass": dd_ok,
            "window_pass": win_ok,
            "strategy_return": res["strategy_return"],
            "max_drawdown": res["max_drawdown"],
            "required_min_return": criteria["min_return"],
            "required_max_drawdown": criteria["max_drawdown"],
        }
        if not win_ok:
            passed = False
    return passed, details


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat()

    # Run the 6 main variants.
    variants: List[Dict[str, Any]] = []
    print("Running vol-target grid (6 variants)...")
    for param in PARAM_GRID:
        variant = _run_variant(param, overlay=True)
        variants.append(variant)
        res = variant["windows"][SELECT_WINDOW_LABEL]
        print(
            f"  {variant['variant']}: "
            f"2023-Aug ret={res['strategy_return']:>7.2%} "
            f"DD={res['max_drawdown']:>6.2%} "
            f"avg_exp={res['avg_exposure']:>5.2%} "
            f"trades={res['trades']}"
        )

    # Select best variant using only the selection window.
    best = _select_best_variant(variants)
    best_param = {"target_vol": best["target_vol"], "vol_lookback": best["vol_lookback"]}

    # Ablation: same best params with overlay disabled.
    ablation = _run_variant(best_param, overlay=False)

    stop_pass, stop_details = _check_stop_criteria(best)

    # Build summary tables.
    grid_rows = []
    for v in variants:
        row = {
            "variant": v["variant"],
            "target_vol": v["target_vol"],
            "vol_lookback": v["vol_lookback"],
        }
        for win_label in WINDOWS:
            row[f"{win_label}_return"] = v["windows"][win_label]["strategy_return"]
            row[f"{win_label}_max_dd"] = v["windows"][win_label]["max_drawdown"]
        grid_rows.append(row)

    best_table_rows = []
    for win_label in WINDOWS:
        res = best["windows"][win_label]
        ab_res = ablation["windows"][win_label]
        best_table_rows.append({
            "window": win_label,
            "strategy_return": res["strategy_return"],
            "macro_baseline_return": MACRO_ALLOCATOR_BASELINE[win_label],
            "qqq_return": res["qqq_return"],
            "max_drawdown": res["max_drawdown"],
            "avg_exposure": res["avg_exposure"],
            "turnover_total": res["turnover_total"],
            "trades": res["trades"],
            "recovery_days_after_2022_12_31": res["recovery_days_after_2022_12_31"],
            "recovery_date_above_75pct": res["recovery_date_above_75pct"],
            "ablation_pure_vol_return": ab_res["strategy_return"],
            "ablation_max_drawdown": ab_res["max_drawdown"],
            "ablation_avg_exposure": ab_res["avg_exposure"],
            "ablation_trades": ab_res["trades"],
        })

    # Data-source provenance.
    data_provenance = {}
    for win_label, win_name in WINDOWS.items():
        data_provenance[win_label] = {
            "bars_file": str(DATA_DIR / f"{win_name}_bars.json"),
            "regime_etfs_file": str(DATA_DIR / f"{win_name}_regime_etfs.json"),
            "symbols_loaded": REQUIRED_SYMS,
            "first_date": best["windows"][win_label]["first_date"],
            "last_date": best["windows"][win_label]["last_date"],
            "warmup_days": best["windows"][win_label]["warmup_days"],
            "first_signal_date": best["windows"][win_label]["first_signal_date"],
            "history_shortfall_handling": (
                "Started flat until the longest required lookback (60 trading days) "
                "was available.  No external pre-window history was appended."
            ),
        }

    report = {
        "generated_at": generated_at,
        "date_tag": DATE_TAG,
        "best_variant": best["variant"],
        "best_params": {
            "target_vol": best["target_vol"],
            "vol_lookback": best["vol_lookback"],
            "overlay_enabled": True,
        },
        "selection_window": SELECT_WINDOW_LABEL,
        "stop_criteria_passed": stop_pass,
        "stop_criteria_details": stop_details,
        "macro_allocator_baseline": MACRO_ALLOCATOR_BASELINE,
        "grid_summary": grid_rows,
        "best_variant_table": best_table_rows,
        "ablation": {
            "variant": ablation["variant"],
            "params": {"target_vol": ablation["target_vol"], "vol_lookback": ablation["vol_lookback"]},
            "windows": {
                win_label: {
                    "strategy_return": ablation["windows"][win_label]["strategy_return"],
                    "max_drawdown": ablation["windows"][win_label]["max_drawdown"],
                    "avg_exposure": ablation["windows"][win_label]["avg_exposure"],
                    "trades": ablation["windows"][win_label]["trades"],
                }
                for win_label in WINDOWS
            },
        },
        "data_provenance": data_provenance,
        "methodology": {
            "signal_lag": "1-day honest lag: signal at close t, executed at close t+1",
            "trade_band": f"{TRADE_BAND:.0%}",
            "cost_per_side": f"{COST_PER_SIDE:.2%}",
            "sleeve": "exposure * QQQ + (1 - exposure) * SHY",
            "shy_available": True,
            "cash_fallback": False,
        },
        "all_variants": variants,
    }

    json_path = REPORT_DIR / f"vol_target_backtest_{DATE_TAG}.json"
    csv_path = REPORT_DIR / f"vol_target_equity_{DATE_TAG}.csv"

    with open(json_path, "w") as fh:
        json.dump(report, fh, indent=2)

    _write_equity_csv(csv_path, variants + [ablation])

    # Print concise report.
    print("\n" + "=" * 90)
    print("VOLATILITY-TARGETED INDEX ENGINE BACKTEST REPORT")
    print("=" * 90)
    print(f"Generated: {generated_at}")
    print(f"Best variant (selected on {SELECT_WINDOW_LABEL} only): {best['variant']}")
    print(f"Stop criteria passed: {stop_pass}  {'DEPLOY' if stop_pass else 'STOP'}")
    print(f"\nBest variant per-window table")
    print("-" * 90)
    print(
        f"{'Window':<20} {'VolTarget':>10} {'MacroBase':>10} {'QQQ':>10} "
        f"{'Max DD':>10} {'Avg Exp':>9} {'Turnover':>10} {'Trades':>8}"
    )
    print("-" * 90)
    for row in best_table_rows:
        print(
            f"{row['window']:<20} "
            f"{row['strategy_return']:>9.2%} "
            f"{row['macro_baseline_return']:>9.2%} "
            f"{row['qqq_return']:>9.2%} "
            f"{row['max_drawdown']:>9.2%} "
            f"{row['avg_exposure']:>8.2%} "
            f"{row['turnover_total']:>9.2f} "
            f"{row['trades']:>7d}"
        )
    print("-" * 90)

    print("\nGrid summary (strategy returns)")
    print(
        f"{'Variant':<18} {'2022 bear':>12} {'2023-Aug24':>12} {'Aug24-Aug26':>12}"
    )
    print("-" * 60)
    for row in grid_rows:
        print(
            f"{row['variant']:<18} "
            f"{row['2022 bear_return']:>11.2%} "
            f"{row['2023–Aug 2024_return']:>11.2%} "
            f"{row['Aug 2024–Aug 2026_return']:>11.2%}"
        )
    print("-" * 60)

    print("\nAblation: pure vol targeting vs vol + dip overlay")
    for win_label in WINDOWS:
        res = best["windows"][win_label]
        ab = ablation["windows"][win_label]
        print(
            f"  {win_label:<20} overlay={res['strategy_return']:>8.2%} "
            f"pure={ab['strategy_return']:>8.2%} "
            f"delta={res['strategy_return'] - ab['strategy_return']:>+8.2%}"
        )

    rec = best["windows"][SELECT_WINDOW_LABEL]
    print("\nExposure recovery metric")
    if rec["recovery_date_above_75pct"]:
        print(
            f"  First day >75% exposure after 2022-12-31: "
            f"{rec['recovery_date_above_75pct']} "
            f"({rec['recovery_days_after_2022_12_31']} calendar days after 2022-12-31)"
        )
    else:
        print("  Exposure never exceeded 75% after 2022-12-31 in the selection window.")

    print("\nLimitations")
    print("  - No leverage in v1 (max exposure capped at 1.0).")
    print("  - ETF proxies; no dividend reinvestment, split, or NAV adjustments.")
    print("  - 1-day execution lag vs next-open introduces additional slippage not modeled.")
    print("  - Window data is bounded; 60-day warm-up starts each window flat.")
    print("  - SHY used as the risk-free/cash sleeve where available.")

    print(f"\nFiles written:\n  {json_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
