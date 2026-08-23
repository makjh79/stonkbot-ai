"""
data_audit.py
Audit the satellite alpha engine's data for survivorship bias, look-ahead bias,
and split-adjustment issues. Reports per-symbol history and point-in-time universe.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, date
from typing import Any, Dict, List, Tuple

import numpy as np


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")

DAILY_BARS_2YR_PATH = os.path.join(DATA_DIR, "daily_bars_2yr.json")
WINDOW_BAR_FILES = {
    "bear_2022": os.path.join(DATA_DIR, "bear_2022_bars.json"),
    "oos_2023_2024": os.path.join(DATA_DIR, "oos_2023_2024_bars.json"),
    "forward_2024_2026": os.path.join(DATA_DIR, "forward_2024_2026_bars.json"),
}

# The daily_bars_2yr.json file does not cover 2022/2023, but the cross-market
# windows contain the historical bars actually used for the bear 2022 and
# 2023-Aug 2024 tests. We audit both.


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_bars(path: str) -> Dict[str, Dict[str, Any]]:
    with open(path) as fh:
        data = json.load(fh)
    out = {}
    for sym, bars in data.items():
        out[sym] = dict(bars)
        if "timestamps" in bars:
            out[sym]["timestamps"] = [parse_ts(ts) for ts in bars["timestamps"]]
    return out


def audit_symbol(bars: Dict[str, Any]) -> Dict[str, Any]:
    ts = bars.get("timestamps", [])
    closes = bars.get("closes", [])
    if not ts or not closes:
        return {"error": "empty"}
    first_date = ts[0].date()
    last_date = ts[-1].date()
    n = len(ts)
    # Count trading days per calendar year
    by_year = defaultdict(int)
    for t in ts:
        by_year[t.year] += 1
    # Check for large one-day drops typical of reverse splits (e.g. 5:1 -> 80% drop)
    # or jumps typical of normal splits. We flag suspicious single-day log returns.
    splits_flagged = []
    if n >= 2:
        log_rets = []
        for i in range(1, n):
            prev = float(closes[i - 1])
            cur = float(closes[i])
            if prev > 0 and cur > 0:
                log_rets.append(np.log(cur / prev))
        if log_rets:
            mean_lr = np.mean(log_rets)
            std_lr = np.std(log_rets) if len(log_rets) > 1 else 0.0
            for i, lr in enumerate(log_rets, start=1):
                z = (lr - mean_lr) / std_lr if std_lr > 0 else 0.0
                # Flag days where log return magnitude exceeds ~10 normal days of vol
                if abs(z) > 10 and abs(lr) > 0.15:
                    splits_flagged.append({
                        "date": ts[i].isoformat(),
                        "prev_close": float(closes[i - 1]),
                        "close": float(closes[i]),
                        "log_return": float(lr),
                        "z_score": float(z),
                    })
    return {
        "first_date": first_date.isoformat(),
        "last_date": last_date.isoformat(),
        "trading_days": n,
        "days_by_year": dict(by_year),
        "still_active_at_end": last_date >= date(2026, 8, 20),
        "suspicious_split_flags": splits_flagged,
    }


def build_pit_universe(
    bars_by_sym: Dict[str, Dict[str, Any]],
    start_date: date,
    end_date: date,
    min_history_days: int = 252,
) -> Dict[str, List[str]]:
    """For each date in [start, end], return list of symbols with min_history_days as of that date."""
    universe_by_date: Dict[str, List[str]] = {}
    # Build index-of-date for each symbol
    for sym, bars in bars_by_sym.items():
        ts = bars.get("timestamps", [])
        if len(ts) < min_history_days:
            continue
        # Count days from start of symbol history up to each date
        for i, t in enumerate(ts):
            d = t.date()
            if d < start_date or d > end_date:
                continue
            if i + 1 >= min_history_days:
                universe_by_date.setdefault(d.isoformat(), []).append(sym)
    return universe_by_date


def count_universe_stats(universe_by_date: Dict[str, List[str]]) -> Dict[str, Any]:
    counts = [len(v) for v in universe_by_date.values()]
    if not counts:
        return {}
    return {
        "dates_covered": len(universe_by_date),
        "avg_symbols": float(np.mean(counts)),
        "median_symbols": float(np.median(counts)),
        "min_symbols": int(np.min(counts)),
        "max_symbols": int(np.max(counts)),
    }


def merge_window_bars(all_windows: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Combine cross-market window bars into a per-symbol full-history dictionary keyed by date."""
    merged: Dict[str, Dict[str, Any]] = {}
    for window_name, bars_by_sym in all_windows.items():
        for sym, bars in bars_by_sym.items():
            if sym not in merged:
                merged[sym] = {
                    "timestamps": [],
                    "closes": [],
                    "volumes": bars.get("volumes", []),
                }
            merged[sym]["timestamps"].extend(bars.get("timestamps", []))
            merged[sym]["closes"].extend(bars.get("closes", []))
            if "volumes" in bars and len(bars["volumes"]) == len(bars["closes"]):
                if "volumes" not in merged[sym] or len(merged[sym]["volumes"]) == 0:
                    merged[sym]["volumes"] = list(bars["volumes"])
                else:
                    merged[sym]["volumes"].extend(bars["volumes"])
    # Sort by date and deduplicate (cross-market windows overlap ~1 month)
    for sym in merged:
        ts = merged[sym]["timestamps"]
        if not ts:
            continue
        seen_dates = set()
        idx = []
        for i in sorted(range(len(ts)), key=lambda i: ts[i]):
            d = ts[i].date()
            if d in seen_dates:
                continue
            seen_dates.add(d)
            idx.append(i)
        merged[sym]["timestamps"] = [ts[i] for i in idx]
        for key in ("closes", "volumes"):
            if key in merged[sym] and len(merged[sym][key]) == len(ts):
                merged[sym][key] = [merged[sym][key][i] for i in idx]
    return merged


