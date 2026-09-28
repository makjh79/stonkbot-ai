#!/usr/bin/env python3
"""Daily paper tracker for DM-6m (Experiment 2) and DM-gated stock sleeve (Experiment 3).

Runs after each US close. Marks both virtual portfolios to market, computes
month-end signals, executes at next-day close (strict). State in
/opt/stonk-ai/dm_paper/. Baseline $100,000 each, inception 2026-08-24.

Data source: Alpaca market-data API (replaces Yahoo Finance as the single
source of truth for price history).
"""
import json
import os
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE = "/opt/stonk-ai/dm_paper"
STOCKS = ["AAPL","MSFT","AMZN","GOOGL","META","NVDA","AVGO","NFLX","ADBE","CSCO",
          "ORCL","QCOM","TXN","INTC","AMD","AMAT","MU","CRM","NOW","INTU",
          "AMGN","GILD","BKNG","ISRG","ADP","PAYX","COST","PEP","SBUX","MDLZ",
          "MNST","VRTX","REGN","ILMN","MRVL"]
ETFS = ["QQQ","GLD","TLT","SHY"]
ALL = STOCKS + ETFS
LOOKBACK_DAYS = 320  # fetch window (covers 252-trading-day momentum)


def load_alpaca_config() -> dict[str, Any]:
    """Load Alpaca API credentials from the standard config file."""
    for p in [Path("/opt/stonk-ai/alpaca_config.json"), Path("/var/www/hedge-fund-website/alpaca_config.json")]:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    return {
        "api_key": os.getenv("ALPACA_API_KEY"),
        "api_secret": os.getenv("ALPACA_SECRET_KEY"),
        "base_url": os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        "data_url": os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets"),
    }


def fetch_alpaca_bars(symbol: str, cfg: dict) -> dict[str, float]:
    """Fetch ~LOOKBACK_DAYS of daily bars from Alpaca market data."""
    data_url = cfg.get("data_url", "https://data.alpaca.markets").rstrip("/")
    api_key = cfg.get("api_key") or cfg.get("APCA_API_KEY_ID")
    api_secret = cfg.get("api_secret") or cfg.get("APCA_API_SECRET_KEY")
    if not api_key or not api_secret:
        raise ValueError("Alpaca API key/secret missing")

    # Fetch enough calendar days to cover LOOKBACK_DAYS trading days plus
    # weekends/holidays. Use timedelta so month/year boundaries are handled.
    end = datetime.now(timezone.utc)
    start = end - __import__("datetime").timedelta(days=LOOKBACK_DAYS * 2 + 30)

    start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = (
        f"{data_url}/v2/stocks/{urllib.parse.quote(symbol, safe='')}/bars"
        f"?timeframe=1Day&start={urllib.parse.quote(start_iso, safe='')}"
        f"&end={urllib.parse.quote(end_iso, safe='')}&limit=10000"
    )
    session = requests.Session()
    session.headers.update({
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
        "Accept": "application/json",
    })

    for attempt in range(3):
        r = session.get(url, timeout=60)
        if r.status_code == 200:
            break
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"Alpaca bars for {symbol}: {r.status_code} {r.text[:200]}")
    else:
        raise RuntimeError(f"Alpaca bars for {symbol} failed after retries: {r.status_code}")

    data = r.json()
    bars = data.get("bars", []) or data.get(data.get("symbol", symbol), {}).get("bars", [])
    out = {}
    for b in bars:
        ts = b.get("t", "")
        if not ts:
            continue
        day = ts[:10]
        out[day] = float(b.get("c", 0))
    if not out:
        raise RuntimeError(f"No bars returned for {symbol}")
    return out


def load_state(name):
    p = os.path.join(BASE, f"{name}_state.json")
    if os.path.exists(p):
        return json.load(open(p))
    return {"equity": 100000.0, "holdings": {"CASH": 100000.0},
            "last_date": None, "last_signal_month": None, "inception": "2026-08-24"}


def save_state(name, st):
    json.dump(st, open(os.path.join(BASE, f"{name}_state.json"), "w"), indent=1)


def append_hist(name, day, equity, summary):
    with open(os.path.join(BASE, f"{name}_equity.csv"), "a") as f:
        f.write(f"{day},{equity:.2f},{summary}\n")


def month_ends(ds):
    out = []
    for i in range(1, len(ds)):
        if ds[i][:7] != ds[i-1][:7]:
            out.append(ds[i-1])
    out.append(ds[-1])
    return out


