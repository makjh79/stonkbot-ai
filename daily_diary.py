#!/usr/bin/env python3
"""Daily diary — one entry per completed US trading session (ET). Idempotent.

Honesty discipline (config-of-truth for prose):
- All numbers are computed into a facts sheet first.
- The LLM may only narrate those facts; every number in its output must appear
  in the facts (float-tolerant match). Any invention -> deterministic template.
- Reads existing pipeline outputs only. No trading logic. No new data deps.
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

WEB = "/var/www/hedge-fund-website"
DIARY_PATH = os.path.join(WEB, "diary.json")
ET = timezone(timedelta(hours=-4))  # EDT; only used for date bucketing
MAX_ENTRIES = 60
OLLAMA_MODEL = "kimi-k2.7-code:cloud"


def _load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _et_date(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET).date()


def _latest_session(now_utc):
    now_et = now_utc.astimezone(ET)
    d = now_et.date()
    if now_et.hour < 16:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _collect_facts(session):
    trades_log = _load(os.path.join(WEB, "trades_log.json"), {})
    all_trades = trades_log.get("trades", [])
    day_trades = []
    for t in all_trades:
        try:
            if _et_date(t.get("timestamp", "")) == session:
                day_trades.append(t)
        except Exception:
            continue
    buys = [t for t in day_trades if t.get("action") == "BUY"]
    sells = [t for t in day_trades if t.get("action") == "SELL"]

    blocks = []
    try:
        with open("/opt/stonk-ai/logs/gate_blocks.jsonl") as f:
            for line in f:
                try:
                    b = json.loads(line)
                    if _et_date(b.get("timestamp", "")) == session:
                        blocks.append(b)
                except Exception:
                    continue
    except Exception:
        pass

    hist = _load(os.path.join(WEB, "portfolio_history.json"), {})
    checks = hist.get("checks", [])
    day_check, prev_check = None, None
    for i, c in enumerate(checks):
        try:
            if _et_date(c.get("timestamp", "")) == session:
                day_check = c
                prev_check = checks[i - 1] if i > 0 else None
        except Exception:
            continue
    if not day_check:
        return None  # no session evidence (holiday) -> skip entry

    pv = day_check.get("portfolio_value", 0)
    cash = day_check.get("cash", 0)
    cash_pct = (cash / pv * 100) if pv else 0
    day_pp = None
    if prev_check and prev_check.get("portfolio_value"):
        day_pp = (pv / prev_check["portfolio_value"] - 1) * 100

    pdata = _load(os.path.join(WEB, "portfolio_data.json"), {})
    pos_lines = []
    for p in pdata.get("positions", []):
        plpc = p.get("unrealized_plpc")
        if plpc is None:
            continue
        pos_lines.append(f"{p.get('symbol')} {p.get('qty')} @ {plpc:+.2f}%")

    tq = _load(os.path.join(WEB, "trade_quality.json"), {})
    trips = (tq.get("amendment1") or {}).get("closed_trips") or {}
    if trips.get("n"):
        window_line = (f"experiment window: {trips['n']} closed trades, "
                       f"profit factor {trips.get('profit_factor', 0):.2f}, "
                       f"median hold {trips.get('median_hold_hours', 0):.1f}h")
    else:
        window_line = "experiment window (amended rules): no closed trades yet"

    def tline(t):
        why = t.get("rationale") or t.get("strategy") or ""
        return t["action"], t["symbol"], t["qty"], t["price"], why

    # group identical trades (action+symbol+reason) into "SELL ROKU ×4 @ $142.28-142.38 — why"
    groups = {}
    order = []
    for t in day_trades:
        a, s, q, px, why = tline(t)
        key = (a, s, why[:40])
        if key not in groups:
            groups[key] = {"a": a, "s": s, "qty": 0, "pxs": [], "why": why}
            order.append(key)
        groups[key]["qty"] += q
        groups[key]["pxs"].append(px)
    clauses = []
    for key in order[:4]:
        g = groups[key]
        lo, hi = min(g["pxs"]), max(g["pxs"])
        px_txt = f"${lo:.2f}" if lo == hi else f"${lo:.2f}-{hi:.2f}"
        c = f"{g['a']} {g['s']}"
        if len(g["pxs"]) > 1:
            c += f" x{len(g['pxs'])}"
        c += f" ({g['qty']} sh) @ {px_txt}"
        if g["why"]:
            c += f" — {g['why'].split('(')[0].strip()}"
        clauses.append(c)
    if len(order) > 4:
        clauses.append(f"+{len(order) - 4} more")
    trades_txt = "; ".join(clauses)

    block_lines = [f"{b.get('symbol')} blocked by {b.get('gate', 'gate')} ({b.get('reason', '')})" for b in blocks]

    weekday = session.strftime("%A")
    lines = [f"SESSION: {weekday} {session.isoformat()} (US ET)"]
    lines.append(f"TRADES ({len(day_trades)}): " + (trades_txt if day_trades else "none"))
    lines.append(f"GATE BLOCKS ({len(blocks)}): " + ("; ".join(block_lines) if block_lines else "none"))
    pl = f"PORTFOLIO: value ${pv:,.0f}"
    if day_pp is not None:
        pl += f" ({day_pp:+.1f}% vs prior day)"
    pl += f", cash ${cash:,.0f} ({cash_pct:.0f}%)"
    lines.append(pl)
    lines.append("POSITIONS: " + (", ".join(pos_lines) if pos_lines else "none"))
    lines.append("WINDOW: " + window_line)
    facts_text = "\n".join(lines)

    stats = {"trades": len(day_trades), "buys": len(buys), "sells": len(sells),
             "blocks": len(blocks), "pv": round(pv), "cash_pct": round(cash_pct, 1)}
    if day_pp is not None:
        stats["day_pp"] = round(day_pp, 2)
    return facts_text, stats, weekday, session


_NUM_RE = re.compile(r"[+\-]?\$?\d[\d,]*\.?\d*\s*(?:%|pp)?")
_MONTH_RE = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\b")


def _nums(text):
    # normalize away constructs that poison extraction: ISO dates, month-name dates, numeric ranges
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
    text = _MONTH_RE.sub(" ", text)
    text = re.sub(r"(?<=\d)-(?=\d)", " to ", text)
    out = []
    for m in _NUM_RE.finditer(text):
        tok = m.group(0).strip().rstrip("%").rstrip("pp").strip()
        tok = tok.replace("$", "").replace(",", "").replace("+", "").strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def _llm_entry(facts_text):
    def _fail(msg):
        try:
            with open("/opt/stonk-ai/logs/diary.log", "a") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
        except Exception:
            pass
        return None

    prompt = (
        "You are the bot in a public $100K autonomous stock-trading experiment, writing your own "
        "diary at the close of the US session. It is published on the project's website, and the "
        "project's only asset is credibility — this diary is its daily record.\n\n"
        "Voice: write like a human keeping a private journal that happens to be public. First person "
        "(\"I\"). Calm, precise, quietly funny — the dryness of a machine that knows exactly what it "
        "did and isn't precious about it. Wit lives in word choice and rhythm: understatement, wry "
        "asides, honest self-deprecation. Never jokes at the expense of the facts, never hype, never "
        "cheerleading, never excuses. A loss gets the same deadpan as a win — name it plainly, maybe "
        "with a small shrug in the phrasing, and move on.\n\n"
        "Form: two or three short paragraphs of flowing prose, 100-140 words, separated by a blank "
        "line. No lists, no headers, no emojis. Open with whatever actually made the day distinctive "
        "— a quiet day is a fine opening — and never with the bare date (\"Tuesday\" or \"Tuesday, "
        "Jul 28\" at most). Tell the story of the session: what you did, why, and how it left the "
        "book. Close on a small observation, not a summary or a morale report.\n\n"
        "Numbers (strictly enforced):\n"
        "- Prefer words for numbers (\"six trades\", \"half the book in cash\"). Use digits at most "
        "three times in the whole entry, and only for figures that genuinely matter.\n"
        "- Every digit-number you write must appear in the FACTS below, exactly. Writing \"down 2.1%\" "
        "is fine when the facts say -2.10% — the word carries the sign. If unsure, use words or leave "
        "it out. Never invent, round, or derive a new digit-number.\n\n"
        "Honesty: use ONLY the facts below. No advice, no predictions, no war or sports metaphors. "
        "You may nod at being a bot with dry humor, but stay in the diary — no meta-commentary about AI.\n\n"
        "FACTS:\n" + facts_text
    )

    # Primary: local Ollama (free, no billing dependency). Fallback: OpenRouter.
    text = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=json.dumps({
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.55},
                }).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=240) as r:
                text = (json.loads(r.read()).get("message") or {}).get("content") or ""
            if text.strip():
                break
        except Exception as e:
            if attempt == 2:
                _fail(f"ollama: {type(e).__name__} {str(e)[:140]}")
            text = None
    if not text or not text.strip():
        return _fail("ollama-empty")
    # strip any reasoning traces before validation
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if not text or len(text) < 40:
        return _fail("empty-content")
    allowed = _nums(facts_text)
    # absolute-value match: prose carries the sign in words ("down 2.1%" for -2.10%)
    bad = [n for n in _nums(text)
           if not any(abs(abs(n) - abs(a)) < 1e-6 or (a != 0 and abs(abs(n) - abs(a)) / abs(a) < 1e-4) for a in allowed)]
    if bad:
        return _fail(f"invented numbers: {bad[:6]}")
    return text


_SMALL = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def _w(n):
    return _SMALL[n] if 0 <= n < 10 else str(n)


def _template_entry(facts_text, stats, weekday, session):
    lines = facts_text.split("\n")
    trades_line = lines[1].split(": ", 1)[1]
    blocks_line = lines[2].split(": ", 1)[1]
    pf_line = lines[3].split(": ", 1)[1]
    pos_line = lines[4].split(": ", 1)[1]
    win_line = lines[5].split(": ", 1)[1]
    p1 = f"{weekday}, {session.strftime('%b %-d')}. "
    if stats["trades"]:
        p1 += f"I made {_w(stats['trades'])} trade{'s' if stats['trades'] != 1 else ''} today: {trades_line}."
    else:
        p1 += "A quiet session — I didn't trade at all."
    if stats["blocks"]:
        p1 += f" The gates turned me away {_w(stats['blocks'])} time{'s' if stats['blocks'] != 1 else ''}: {blocks_line}."
    # portfolio sentence: facts say "value $93,089 (+0.2% vs prior day), cash $44,782 (48%)"
    p2 = f"The book closed at {pf_line.replace('value ', '')}. "
    # name only the best and worst seats rather than reading out the whole ledger
    movers = []
    for chunk in pos_line.split(", "):
        m = re.match(r"([A-Z.]+) \d+ @ ([+\-\d.]+)%", chunk)
        if m:
            movers.append((m.group(1), float(m.group(2))))
    if len(movers) >= 2:
        movers.sort(key=lambda x: x[1])
        p2 += f"Best seat in the house: {movers[-1][0]} at {movers[-1][1]:+.2f}%; "
        p2 += f"{movers[0][0]} brings up the rear at {movers[0][1]:+.2f}%. "
    elif movers:
        p2 += f"Only name on the sheet: {movers[0][0]} at {movers[0][1]:+.2f}%. "
    p2 += win_line[0].upper() + win_line[1:] + "."
    return p1 + " " + p2


def maybe_generate():
    now = datetime.now(timezone.utc)
    session = _latest_session(now)
    diary = _load(DIARY_PATH, {"entries": []})
    entries = diary.get("entries", [])
    if any(e.get("date") == session.isoformat() for e in entries):
        return f"exists ({session})"
    collected = _collect_facts(session)
    if not collected:
        return f"no-session ({session})"
    facts_text, stats, weekday, sess = collected
    body = _llm_entry(facts_text)
    source = "llm"
    if body is None:
        body = _template_entry(facts_text, stats, weekday, sess)
        source = "template"
    entry = {"date": session.isoformat(),
             "generated_at": now.isoformat().replace("+00:00", "Z"),
             "body": body, "stats": stats,
             "source": source}
    entries = [entry] + entries
    diary = {"entries": entries[:MAX_ENTRIES]}
    tmp = DIARY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(diary, f)
    os.replace(tmp, DIARY_PATH)
    try:
        os.chown(DIARY_PATH, 1000, 1000)
    except Exception:
        pass
    return f"written ({session}, {entry['source']})"


if __name__ == "__main__":
    print(maybe_generate())