def main() -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # 1. Audit daily_bars_2yr.json (forward test universe)
    bars_2yr = load_bars(DAILY_BARS_2YR_PATH)
    per_symbol_2yr = {}
    for sym, bars in bars_2yr.items():
        per_symbol_2yr[sym] = audit_symbol(bars)

    full_history_2yr = sum(
        1 for v in per_symbol_2yr.values()
        if v.get("trading_days", 0) >= 500  # ~2 years
    )
    mid_window_additions = [
        sym for sym, v in per_symbol_2yr.items()
        if v.get("first_date", "") > "2024-08-15" and v.get("trading_days", 0) < 500
    ]
    delisted_2yr = [
        sym for sym, v in per_symbol_2yr.items()
        if not v.get("still_active_at_end", True)
    ]
    suspicious_splits_2yr = {
        sym: v["suspicious_split_flags"]
        for sym, v in per_symbol_2yr.items()
        if v.get("suspicious_split_flags")
    }

    # Point-in-time universe for daily_bars_2yr.json
    pit_2yr = build_pit_universe(bars_2yr, date(2024, 8, 14), date(2026, 8, 21), 252)
    pit_2yr_stats = count_universe_stats(pit_2yr)

    # 2. Audit cross-market windows for 2022 and 2023-2024 look-ahead / survivorship
    window_bars = {}
    for name, path in WINDOW_BAR_FILES.items():
        window_bars[name] = load_bars(path)

    merged_bars = merge_window_bars(window_bars)
    per_symbol_merged = {}
    for sym, bars in merged_bars.items():
        per_symbol_merged[sym] = audit_symbol(bars)

    # Use calendar coverage check: must include 2022-01-03 and 2026-08-21 and have enough trading days.
    full_history_merged = sum(
        1 for v in per_symbol_merged.values()
        if v.get("first_date", "9999-01-01") <= "2022-01-03"
        and v.get("last_date", "") >= "2026-08-21"
        and v.get("trading_days", 0) >= 620
    )
    # Mid-window additions: symbols that first appear after the start of the bear window
    # and do not remain active through the end of the test window.
    mid_window_additions_merged = [
        sym for sym, v in per_symbol_merged.items()
        if v.get("first_date", "") > "2022-01-03"
    ]
    delisted_merged = [
        sym for sym, v in per_symbol_merged.items()
        if not v.get("still_active_at_end", True)
    ]
    suspicious_splits_merged = {
        sym: v["suspicious_split_flags"]
        for sym, v in per_symbol_merged.items()
        if v.get("suspicious_split_flags")
    }

    pit_merged = build_pit_universe(merged_bars, date(2022, 1, 3), date(2026, 8, 21), 252)
    pit_merged_stats = count_universe_stats(pit_merged)

    # Report how many symbols had 252+ days as of each rebalance month end across all windows
    sample_pit_dates = sorted(pit_merged.keys())[-24:]  # last 24 months
    pit_sample = {d: len(pit_merged.get(d, [])) for d in sample_pit_dates}

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "daily_bars_2yr": {
            "file": DAILY_BARS_2YR_PATH,
            "total_symbols": len(bars_2yr),
            "full_history_symbols": full_history_2yr,
            "mid_window_additions": mid_window_additions,
            "delisted_or_disappeared": delisted_2yr,
            "suspicious_split_flags_count": sum(len(v) for v in suspicious_splits_2yr.values()),
            "suspicious_split_flags": suspicious_splits_2yr,
            "pit_universe_252d_stats": pit_2yr_stats,
        },
        "cross_market_windows": {
            "total_symbols_merged": len(merged_bars),
            "full_history_2022_to_2026": full_history_merged,
            "mid_window_additions": mid_window_additions_merged,
            "delisted_or_disappeared": delisted_merged,
            "suspicious_split_flags_count": sum(len(v) for v in suspicious_splits_merged.values()),
            "suspicious_split_flags": suspicious_splits_merged,
            "pit_universe_252d_stats": pit_merged_stats,
        },
        "per_symbol": per_symbol_merged,
        "pit_sample_last_24mo": pit_sample,
    }

    out_path = os.path.join(REPORTS_DIR, "data_audit_summary_20260823.json")
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=2)

    print("=" * 80)
    print("DATA AUDIT SUMMARY")
    print("=" * 80)
    print(f"daily_bars_2yr symbols: {summary['daily_bars_2yr']['total_symbols']}")
    print(f"  full history (>=500d): {summary['daily_bars_2yr']['full_history_symbols']}")
    print(f"  mid-window additions: {len(summary['daily_bars_2yr']['mid_window_additions'])}")
    print(f"  delisted/disappeared: {len(summary['daily_bars_2yr']['delisted_or_disappeared'])}")
    print(f"  suspicious split flags: {summary['daily_bars_2yr']['suspicious_split_flags_count']}")
    print()
    print(f"cross-market merged symbols: {summary['cross_market_windows']['total_symbols_merged']}")
    print(f"  full history 2022-2026 (>=630d): {summary['cross_market_windows']['full_history_2022_to_2026']}")
    print(f"  mid-window additions: {len(summary['cross_market_windows']['mid_window_additions'])}")
    print(f"  delisted/disappeared: {len(summary['cross_market_windows']['delisted_or_disappeared'])}")
    print(f"  suspicious split flags: {summary['cross_market_windows']['suspicious_split_flags_count']}")
    print()
    print("PIT universe 252d stats (merged 2022-2026):")
    for k, v in pit_merged_stats.items():
        print(f"  {k}: {v}")
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
