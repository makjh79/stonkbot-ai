#!/usr/bin/env python3
"""Daily paper tracker for DM-6m (Experiment 2) and DM-gated stock sleeve (Experiment 3).

Runs after each US close. Marks both virtual portfolios to market, computes
month-end signals, executes at next-day close (strict). State in
/opt/stonk-ai/dm_paper/. Baseline $100,000 each, inception 2026-08-24.
"""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = "/opt/stonk-ai/dm_paper"
STOCKS = ["AAPL","MSFT","AMZN","GOOGL","META","NVDA","AVGO","NFLX","ADBE","CSCO",
          "ORCL","QCOM","TXN","INTC","AMD","AMAT","MU","CRM","NOW","INTU",
          "AMGN","GILD","BKNG","ISRG","ADP","PAYX","COST","PEP","SBUX","MDLZ",
          "MNST","VRTX","REGN","ILMN","MRVL"]
ETFS = ["QQQ","GLD","TLT","SHY"]
ALL = STOCKS + ETFS
LOOKBACK_DAYS = 320  # fetch window (covers 252-trading-day momentum)

def yahoo(sym):
    enc = urllib.parse.quote(sym, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?range={LOOKBACK_DAYS}d&interval=1d&includeAdjustedClose=true"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        j = json.load(r)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]; adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for t,p in zip(ts,adj):
        if p is None: continue
        out[datetime.fromtimestamp(t,tz=timezone.utc).strftime("%Y-%m-%d")] = float(p)
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

def dm_signal(ds, P, i):
    def r6(s):
        if i-126 < 0: return None
        a, b = P[s].get(ds[i]), P[s].get(ds[i-126])
        if a is None or b is None: return None
        return a/b - 1.0
    r = {e: r6(e) for e in ETFS}
    if any(v is None for v in r.values()): return "CASH"
    if max(r["QQQ"], r["GLD"]) > r["SHY"]:
        return "QQQ" if r["QQQ"] >= r["GLD"] else "GLD"
    return "TLT" if r["TLT"] > r["SHY"] else "SHY"

def sleeve_target(ds, P, i):
    sel = dm_signal(ds, P, i)
    if sel != "QQQ":
        return {sel: 1.0} if sel != "CASH" else {"CASH": 1.0}
    cands = []
    for s in STOCKS:
        if i-252 < 0: continue
        a, b = P[s].get(ds[i-21]), P[s].get(ds[i-252])
        if a is None or b is None or b == 0: continue
        cands.append((s, a/b - 1.0))
    cands.sort(key=lambda x: -x[1])
    top = [s for s,_ in cands[:10]]
    return {s: 1.0/len(top) for s in top} if top else {"QQQ": 1.0}

def ret_on(P, s, d0, d1):
    a, b = P[s].get(d0), P[s].get(d1)
    if a is None or b is None or a == 0: return 0.0
    return b/a - 1.0

def run_portfolio(name, target_fn, ds, P, me_days):
    st = load_state(name)
    # determine unprocessed trading days
    if st["last_date"] is None:
        proc = [d for d in ds if d >= st["inception"]]
    else:
        proc = [d for d in ds if d > st["last_date"]]
    for d in proc:
        # mark-to-market from previous processed day
        prev = st["last_date"]
        if prev is not None:
            for a in list(st["holdings"]):
                if a != "CASH":
                    st["holdings"][a] *= 1.0 + ret_on(P, a, prev, d)
            st["equity"] = sum(st["holdings"].values())
        # month-end signal: if d is the trading day right after a month-end, execute
        # find most recent month-end <= d
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
                if not st["holdings"]: st["holdings"] = {"CASH": st["equity"]}
                st["last_signal_month"] = m[:7]
                print(f"{name}: signal @ {m} -> {sorted(tw.items(), key=lambda x:-x[1])[:3]}...")
        st["last_date"] = d
        summary = ",".join(f"{a}:{v/ st['equity']:.3f}" for a, v in sorted(st["holdings"].items(), key=lambda x:-x[1])[:4])
        append_hist(name, d, st["equity"], summary)
    save_state(name, st)
    print(f"{name}: equity ${st['equity']:,.2f} as of {st['last_date']} holdings {list(st['holdings'])[:4]}")

def main():
    os.makedirs(BASE, exist_ok=True)
    P = {}
    for s in ALL:
        for a in range(3):
            try: P[s] = yahoo(s); break
            except Exception: time.sleep(2)
        time.sleep(0.25)
    ds = sorted(set().union(*[set(P[s]) for s in ETFS]))
    ds = [d for d in ds if d >= "2025-08-01"]
    me_days = month_ends(ds)
    run_portfolio("dm", dm_signal_target, ds, P, me_days)
    run_portfolio("sleeve", sleeve_target, ds, P, me_days)

def dm_signal_target(ds, P, i):
    sel = dm_signal(ds, P, i)
    return {sel: 1.0} if sel != "CASH" else {"CASH": 1.0}

if __name__ == "__main__":
    main()