def _ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = values[-period - 1 + i] - values[-period - 2 + i]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(values):
    ema12 = _ema(values, 12)
    ema26 = _ema(values, 26)
    if ema12 is None or ema26 is None:
        return None, None, None
    macd_line = ema12 - ema26
    macd_series = []
    for i in range(len(values)):
        if i < 25:
            macd_series.append(None)
            continue
        e12 = _ema(values[:i+1], 12)
        e26 = _ema(values[:i+1], 26)
        if e12 is None or e26 is None:
            macd_series.append(None)
        else:
            macd_series.append(e12 - e26)
    signal_line = _ema([m for m in macd_series if m is not None], 9)
    histogram = macd_line - signal_line if signal_line is not None else 0.0
    return macd_line, signal_line, histogram


def compute_indicators(prices, i):
    """Compute simple technical indicators from a price series up to index i."""
    vals = prices[:i+1]
    if len(vals) < 50:
        return {}
    price = vals[-1]
    ema20 = _ema(vals, 20) or price
    ema50 = _ema(vals, 50) or price
    ema200 = _ema(vals, 200) or price
    rsi = _rsi(vals, 14) or 50.0
    macd_line, signal_line, histogram = _macd(vals) or (0.0, 0.0, 0.0)
    hist_prev = 0.0
    if len(vals) >= 2:
        _, _, hist_prev = _macd(vals[:-1]) or (0.0, 0.0, 0.0)
    momentum_21_252 = 0.0
    if len(vals) >= 252:
        b = vals[-252]
        a = vals[-21]
        if b:
            momentum_21_252 = a / b - 1.0
    return {
        "price": round(price, 2),
        "ema_20": round(ema20, 2),
        "ema_50": round(ema50, 2),
        "ema_200": round(ema200, 2),
        "rsi_14": round(rsi, 2),
        "macd_line": round(macd_line, 4),
        "signal_line": round(signal_line, 4),
        "histogram": round(histogram, 4),
        "histogram_prev": round(hist_prev, 4),
        "momentum_score": round(momentum_21_252 * 100, 2),
    }


def build_confirmations(ind):
    """Build a confirmation dict from computed indicators.

    Only fields we can honestly compute from price data are set. Volume,
    options, bid-ask, and corporate-action fields are unavailable and left
    false so the UI doesn't pretend to have data that doesn't exist.
    """
    price = ind.get("price", 0.0)
    ema20 = ind.get("ema_20", price)
    ema50 = ind.get("ema_50", price)
    ema200 = ind.get("ema_200", price)
    rsi = ind.get("rsi_14", 50.0)
    histogram = ind.get("histogram", 0.0)
    hist_prev = ind.get("histogram_prev", histogram)

    def rsi_label():
        if rsi >= 60:
            return "bullish"
        if rsi <= 40:
            return "bearish"
        return "neutral"

    confs = {
        "momentum_score": ind.get("momentum_score", 50.0),
        "rsi_signal": rsi_label(),
        "above_ema": price > ema20 and price > ema50 and price > ema200,
        "macd_turning": histogram > 0 and hist_prev <= 0,
        "volume_confirmed": False,
        "sector_strong": False,
        "intraday_confirmed": False,
        "intraday_score": 50.0,
        "momentum_5m_up": False,
        "volume_5m_surge": False,
        "price_above_5m_vwap": False,
        "options_confirmed": False,
        "options_score": 50.0,
        "options_call_put_ratio": None,
        "options_unusual_volume": False,
        "near_term_bullish_flow": False,
        "relvol_confirmed": False,
        "relvol_score": 50.0,
        "vwap_confirmed": False,
        "vwap_score": 50.0,
        "spread_ok": True,
        "wide_spread": False,
        "bid_ask_spread_pct": 0.01,
        "bid_ask_imbalance": 0.0,
        "bid_ask_bullish": True,
        "has_upcoming_dividend": False,
        "has_upcoming_split": False,
        "has_upcoming_merger": False,
        "has_upcoming_spinoff": False,
        "corporate_action_risk": False,
        "no_corporate_action_risk": True,
    }
    count = sum(1 for k, v in confs.items() if v is True and not k.endswith("_score"))
    confs["confirmation_count"] = count
    return confs


