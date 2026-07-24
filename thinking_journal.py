#!/usr/bin/env python3
"""
thinking_journal.py — "Bot Thinking" stream sidecar (Phase 1)

Watches canonical bot outputs (READ-ONLY) and emits a compact decision
stream to the web root for the site's Thinking page + Holdings teaser.

Inputs (read-only):
  - trades_log.json        executed trades (Alpaca fills + bot rationale)
  - signals.json           latest signal-engine refresh (readiness, gates)
  - portfolio_data.json    cash / portfolio value

Output (sole writer):
  - /var/www/hedge-fund-website/thinking_stream.json

State (sole writer):
  - /opt/stonk-ai/thinking_state.json

Runs every 5 min via stonkai cron, 24/7. Emits:
  - trade events  (as they appear in trades_log.json)
  - scan windows  (collapsed routine scans during market hours)
  - day digest    (once per market day, after close)

No LLM. Decision logic untouched — this observes, it does not act.
"""

import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stonk_utils import atomic_write_json

BASE = "/opt/stonk-ai"
WEB_DIR = "/var/www/hedge-fund-website"
ET = ZoneInfo("America/New_York")

TRADES_LOG = os.path.join(BASE, "trades_log.json")
SIGNALS = os.path.join(BASE, "signals.json")
PORTFOLIO = os.path.join(BASE, "portfolio_data.json")
STATE_PATH = os.path.join(BASE, "thinking_state.json")
OUT_PATH = os.path.join(WEB_DIR, "thinking_stream.json")

MAX_ENTRIES = 400
MAX_TRADE_IDS = 800
SIGNAL_STALE_MIN = 40  # don't count a scan if signals.json itself is lagging

# Live entry gate (trading_bot.py startup banner) — used only to explain
# near-misses in plain language. Keep in sync with the bot if the gate moves.
GATE_READINESS = 77
GATE_CONFIRMATIONS = 5


# ---------------------------------------------------------------- helpers

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def now_utc():
    return datetime.now(timezone.utc)


def et_now():
    return now_utc().astimezone(ET)


def is_market_day(dt_et):
    return dt_et.weekday() < 5


def in_market_hours(dt_et):
    if not is_market_day(dt_et):
        return False
    mins = dt_et.hour * 60 + dt_et.minute
    return (9 * 60 + 30) <= mins < (16 * 60)


