#!/usr/bin/env python3
"""Compute portfolio risk statistics from portfolio_history.json.

Outputs risk_stats.json (web root + /opt copy) powering the site
"Bot vs. Market" risk strip: Sharpe, max drawdown, beta, volatility,
win rate. Read-only on inputs; safe to run any time.

Method:
  - Daily close-to-close returns from portfolio_history.json checks
    (one row per date; non-trading days where nothing moved are dropped).
  - Sharpe uses a fixed 4% annual risk-free rate.
  - Beta/alpha vs the benchmark series stored in portfolio_history.json (SPY).
  - Win rate / profit factor from FIFO round trips in trades_log.json.
"""
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from stonk_utils import atomic_write_json

BASE = Path("/opt/stonk-ai")
WEB = Path("/var/www/hedge-fund-website")
HISTORY = BASE / "portfolio_history.json"
TRADES = BASE / "trades_log.json"

RF_ANNUAL = 0.04
MIN_CALENDAR_DAYS = 30  # frontend also gates on this


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def daily_series(checks):
    """Return [(date, portfolio_value, benchmark_value)] trading days only."""
    by_date = {}
    for c in checks:
        d = (c.get("timestamp") or "")[:10]
        pv, bv = c.get("portfolio_value"), c.get("benchmark_value")
        if not d or pv is None or bv is None:
            continue
        by_date[d] = (float(pv), float(bv))  # last write per date wins
    rows = [(d, *by_date[d]) for d in sorted(by_date)]
    out = []
    for row in rows:
        # Drop rows where neither series moved (weekends/holidays)
        if out and row[1] == out[-1][1] and row[2] == out[-1][2]:
            continue
        out.append(row)
    return out


def round_trips(trades):
    """FIFO pair BUY/SELL per symbol -> [{symbol, buy_ts, sell_ts, pnl_pct}]."""
    positions = defaultdict(list)
    closed = []
    for t in sorted(trades, key=lambda x: x.get("timestamp", "")):
        action = (t.get("action") or "").upper()
        sym = t.get("symbol")
        if not sym:
            continue
        if action == "BUY":
            positions[sym].append(t)
        elif action == "SELL" and positions[sym]:
            buy = positions[sym].pop(0)
            bp, sp = float(buy.get("price") or 0), float(t.get("price") or 0)
            if bp > 0:
                closed.append({
                    "symbol": sym,
                    "buy_ts": buy.get("timestamp", ""),
                    "sell_ts": t.get("timestamp", ""),
                    "pnl_pct": (sp - bp) / bp,
                })
    return closed


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def main():
    hist = load_json(HISTORY, {})
    checks = hist.get("checks", []) if isinstance(hist, dict) else []
    series = daily_series(checks)

    trades = load_json(TRADES, {}).get("trades", [])
    closed = round_trips(trades)

    if len(series) < 2:
        print("Not enough history yet; writing minimal file")
        out = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "window": {"sufficient": False, "trading_days": len(series)},
        }
    else:
        dates = [r[0] for r in series]
        pvals = [r[1] for r in series]
        bvals = [r[2] for r in series]
        rp = [pvals[i] / pvals[i - 1] - 1 for i in range(1, len(pvals))]
        rb = [bvals[i] / bvals[i - 1] - 1 for i in range(1, len(bvals))]
        n = len(rp)

        mp, mb = mean(rp), mean(rb)
        sp, sb = stdev(rp), stdev(rb)

        rf_daily = RF_ANNUAL / 252.0
        sharpe = ((mp - rf_daily) / sp * math.sqrt(252)) if sp > 0 else None

        # Beta / alpha vs benchmark
        beta = alpha_ann = None
        if sp > 0 and sb > 0:
            cov = mean([(rp[i] - mp) * (rb[i] - mb) for i in range(n)]) * n / (n - 1)
            var_b = sb ** 2
            beta = cov / var_b if var_b > 0 else None
            if beta is not None:
                alpha_ann = (mp - beta * mb) * 252

        # Drawdown on portfolio values
        peak = pvals[0]
        max_dd = 0.0
        for v in pvals:
            peak = max(peak, v)
            max_dd = min(max_dd, v / peak - 1)
        current_dd = pvals[-1] / max(pvals) - 1

        # Trade stats
        wins = [c for c in closed if c["pnl_pct"] > 0]
        losses = [c for c in closed if c["pnl_pct"] <= 0]
        gross_win = sum(c["pnl_pct"] for c in wins)
        gross_loss = abs(sum(c["pnl_pct"] for c in losses))
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else None

        d0 = datetime.strptime(dates[0], "%Y-%m-%d")
        d1 = datetime.strptime(dates[-1], "%Y-%m-%d")

        out = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "window": {
                "start": dates[0],
                "end": dates[-1],
                "calendar_days": (d1 - d0).days,
                "trading_days": n,
                "sufficient": (d1 - d0).days >= MIN_CALENDAR_DAYS,
            },
            "portfolio": {
                "total_return_pct": round((pvals[-1] / pvals[0] - 1) * 100, 2),
                "benchmark_return_pct": round((bvals[-1] / bvals[0] - 1) * 100, 2),
                "volatility_annual_pct": round(sp * math.sqrt(252) * 100, 1) if sp else None,
                "sharpe": round(sharpe, 2) if sharpe is not None else None,
                "beta": round(beta, 2) if beta is not None else None,
                "alpha_annual_pct": round(alpha_ann * 100, 1) if alpha_ann is not None else None,
                "max_drawdown_pct": round(max_dd * 100, 1),
                "current_drawdown_pct": round(current_dd * 100, 1),
            },
            "trades": {
                "closed_trades": len(closed),
                "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
                "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
                "avg_winner_pct": round(mean([c["pnl_pct"] for c in wins]) * 100, 2) if wins else None,
                "avg_loser_pct": round(mean([c["pnl_pct"] for c in losses]) * 100, 2) if losses else None,
            },
            "meta": {
                "risk_free_annual": RF_ANNUAL,
                "method": "daily close-to-close",
                "source": "portfolio_history.json",
            },
        }

    atomic_write_json(str(WEB / "risk_stats.json"), out)
    atomic_write_json(str(BASE / "risk_stats.json"), out)
    w = out.get("window", {})
    p = out.get("portfolio", {})
    print(f"risk_stats.json written: {w.get('trading_days')} trading days, "
          f"Sharpe {p.get('sharpe')}, MaxDD {p.get('max_drawdown_pct')}%")


if __name__ == "__main__":
    main()
