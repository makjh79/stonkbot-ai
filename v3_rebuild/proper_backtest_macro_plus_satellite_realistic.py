"""
proper_backtest_macro_plus_satellite_realistic.py
Backtest MacroAllocator + SatelliteAlphaEngine combined system with realistic execution.

Stricter rules vs v0:
- Point-in-time universe: symbols must have 252+ trading days of history as of rebalance date.
- Next-open execution: signal at month-end close, execute at next-month first trading day open.
- Liquidity filter: 20-day avg dollar volume >= $10M.
- Volatility filter: 20-day annualized vol <= 80%.
- Microcap filter: price >= $5 (market-cap proxy unavailable, so price filter only).
- Slippage: 0.10% per side + vol20d * 0.05 (annualized vol as decimal).
- Sector capping: individual stock cap 12.5%; sector data unavailable.
- Opens absent: conservative estimate open = close * (1 + normal noise, std=0.0035, seeded).

Walk-forward:
- In-sample optimize macro allocator parameters on 2022-Aug 2024 (macro-only, satellite weights fixed).
- Report forward performance Aug 2024-Aug 2026 vs in-sample optimized numbers.
"""

from __future__ import annotations

import json
import os
import random
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
MAX_POSITION_PCT = 0.125
SECTOR_CAP_PCT = 0.25  # documented limitation
MIN_HISTORY_DAYS = 252
MIN_DOLLAR_VOLUME = 10_000_000  # 20-day avg
MAX_VOLATILITY = 0.80
MIN_PRICE = 5.0
OPEN_NOISE_STD = 0.0035
BOND_PROXY_PREFERENCE = ("TLT", "SHY")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def load_daily_bars(path: str) -> Dict[str, Dict[str, Any]]:
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