def extract_trades(raw):
    """trades_log.json may be a list or a dict wrapping the list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("trades", "entries", "fills"):
            if isinstance(raw.get(key), list):
                return raw[key]
    return []


def trade_id(t):
    return "|".join(str(t.get(k, "")) for k in ("timestamp", "action", "symbol", "qty", "price"))


def clean_reason(r):
    if not r:
        return ""
    r = str(r).replace("_", " ").strip()
    return r.rstrip(".")


def trade_verb(action, rationale):
    r = (rationale or "").lower()
    if action == "BUY":
        if "avg-in" in r or "avg in" in r:
            return "Added to"
        return "Bought"
    # SELL
    if "hard cut" in r or "stop" in r:
        return "Stopped out of"
    if "thesis" in r:
        return "Cut"
    if "trim" in r:
        return "Trimmed"
    if "profit" in r:
        return "Took profit on"
    if "flat" in r or "dead money" in r:
        return "Cut"
    return "Sold"


def trade_text(t):
    action = (t.get("action") or "").upper()
    sym = t.get("symbol") or "?"
    qty = t.get("qty")
    price = t.get("price")
    rationale = t.get("rationale") or t.get("reason") or ""
    verb = trade_verb(action, rationale)
    core = f"{verb} {sym}"
    if qty is not None and price is not None:
        try:
            core += f" {qty:g} @ ${float(price):,.2f}"
        except (TypeError, ValueError):
            pass
    reason = clean_reason(rationale)
    return f"{core} — {reason}" if reason else core


# ---------------------------------------------------------------- signals

def gate_failures(sig):
    """Return list of plain-English gate failures for a signal dict."""
    fails = []
    r = sig.get("readiness_score")
    conf = sig.get("confirmation_count")
    above = sig.get("above_ema20")
    if r is None or r < GATE_READINESS:
        fails.append(f"readiness {r:.0f}" if r is not None else "no readiness")
    if conf is None or conf < GATE_CONFIRMATIONS:
        fails.append(f"{conf}/5 conf" if conf is not None else "no conf")
    if not above:
        fails.append("below EMA20")
    return fails


def scan_stats(signals_doc):
    """Distribution + closest near-miss from one signals.json refresh."""
    sigs = (signals_doc or {}).get("signals") or []
    n = len(sigs)
    n70 = n77 = qualified = 0
    closest = None
    closest_key = None
    for s in sigs:
        r = s.get("readiness_score")
        if r is None:
            continue
        if r >= 70:
            n70 += 1
        if r >= GATE_READINESS:
            n77 += 1
        fails = gate_failures(s)
        if not fails:
            qualified += 1
            continue
        passed = 3 - len(fails)
        key = (passed, r)
        if closest_key is None or key > closest_key:
            closest_key = key
            closest = (s.get("symbol"), r, fails)
    dist = f"{n} candidates · {n70} ≥70 · {n77} ≥{GATE_READINESS}"
    if qualified:
        tail = f"{qualified} qualified"
    elif closest:
        sym, _r, fails = closest
        tail = f"closest: {sym} — {', '.join(fails)}"
    else:
        tail = "nothing close"
    return dist, tail


# ---------------------------------------------------------------- state

def default_state():
    return {
        "emitted_trade_ids": [],
        "open_scan_id": None,
        "last_signals_ts": None,
        "digest_date": None,
        "quiet_streak": 0,
        "bootstrapped": False,
    }


# ---------------------------------------------------------------- main

def main():
    state = load_json(STATE_PATH) or default_state()
    for k, v in default_state().items():
        state.setdefault(k, v)

    stream = load_json(OUT_PATH) or {}
    entries = stream.get("entries") or []

    now = now_utc()
    now_et = now.astimezone(ET)
    today_et = now_et.date().isoformat()

    # ---- 1. trades -----------------------------------------------------
    trades = extract_trades(load_json(TRADES_LOG, []))
    emitted = set(state["emitted_trade_ids"])
    first_run = not state["bootstrapped"]

    new_trades = []
    for t in trades:
        tid = trade_id(t)
        if not tid.strip("|") or tid in emitted:
            continue
        ts = parse_ts(t.get("timestamp"))
        if ts is None:
            continue
        if first_run:
            # Don't backfill history — swallow everything before today,
            # mark it emitted so it never floods the stream later.
            emitted.add(tid)
            if ts.astimezone(ET).date().isoformat() != today_et:
                continue
        new_trades.append((ts, tid, t))

    new_trades.sort(key=lambda x: x[0])
    trades_today = 0
    for e in entries:
        if e.get("type") == "trade" and e.get("et_date") == today_et:
            trades_today += 1

    for ts, tid, t in new_trades:
        et_d = ts.astimezone(ET).date().isoformat()
        entries.insert(0, {
            "id": f"trade-{tid}",
            "ts": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "et_date": et_d,
            "type": "trade",
            "action": (t.get("action") or "").upper(),
            "symbol": t.get("symbol"),
            "text": trade_text(t),
        })
        emitted.add(tid)
        if et_d == today_et:
            trades_today += 1
        # A trade closes any open scan window — the trade is the story.
        state["open_scan_id"] = None

    state["emitted_trade_ids"] = list(emitted)[-MAX_TRADE_IDS:]
    state["bootstrapped"] = True

    # ---- 2. scan windows (market hours only) ---------------------------
    if in_market_hours(now_et):
        sig_doc = load_json(SIGNALS)
        sig_ts_raw = (sig_doc or {}).get("generated_at")
        sig_ts = parse_ts(sig_ts_raw)
        if sig_ts and sig_ts_raw != state["last_signals_ts"]:
            age_min = (now - sig_ts).total_seconds() / 60
            if age_min <= SIGNAL_STALE_MIN:
                dist, tail = scan_stats(sig_doc)
                if state["open_scan_id"]:
                    win = next((e for e in entries if e.get("id") == state["open_scan_id"]), None)
                else:
                    win = None
                if win is None:
                    win = {
                        "id": f"scan-{sig_ts_raw}",
                        "ts": sig_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "et_date": today_et,
                        "type": "scan",
                        "n": 0,
                        "start": sig_ts_raw,
                    }
                    entries.insert(0, win)
                    state["open_scan_id"] = win["id"]
                win["n"] = int(win.get("n") or 0) + 1
                win["ts"] = sig_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                win["end"] = sig_ts_raw
                n = win["n"]
                win["text"] = f"{n} routine scan{'s' if n != 1 else ''} · {dist} · {tail}"
                # newest activity on top
                entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
                state["last_signals_ts"] = sig_ts_raw
    else:
        # Market closed: any open window is done for the day.
        if not is_market_day(now_et) or now_et.hour >= 16:
            state["open_scan_id"] = None

    # ---- 3. day digest (after close, once per market day) --------------
    scans_today = 0
    for e in entries:
        if e.get("type") == "scan" and e.get("et_date") == today_et:
            scans_today += int(e.get("n") or 0)

    if (is_market_day(now_et) and (now_et.hour, now_et.minute) >= (16, 5)
            and state["digest_date"] != today_et):
        port = load_json(PORTFOLIO) or {}
        acct = port.get("account") or {}
        pv = acct.get("portfolio_value") or 0
        cash = acct.get("cash") or 0
        cash_pct = (cash / pv * 100) if pv else 0
        if trades_today == 0:
            state["quiet_streak"] = int(state.get("quiet_streak") or 0) + 1
            head = f"Quiet day"
            if state["quiet_streak"] > 1:
                head += f" #{state['quiet_streak']}"
            body = f"{scans_today} scans, no trades" if scans_today else "no trades"
        else:
            state["quiet_streak"] = 0
            sells = sum(1 for e in entries
                        if e.get("type") == "trade" and e.get("et_date") == today_et
                        and e.get("action") == "SELL")
            buys = trades_today - sells
            parts = []
            if sells:
                parts.append(f"{sells} sell{'s' if sells != 1 else ''}")
            if buys:
                parts.append(f"{buys} buy{'s' if buys != 1 else ''}")
            head = " · ".join(parts)
            body = f"{scans_today} scans" if scans_today else ""
        tail = f"cash {cash_pct:.0f}%"
        mid = f" — {body}" if body else ""
        entries.insert(0, {
            "id": f"digest-{today_et}",
            "ts": now.isoformat().replace("+00:00", "Z"),
            "et_date": today_et,
            "type": "digest",
            "text": f"{head}{mid} · {tail}",
        })
        state["digest_date"] = today_et
        state["open_scan_id"] = None

    # ---- 4. write ------------------------------------------------------
    entries = entries[:MAX_ENTRIES]
    out = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }
    atomic_write_json(OUT_PATH, out)
    atomic_write_json(STATE_PATH, state)


if __name__ == "__main__":
    main()
