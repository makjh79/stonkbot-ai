#!/usr/bin/env python3
"""
STONK.AI v3 Trend-Following + Tactical Satellite Engine Backtest v1
====================================================================

Runs the trend engine over daily bars and reports full performance metrics
plus benchmark comparison vs QQQ buy-and-hold over the same window.

Execution modes
---------------
- "t1_close": signal at close, execute at next day's close (default).
- "next_open": signal at close, execute at next day's open with slippage.

Outputs
-------
- /opt/stonk-ai/reports/v3_trend_v1_vNN_backtest_YYYYMMDD.json
- /opt/stonk-ai/reports/v3_trend_v1_vNN_equity_YYYYMMDD.csv
- /opt/stonk-ai/reports/v3_trend_v1_vNN_equity_YYYYMMDD.png

Author: OpenClaw subagent
Date: 2026-08-23
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from trend_engine_v1 import (
    TrendSignalEngine, _realized_volatility, _atr_pct, load_bars,
    SYMBOL_TO_SECTOR, COST_PER_SIDE,
)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
REPORT_DIR = Path("/opt/stonk-ai/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

START_VALUE = 100_000.0

DEFAULT_CONFIG: Dict[str, Any] = {
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


@dataclass
class Position:
    symbol: str
    side: str
    shares: float
    entry_price: float
    entry_cost: float
    entry_date: str
    entry_idx: int
    sector: str
    source: str
    remaining_fraction: float = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trading_days_between(dates: List[str], start: str, end: str) -> int:
    try:
        return max(0, dates.index(end) - dates.index(start))
    except ValueError:
        return 0


def _execution_price(sym_bars: Dict[str, List], i: int, mode: str, cfg: Dict[str, Any]) -> Tuple[float, str]:
    """
    Execution price for day i.  For t1_close we use the close of day i.
    For next_open we use the previous day's close as an open proxy and add
    slippage: 0.05% + 0.1 * daily_volatility.
    """
    if i >= len(sym_bars["timestamps"]):
        return 0.0, "close"

    if mode == "next_open":
        if "opens" in sym_bars and i < len(sym_bars["opens"]):
            price = sym_bars["opens"][i]
        elif i > 0:
            price = sym_bars["closes"][i - 1]
        else:
            price = sym_bars["closes"][i]
        vol = _realized_volatility(sym_bars["closes"][:i + 1], 20) if i > 20 else 0.20
        slip = 0.0005 + cfg.get("vol_slippage_mult", 0.1) * vol / math.sqrt(252)
        # For a buy we slip the price up; for short sale we also use the slippage adjusted price.
        price = price * (1.0 + slip)
        return price, "open"
    else:
        return sym_bars["closes"][i], "close"


def _benchmark_metrics(prices: List[float]) -> Dict[str, float]:
    total = prices[-1] / prices[0] - 1.0 if prices[0] > 0 else 0.0
    rets = np.diff(prices) / prices[:-1]
    ann_factor = 252
    ann_ret = (1 + total) ** (ann_factor / len(prices)) - 1.0 if len(prices) > 1 else 0.0
    vol = float(np.std(rets) * math.sqrt(ann_factor))
    sharpe = ann_ret / vol if vol > 0 else 0.0
    running_peak = np.maximum.accumulate(np.array(prices))
    max_dd = float(np.max((running_peak - np.array(prices)) / running_peak))
    return {"total_return": float(total), "annualized_return": float(ann_ret),
            "volatility": vol, "sharpe_ratio": sharpe, "max_drawdown": max_dd}


def _compute_metrics(equity_curve: List[Dict], qqq_closes: List[float], trades: List[Dict],
                     start_value: float, cfg: Dict[str, Any]) -> Dict[str, Any]:
    eq_vals = np.array([e["equity"] for e in equity_curve])
    rets = np.diff(eq_vals) / eq_vals[:-1]
    ann_factor = 252
    total_ret = eq_vals[-1] / start_value - 1.0
    ann_ret = (1 + total_ret) ** (ann_factor / len(eq_vals)) - 1.0 if len(eq_vals) > 1 else 0.0
    vol = float(np.std(rets) * math.sqrt(ann_factor))
    sharpe = float(ann_ret / vol) if vol > 0 else 0.0

    running_peak = np.maximum.accumulate(eq_vals)
    max_dd = float(np.max((running_peak - eq_vals) / running_peak))

    closed_trades = [t for t in trades if t["reason"] != "final_liquidation"]
    winners = [t for t in closed_trades if t["pnl"] > 0]
    losers = [t for t in closed_trades if t["pnl"] <= 0]
    win_rate = len(winners) / len(closed_trades) if closed_trades else 0.0
    avg_win = float(np.mean([t["pnl_pct"] for t in winners])) if winners else 0.0
    avg_loss = float(np.mean([t["pnl_pct"] for t in losers])) if losers else 0.0
    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_hold = float(np.mean([t["hold_days"] for t in closed_trades])) if closed_trades else 0.0

    qqq_metrics = _benchmark_metrics(qqq_closes)
    qqq_final_value = START_VALUE * (1 + qqq_metrics["total_return"])

    avg_long = float(np.mean([e.get("long_exposure", 0.0) for e in equity_curve]))
    avg_short = float(np.mean([e.get("short_exposure", 0.0) for e in equity_curve]))
    avg_gross = avg_long + avg_short
    avg_net = avg_long - avg_short
    avg_cash = float(np.mean([e.get("cash", 0.0) for e in equity_curve]))
    avg_invested = avg_gross / start_value

    return {
        "total_return": float(total_ret),
        "annualized_return": float(ann_ret),
        "volatility": vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "avg_winner": avg_win,
        "avg_loser": avg_loss,
        "profit_factor": profit_factor,
        "number_of_trades": len(closed_trades),
        "avg_holding_days": avg_hold,
        "avg_long_exposure_pct": float(avg_long / start_value),
        "avg_short_exposure_pct": float(avg_short / start_value),
        "avg_gross_exposure_pct": float(avg_gross / start_value),
        "avg_net_exposure_pct": float(avg_net / start_value),
        "avg_cash_pct": float(avg_cash / start_value),
        "avg_invested_pct": float(avg_invested),
        "qqq_total_return": qqq_metrics["total_return"],
        "qqq_sharpe_ratio": qqq_metrics["sharpe_ratio"],
        "qqq_max_drawdown": qqq_metrics["max_drawdown"],
        "final_equity": float(eq_vals[-1]),
        "final_qqq_equity": float(qqq_final_value),
        "start_value": start_value,
    }


def make_chart(equity_curve: List[Dict], qqq_final_value: float, output_path: str, variant: str):
    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    start_value = df["equity"].iloc[0]
    df["strategy"] = df["equity"] / start_value
    qqq_start = df["qqq_close"].iloc[0]
    df["qqq"] = df["qqq_close"] / qqq_start

    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(df["date"], df["strategy"], label="Trend Engine", linewidth=2)
    ax1.plot(df["date"], df["qqq"], label="QQQ buy-and-hold", linewidth=2, linestyle="--")
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Normalized Equity")
    ax1.set_title(f"STONK.AI v3 Trend Engine {variant} vs QQQ Buy-and-Hold")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    regime_colors = {"RISK_ON": "#d4edda", "RECOVERY": "#fff3cd", "RISK_OFF": "#f8d7da"}
    current_regime = df["regime"].iloc[0]
    start_idx = 0
    for i in range(1, len(df)):
        if df["regime"].iloc[i] != current_regime:
            ax1.axvspan(df["date"].iloc[start_idx], df["date"].iloc[i],
                        color=regime_colors.get(current_regime, "white"), alpha=0.2)
            current_regime = df["regime"].iloc[i]
            start_idx = i
    ax1.axvspan(df["date"].iloc[start_idx], df["date"].iloc[-1],
                color=regime_colors.get(current_regime, "white"), alpha=0.2)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def fetch_benchmark_series(symbol: str, start_date: str, end_date: str) -> pd.Series:
    ticker = yf.Ticker(symbol)
    hist = ticker.history(start=start_date, end=end_date, auto_adjust=True)
    if hist.empty:
        raise RuntimeError(f"No data returned for {symbol}")
    hist.index = hist.index.tz_convert("UTC")
    return hist["Close"]


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def run_backtest(cfg: Dict[str, Any], bars: Optional[Dict[str, Dict[str, List]]] = None,
                 variant: str = "v01", execution_mode: Optional[str] = None,
                 date_tag: Optional[str] = None,
                 spy_series: Optional[pd.Series] = None,
                 qqq_series: Optional[pd.Series] = None) -> Dict[str, Any]:
    if bars is None:
        bars = load_bars(DATA_DIR / "daily_bars_2yr.json")
    if execution_mode is None:
        execution_mode = cfg.get("execution_mode", "t1_close")
    if date_tag is None:
        date_tag = datetime.now().strftime("%Y%m%d")

    engine = TrendSignalEngine(cfg)

    dates = bars["QQQ"]["timestamps"]
    qqq_closes = bars["QQQ"]["closes"]

    # Pre-compute regime series from continuous benchmark history
    if spy_series is None or qqq_series is None:
        start_dt = pd.to_datetime(dates[0], utc=True) - pd.Timedelta(days=300)
        end_dt = pd.to_datetime(dates[-1], utc=True) + pd.Timedelta(days=5)
        spy_series = fetch_benchmark_series(cfg.get("benchmark", "SPY"),
                                            start_dt.strftime("%Y-%m-%d"),
                                            end_dt.strftime("%Y-%m-%d"))
        qqq_series = fetch_benchmark_series("QQQ",
                                            start_dt.strftime("%Y-%m-%d"),
                                            end_dt.strftime("%Y-%m-%d"))
    engine.regime_df = engine.trend.compute_from_series(spy_series, qqq_series, dates)

    cash = START_VALUE
    equity_peak = START_VALUE
    positions: List[Position] = []
    pending_orders: List[Dict] = []
    trades: List[Dict] = []
    equity_curve: List[Dict] = []
    halted = False
    drawdown_halt_date: Optional[str] = None
    rebalance_counter = 0
    last_regime: Optional[str] = None

    def mark_portfolio(positions_list: List[Position], cash_value: float, day_idx: int, day_date: str) -> Tuple[float, float, float]:
        long_mv = 0.0
        short_mv = 0.0
        for p in positions_list:
            if day_idx < p.entry_idx:
                continue
            sym_dates = bars[p.symbol]["timestamps"]
            if day_idx < len(sym_dates) and sym_dates[day_idx] == day_date:
                price = bars[p.symbol]["closes"][day_idx]
            else:
                price = p.entry_price
            mv = p.shares * p.remaining_fraction * price
            if p.side == "long":
                long_mv += mv
            else:
                short_mv += mv
        return cash_value + long_mv - short_mv, long_mv, short_mv

    def execute_orders(day_idx: int, day_date: str):
        nonlocal cash, positions
        for o in pending_orders:
            if o["exec_idx"] != day_idx:
                continue
            sym_bars = bars[o["symbol"]]
            if day_idx >= len(sym_bars["timestamps"]) or sym_bars["timestamps"][day_idx] != day_date:
                continue
            exec_price, _ = _execution_price(sym_bars, day_idx, execution_mode, cfg)
            if exec_price <= 0:
                continue

            if o["action"] == "buy":
                shares = o["target_value"] / exec_price
                cost = shares * exec_price * (1 + COST_PER_SIDE)
                if cost > cash:
                    shares = cash / (exec_price * (1 + COST_PER_SIDE))
                    cost = shares * exec_price * (1 + COST_PER_SIDE)
                if shares <= 0 or cost <= 0:
                    continue
                positions.append(Position(
                    symbol=o["symbol"],
                    side="long",
                    shares=float(shares),
                    entry_price=float(exec_price),
                    entry_cost=float(cost),
                    entry_date=day_date,
                    entry_idx=day_idx,
                    sector=o["sector"],
                    source=o.get("source", "momentum"),
                ))
                cash -= cost
            elif o["action"] == "sell":
                p = o["position"]
                if p not in positions:
                    continue
                gross = p.shares * p.remaining_fraction * exec_price
                proceeds = gross * (1 - COST_PER_SIDE)
                pnl = proceeds - p.entry_cost * p.remaining_fraction
                pnl_pct = pnl / p.entry_cost if p.entry_cost > 0 else 0.0
                trades.append({
                    "symbol": p.symbol, "entry_date": p.entry_date, "exit_date": day_date,
                    "reason": o["reason"], "entry_price": p.entry_price,
                    "exit_price": exec_price, "shares": p.shares * p.remaining_fraction,
                    "pnl": pnl, "pnl_pct": pnl_pct,
                    "hold_days": _trading_days_between(dates, p.entry_date, day_date),
                    "side": "long", "source": p.source,
                })
                cash += proceeds
                p.remaining_fraction = 0.0
            elif o["action"] == "short":
                shares = o["target_value"] / exec_price
                proceeds = shares * exec_price * (1 - COST_PER_SIDE)
                if o["target_value"] > cash:
                    # Short sale margin: require cash equal to notional we are shorting
                    shares = cash / exec_price
                    proceeds = shares * exec_price * (1 - COST_PER_SIDE)
                if shares <= 0:
                    continue
                positions.append(Position(
                    symbol=o["symbol"],
                    side="short",
                    shares=float(shares),
                    entry_price=float(exec_price),
                    entry_cost=float(shares * exec_price),
                    entry_date=day_date,
                    entry_idx=day_idx,
                    sector="Hedge",
                    source="hedge",
                ))
                cash += proceeds
            elif o["action"] == "cover":
                p = o["position"]
                if p not in positions:
                    continue
                gross = p.shares * p.remaining_fraction * exec_price
                buyback = gross * (1 + COST_PER_SIDE)
                pnl = p.entry_cost * p.remaining_fraction - buyback
                pnl_pct = pnl / p.entry_cost if p.entry_cost > 0 else 0.0
                trades.append({
                    "symbol": p.symbol, "entry_date": p.entry_date, "exit_date": day_date,
                    "reason": o["reason"], "entry_price": p.entry_price,
                    "exit_price": exec_price, "shares": p.shares * p.remaining_fraction,
                    "pnl": pnl, "pnl_pct": pnl_pct,
                    "hold_days": _trading_days_between(dates, p.entry_date, day_date),
                    "side": "short", "source": "hedge",
                })
                cash -= buyback
                p.remaining_fraction = 0.0

        pending_orders[:] = [o for o in pending_orders if o["exec_idx"] > day_idx]
        positions = [p for p in positions if p.remaining_fraction > 1e-9]

    for i, d in enumerate(dates):
        # Execute pending orders at today's open/close
        execute_orders(i, d)

        dt = pd.to_datetime(d, utc=True)
        qqq_price = qqq_closes[i]

        mv, long_mv, short_mv = mark_portfolio(positions, cash, i, d)

        if mv > equity_peak:
            equity_peak = mv
        dd = (equity_peak - mv) / equity_peak

        halted_today = False
        if dd >= cfg["drawdown_halt_pct"]:
            if not halted:
                halted = True
                drawdown_halt_date = d
                halted_today = True
        elif dd <= cfg["drawdown_halt_pct"] * 0.5:
            halted = False

        # Liquidate everything on a fresh halt
        if halted_today:
            for p in list(positions):
                sym_bars = bars[p.symbol]
                if i >= len(sym_bars["timestamps"]) or sym_bars["timestamps"][i] != d:
                    continue
                close = sym_bars["closes"][i]
                gross = p.shares * p.remaining_fraction * close
                if p.side == "long":
                    proceeds = gross * (1 - COST_PER_SIDE)
                    pnl = proceeds - p.entry_cost * p.remaining_fraction
                    cash += proceeds
                else:
                    buyback = gross * (1 + COST_PER_SIDE)
                    pnl = p.entry_cost * p.remaining_fraction - buyback
                    cash -= buyback
                trades.append({
                    "symbol": p.symbol, "entry_date": p.entry_date, "exit_date": d,
                    "reason": "drawdown_halt", "entry_price": p.entry_price,
                    "exit_price": close, "shares": p.shares * p.remaining_fraction,
                    "pnl": pnl, "pnl_pct": pnl / p.entry_cost if p.entry_cost > 0 else 0,
                    "hold_days": _trading_days_between(dates, p.entry_date, d),
                    "side": p.side, "source": p.source,
                })
                p.remaining_fraction = 0.0
            positions = []
            pending_orders.clear()

        regime, signals = engine.generate(bars, dates, i)

        # ---- Rebalance / entry logic ----
        if not halted and not halted_today:
            rebalance_counter += 1
            regime_changed = (last_regime != regime)
            if rebalance_counter >= cfg.get("rebalance_freq_days", 10) or regime_changed:
                rebalance_counter = 0
                last_regime = regime

                # Current state
                pos_map = {p.symbol: p for p in positions}
                sector_exposure: Dict[str, float] = defaultdict(float)
                current_long = 0.0
                current_short = 0.0
                for p in positions:
                    sym_bars = bars[p.symbol]
                    price = sym_bars["closes"][i] if i < len(sym_bars["timestamps"]) and sym_bars["timestamps"][i] == d else p.entry_price
                    mv_pos = p.shares * p.remaining_fraction * price
                    if p.side == "long":
                        current_long += mv_pos
                        sector_exposure[p.sector] += mv_pos
                    else:
                        current_short += mv_pos

                # Hedge target
                short_alloc = cfg.get("short_alloc_pct", 0.0)
                target_short = 0.0
                if regime == "RISK_OFF" and short_alloc > 0:
                    target_short = mv * short_alloc

                hedge_symbol = "QQQ" if "SQQQ" not in bars else "SQQQ"
                short_position = pos_map.get(hedge_symbol)
                exec_i = min(i + 1, len(dates) - 1)

                if target_short > current_short + 100:
                    if hedge_symbol in bars:
                        pending_orders.append({
                            "exec_idx": exec_i,
                            "action": "short",
                            "symbol": hedge_symbol,
                            "target_value": target_short - current_short,
                        })
                elif target_short < current_short - 100 and short_position is not None:
                    pending_orders.append({
                        "exec_idx": exec_i,
                        "action": "cover",
                        "symbol": hedge_symbol,
                        "position": short_position,
                        "reason": "hedge_trim",
                    })

                # Long portfolio
                if regime in ("RISK_ON", "RECOVERY"):
                    selected = [s for s in signals if s.selected]
                    target_symbols = {s.symbol for s in selected}

                    # Sell positions not in target
                    for p in list(positions):
                        if p.side != "long":
                            continue
                        if p.symbol not in target_symbols:
                            pending_orders.append({
                                "exec_idx": exec_i,
                                "action": "sell",
                                "symbol": p.symbol,
                                "position": p,
                                "reason": "rebalance_drop",
                            })

                    # Buy new selected names
                    for s in selected:
                        if s.symbol in pos_map:
                            continue
                        sector = SYMBOL_TO_SECTOR.get(s.symbol, "Other")
                        sec_room = max(0.0, mv * cfg["max_sector_pct"] - sector_exposure.get(sector, 0.0))
                        if sec_room <= 0:
                            continue

                        current_gross = current_long + current_short
                        current_net = current_long - current_short
                        long_budget = min(mv * cfg["max_position_pct"],
                                          mv * cfg["max_gross_exposure_pct"] - current_gross,
                                          mv * cfg["max_net_long_pct"] - current_net)
                        target_value = min(mv * cfg["base_size_pct"], long_budget, sec_room, cash)
                        if s.source == "tactical":
                            target_value *= cfg.get("tactical_weight_pct", 0.20)
                        if target_value < 100:
                            continue

                        pending_orders.append({
                            "exec_idx": exec_i,
                            "action": "buy",
                            "symbol": s.symbol,
                            "target_value": target_value,
                            "sector": sector,
                            "source": s.source,
                        })
                        current_long += target_value
                        sector_exposure[sector] += target_value

        # EOD mark
        mv, long_mv, short_mv = mark_portfolio(positions, cash, i, d)
        equity_curve.append({
            "date": d,
            "equity": float(mv),
            "cash": float(cash),
            "regime": regime,
            "n_positions": len(positions),
            "drawdown": float(dd),
            "qqq_close": float(qqq_price),
            "long_exposure": float(long_mv),
            "short_exposure": float(short_mv),
            "gross_exposure": float(long_mv + short_mv),
            "net_exposure": float(long_mv - short_mv),
        })

    # Final liquidation
    final_i = len(dates) - 1
    final_date = dates[-1]
    for p in positions:
        if p.entry_idx > final_i:
            continue
        sym_bars = bars[p.symbol]
        if final_i < len(sym_bars["timestamps"]) and sym_bars["timestamps"][final_i] == final_date:
            exit_price = sym_bars["closes"][final_i]
        else:
            exit_price = p.entry_price
        gross = p.shares * p.remaining_fraction * exit_price
        if p.side == "long":
            proceeds = gross * (1 - COST_PER_SIDE)
            pnl = proceeds - p.entry_cost * p.remaining_fraction
            cash += proceeds
        else:
            buyback = gross * (1 + COST_PER_SIDE)
            pnl = p.entry_cost * p.remaining_fraction - buyback
            cash -= buyback
        cost_basis = p.entry_cost * p.remaining_fraction
        pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0
        trades.append({
            "symbol": p.symbol,
            "entry_date": p.entry_date,
            "exit_date": final_date,
            "reason": "final_liquidation",
            "entry_price": p.entry_price,
            "exit_price": exit_price,
            "shares": p.shares * p.remaining_fraction,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "hold_days": _trading_days_between(dates, p.entry_date, final_date),
            "side": p.side,
            "source": p.source,
        })
        p.remaining_fraction = 0.0

    final_equity = cash
    metrics = _compute_metrics(equity_curve, qqq_closes, trades, START_VALUE, cfg)
    metrics.update({
        "variant": variant,
        "config": cfg,
        "start_date": dates[0],
        "end_date": dates[-1],
        "drawdown_halt_date": drawdown_halt_date,
        "execution_mode": execution_mode,
        "methodology": {
            "signal_engine": "trend_engine_v1: SPY/QQQ 200d EMA slope + 50/200 cross",
            "execution": f"{execution_mode}, cost {COST_PER_SIDE} per side",
            "regime": "trend model RISK_ON / RECOVERY / RISK_OFF",
        },
    })

    report_path = REPORT_DIR / f"v3_trend_v1_{variant}_backtest_{date_tag}.json"
    with open(report_path, "w") as f:
        json.dump(metrics, f, indent=2)

    equity_csv_path = REPORT_DIR / f"v3_trend_v1_{variant}_equity_{date_tag}.csv"
    pd.DataFrame(equity_curve).to_csv(equity_csv_path, index=False)

    chart_path = REPORT_DIR / f"v3_trend_v1_{variant}_equity_{date_tag}.png"
    make_chart(equity_curve, metrics["final_qqq_equity"], str(chart_path), variant)

    return {
        "result": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "report_path": str(report_path),
        "equity_csv_path": str(equity_csv_path),
        "chart_path": str(chart_path),
    }


if __name__ == "__main__":
    out = run_backtest(DEFAULT_CONFIG, variant="v01")
    r = out["result"]
    print(json.dumps({k: r[k] for k in [
        "variant", "total_return", "sharpe_ratio", "max_drawdown",
        "win_rate", "profit_factor", "number_of_trades", "avg_holding_days",
        "avg_gross_exposure_pct", "avg_net_exposure_pct",
        "qqq_total_return", "qqq_sharpe_ratio", "qqq_max_drawdown"
    ]}, indent=2))