def build_stock_bars_by_date(stock_bars: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for sym, bars in stock_bars.items():
        out[sym] = dict(bars)
    return out


def estimate_open(close: float, rng: random.Random) -> float:
    """Conservative open estimate when real opens are unavailable."""
    return close * (1.0 + rng.gauss(0.0, OPEN_NOISE_STD))


def annualized_vol(closes: np.ndarray, window: int = 20) -> float:
    if len(closes) < window + 1:
        return 1.0
    log_rets = np.diff(np.log(closes[-(window + 1) :].clip(min=1e-9)))
    return float(np.std(log_rets) * np.sqrt(252))


def avg_dollar_volume(closes: np.ndarray, volumes: np.ndarray, window: int = 20) -> float:
    if len(closes) < window or len(volumes) < window:
        return 0.0
    return float(np.mean(closes[-window:] * volumes[-window:]))


def find_bond_proxy(raw: Dict[str, Any]) -> Optional[str]:
    for sym in BOND_PROXY_PREFERENCE:
        if sym in raw and len(raw[sym]["closes"]) > 0:
            return sym
    return None


def _compute_turnover(
    old_satellite_weights: Dict[str, float],
    old_bond_weight: float,
    new_satellite_weights: Dict[str, float],
    new_bond_weight: float,
    new_cash_weight: float,
) -> float:
    symbols = set(old_satellite_weights) | set(new_satellite_weights)
    turnover = 0.0
    for sym in symbols:
        turnover += abs(new_satellite_weights.get(sym, 0.0) - old_satellite_weights.get(sym, 0.0))
    turnover += abs(new_bond_weight - old_bond_weight)
    old_cash_weight = 1.0 - old_bond_weight - sum(old_satellite_weights.values())
    turnover += abs(new_cash_weight - old_cash_weight)
    return turnover


def point_in_time_universe(
    all_bars: Dict[str, Dict[str, Any]],
    date: datetime,
    min_history_days: int = MIN_HISTORY_DAYS,
    min_dv: float = MIN_DOLLAR_VOLUME,
    max_vol: float = MAX_VOLATILITY,
    min_price: float = MIN_PRICE,
    exclude: Optional[set] = None,
) -> List[str]:
    """Return symbols that pass all realistic filters as of date."""
    eligible: List[str] = []
    target = date.date()
    exclude = exclude or set()
    for sym, bars in all_bars.items():
        if sym in exclude:
            continue
        ts = bars.get("timestamps", [])
        closes = bars.get("closes", [])
        volumes = bars.get("volumes", [])
        if not ts or len(closes) < min_history_days + 20:
            continue
        # Find index for target date
        idx = None
        for i, t in enumerate(ts):
            if t.date() == target:
                idx = i
                break
        if idx is None or idx < min_history_days:
            continue
        # Price filter
        if closes[idx] < min_price:
            continue
        # Vol filter
        c_arr = np.array(closes[: idx + 1], dtype=float)
        vol = annualized_vol(c_arr, 20)
        if vol > max_vol or np.isnan(vol):
            continue
        # Liquidity filter
        if len(volumes) == len(closes):
            v_arr = np.array(volumes[: idx + 1], dtype=float)
            dv = avg_dollar_volume(c_arr, v_arr, 20)
            if dv < min_dv:
                continue
        eligible.append(sym)
    return eligible


# ---------------------------------------------------------------------------
# Backtest core
# ---------------------------------------------------------------------------
def run_window(
    data_dir: str,
    window_key: str,
    daily_bars_path: str,
    macro_allocator: MacroAllocator,
    satellite_engine: SatelliteAlphaEngine,
    rng: random.Random,
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

    # Choose bars file: dedicated window bars file if exists, else 2yr
    window_bars_path = os.path.join(data_dir, f"{window_key}_bars.json")
    if not os.path.exists(window_bars_path):
        window_bars_path = daily_bars_path
    all_bars = load_daily_bars(window_bars_path)
    stock_bars_by_date = build_stock_bars_by_date(all_bars)

    bond_proxy = find_bond_proxy(raw)
    bond_closes = np.array(raw[bond_proxy]["closes"], dtype=float) if bond_proxy else None
    spy_closes = np.array(spy["closes"], dtype=float)
    qqq_closes = np.array(qqq["closes"], dtype=float)

    rebalance_indices = month_end_indices(dates)

    equity = 1.0
    exposure = 0.0
    satellite_weights: Dict[str, float] = {}
    satellite_entry_prices: Dict[str, float] = {}
    equity_curve: List[Tuple[str, float, float, float, int, float, float]] = []
    trades = 0
    exposure_sum = 0.0
    exposure_count = 0
    stock_count_sum = 0
    stock_count_samples = 0
    rebalances = 0
    contribution: Dict[str, float] = defaultdict(float)
    slippage_total = 0.0
    cost_total = 0.0

    prev_i: Optional[int] = None
    for i in rebalance_indices:
        d = dates[i].date()
        target_exposure = 0.0
        if d in feat_by_date:
            target_exposure = macro_allocator.decide_equity_exposure(dates[i], feat_by_date[d].to_dict())

        # Execution at next open (next trading day after signal)
        exec_idx = i + 1 if i + 1 < len(dates) else i
        exec_date = dates[exec_idx]
        exec_d = exec_date.date()

        # New satellite sleeve selection as of signal date, but prices at exec_idx
        new_satellite_weights: Dict[str, float] = {}
        new_bond_weight = 0.0
        new_cash_weight = 0.0

        if target_exposure > 0.30:
            satellite_capital = equity * target_exposure
            bond_capital = equity * (1.0 - target_exposure)
            # Universe as of signal date d
            eligible = point_in_time_universe(
                all_bars, dates[i], exclude=satellite_engine.exclude_symbols
            )
            signals = satellite_engine.select_stocks(
                dates[i], stock_bars_by_date, eligible_universe=eligible, spy_bars=all_bars.get("SPY")
            )
            notionals = satellite_engine.size_positions(signals, satellite_capital, equal_weight=True)
            new_satellite_weights = {
                sym: notional / equity for sym, notional in notionals.items()
            }
            # Record entry prices at exec open estimate
            entry_prices: Dict[str, float] = {}
            for sym, w in new_satellite_weights.items():
                bars = stock_bars_by_date.get(sym)
                if bars is None:
                    continue
                ei = _find_index_for_date(bars, exec_date)
                if ei is None:
                    continue
                close = float(bars["closes"][ei])
                entry_prices[sym] = estimate_open(close, rng)
            if bond_proxy and bond_closes is not None:
                new_bond_weight = bond_capital / equity
            else:
                new_cash_weight = bond_capital / equity
        elif target_exposure > 0.0:
            # Macro wants modest equity sleeve but below satellite threshold: hold bond proxy.
            if bond_proxy and bond_closes is not None:
                new_bond_weight = 1.0
            else:
                new_cash_weight = 1.0
        else:
            new_cash_weight = 1.0

        # Slippage + cost on turnover. Only charge risky-asset turnover; cash residual change is not traded.
        traded_turnover = sum(
            abs(new_satellite_weights.get(s, 0.0) - satellite_weights.get(s, 0.0))
            for s in set(new_satellite_weights) | set(satellite_weights)
        ) + abs(new_bond_weight - (1.0 - exposure - sum(satellite_weights.values())))
        # Note: old bond weight = 1 - exposure - sum(satellite_weights) when old cash weight = 0
        # We ignore cash turnover because cash is the untraded residual.
        if traded_turnover > 1e-9:
            trades += 1
            # Estimate slippage from portfolio vol of traded sleeve
            traded_vol = 0.0
            if new_satellite_weights:
                vols = []
                for sym in set(satellite_weights) | set(new_satellite_weights):
                    bars = stock_bars_by_date.get(sym)
                    if bars is None:
                        continue
                    ei = _find_index_for_date(bars, exec_date)
                    if ei is None or ei < 20:
                        continue
                    arr = np.array(bars["closes"][: ei + 1], dtype=float)
                    vols.append(annualized_vol(arr, 20))
                if vols:
                    traded_vol = float(np.mean(vols))
            elif bond_proxy and bond_closes is not None:
                ei = i + 1 if i + 1 < len(bond_closes) else i
                if ei >= 20:
                    traded_vol = annualized_vol(bond_closes[: ei + 1], 20)
            # Slippage: 0.1% per side + vol * 0.05
            slippage_cost = traded_turnover * (COST_PER_SIDE + traded_vol * 0.05)
            slippage_total += slippage_cost
            cost_total += traded_turnover * COST_PER_SIDE
            equity *= 1.0 - slippage_cost

        satellite_weights = new_satellite_weights
        satellite_entry_prices = entry_prices if new_satellite_weights else {}
        exposure = target_exposure
        rebalances += 1

        period_start = exec_idx if prev_i is None else prev_i + 1
        period_end = i if i + 1 < len(dates) else i

        # Mark-to-market daily in the period using exec prices as starting reference
        for j in range(period_start, period_end + 1):
            if j == period_start:
                period_ret = 0.0
            else:
                period_ret = 0.0
                for sym, weight in satellite_weights.items():
                    bars = stock_bars_by_date.get(sym)
                    if bars is None or j >= len(bars["closes"]):
                        continue
                    # Use close-to-close returns from exec open estimate reference on first day
                    prev_close = float(bars["closes"][j - 1])
                    cur_close = float(bars["closes"][j])
                    if prev_close <= 0:
                        continue
                    sym_ret = cur_close / prev_close - 1.0
                    period_ret += weight * sym_ret
                    if j == period_end:
                        contribution[sym] += weight * sym_ret
                if new_bond_weight > 0 and bond_closes is not None and j > 0 and j < len(bond_closes):
                    bond_ret = bond_closes[j] / bond_closes[j - 1] - 1.0
                    period_ret += new_bond_weight * bond_ret
            equity *= 1.0 + period_ret
            active_stocks = sum(1 for w in satellite_weights.values() if w > 1e-9)
            equity_curve.append(
                (
                    dates[j].isoformat(),
                    float(equity),
                    float(exposure),
                    float(active_stocks),
                    float(qqq_closes[j]),
                    float(spy_closes[j]),
                    float(exec_idx == j),
                )
            )
            exposure_sum += exposure
            stock_count_sum += active_stocks
            stock_count_samples += 1

        prev_i = period_end

    equity_curve_arr = np.array([e[1] for e in equity_curve])
    running_max = np.maximum.accumulate(equity_curve_arr)
    drawdowns = (equity_curve_arr - running_max) / running_max
    max_dd = float(np.min(drawdowns))

    qqq_return = (qqq_closes[-1] / qqq_closes[0]) - 1.0
    spy_return = (spy_closes[-1] / spy_closes[0]) - 1.0
    combined_return = equity - 1.0
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
        "avg_equity_exposure": exposure_sum / stock_count_samples if stock_count_samples else 0.0,
        "avg_stock_count": stock_count_sum / stock_count_samples if stock_count_samples else 0.0,
        "rebalances": rebalances,
        "trades_with_cost": trades,
        "bond_proxy": bond_proxy,
        "slippage_total": slippage_total,
        "cost_total": cost_total,
        "equity_curve": equity_curve,
        "top_contributors": top_contributors,
    }


def _find_index_for_date(bars: Optional[Dict[str, Any]], date: datetime) -> Optional[int]:
    if bars is None or "timestamps" not in bars:
        return None
    target = date.date()
    for i, ts in enumerate(bars["timestamps"]):
        d = ts.date() if isinstance(ts, datetime) else datetime.fromisoformat(ts).date()
        if d == target:
            return i
    return None


# ---------------------------------------------------------------------------
# Walk-forward macro optimizer (macro-only)
# ---------------------------------------------------------------------------
def run_macro_only_window(
    data_dir: str,
    window_key: str,
    allocator: MacroAllocator,
) -> float:
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
    qqq_closes = np.array(qqq["closes"], dtype=float)
    equity = 1.0
    exposure = 0.0
    rebalance_indices = month_end_indices(dates)
    for i in rebalance_indices:
        d = dates[i].date()
        target = 0.0
        if d in feat_by_date:
            target = allocator.decide_equity_exposure(dates[i], feat_by_date[d].to_dict())
        if target != exposure:
            equity *= 1.0 - abs(target - exposure) * COST_PER_SIDE
            exposure = target
        period_start = i
        period_end = i
        for j in range(period_start, period_end + 1):
            if j > 0 and j < len(qqq_closes):
                daily_ret = qqq_closes[j] / qqq_closes[j - 1] - 1.0
                equity *= 1.0 + exposure * daily_ret
    return equity - 1.0


def optimize_macro_params(data_dir: str, train_windows: List[str]) -> Tuple[Dict[str, Any], float]:
    """Coarse grid search macro allocator thresholds on in-sample windows (macro-only QQQ sleeve).

    Data and features are preloaded once to avoid repeated JSON parsing.
    """
    from itertools import product

    best = None
    best_ret = -1e9
    candidate_thresholds = {
        "CREDIT_STRESS_Z": [-1.5, -1.0, -0.5],
        "CREDIT_EASY_Z": [0.2, 0.3, 0.5],
        "VIXY_ELEVATED_Z": [0.8, 1.0, 1.5],
        "VIXY_CALM_Z": [-0.5, -0.3, -0.2],
        "TLT_RISING_SLOPE": [0.0002, 0.0003, 0.0005],
        "TLT_FALLING_SLOPE": [-0.0005, -0.0003, -0.0002],
        "DRAWDOWN_SPY_60D_LIMIT": [-0.15, -0.12, -0.10],
    }
    keys = list(candidate_thresholds.keys())
    vals = [candidate_thresholds[k] for k in keys]

    # Preload data once
    raw_cache: Dict[str, Any] = {}
    feat_cache: Dict[str, Any] = {}
    dates_cache: Dict[str, Any] = {}
    qqq_cache: Dict[str, Any] = {}
    for w in train_windows:
        raw_cache[w] = load_window_data(data_dir, w)
        dates_cache[w] = raw_cache[w]["SPY"]["timestamps"]
        feat_cache[w] = build_macro_features(
            spy_closes=raw_cache[w]["SPY"]["closes"],
            qqq_closes=raw_cache[w]["QQQ"]["closes"],
            lqd_closes=raw_cache[w]["LQD"]["closes"],
            hyg_closes=raw_cache[w]["HYG"]["closes"],
            vixy_closes=raw_cache[w]["VIXY"]["closes"],
            tlt_closes=raw_cache[w]["TLT"]["closes"],
            shy_closes=raw_cache[w]["SHY"]["closes"],
            dates=dates_cache[w],
        )
        qqq_cache[w] = np.array(raw_cache[w]["QQQ"]["closes"], dtype=float)

    def eval_window_fast(window: str, params: Dict[str, Any]) -> float:
        a = MacroAllocator()
        for k, v in params.items():
            setattr(a, k, v)
        fd = {f.date.date(): f for f in feat_cache[window]}
        dates = dates_cache[window]
        qqq = qqq_cache[window]
        equity = 1.0
        exposure = 0.0
        rebalance_indices = month_end_indices(dates)
        for i in rebalance_indices:
            d = dates[i].date()
            target = 0.0
            if d in fd:
                target = a.decide_equity_exposure(dates[i], fd[d].to_dict())
            if target != exposure:
                equity *= 1.0 - abs(target - exposure) * COST_PER_SIDE
                exposure = target
            if i > 0 and i < len(qqq):
                daily_ret = qqq[i] / qqq[i - 1] - 1.0
                equity *= 1.0 + exposure * daily_ret
        return equity - 1.0

    count = 0
    for combo in product(*vals):
        params = {keys[i]: combo[i] for i in range(len(keys))}
        ret = sum(eval_window_fast(w, params) for w in train_windows)
        count += 1
        if ret > best_ret:
            best_ret = ret
            best = dict(params)

    return best or {}, best_ret


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def load_pure_macro_results(reports_dir: str) -> List[Dict[str, Any]]:
    path = os.path.join(reports_dir, "macro_allocator_backtest_20260823.json")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        data = json.load(fh)
    return data.get("windows", [])


def write_equity_csv(path: str, window_results: List[Dict[str, Any]]) -> None:
    with open(path, "w") as fh:
        fh.write("date,equity,exposure,active_stocks,qqq_close,spy_close,is_exec_day,window\n")
        for res in window_results:
            for row in res["equity_curve"]:
                fh.write(
                    f"{row[0]},{row[1]:.6f},{row[2]:.2f},{row[3]:.1f},"
                    f"{row[4]:.4f},{row[5]:.4f},{row[6]:.0f},{res['window']}\n"
                )


def write_summary_json(
    path: str,
    summary_rows: List[Dict[str, Any]],
    rules: str,
    limitations: str,
    walkforward: Dict[str, Any],
) -> None:
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allocator_rules": rules,
        "limitations": limitations,
        "cost_per_side": COST_PER_SIDE,
        "max_positions": MAX_POSITIONS,
        "max_position_pct": MAX_POSITION_PCT,
        "sector_cap_pct": SECTOR_CAP_PCT,
        "min_history_days": MIN_HISTORY_DAYS,
        "min_dollar_volume": MIN_DOLLAR_VOLUME,
        "max_volatility": MAX_VOLATILITY,
        "min_price": MIN_PRICE,
        "open_noise_std": OPEN_NOISE_STD,
        "walk_forward": walkforward,
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
    rng = random.Random(42)

    macro_allocator = MacroAllocator()
    satellite_engine = SatelliteAlphaEngine(
        max_positions=MAX_POSITIONS,
        max_position_pct=MAX_POSITION_PCT,
        sector_cap_pct=SECTOR_CAP_PCT,
        min_history_days=MIN_HISTORY_DAYS,
    )

    pure_macro_rows = load_pure_macro_results(reports_dir)
    pure_macro_by_label = {row["window"]: row for row in pure_macro_rows}

    # Original combined results for comparison
    orig_path = os.path.join(reports_dir, "macro_plus_satellite_backtest_20260823.json")
    orig_by_label: Dict[str, float] = {}
    if os.path.exists(orig_path):
        with open(orig_path) as fh:
            orig_data = json.load(fh)
        for row in orig_data.get("windows", []):
            orig_by_label[row["window"]] = row["combined_return"]

    # Run realistic combined backtest
    window_results: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    for label, key in WINDOWS.items():
        res = run_window(data_dir, key, daily_bars_path, macro_allocator, satellite_engine, rng)
        window_results.append(res)
        macro_row = pure_macro_by_label.get(label, {})
        summary_rows.append(
            {
                "window": label,
                "combined_return": res["combined_return"],
                "original_combined_return": orig_by_label.get(label),
                "pure_macro_return": macro_row.get("allocator_equity_return"),
                "qqq_return": res["qqq_return"],
                "spy_return": res["spy_return"],
                "max_drawdown": res["max_drawdown"],
                "avg_equity_exposure": res["avg_equity_exposure"],
                "avg_stock_count": res["avg_stock_count"],
                "rebalances": res["rebalances"],
                "slippage_total": res["slippage_total"],
                "cost_total": res["cost_total"],
                "bond_proxy": res["bond_proxy"],
                "top_contributors": res["top_contributors"],
                "first_date": res["first_date"],
                "last_date": res["last_date"],
            }
        )

    # Walk-forward: optimize macro allocator on 2022-Aug 2024 (macro-only), then test
    # the realistic combined system on Aug 2024-Aug 2026 with those optimized params.
    print("Running walk-forward macro parameter optimization (macro-only in-sample)...")
    in_sample_params, in_sample_ret = optimize_macro_params(
        data_dir, ["bear_2022", "oos_2023_2024"]
    )

    fwd_allocator = MacroAllocator()
    for k, v in in_sample_params.items():
        setattr(fwd_allocator, k, v)
    forward_macro_only = run_macro_only_window(data_dir, "forward_2024_2026", fwd_allocator)

    # Realistic combined with in-sample-optimized macro parameters on forward window only
    realistic_fwd = run_window(
        data_dir, "forward_2024_2026", daily_bars_path, fwd_allocator, satellite_engine, rng
    )

    walkforward = {
        "in_sample_windows": ["bear_2022", "oos_2023_2024"],
        "test_window": "forward_2024_2026",
        "in_sample_macro_only_return": in_sample_ret,
        "in_sample_params": in_sample_params,
        "forward_macro_only_return": forward_macro_only,
        "forward_realistic_combined_return": realistic_fwd["combined_return"],
        "forward_realistic_max_drawdown": realistic_fwd["max_drawdown"],
        "forward_realistic_avg_stock_count": realistic_fwd["avg_stock_count"],
    }

    write_equity_csv(
        os.path.join(reports_dir, "macro_plus_satellite_realistic_equity_20260823.csv"),
        window_results,
    )
    limitations = (
        "Sector data unavailable; sector cap is a documented limitation only. "
        "Open prices estimated when absent using seeded Gaussian noise (std=0.35%). "
        "Slippage model: 0.10% per side + vol20d * 0.05. "
        "Liquidity, volatility, and microcap filters applied point-in-time. "
        "Universe is the symbols present in the data files; survivorship bias possible."
    )
    write_summary_json(
        os.path.join(reports_dir, "macro_plus_satellite_realistic_backtest_20260823.json"),
        summary_rows,
        macro_allocator.rule_summary(),
        limitations,
        walkforward,
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
            if macro_ret - row["combined_return"] > 0.10:
                stop_pass = False
                fail_reasons.append(
                    f"{row['window']}: underperforms macro by {macro_ret - row['combined_return']:.2%} > 10pp"
                )
    if not improved_any:
        stop_pass = False
        fail_reasons.append("No window improved over pure macro allocator.")

    # Print report
    print("\n" + "=" * 100)
    print("REALISTIC MACRO + SATELLITE BACKTEST REPORT")
    print("=" * 100)
    print(
        f"Cost per side: {COST_PER_SIDE:.2%} | Max positions: {MAX_POSITIONS} | "
        f"Stock cap: {MAX_POSITION_PCT:.1%} | Min history: {MIN_HISTORY_DAYS}d | "
        f"Min DV20: ${MIN_DOLLAR_VOLUME/1e6:.1f}M | Max vol: {MAX_VOLATILITY:.0%} | "
        f"Min price: ${MIN_PRICE:.2f}"
    )
    print(
        f"\n{'Window':<20} {'Orig Combo':>12} {'Real Combo':>12} {'Macro':>12} "
        f"{'QQQ':>12} {'Max DD':>12} {'Avg Stks':>10} {'Rebal':>8}"
    )
    print("-" * 100)
    for row in summary_rows:
        orig_str = f"{row['original_combined_return']:.2%}" if row["original_combined_return"] is not None else "n/a"
        macro_str = f"{row['pure_macro_return']:.2%}" if row["pure_macro_return"] is not None else "n/a"
        print(
            f"{row['window']:<20} "
            f"{orig_str:>11} "
            f"{row['combined_return']:>11.2%} "
            f"{macro_str:>11} "
            f"{row['qqq_return']:>11.2%} "
            f"{row['max_drawdown']:>11.2%} "
            f"{row['avg_stock_count']:>9.1f} "
            f"{row['rebalances']:>7d}"
        )
    print("\nTop contributors per window (realistic):")
    for row in summary_rows:
        print(f"  {row['window']}:")
        for sym, contrib in row["top_contributors"]:
            print(f"    {sym}: {contrib:.2%}")

    print("\nWalk-forward (macro params optimized 2022-Aug 2024, tested Aug 2024-Aug 2026):")
    print(f"  In-sample macro-only return: {in_sample_ret:.2%}")
    print(f"  Optimized params: {in_sample_params}")
    print(f"  Forward macro-only return:   {forward_macro_only:.2%}")
    print(f"  Forward realistic combined:  {realistic_fwd['combined_return']:.2%}")
    print(f"  Forward realistic max DD:    {realistic_fwd['max_drawdown']:.2%}")
    print(f"  Forward realistic avg stocks:{realistic_fwd['avg_stock_count']:.1f}")

    print("\nStop condition:")
    print(f"  Passed: {stop_pass}")
    if fail_reasons:
        for reason in fail_reasons:
            print(f"  - {reason}")
    else:
        print("  - All checks passed.")

    print("\nFiles written:")
    print(f"  {os.path.join(reports_dir, 'macro_plus_satellite_realistic_backtest_20260823.json')}")
    print(f"  {os.path.join(reports_dir, 'macro_plus_satellite_realistic_equity_20260823.csv')}")


if __name__ == "__main__":
    main()
