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
import re as _re
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
LIVE_QUOTES = os.path.join(WEB_DIR, "live_quotes.json")
LLM_EXPLAINERS = os.path.join(BASE, "thinking_llm.json")
BOT_LOG = os.path.join(BASE, "logs", "trading_bot.log")
HKT = ZoneInfo("Asia/Hong_Kong")  # bot log timestamps are server-local

SKIP_RE = _re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - \S+ - \w+ - Skipping ([A-Z0-9.]+): (.+)$"
)
SEED_LOG_BYTES = 3 * 1024 * 1024  # first run reads at most this much backlog

MAX_ENTRIES = 400
NON_TRADE_RESERVE = 40  # slots protected from trade floods (skips/scans/digests)
MAX_TRADE_IDS = 2000
SIGNAL_STALE_MIN = 40  # don't count a scan if signals.json itself is lagging

# Live entry gate (trading_bot.py startup banner) — used only to explain
# near-misses in plain language. Keep in sync with the bot if the gate moves.
GATE_READINESS = 80
GATE_CONFIRMATIONS = 6


# ---------------------------------------------------------------- helpers

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def load_watchlist_ranks(path="/var/www/hedge-fund-website/ai_watchlist_live.json"):
    """Return ({symbol: 1-based rank}, watchlist_set) from live watchlist."""
    try:
        doc = load_json(path) or {}
        wl = doc.get("watchlist") or []
        return {sym: i + 1 for i, sym in enumerate(wl)}, set(wl)
    except Exception:
        return {}, set()


def held_symbols_from_portfolio(port_path="/var/www/hedge-fund-website/portfolio_data.json"):
    try:
        port = load_json(port_path) or {}
        positions = port.get("positions") or port.get("account", {}).get("positions") or []
        return {p.get("symbol") for p in positions if p.get("symbol")}
    except Exception:
        return set()


def symbol_relevant_for_thinking(sym, sig, held, watchlist_ranks, min_readiness=75.0, max_rank=10):
    """Held positions and top-of-list or near-entry names are worth thinking about."""
    if sym in held:
        return True
    rank = watchlist_ranks.get(sym)
    if rank is not None and rank <= max_rank:
        return True
    r = sig.get("readiness_score") if sig else None
    if isinstance(r, (int, float)) and r >= min_readiness:
        return True
    return False


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
    qty = t.get("qty", "")
    price = t.get("price", "")
    try:
        qty = f"{float(qty):g}"
    except (TypeError, ValueError):
        qty = str(qty)
    try:
        price = f"{float(price):.2f}"
    except (TypeError, ValueError):
        price = str(price)
    return "|".join(str(x) for x in (t.get("timestamp", ""), t.get("action", ""), t.get("symbol", ""), qty, price))


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

def canonical_reason(raw):
    """Collapse dynamic skip reasons into stable, displayable buckets."""
    r = (raw or "").lower()
    if "persistence gate" in r:
        return "persistence gate — needs consecutive eligible scans"
    if "stop-out cooldown" in r:
        return "stop-out cooldown — no same-day re-entry after stop-loss"
    if "too hot" in r:
        return "intraday pump — entry too hot"
    if "entry/exit conflict" in r:
        return "entry/exit conflict — price inside VWAP stop zone"
    return (raw or "unknown").strip()[:60]


def read_new_log_lines(offset):
    """Tail BOT_LOG from byte offset; rotation-safe. Returns (lines, new_offset)."""
    try:
        size = os.path.getsize(BOT_LOG)
    except OSError:
        return [], offset
    if offset is None:
        offset = max(0, size - SEED_LOG_BYTES)
    if size < offset:  # rotated/truncated
        offset = 0
    try:
        with open(BOT_LOG, "r", errors="replace") as f:
            f.seek(offset)
            data = f.read()
            return data.splitlines(), f.tell()
    except OSError:
        return [], offset


def qualify_note(sig):
    """'would otherwise qualify' annotation for skip entries."""
    if not sig:
        return ""
    r = sig.get("readiness_score")
    base = f"readiness {r:.0f}" if isinstance(r, (int, float)) else "readiness n/a"
    fails = gate_failures(sig)
    if not fails:
        return base + " — would otherwise qualify"
    return base + f" — gate also blocks ({', '.join(fails)})"