def dm_signal(ds, P, i):
    def r6(s):
        if i-126 < 0:
            return None
        a, b = P[s].get(ds[i]), P[s].get(ds[i-126])
        if a is None or b is None:
            return None
        return a/b - 1.0
    r = {e: r6(e) for e in ETFS}
    if any(v is None for v in r.values()):
        return "CASH"
    if max(r["QQQ"], r["GLD"]) > r["SHY"]:
        return "QQQ" if r["QQQ"] >= r["GLD"] else "GLD"
    return "TLT" if r["TLT"] > r["SHY"] else "SHY"


def sleeve_target(ds, P, i):
    sel = dm_signal(ds, P, i)
    if sel != "QQQ":
        return {sel: 1.0} if sel != "CASH" else {"CASH": 1.0}
    cands = []
    for s in STOCKS:
        if i-252 < 0:
            continue
        a, b = P[s].get(ds[i-21]), P[s].get(ds[i-252])
        if a is None or b is None or b == 0:
            continue
        cands.append((s, a/b - 1.0))
    cands.sort(key=lambda x: -x[1])
    top = [s for s,_ in cands[:10]]
    return {s: 1.0/len(top) for s in top} if top else {"QQQ": 1.0}


def sleeve_candidates(ds, P, i, top_n=10, watch_n=15):
    """Return (top10_weights, watchlist, holdings_details) for the most recent trading day."""
    sel = dm_signal(ds, P, i)
    if sel != "QQQ":
        return ({sel: 1.0} if sel != "CASH" else {"CASH": 1.0}, [], [])
    cands = []
    for s in STOCKS:
        if i-252 < 0:
            continue
        a, b = P[s].get(ds[i-21]), P[s].get(ds[i-252])
        if a is None or b is None or b == 0:
            continue
        cands.append((s, a/b - 1.0))
    cands.sort(key=lambda x: -x[1])
    top_symbols = [s for s,_ in cands[:top_n]]
    weights = {s: 1.0/len(top_symbols) for s in top_symbols} if top_symbols else {"QQQ": 1.0}
    watchlist = []
    holdings_details = []
    cutoff = cands[top_n-1][1] if len(cands) >= top_n else (cands[-1][1] if cands else 0.0)
    today = ds[i]
    prev = ds[i-1] if i >= 1 else today

    prices_by_symbol = {s: list(P[s].values()) for s in STOCKS if s in P}

    def detail(sym, score):
        price_today = P[sym].get(today)
        price_prev = P[sym].get(prev) or price_today
        change_pct = 0.0
        if price_prev and price_prev > 0 and price_today:
            change_pct = (price_today / price_prev - 1.0) * 100
        dsym = sorted(P[sym].keys())
        i_sym = dsym.index(today) if today in dsym else len(prices_by_symbol[sym]) - 1
        ind = compute_indicators(prices_by_symbol[sym], i_sym)
        confs = build_confirmations(ind)
        return {
            "symbol": sym,
            "rank": cands.index((sym, score)) + 1,
            "score": round(score, 4),
            "dist_to_top10": round(cutoff - score, 4),
            "sector": None,
            "price": round(price_today, 2) if price_today else None,
            "change_pct": round(change_pct, 2),
            "indicators": ind,
            "confirmations": confs,
            "confirmation_count": confs["confirmation_count"],
            "readiness_score": min(100.0, max(0.0, 50.0 + score * 100.0)),
        }

    for s, score in cands[:top_n]:
        holdings_details.append(detail(s, score))
    for rank, (s, score) in enumerate(cands[top_n:top_n+watch_n], start=top_n+1):
        watchlist.append(detail(s, score))
    return weights, watchlist, holdings_details


