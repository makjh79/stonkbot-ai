#!/usr/bin/env python3
"""Long-history backtest driver (2007-2026).

Reuses the VERIFIED engines unmodified:
  - macro allocator via proper_backtest_macro_allocator.run_window
  - dual momentum via proper_backtest_dual_momentum.run_window (12m and 6m)

Slices the full-period equity curves into named regimes and writes
/opt/stonk-ai/reports/long_backtest_20260823.json.
"""
import json
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, "/opt/stonk-ai/v3_rebuild")

from proper_backtest_macro_allocator import run_window as macro_run  # noqa: E402
import proper_backtest_dual_momentum as dm  # noqa: E402

dm.WINDOWS["long_2007_2026"] = {"start": "2007-04-11", "end": "2026-08-21"}


DATA_DIR = "/opt/stonk-ai/v3_rebuild/data"
WKEY = "long_2007_2026"
REPORT = "/opt/stonk-ai/reports/long_backtest_20260823.json"

REGIMES = [
    ("GFC 2008-09", "2008-01-01", "2009-12-31"),
    ("2011", "2011-01-01", "2011-12-31"),
    ("2015-16", "2015-01-01", "2016-12-31"),
    ("2018", "2018-01-01", "2018-12-31"),
    ("2020 COVID", "2020-01-01", "2020-12-31"),
    ("2022 bear", "2022-01-01", "2022-12-31"),
    ("2023-2026 bull", "2023-01-01", "2026-08-21"),
]


def day_str(x) -> str:
    if isinstance(x, str):
        return x[:10]
    if isinstance(x, datetime):
        return x.strftime("%Y-%m-%d")
    return str(x)[:10]


def regime_metrics(days, vals):
    """vals aligned to days. Return per-regime return and max DD using the
    close just before the regime start as base when available."""
    out = {}
    n = len(days)
    for name, a, b in REGIMES:
        idx = [i for i in range(n) if a <= days[i] <= b]
        if len(idx) < 5:
            out[name] = None
            continue
        base_i = max(0, idx[0] - 1)
        eq = np.array([vals[base_i]] + [vals[i] for i in idx], dtype=float)
        ret = float(eq[-1] / eq[0] - 1.0)
        rm = np.maximum.accumulate(eq)
        dd = float(np.min((eq - rm) / rm))
        out[name] = {"return": round(ret, 4), "max_dd": round(dd, 4)}
    return out


def full_metrics(days, vals):
    eq = np.array(vals, dtype=float)
    rets = np.diff(eq) / eq[:-1]
    total = float(eq[-1] / eq[0] - 1.0)
    yrs = (datetime.fromisoformat(days[-1]) - datetime.fromisoformat(days[0])).days / 365.25
    cagr = float((eq[-1] / eq[0]) ** (1.0 / yrs) - 1.0) if yrs > 0 else None
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if np.std(rets) > 0 else None
    rm = np.maximum.accumulate(eq)
    dd = float(np.min((eq - rm) / rm))
    return {
        "total_return": round(total, 4),
        "cagr": round(cagr, 4) if cagr is not None else None,
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "max_dd": round(dd, 4),
        "years": round(yrs, 2),
    }


def exposure_stats(days, exposures):
    out = {}
    n = len(days)
    for name, a, b in REGIMES:
        xs = [exposures[i] for i in range(n) if a <= days[i] <= b]
        out[name] = round(float(np.mean(xs)), 3) if xs else None
    out["full"] = round(float(np.mean(exposures)), 3)
    return out


def main() -> None:
    report = {"generated_at": datetime.utcnow().isoformat() + "Z", "window_key": WKEY}

    # --- Macro allocator ---
    res = macro_run(DATA_DIR, WKEY)
    curve = res["equity_curve"]  # (iso, equity, exposure, qqq_close, spy_close)
    days = [day_str(r[0]) for r in curve]
    eq = [float(r[1]) for r in curve]
    expo = [float(r[2]) for r in curve]
    qqq = [float(r[3]) for r in curve]
    spy = [float(r[4]) for r in curve]

    report["macro_allocator"] = {
        "first_date": days[0],
        "last_date": days[-1],
        "full": full_metrics(days, eq),
        "regimes": regime_metrics(days, eq),
        "avg_exposure_by_regime": exposure_stats(days, expo),
        "rebalances": res.get("rebalances"),
    }
    report["qqq_buy_hold"] = {
        "full": full_metrics(days, qqq),
        "regimes": regime_metrics(days, qqq),
    }
    report["spy_buy_hold"] = {
        "full": full_metrics(days, spy),
        "regimes": regime_metrics(days, spy),
    }

    # --- Dual momentum 12m / 6m ---
    for lb in (12, 6):
        try:
            r = dm.run_window(WKEY, lb)
            dc = r["equity_curve"]  # (datetime, equity, position, daily_ret)
            ddays = [day_str(row[0]) for row in dc]
            deq = [float(row[1]) for row in dc]
            report[f"dual_momentum_{lb}m"] = {
                "first_date": ddays[0],
                "last_date": ddays[-1],
                "full": full_metrics(ddays, deq),
                "regimes": regime_metrics(ddays, deq),
                "rebalances": r.get("rebalances"),
            }
        except Exception as e:  # noqa: BLE001
            report[f"dual_momentum_{lb}m"] = {"error": f"{type(e).__name__}: {e}"}

    with open(REPORT, "w") as fh:
        json.dump(report, fh, indent=2)

    # Compact stdout summary
    print("FULL-PERIOD SUMMARY")
    for k in ("macro_allocator", "dual_momentum_12m", "dual_momentum_6m", "qqq_buy_hold", "spy_buy_hold"):
        blk = report.get(k) or {}
        if "error" in blk:
            print(k, "ERROR", blk["error"])
            continue
        f = blk.get("full") or {}
        print(k, json.dumps(f))
    print("\nREGIME RETURNS (strategy | QQQ):")
    for name, _, _ in REGIMES:
        m = (report["macro_allocator"]["regimes"].get(name) or {})
        q = (report["qqq_buy_hold"]["regimes"].get(name) or {})
        d12 = (report.get("dual_momentum_12m", {}).get("regimes") or {}).get(name) or {}
        print(
            f"{name:18s} macro {m.get('return')} (dd {m.get('max_dd')}) | "
            f"dm12 {d12.get('return')} (dd {d12.get('max_dd')}) | "
            f"qqq {q.get('return')} (dd {q.get('max_dd')})"
        )
    print("\nreport written:", REPORT)


if __name__ == "__main__":
    main()