def find_signal(signals_doc, symbol):
    for s in (signals_doc or {}).get("signals") or []:
        if s.get("symbol") == symbol:
            return s
    return None


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

def market_ctx():
    """Point-in-time tape snapshot stamped onto entries. SPY return is since
    the Jul 7 reset — the same baseline the site's race card uses."""
    ctx = {}
    lq = load_json(LIVE_QUOTES) or {}
    spy = lq.get("spy") or {}
    if isinstance(spy.get("return_pct"), (int, float)):
        ctx["spy_pct"] = round(spy["return_pct"], 2)
    if isinstance(lq.get("day_change_pct"), (int, float)):
        ctx["day_chg_pct"] = round(lq["day_change_pct"], 2)
    pv, cash = lq.get("portfolio_value"), lq.get("cash")
    if not (pv and cash):
        acct = (load_json(PORTFOLIO) or {}).get("account") or {}
        pv, cash = acct.get("portfolio_value"), acct.get("cash")
    if pv and cash:
        ctx["cash_pct"] = round(cash / pv * 100, 1)
    return ctx


def default_state():
    return {
        "emitted_trade_ids": [],
        "open_scan_id": None,
        "last_signals_ts": None,
        "digest_date": None,
        "quiet_streak": 0,
        "bootstrapped": False,
        "log_offset": None,
        "open_skips": {},
        "skips_bootstrapped": False,
    }


# ---------------------------------------------------------------- main