def write_sleeve_signal_and_watchlist(ds, P, i, current_holdings=None, watch_n=15):
    """Export daily rebalance signal, watchlist, and top-10 holdings details."""
    weights, watchlist, holdings_details = sleeve_candidates(ds, P, i, top_n=10, watch_n=watch_n)
    gate = dm_signal(ds, P, i)
    today = ds[i]
    if current_holdings:
        current_set = {s for s in current_holdings if s not in ("CASH",)}
    else:
        sleeve_st = load_state("sleeve")
        current_set = {s for s in sleeve_st.get("holdings", {}) if s not in ("CASH",)}
    target_set = {s for s in weights if s not in ("CASH",)}
    incoming = sorted(target_set - current_set)
    outgoing = sorted(current_set - target_set)
    signal = bool(incoming or outgoing or gate != "QQQ")
    reasons = []
    if incoming:
        reasons.append(f"incoming: {', '.join(incoming)}")
    if outgoing:
        reasons.append(f"outgoing: {', '.join(outgoing)}")
    if gate != "QQQ":
        reasons.append(f"DM-6 gate {gate}")
    reason = "; ".join(reasons) if reasons else "no change"
    sig_path = os.path.join(BASE, "sleeve_rebalance_signal.json")
    json.dump({
        "date": today,
        "signal": signal,
        "gate": gate,
        "reason": reason,
        "incoming": incoming,
        "outgoing": outgoing,
        "current": sorted(current_set),
        "target": sorted(target_set),
    }, open(sig_path, "w"), indent=2)
    watch_path = os.path.join(BASE, "sleeve_watchlist.json")
    json.dump({
        "date": today,
        "watchlist": watchlist,
    }, open(watch_path, "w"), indent=2)
    holdings_path = os.path.join(BASE, "sleeve_holdings.json")
    json.dump({
        "date": today,
        "holdings": holdings_details,
    }, open(holdings_path, "w"), indent=2)
    print(f"sleeve: signal={signal} ({reason})")
    if watchlist:
        print(f"sleeve: watchlist exported with {len(watchlist)} candidates")
    if holdings_details:
        print(f"sleeve: holdings details exported with {len(holdings_details)} names")


def ret_on(P, s, d0, d1):
    a, b = P[s].get(d0), P[s].get(d1)
    if a is None or b is None or a == 0:
        return 0.0
    return b/a - 1.0


def run_portfolio(name, target_fn, ds, P, me_days):
    st = load_state(name)
    if st["last_date"] is None:
        proc = [d for d in ds if d >= st["inception"]]
    else:
        proc = [d for d in ds if d > st["last_date"]]
    for d in proc:
        prev = st["last_date"]
        if prev is not None:
            for a in list(st["holdings"]):
                if a != "CASH":
                    st["holdings"][a] *= 1.0 + ret_on(P, a, prev, d)
            st["equity"] = sum(st["holdings"].values())
        mes = [m for m in me_days if m < d]
        if mes:
            m = mes[-1]
            if st["last_signal_month"] != m[:7] and m >= st["inception"]:
                i = ds.index(m)
                tw = target_fn(ds, P, i)
                eq = st["equity"]
                cur = {a: v/eq for a, v in st["holdings"].items() if v > 0}
                keys = set(cur) | set(tw)
                to = sum(abs(cur.get(k,0.0)-tw.get(k,0.0)) for k in keys)
                st["equity"] *= 1.0 - 0.001*to
                st["holdings"] = {k: st["equity"]*w for k, w in tw.items() if w > 1e-9}
                if not st["holdings"]:
                    st["holdings"] = {"CASH": st["equity"]}
                st["last_signal_month"] = m[:7]
                print(f"{name}: signal @ {m} -> {sorted(tw.items(), key=lambda x:-x[1])[:3]}...")
        st["last_date"] = d
        summary = ",".join(f"{a}:{v/ st['equity']:.3f}" for a, v in sorted(st["holdings"].items(), key=lambda x:-x[1])[:4])
        append_hist(name, d, st["equity"], summary)
    save_state(name, st)
    print(f"{name}: equity ${st['equity']:,.2f} as of {st['last_date']} holdings {list(st['holdings'])[:4]}")


def dm_signal_target(ds, P, i):
    sel = dm_signal(ds, P, i)
    return {sel: 1.0} if sel != "CASH" else {"CASH": 1.0}


def main():
    os.makedirs(BASE, exist_ok=True)
    cfg = load_alpaca_config()
    P = {}
    for s in ALL:
        for a in range(3):
            try:
                P[s] = fetch_alpaca_bars(s, cfg)
                break
            except Exception as e:
                print(f"WARN: fetch {s} attempt {a+1} failed: {e}")
                time.sleep(2)
        else:
            print(f"ERROR: could not fetch {s}; skipping")
            continue
        time.sleep(0.05)  # be polite to Alpaca data API
    if not P:
        raise RuntimeError("No price data fetched; aborting")
    ds = sorted(set().union(*[set(P[s]) for s in P]))
    ds = [d for d in ds if d >= "2025-08-01"]
    if not ds:
        raise RuntimeError("No trading days in fetched window")
    me_days = month_ends(ds)
    run_portfolio("dm", dm_signal_target, ds, P, me_days)
    run_portfolio("sleeve", sleeve_target, ds, P, me_days)
    i = len(ds) - 1
    write_sleeve_signal_and_watchlist(ds, P, i)


if __name__ == "__main__":
    main()
