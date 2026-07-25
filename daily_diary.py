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
MODEL = "moonshotai/kimi-k2.6"


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


def _openrouter_key():
    for home in ("/home/stonkai", "/root", os.environ.get("HOME", "")):
        if not home:
            continue
        p = Path(home) / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
        try:
            key = json.loads(p.read_text()).get("profiles", {}).get("openrouter:default", {}).get("key")
            if key:
                return key
        except Exception:
            continue
    return None


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


def _nums(text):
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
    key = _openrouter_key()
    if not key:
        return None
    prompt = (
        "You write the daily diary of a public $100K autonomous stock-trading experiment. "
        "The project's only asset is credibility.\n"
        "Rules:\n"
        "- Use ONLY the facts below. Every number you write must appear in the facts, copied exactly.\n"
        "- Max 110 words, plain prose, 1-2 short paragraphs. No emojis, no headers, no bullet lists.\n"
        "- Be flatly honest about losses and mistakes; no excuses, no hype, no war metaphors.\n"
        "- No advice, no predictions. If nothing happened, say so plainly.\n"
        "- Refer to the bot in third person (\"the bot\").\n\n"
        "FACTS:\n" + facts_text
    )
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps({
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,  # K2.6 spends most of budget on reasoning; content needs the headroom (same as narratives module)
                "temperature": 0.4,
            }).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "https://stonkbot.ai", "X-Title": "StonkBOT.AI"},
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read())
            choices = data.get("choices") or []
            text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    except Exception:
        return None
    if not text or len(text) < 40:
        return None
    allowed = _nums(facts_text)
    for n in _nums(text):
        if not any(abs(n - a) < 1e-6 or (a != 0 and abs(n - a) / abs(a) < 1e-4) for a in allowed):
            return None  # invented number -> reject
    return text


def _template_entry(facts_text, stats, weekday, session):
    lines = facts_text.split("\n")
    trades_line = lines[1].split(": ", 1)[1]
    blocks_line = lines[2].split(": ", 1)[1]
    pf_line = lines[3].split(": ", 1)[1]
    pos_line = lines[4].split(": ", 1)[1]
    win_line = lines[5].split(": ", 1)[1]
    p1 = f"{weekday}, {session.strftime('%b %-d')}. "
    if stats["trades"]:
        p1 += f"The bot made {stats['trades']} trade{'s' if stats['trades'] != 1 else ''}: {trades_line}."
    else:
        p1 += "No trades today."
    if stats["blocks"]:
        p1 += f" Entry gates blocked {stats['blocks']}: {blocks_line}."
    p2 = f"Portfolio {pf_line.lower()}. Holdings: {pos_line}. "
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