def main():
    state = load_json(STATE_PATH) or default_state()
    for k, v in default_state().items():
        state.setdefault(k, v)

    stream = load_json(OUT_PATH) or {}
    entries = stream.get("entries") or []

    # Live context for deciding which symbols deserve thinking-stream airtime.
    watchlist_ranks, _watchlist_set = load_watchlist_ranks()
    held = held_symbols_from_portfolio(PORTFOLIO)
    # Digests retired 2026-07-25: strip any remaining digest entries (Bot's Diary owns session summaries)
    entries = [e for e in entries if e.get("type") != "digest"]

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

    ctx = market_ctx()
    for ts, tid, t in new_trades:
        et_d = ts.astimezone(ET).date().isoformat()
        entry = {
            "id": f"trade-{tid}",
            "ts": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "et_date": et_d,
            "type": "trade",
            "action": (t.get("action") or "").upper(),
            "symbol": t.get("symbol"),
            "text": trade_text(t),
        }
        if ctx:
            entry["ctx"] = ctx
        entries.insert(0, entry)
        emitted.add(tid)
        if et_d == today_et:
            trades_today += 1
        # A trade closes any open scan window — the trade is the story.
        state["open_scan_id"] = None

    # FIFO order: keep ids in append order so trimming forgets the OLDEST,
    # not a random hash-ordered subset (set->list order is process-random).
    prev_order = state.get("emitted_trade_ids") or []
    prev_set = set(prev_order)
    ordered = [x for x in prev_order if x in emitted]
    for _ts, _tid, _t in new_trades:
        if _tid not in prev_set:
            ordered.append(_tid)
            prev_set.add(_tid)
    for _tid in emitted:  # bootstrap-added ids (first_run path)
        if _tid not in prev_set:
            ordered.append(_tid)
            prev_set.add(_tid)
    state["emitted_trade_ids"] = ordered[-MAX_TRADE_IDS:]
    state["bootstrapped"] = True

    # ---- 2. skip decisions (bot log tail) ------------------------------
    # The bot logs "Skipping SYM: reason" every cycle it declines to act on
    # an otherwise-actionable name. Collapse by (day, symbol, reason) into a
    # single living entry — the stream shows the decision, not the spam.
    sig_doc = load_json(SIGNALS)
    lines, new_offset = read_new_log_lines(state.get("log_offset"))
    state["log_offset"] = new_offset
    first_skip_run = not state["skips_bootstrapped"]

    # day rollover: freeze yesterday's skip windows
    for k in [k for k in state["open_skips"] if not k.startswith(today_et)]:
        del state["open_skips"][k]

    skips_changed = False
    for line in lines:
        m = SKIP_RE.match(line)
        if not m:
            continue
        ts_hkt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=HKT)
        ts_utc = ts_hkt.astimezone(timezone.utc)
        et_d = ts_utc.astimezone(ET).date().isoformat()
        if first_skip_run and et_d != today_et:
            continue  # seed: only today's skips on first pass
        sym, canon = m.group(2), canonical_reason(m.group(3))
        key = f"{et_d}|{sym}|{canon}"
        entry_id = f"skip-{et_d}-{sym}-{_re.sub(r'[^a-z0-9]+', '-', canon.lower())[:30]}"
        sig = find_signal(sig_doc, sym)
        # Don't give thinking-stream airtime to low-priority names. Held
        # positions, top-10 watchlist, and near-entry readiness (>=75) matter;
        # rank-8 rebuild chatter for a 72-readiness name is noise.
        if not symbol_relevant_for_thinking(sym, sig, held, watchlist_ranks):
            continue
        win = next((e for e in entries if e.get("id") == entry_id), None)
        if win is None:
            # Only surface skips with real tension: the entry gate passes and
            # another rule is the sole blocker. When the gate also blocks, the
            # skip is noise — scan windows already tell that story.
            if not sig or gate_failures(sig):
                continue
            win = {
                "id": entry_id,
                "ts": ts_utc.isoformat().replace("+00:00", "Z"),
                "et_date": et_d,
                "type": "skip",
                "symbol": sym,
                "reason": canon,
                "n": 0,
            }
            entries.insert(0, win)
        win["n"] = int(win.get("n") or 0) + 1
        win["ts"] = ts_utc.isoformat().replace("+00:00", "Z")
        n = win["n"]
        note = qualify_note(find_signal(sig_doc, sym))
        win["text"] = (f"Skipped {sym}{f' ×{n}' if n > 1 else ''} — {canon}"
                       + (f" · {note}" if note else ""))
        state["open_skips"][key] = entry_id
        skips_changed = True

    state["skips_bootstrapped"] = True
    if skips_changed:
        entries.sort(key=lambda e: e.get("ts", ""), reverse=True)

    # ---- 3. scan windows (market hours only) ---------------------------
    if in_market_hours(now_et):
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

    # Digests retired 2026-07-25: Bot's Diary (diary.json) owns session summaries.
    DIGESTS_ENABLED = False
    # ---- 4. day digest (after close, once per market day) --------------
    scans_today = 0
    for e in entries:
        if e.get("type") == "scan" and e.get("et_date") == today_et:
            scans_today += int(e.get("n") or 0)

    if (DIGESTS_ENABLED and is_market_day(now_et) and (now_et.hour, now_et.minute) >= (16, 5)
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
        d_entry = {
            "id": f"digest-{today_et}",
            "ts": now.isoformat().replace("+00:00", "Z"),
            "et_date": today_et,
            "type": "digest",
            "text": f"{head}{mid} · {tail}",
        }
        d_ctx = market_ctx()
        if d_ctx:
            d_entry["ctx"] = d_ctx
        entries.insert(0, d_entry)
        state["digest_date"] = today_et
        state["open_scan_id"] = None

    # ---- 4.5 pre-action risk watch ----------------------------------
    try:
        port = load_json(PORTFOLIO) or {}
        sigs_doc = load_json(SIGNALS) or {}
        risk_cfg = {"max_single_position_pct": 0.08}
        portfolio_value = (port.get("account") or {}).get("portfolio_value") or port.get("portfolio_value") or 0
        cash = (port.get("account") or {}).get("cash") or port.get("cash") or 0
        if portfolio_value > 0:
            risk_entries = _build_risk_watch_entries(
                entries, port.get("positions", []), risk_cfg, sigs_doc, portfolio_value
            )
            if risk_entries:
                entries.extend(risk_entries)
                # merge into state ids so duplicates are caught
                for rentry in risk_entries:
                    state.setdefault("seen_ids", {})[rentry["id"]] = rentry["ts"]
    except Exception as exc:
        print(f"[WARN] risk watch failed: {exc}", file=sys.stderr)

    # ---- 5. merge LLM explainers (written async by
    # generate_thinking_explainers.py; sidecar stays sole stream writer) ----
    llm_doc = load_json(LLM_EXPLAINERS) or {}
    explainers = llm_doc.get("explainers") or {}
    if explainers:
        for e in entries:
            if "explainer" not in e and e.get("id") in explainers:
                e["explainer"] = explainers[e["id"]]

    # ---- 6. write ------------------------------------------------------
    # Dedupe by entry id (keep first copy) and order strictly newest-first,
    # so re-emitted trades land in chronological place instead of pile-ups.
    _seen = set()
    _deduped = []
    for e in entries:
        eid = e.get("id")
        if eid:
            if eid in _seen:
                continue
            _seen.add(eid)
        _deduped.append(e)
    _deduped.sort(key=lambda e: e.get("ts", ""), reverse=True)
    # Reserve slots for non-trade entries so trade floods can't crowd out
    # skips/scans/digests — the "thinking" is the differentiating content.
    _non_trade = [e for e in _deduped if e.get("type") != "trade"][:NON_TRADE_RESERVE]
    _trades = [e for e in _deduped if e.get("type") == "trade"]
    entries = sorted(_non_trade + _trades[:MAX_ENTRIES - len(_non_trade)],
                     key=lambda e: e.get("ts", ""), reverse=True)
    out = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "entries": entries,
    }
    atomic_write_json(OUT_PATH, out)
    atomic_write_json(STATE_PATH, state)



