#!/usr/bin/env python3
"""trade_quality.json generator (EXPERIMENT.md Amendment 1F).
Rolling diagnostics: PF (all/same-day/multi-day), median hold, whipsaw tax,
re-entry-rule opportunity cost, sub-3% stops, exit-reason attribution,
and post-Amendment-1 scoreboard (PF + QQQ comparison from 2026-07-27).
Cron: 3x/day. Output: /var/www/hedge-fund-website/trade_quality.json
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

sys.path.insert(0, "/opt/stonk-ai")

TRADES = "/var/www/hedge-fund-website/trades_log.json"
RISK_STATE = "/opt/stonk-ai/risk_state.json"
OUT = "/var/www/hedge-fund-website/trade_quality.json"
ET = timedelta(hours=-4)
AMENDMENT_LIVE = "2026-07-27"  # first session under amended rules

def parse_ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)

def classify(r):
    r = (r or "").lower()
    if "concentration trim:" in r or "reallocate" in r: return "conc_trim"
    if "sector trim:" in r: return "sector_trim"
    if "v3 scale-out t1:" in r or "v3 scale-out t2:" in r: return "profit_trim"
    if "thesis exit:" in r: return "thesis_exit"
    if "hard cut:" in r or "hard cut at" in r: return "hard_stop"
    if "hard stop:" in r or "hard stop at" in r: return "hard_stop"
    if "trailing stop:" in r or "trailing stop at" in r: return "trailing_stop"
    if "vwap stop:" in r or "vwap stop at" in r: return "vwap_stop"
    if "stop loss" in r: return "stop_loss"
    if "rotation:" in r: return "rotation"
    if "cash raise:" in r: return "cash_raise"
    if "full sell" in r or "unattributed" in r: return "full_sell_unattributed"
    # Partial trims that do not match explicit bucket patterns
    if r.startswith("trim "): return "conc_trim"
    return "other"

STOP_KINDS = {"trailing_stop", "hard_stop", "vwap_stop"}

def fifo_trips(trades):
    open_lots, trips = defaultdict(list), []
    for x in trades:
        sym, act = x["symbol"], x["action"].upper()
        qty, px, ts = x["qty"], x["price"], parse_ts(x["timestamp"])
        if act == "BUY":
            open_lots[sym].append([qty, px, ts])
        elif act == "SELL":
            reason = classify(x.get("rationale"))
            rem = qty
            while rem > 1e-9 and open_lots[sym]:
                lot = open_lots[sym][0]
                take = min(rem, lot[0])
                trips.append({"symbol": sym, "qty": take, "entry_ts": lot[2], "exit_ts": ts,
                              "entry_px": lot[1], "exit_px": px, "pnl": take * (px - lot[1]),
                              "hold_hours": (ts - lot[2]).total_seconds() / 3600,
                              "same_day_et": (lot[2] + ET).date() == (ts + ET).date(),
                              "exit_reason": reason})
                lot[0] -= take; rem -= take
                if lot[0] <= 1e-9: open_lots[sym].pop(0)
    return trips

def pf(rs):
    gp = sum(t["pnl"] for t in rs if t["pnl"] > 0)
    gl = sum(t["pnl"] for t in rs if t["pnl"] < 0)
    return (round(gp / abs(gl), 3) if gl else (None if gp == 0 else 999.0)), round(gp + gl, 2)

def block_stats(trips):
    if not trips:
        return {"n": 0}
    wins = [t for t in trips if t["pnl"] > 0]
    p, net = pf(trips)
    holds = sorted(t["hold_hours"] for t in trips)
    return {"n": len(trips), "win_rate_pct": round(100 * len(wins) / len(trips), 1),
            "profit_factor": p, "net_pnl": net,
            "median_hold_hours": round(holds[len(holds) // 2], 1)}

def main():
    now = datetime.now(timezone.utc)
    items = json.load(open(TRADES))
    items = items if isinstance(items, list) else items.get("trades", [])
    cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    w = sorted([x for x in items if x.get("timestamp", "") >= cutoff], key=lambda x: x["timestamp"])
    trips = fifo_trips(w)

    same = [t for t in trips if t["same_day_et"]]
    multi = [t for t in trips if not t["same_day_et"]]

    # rolling 20-trade expectancy by exit time
    last20 = sorted(trips, key=lambda t: t["exit_ts"])[-20:]
    exp20 = round(sum(t["pnl"] for t in last20), 2)

    # whipsaw pairs (stop-out -> re-entry <=5d)
    sells = [x for x in w if x["action"].upper() == "SELL"]
    buys = [x for x in w if x["action"].upper() == "BUY"]
    pairs, used = [], set()
    for s in sells:
        if classify(s.get("rationale")) not in STOP_KINDS: continue
        sts = parse_ts(s["timestamp"])
        for i, b in enumerate(buys):
            if i in used or b["symbol"] != s["symbol"]: continue
            dt = (parse_ts(b["timestamp"]) - sts).total_seconds()
            if 0 < dt <= 5 * 86400:
                pairs.append({"symbol": s["symbol"], "stop_ts": s["timestamp"][:16], "stop_px": s["price"],
                              "reentry_ts": b["timestamp"][:16], "reentry_px": b["price"],
                              "tax_usd": round(max(0.0, (b["price"] - s["price"]) * b["qty"]), 2)})
                used.add(i); break
    sub3 = sum(1 for x in sells
               if (m := re.search(r"Trailing stop: (-?\d+\.?\d*)% from peak", x.get("rationale", "")))
               and abs(float(m.group(1))) < 3.0)

    reasons = {}
    for t in trips:
        r = reasons.setdefault(t["exit_reason"], {"n": 0, "pnl": 0.0})
        r["n"] += 1; r["pnl"] += t["pnl"]

    # re-entry rule opportunity cost (Amendment 1D), priced now
    blocked, opp = [], 0.0
    try:
        state = json.load(open(RISK_STATE))
        blocked = state.get("blocked_reentries", [])[-50:]
        if blocked:
            from alpaca_data import AlpacaDataHub
            hub = AlpacaDataHub()
            px_now = hub.get_latest_prices(list({b["symbol"] for b in blocked}))
            for b in blocked:
                cur = px_now.get(b["symbol"])
                if cur:
                    opp += (cur - b["attempt_px"]) * 1  # per-share; qty unknown at block time
                    b["current_px"] = round(cur, 2)
                    b["drift_pct"] = round((cur / b["attempt_px"] - 1) * 100, 2)
    except Exception as e:
        blocked.append({"error": f"{type(e).__name__}: {e}"})

    # Amendment 2: gate blocks from logs/gate_blocks.jsonl
    gate_blocks = {"24h": 0, "7d": 0, "by_gate": {}, "recent": []}
    try:
        gpath = "/opt/stonk-ai/logs/gate_blocks.jsonl"
        if os.path.exists(gpath):
            for line in open(gpath):
                try:
                    b = json.loads(line)
                except Exception:
                    continue
                ts = parse_ts(b.get("ts", "1970"))
                age_h = (now.replace(tzinfo=None) - ts).total_seconds() / 3600
                if age_h <= 24: gate_blocks["24h"] += 1
                if age_h <= 7 * 24: gate_blocks["7d"] += 1
                g = b.get("gate", "?")
                gate_blocks["by_gate"][g] = gate_blocks["by_gate"].get(g, 0) + 1
                gate_blocks["recent"].append(b)
            gate_blocks["recent"] = gate_blocks["recent"][-10:]
    except Exception as e:
        gate_blocks["error"] = str(e)

    # Amendment 2C: breadth — % of signal universe above own 50DMA (existing Alpaca bars)
    breadth = None
    try:
        from alpaca_data import AlpacaDataHub
        sraw = json.load(open("/var/www/hedge-fund-website/signals.json"))
        symbols = [x.get("symbol") for x in (sraw if isinstance(sraw, list) else sraw.get("signals", sraw.get("data", []))) if x.get("symbol")]
        bars = AlpacaDataHub().get_daily_bars(symbols, days=120)
        above = n_ok = 0
        for sym, q in bars.items():
            closes = (q or {}).get("closes", []) if isinstance(q, dict) else []
            if len(closes) >= 50:
                n_ok += 1
                if closes[-1] > sum(closes[-50:]) / 50:
                    above += 1
        if n_ok:
            breadth = {"pct_above_50dma": round(100 * above / n_ok, 1), "n": n_ok, "universe": len(symbols)}
    except Exception as e:
        breadth = {"error": f"{type(e).__name__}: {e}"}

    # Amendment 2D: macro calendar (approx 2026 schedule — measurement only, NOT blocking)
    MACRO_DATES = {
        "2026-01-13", "2026-02-11", "2026-03-11", "2026-04-14", "2026-05-12", "2026-06-10",
        "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-13", "2026-11-10", "2026-12-10",  # CPI
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
        "2026-10-28", "2026-12-09",  # FOMC (day 2)
    }
    macro_trips = [t for t in trips if (t["entry_ts"] + ET).date().isoformat() in MACRO_DATES]
    macro = {"entries_on_macro_days": len(macro_trips), "net_pnl": round(sum(t["pnl"] for t in macro_trips), 2)}

    # Amendment 2A radar: current holdings with earnings <= 7d out
    earnings_radar = []
    try:
        ec = json.load(open("/opt/stonk-ai/earnings_cache.json")).get("earnings", {})
        pd_pos = json.load(open("/var/www/hedge-fund-website/portfolio_data.json")).get("positions", [])
        et_today = (now - ET).date()
        for p in pd_pos:
            rec = ec.get(p.get("symbol"))
            if rec and rec.get("date"):
                from datetime import date as _d
                y, m, dd = map(int, rec["date"].split("-"))
                delta = (_d(y, m, dd) - et_today).days
                if 0 <= delta <= 7:
                    earnings_radar.append({"symbol": p.get("symbol"), "date": rec["date"], "days": delta, "hour": rec.get("hour")})
    except Exception:
        pass

    # post-amendment scoreboard (live from Jul 27)
    post = [t for t in trips if t["exit_ts"].strftime("%Y-%m-%d") >= AMENDMENT_LIVE]
    qqq_since = None
    try:
        from alpaca_data import AlpacaDataHub
        raw = AlpacaDataHub().get_daily_bars(["QQQ"], days=20)
        q = raw.get("QQQ", {})
        ts, cl = q.get("timestamps", []), q.get("closes", [])
        series = [(str(t)[:10], c) for t, c in zip(ts, cl) if str(t)[:10] >= AMENDMENT_LIVE]
        if len(series) >= 2:
            qqq_since = round((series[-1][1] / series[0][1] - 1) * 100, 2)
    except Exception:
        pass

    # Website config-of-truth + earnings chip map (site copy must never drift from code)
    try:
        from risk_engine import RiskConfig as _RC, tier_max_position_pct as _tmpp
        from strategy_config import export_for_website, validate as _sc_validate
        _cfg = _RC()
        # v3 2026-08-01: use strategy_config as single source of truth
        _sc_issues = _sc_validate()
        if _sc_issues:
            print(f"WARNING: strategy_config validation issues: {_sc_issues}")
        _sc = export_for_website()
        ct = {
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "mode": "PAPER",
            **_sc,
            "caps": {t: _tmpp(t, _cfg.max_single_position_pct) for t in ("STRONG_NOW", "NOW", "WATCH", "MONITOR")},
            "caps_note": "single source of truth: risk_engine.tier_max_position_pct",
            "gates": {"earnings": "no entries within 2 days of confirmed earnings",
                      "implied_move": "3-7d pre-earnings: no entries when IV daily move > 1.5x ATR",
                      "reentry": "post-stop re-entry only at/below stop price (7d)"},
            "experiment": {"window": "Jul 7 2026 reset ongoing", "status": "Live A1+A2+v3 rules. Jul 27 pre-registered protocol ended. Aug 1 2026: churn fix + v3 signal/profit architecture deployed. strategy_config.py is single source of truth."},
        }
        with open("/var/www/hedge-fund-website/config_truth.json", "w") as f:
            json.dump(ct, f, indent=1)
        try: os.chown("/var/www/hedge-fund-website/config_truth.json", 999, 988)  # stonkai:stonkai (was uid 1000 = xcloud)
        except Exception: pass

        syms = set()
        try:
            pdp = json.load(open("/var/www/hedge-fund-website/portfolio_data.json"))
            syms |= {p.get("symbol") for p in pdp.get("positions", []) if p.get("symbol")}
        except Exception: pass
        for wf in ("ai_watchlist_live.json", "ai_watchlist.json"):
            try:
                wl = json.load(open(f"/var/www/hedge-fund-website/{wf}"))
                wl = wl if isinstance(wl, list) else wl.get("watchlist", wl.get("symbols", []))
                for x in wl:
                    s = x.get("symbol") if isinstance(x, dict) else x
                    if s: syms.add(s)
                break
            except Exception: continue
        ec = json.load(open("/opt/stonk-ai/earnings_cache.json")).get("earnings", {})
        emap = {s: {"date": ec[s]["date"], "hour": ec[s].get("hour", "")} for s in sorted(syms) if s in ec}
        with open("/var/www/hedge-fund-website/earnings.json", "w") as f:
            json.dump({"generated_at": ct["generated_at"], "earnings": emap}, f)
        try: os.chown("/var/www/hedge-fund-website/earnings.json", 999, 988)  # stonkai:stonkai (was uid 1000 = xcloud)
        except Exception: pass
    except Exception as e:
        print(f"config_truth/earnings export skipped: {e}")

    out = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "window_days": 30,
        "all": block_stats(trips),
        "same_day": block_stats(same),
        "multi_day": block_stats(multi),
        "rolling_20_trade_net_pnl": exp20,
        "whipsaw": {"pairs": len(pairs), "tax_usd": round(sum(p["tax_usd"] for p in pairs), 2), "detail": pairs[-15:]},
        "sub3pct_trailing_stops_30d": sub3,
        "exit_reasons": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)} for k, v in sorted(reasons.items(), key=lambda kv: kv[1]["pnl"])},
        "reentry_rule": {"blocked_count": len([b for b in blocked if "error" not in b]),
                         "opp_cost_per_share_sum": round(opp, 2), "recent": blocked[-10:]},
        "amendment1": {"live_from": AMENDMENT_LIVE, "closed_trips": block_stats(post),
                       "qqq_return_pct_since_live": qqq_since},
        "amendment2": {"gate_blocks": gate_blocks, "breadth": breadth, "macro": macro,
                       "earnings_radar": earnings_radar},
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    try:
        os.chown(OUT, 999, 988)  # stonkai:stonkai (was uid 1000 = xcloud)
    except Exception:
        pass
    # Daily diary — idempotent, one entry per completed US session
    try:
        import daily_diary
        print("diary:", daily_diary.maybe_generate())
    except Exception as e:
        print(f"diary skipped: {e}")
    print(f"trade_quality.json written: trips={len(trips)} pf={out['all'].get('profit_factor')} "
          f"whipsaw=${out['whipsaw']['tax_usd']} blocked={out['reentry_rule']['blocked_count']} "
          f"breadth={breadth and breadth.get('pct_above_50dma') if isinstance(breadth, dict) else breadth}")

if __name__ == "__main__":
    main()
