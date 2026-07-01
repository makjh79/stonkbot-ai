#!/usr/bin/env python3
"""
Compute rolling beta / correlation report for the watchlist.

Outputs /var/www/hedge-fund-website/correlation_report.json
"""

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

BOT_DIR = Path(os.environ.get("STONKBOT_BOT_DIR", "/opt/stonk-ai"))
WEB_DIR = Path(os.environ.get("STONKBOT_WEB_DIR", "/var/www/hedge-fund-website"))


def _load_alpaca_data():
    import sys
    sys.path.insert(0, str(BOT_DIR))
    from alpaca_data import get_data_hub
    return get_data_hub()


def log_returns(closes: List[float]) -> List[float]:
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]


def beta(asset_returns: List[float], market_returns: List[float]) -> Optional[float]:
    if len(asset_returns) < 20 or len(market_returns) < 20:
        return None
    a = np.array(asset_returns)
    m = np.array(market_returns)
    covariance = np.cov(a, m)[0, 1]
    variance = np.var(m, ddof=1)
    if variance == 0 or math.isnan(variance):
        return None
    return float(covariance / variance)


def correlation(a: List[float], b: List[float]) -> Optional[float]:
    if len(a) < 20 or len(b) < 20:
        return None
    if np.std(a, ddof=1) == 0 or np.std(b, ddof=1) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main():
    watchlist_path = WEB_DIR / "ai_watchlist_live.json"
    watchlist = json.loads(watchlist_path.read_text())
    symbols = sorted(watchlist.get("prices", {}).keys())
    if not symbols:
        print("No watchlist symbols found")
        return

    bench_symbols = ["SPY", "QQQ"]
    all_symbols = symbols + bench_symbols

    hub = _load_alpaca_data()
    bars = hub.get_daily_bars(all_symbols, days=120)

    # Compute returns
    returns = {}
    closes = {}
    timestamps = {}
    for sym, data in bars.items():
        c = data.get("closes", [])
        ts = data.get("timestamps", [])
        if len(c) >= 20:
            closes[sym] = c
            timestamps[sym] = ts
            returns[sym] = log_returns(c)

    # Betas vs SPY / QQQ
    spy_returns = returns.get("SPY", [])
    qqq_returns = returns.get("QQQ", [])
    min_len = min(len(spy_returns), len(qqq_returns), min(len(r) for r in returns.values()))

    betas = {}
    for sym in symbols:
        r = returns.get(sym, [])
        if not r or len(r) < 20:
            betas[sym] = {"spy": None, "qqq": None, "history_days": len(r)}
            continue
        # Align lengths for beta calculation
        use_len = min(len(r), len(spy_returns))
        betas[sym] = {
            "spy": beta(r[-use_len:], spy_returns[-use_len:]),
            "qqq": beta(r[-use_len:], qqq_returns[-use_len:]),
            "history_days": len(r),
            "spy_corr": correlation(r[-use_len:], spy_returns[-use_len:]),
            "qqq_corr": correlation(r[-use_len:], qqq_returns[-use_len:]),
        }

    # Pairwise correlation matrix
    matrix = {}
    for sym in symbols:
        matrix[sym] = {}
    for i, sym_a in enumerate(symbols):
        ra = returns.get(sym_a, [])
        if not ra:
            continue
        matrix[sym_a][sym_a] = 1.0
        for sym_b in symbols[i + 1 :]:
            rb = returns.get(sym_b, [])
            if not rb:
                continue
            use_len = min(len(ra), len(rb))
            corr = correlation(ra[-use_len:], rb[-use_len:])
            if corr is not None:
                matrix[sym_a][sym_b] = round(corr, 3)
                matrix[sym_b][sym_a] = round(corr, 3)

    # Sector grouping
    sectors = defaultdict(list)
    for sym in symbols:
        info = watchlist["prices"].get(sym, {})
        sector = info.get("sector", "Unknown")
        sectors[sector].append(sym)

    # Average correlations
    pairwise_values = []
    for i, sym_a in enumerate(symbols):
        for sym_b in symbols[i + 1 :]:
            val = matrix.get(sym_a, {}).get(sym_b)
            if val is not None:
                pairwise_values.append(val)

    avg_correlation = float(np.mean(pairwise_values)) if pairwise_values else None
    max_correlation = float(max(pairwise_values)) if pairwise_values else None

    sector_avgs = {}
    for sector, members in sectors.items():
        vals = []
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                val = matrix.get(a, {}).get(b)
                if val is not None:
                    vals.append(val)
        sector_avgs[sector] = round(float(np.mean(vals)), 3) if vals else None

    # High-beta / high-correlation basket
    high_beta_symbols = [
        sym
        for sym in symbols
        if betas.get(sym, {}).get("spy") is not None
        and (betas[sym]["spy"] > 1.2 or betas[sym].get("spy_corr", 0) > 0.7)
    ]

    # Portfolio exposure to high-beta names (using current positions)
    portfolio_path = WEB_DIR / "portfolio_data.json"
    portfolio = json.loads(portfolio_path.read_text()) if portfolio_path.exists() else {}
    pv = portfolio.get("account", {}).get("portfolio_value", 0)
    positions = {p["symbol"]: p for p in portfolio.get("positions", [])}
    high_beta_deployed = sum(
        positions[sym]["market_value"] for sym in high_beta_symbols if sym in positions
    )
    high_beta_deployed_pct = (high_beta_deployed / pv * 100) if pv else None

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lookback_trading_days": min_len,
        "symbols": symbols,
        "benchmarks": bench_symbols,
        "betas": betas,
        "correlation_matrix": matrix,
        "average_pairwise_correlation": round(avg_correlation, 3) if avg_correlation is not None else None,
        "max_pairwise_correlation": round(max_correlation, 3) if max_correlation is not None else None,
        "sector_average_correlation": sector_avgs,
        "high_beta_basket": {
            "symbols": high_beta_symbols,
            "count": len(high_beta_symbols),
            "deployed_value": round(high_beta_deployed, 2) if high_beta_deployed else 0,
            "deployed_pct": round(high_beta_deployed_pct, 2) if high_beta_deployed_pct is not None else None,
        },
        "diversification_score": round(1.0 - (avg_correlation or 0), 3),
    }

    out_path = WEB_DIR / "correlation_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {out_path}")

    # Summary to stdout
    print(f"Symbols analyzed: {len(symbols)}")
    print(f"Avg pairwise correlation: {report['average_pairwise_correlation']}")
    print(f"Max pairwise correlation: {report['max_pairwise_correlation']}")
    print(f"High-beta basket: {len(high_beta_symbols)} symbols")
    print(f"Deployed in high-beta names: ${high_beta_deployed:,.2f} ({high_beta_deployed_pct:.1f}% of portfolio)")


if __name__ == "__main__":
    main()