# ── Pre-action risk watch (added 2026-07-27) ────────────────────────

def _build_risk_watch_entries(entries, positions, risk_config, signals_doc=None, portfolio_value=0):
    """Return new 'watch' entries for positions nearing trim/stop triggers.

    These are informational only; the bot still makes decisions in trading_bot.py.
    They give the public thinking stream advance notice of likely actions.
    """
    from risk_engine import tier_max_position_pct
    new_entries = []
    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    existing_ids = {e.get("id") for e in entries if e.get("id")}

    # map symbol -> current tier from signals.json
    sigs = {s.get("symbol"): s for s in (signals_doc or {}).get("signals", []) if s.get("symbol")}

    total_value = portfolio_value or 0
    if total_value <= 0:
        return []  # need a real portfolio value to compute concentration %
    for p in positions:
        sym = p.get("symbol")
        mv = p.get("market_value", 0)
        tier = (sigs.get(sym, {}).get("tier")
                or sigs.get(sym, {}).get("signal_tier")
                or p.get("tier", "MONITOR"))
        cap = tier_max_position_pct(tier, risk_config.get("max_single_position_pct", 0.08))
        pct = mv / total_value
        over = pct - cap
        # trim risk if already over cap or within 0.5pp of cap
        if over >= -0.005:
            eid = f"watch-cap-{today_et}-{sym}"
            if eid not in existing_ids:
                if over > 0:
                    text = (
                        f"{sym} is {pct*100:.1f}% of book, {over*100:.1f}pp over the {cap*100:.0f}% "
                        f"{tier} cap. A tier-cap trim is likely on the next cycle."
                    )
                else:
                    text = (
                        f"{sym} is {pct*100:.1f}% of book, within {(over)*-100:.1f}pp of the {cap*100:.0f}% "
                        f"{tier} cap. Watch for a concentration trim soon."
                    )
                new_entries.append({
                    "id": eid,
                    "ts": now.isoformat().replace("+00:00", "Z"),
                    "et_date": today_et,
                    "type": "watch",
                    "symbol": sym,
                    "text": text,
                })

        # stop risk: hard or trailing stop within 1.5% of current price
        current = p.get("current") or p.get("current_price")
        hard = p.get("hard_stop")
        trailing = p.get("trailing_stop")
        if current:
            nearest = None
            ndist = 1.0
            if hard:
                ndist = (current - hard) / current
                nearest = f"hard stop ${hard:.2f}"
            if trailing and (current - trailing) / current < ndist:
                ndist = (current - trailing) / current
                nearest = f"trailing stop ${trailing:.2f}"
            if ndist <= 0.015:
                eid = f"watch-stop-{today_et}-{sym}"
                if eid not in existing_ids:
                    new_entries.append({
                        "id": eid,
                        "ts": now.isoformat().replace("+00:00", "Z"),
                        "et_date": today_et,
                        "type": "watch",
                        "symbol": sym,
                        "text": f"{sym} is within {ndist*100:.1f}% of its {nearest}. "
                                  "A stop exit is close if the tape weakens.",
                    })
    return new_entries


if __name__ == "__main__":
    main()
