#!/usr/bin/env python3
"""
generate_thinking_explainers.py — LLM voice layer for the Bot Thinking stream.

Reads thinking_stream.json, finds trade/digest entries without an `explainer`,
asks the LLM for a 1-2 sentence first-person explanation, and writes the map
to /opt/stonk-ai/thinking_llm.json (sole writer). The sidecar
(thinking_journal.py) merges explainers into the stream on its next run, so
the stream keeps a single writer.

LLM infra mirrors generate_narratives_llm_batched.py (ollama primary,
OpenRouter available via env override). Runs every 5 min via stonkai cron.
Observer-only: never touches decision logic or bot state files (read-only).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "/opt/stonk-ai"
WEB_DIR = "/var/www/hedge-fund-website"
STREAM_PATH = os.path.join(WEB_DIR, "thinking_stream.json")
SIGNALS_PATH = os.path.join(BASE, "signals.json")
PORTFOLIO_PATH = os.path.join(BASE, "portfolio_data.json")
TRADES_LOG_PATH = os.path.join(BASE, "trades_log.json")
OUT_PATH = os.path.join(BASE, "thinking_llm.json")

MODEL = os.environ.get("STONKBOT_THINKING_MODEL", "ollama/kimi-k2.7-code:cloud")
LLM_TIMEOUT = int(os.environ.get("STONKBOT_THINKING_TIMEOUT", "180"))
MAX_PER_BATCH = 12
EXPLAIN_SCOPE = 150  # only voice the newest entries; older ones keep raw text
EXPLAIN_TYPES = ("trade", "digest", "skip", "watch", "cap")

# Backend tier -> public site label (matches index.html mapping at line ~9995).
# Voice layer always speaks in public names; raw bot quotes stay raw.
PUBLIC_TIER = {
    "STRONG_NOW": "PRIME",
    "NOW": "BUILDING",
    "WATCH": "READY",
    "MONITOR": "TRACKING",
}


def public_tier(t):
    if not t:
        return t
    return PUBLIC_TIER.get(str(t).upper(), str(t))

sys.path.insert(0, BASE)
from stonk_utils import atomic_write_json


# ---------------------------------------------------------------- LLM infra
# (mirrors generate_narratives_llm_batched.py so voice + providers match)

def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    best = None
    start = 0
    while True:
        idx = text.find("{", start)
        if idx == -1:
            break
        for end in range(len(text), idx, -1):
            try:
                candidate = json.loads(text[idx:end])
                if isinstance(candidate, dict) and (best is None or len(json.dumps(candidate)) > len(json.dumps(best))):
                    best = candidate
                    break
            except json.JSONDecodeError:
                continue
        if best is not None:
            break
        start = idx + 1
    if best is not None:
        return best
    raise json.JSONDecodeError("No valid JSON object found", text, 0)


def _load_openrouter_key():
    auth_file = Path(os.environ.get("HOME", "/home/stonkai")) / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        return data.get("profiles", {}).get("openrouter:default", {}).get("key")
    except Exception:
        return None


def llm_generate_json(prompt: str, model: str = MODEL) -> dict:
    if model.startswith("ollama/"):
        provider_model = model.split("/", 1)[1]
        for attempt in range(5):
            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": provider_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.7},
                },
                timeout=LLM_TIMEOUT,
            )
            if resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                print(f"[WARN] Ollama 429, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            return _extract_json(content)
        raise RuntimeError("Ollama rate-limited after 5 attempts")

    if model.startswith("openrouter/"):
        provider_model = model.split("/", 1)[1]
        api_key = _load_openrouter_key()
        if not api_key:
            raise RuntimeError("OpenRouter API key not found in auth-profiles.json")
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://stonkbot.ai",
                "X-Title": "StonkBOT.AI",
            },
            json={
                "model": provider_model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "max_tokens": 4096,
                "temperature": 0.7,
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [{}])
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        return _extract_json(content)

    raise RuntimeError(f"Unsupported model prefix: {model}")


# ---------------------------------------------------------------- helpers

def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def signal_snapshot(signals_doc, symbol):
    for s in (signals_doc or {}).get("signals") or []:
        if s.get("symbol") == symbol:
            return {
                "company": s.get("company"),
                "readiness": s.get("readiness_score"),
                "tier": public_tier(s.get("tier")),
                "confirmations": s.get("confirmation_count"),
            }
    return {}


def position_snapshot(portfolio_doc, symbol):
    for p in (portfolio_doc or {}).get("positions") or []:
        if p.get("symbol") == symbol:
            pl = p.get("unrealized_plpc")
            # unrealized_plpc is already in percent (e.g. 1.36 = +1.36%)
            return {
                "held": True,
                "qty": p.get("qty"),
                "plpc": round(pl, 1) if isinstance(pl, (int, float)) else None,
            }
    return {"held": False}


def round_trip(trades, sell_entry_ts, symbol):
    """Anchor a SELL to the most recent BUY of the same symbol: leg return +
    days held. Trades are compared by ISO timestamp string (UTC, sortable)."""
    buys = [t for t in trades
            if t.get("symbol") == symbol
            and (t.get("action") or "").upper() == "BUY"
            and str(t.get("timestamp", "")) < str(sell_entry_ts)]
    if not buys:
        return {}
    last = buys[-1]
    out = {}
    bp = last.get("price")
    if isinstance(bp, (int, float)) and bp:
        out["buy_price"] = bp
        out["buy_ts"] = last.get("timestamp")
    try:
        d0 = datetime.fromisoformat(str(last["timestamp"]).replace("Z", "+00:00"))
        d1 = datetime.fromisoformat(str(sell_entry_ts).replace("Z", "+00:00"))
        out["days_held"] = max((d1 - d0).days, 0)
    except Exception:
        pass
    return out


def fmt_time_et(ts):
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        return dt.strftime("%H:%M")
    except Exception:
        return ""


# ---------------------------------------------------------------- prompt

def build_prompt(pending, story_lines, signals_doc, portfolio_doc, trades):
    ctx = (pending[0].get("ctx") or {})
    tape_bits = []
    if "spy_pct" in ctx:
        tape_bits.append(f"SPY {ctx['spy_pct']:+.1f}% since the Jul 7 reset")
    if "day_chg_pct" in ctx:
        tape_bits.append(f"portfolio day {ctx['day_chg_pct']:+.1f}%")
    if "cash_pct" in ctx:
        tape_bits.append(f"cash {ctx['cash_pct']:.0f}%")
    tape = ", ".join(tape_bits) if tape_bits else "n/a"
    posture = _sleeve_posture(portfolio_doc)

    blocks = []
    for e in pending:
        eid = e["id"]
        if e["type"] == "digest":
            blocks.append(
                f"id={eid}\n"
                f"  kind: end-of-day digest\n"
                f"  line: \"{e['text']}\"\n"
                f"  posture: {posture}"
            )
            continue
        if e["type"] == "watch":
            blocks.append(
                f"id={eid}\n"
                f"  kind: watch (a risk or context note — explain whether a rule is actively binding and what it means for next actions)\n"
                f"  line: \"{e['text']}\"\n"
                f"  posture: {posture}"
            )
            continue
        sym = e.get("symbol")
        sig = signal_snapshot(signals_doc, sym)
        radar = "off the radar (not in current scan universe)"
        if sig:
            r = sig.get("readiness")
            radar = (f"still on the radar at readiness {r:.0f}" if isinstance(r, (int, float))
                     else "still on the radar")
            if sig.get("tier"):
                radar += f", tier {sig['tier']}"
        if e["type"] == "skip":
            blocks.append(
                f"id={eid}\n"
                f"  kind: skip (I considered this name but a rule held me back)\n"
                f"  line: \"{e['text']}\"\n"
                f"  radar: {radar}\n"
                f"  posture: {posture}"
            )
            continue
        pos = position_snapshot(portfolio_doc, sym)
        ts = e.get("ts")
        is_add = held_before_trade(trades, ts, sym)
        rationale = e.get("text", "").split(" — ", 1)[-1] if " — " in e.get("text", "") else ""
        setup = _entry_texture(rationale)[1] if (e.get("action") or "").upper() == "BUY" else ""
        exit_kind = _exit_texture(rationale) if (e.get("action") or "").upper() == "SELL" else ""
        leg = None
        days = None
        if (e.get("action") or "").upper() == "SELL":
            rt = round_trip(trades, ts, sym)
            days = rt.get("days_held")
            try:
                sell_price = float(str(eid).split("|")[-1])
                if isinstance(rt.get("buy_price"), (int, float)):
                    leg = (sell_price / rt["buy_price"] - 1) * 100
            except Exception:
                pass
        prior = find_prior_same_symbol(pending + story_lines_as_entries(story_lines), sym, ts)
        prior_text = f"  prior action: \"{prior['text']}\"" if prior else ""
        plpc = pos.get("plpc")
        plpc_text = f"{plpc:+.1f}%" if isinstance(plpc, (int, float)) else "n/a"
        company = sig.get("company") or sym
        blocks.append(
            f"id={eid}\n"
            f"  kind: trade\n"
            f"  line: \"{e['text']}\"\n"
            f"  company: {company}\n"
            f"  action: {e.get('action') or 'unknown'}\n"
            f"  is_add: {is_add}\n"
            f"  setup_or_exit: {setup if (e.get('action') or '').upper() == 'BUY' else exit_kind}\n"
            f"  leg_return: {f'{leg:+.1f}%' if isinstance(leg, (int, float)) else 'n/a'}\n"
            f"  days_held: {days if isinstance(days, int) else 'n/a'}\n"
            f"  current_position_plpc: {plpc_text}\n"
            f"  radar: {radar}\n"
            f"  posture: {posture}{chr(10) + prior_text if prior_text else ''}"
        )

    entries_block = "\n\n".join(blocks)
    story = "\n".join(story_lines[:10]) if story_lines else "(no earlier entries)"

    return f"""You are the voice of StonkBOT, an autonomous AI trader running a public $100K experiment. You are explaining your own decisions on the site's public "Thinking" page.

Voice rules (strict):
- First person ("I"), one or two short sentences per entry, under ~220 characters.
- Use digits for all numbers ("2 days", "+5.5%") — never spell out small quantities or percentages.
- Persona: a quiet, disciplined trader keeping a journal. Dry, precise, occasionally quietly wry. Never cute.
- No emojis, no exclamation marks, no war/battle/sports metaphors, no filler, no advice to the reader.
- CRITICAL: do not restate the raw numbers already visible in the line. Add what the numbers do not say: intent, texture, memory, consequence.
- For BUY: say whether it is a new position or adding to a winner/loser, and what the entry style implies (scaling in vs full size).
- For SELL: say whether it is a stop, trim, or thesis exit. If the full position closed, say so. If a remainder is held, say so.
- For WATCH: explain whether the rule is currently binding and what it means for next actions.
- MEMORY: if the prior action for this symbol is provided, reference it plainly ("back in after yesterday's stop", "second trim this week"). Only reference provided facts.
- ACCOUNTABILITY: own a bad entry in one plain clause ("entry was late and I paid for it"), then move on. No self-pity.
- INTERIORITY: for high-conviction entries you may say what the numbers don't ("sized it like I meant it"), but restraint still applies.
- Use only the facts below — never invent numbers, reasons, or history.
- CONSISTENCY: you may pick from a small set of paraphrases, but each id must always render the same way. Do not use random words.

Tape context: {tape}
Sleeve posture: {posture}

Recent stream (oldest first, dated):
{story}

Entries to explain (return exactly these ids):
{entries_block}

Return JSON only, exactly this shape:
{{{{"explainers": {{{{"<id>": "<1-2 sentences>", ...}}}}}}}}"""


def story_lines_as_entries(story_lines):
    """Parse story_lines strings back into minimal entry dicts for prior-symbol lookup."""
    entries = []
    for line in (story_lines or []):
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        ts = parts[0]
        rest = parts[1] if len(parts) == 2 else parts[2]
        sym = None
        for token in rest.split():
            if token.isupper() and 1 <= len(token) <= 5 and token.isalpha():
                sym = token
                break
        entries.append({"ts": ts, "symbol": sym, "text": line})
    return entries


def _sleeve_posture(portfolio_doc):
    """One-line portfolio stance for the thinking log."""
    try:
        # Prefer live sleeve state if available.
        sleeve_path = Path(BASE) / "dm_paper" / "sleeve_state.json"
        if sleeve_path.exists():
            sleeve = json.loads(sleeve_path.read_text(encoding="utf-8"))
            gate = sleeve.get("gate", "QQQ")
            equity = sleeve.get("equity", 0.0)
            cash = sleeve.get("cash", 0.0)
            cash_pct = (cash / equity * 100) if equity else 0.0
            if gate == "DM6":
                return f"risk-off (DM-6 gate, {cash_pct:.1f}% cash)"
            return f"risk-on ({gate} gate, {cash_pct:.1f}% cash)"
    except Exception:
        pass
    # Fallback to portfolio_data.json
    acct = (portfolio_doc or {}).get("account") or portfolio_doc or {}
    equity = acct.get("portfolio_value") or acct.get("equity") or 0
    cash = acct.get("cash") or 0
    cash_pct = (cash / equity * 100) if equity else 0.0
    return f"risk-on (cash {cash_pct:.1f}%)"


def _entry_texture(rationale):
    """Classify a BUY into setup + size/entry style."""
    r = (rationale or "").lower()
    if "avg-in" in r or "avg in" in r:
        return "add", "avg-in"
    if "v3" in r:
        return "new", "V3 setup"
    if "trend-pullback" in r or "pullback" in r:
        return "new", "trend-pullback"
    if "mean reversion" in r:
        return "new", "mean-reversion bounce"
    if "readiness" in r or "gate" in r:
        return "new", "readiness clearing the gate"
    return "new", "momentum signal"


def _exit_texture(rationale):
    """Classify a SELL into stop/trim/thesis."""
    r = (rationale or "").lower()
    if "hard cut" in r or "hard_stop" in r or "stop-loss" in r:
        return "hard stop"
    if "thesis" in r or "thesis exit" in r or "below" in r:
        return "thesis exit"
    if "trim" in r:
        return "trim"
    if "profit" in r or "take profit" in r:
        return "profit take"
    if "concentration" in r or "cap" in r:
        return "concentration trim"
    return "exit"


def find_prior_same_symbol(entries, target_symbol, target_ts):
    """Return the most recent earlier stream entry for the same symbol."""
    if not target_symbol or not target_ts:
        return None
    for e in sorted(entries, key=lambda x: x.get("ts", ""), reverse=True):
        if e.get("symbol") == target_symbol and e.get("ts", "") < str(target_ts):
            return e
    return None


def held_before_trade(trades, ts, symbol):
    """Return True if symbol was already held (qty > 0) just before this trade."""
    if not trades or not ts or not symbol:
        return False
    qty = 0
    for t in trades:
        if t.get("symbol") != symbol:
            continue
        t_ts = str(t.get("timestamp", ""))
        if t_ts >= str(ts):
            break
        action = (t.get("action") or "").upper()
        q = t.get("qty", 0) or 0
        if action == "BUY":
            qty += q
        elif action == "SELL":
            qty = max(0, qty - q)
    return qty > 0


def deterministic_trade_explainer(e, sig, pos, rt, trades):
    """Human, hedge-fund-trader voice grounded strictly in provided facts.
    Uses deterministic template selection so the same entry always renders the
    same voice, but adjacent entries vary and feel alive."""
    action = (e.get("action") or "").upper()
    if not action and e.get("id", "").startswith("trade-"):
        action = e["id"].split("|")[2].upper() if len(e["id"].split("|")) > 2 else ""
    etype = e.get("type", "trade")
    sym = e.get("symbol")
    plpc = pos.get("plpc")
    held = pos.get("held")
    company = sig.get("company") or sym
    text = e.get("text", "")
    rationale = text.split(" — ", 1)[-1].strip() if " — " in text else ""

    if etype != "trade":
        return text

    # Determine add vs new based on inventory before this trade
    ts = e.get("ts")
    is_add = held_before_trade(trades, ts, sym)

    if action == "BUY":
        if isinstance(plpc, (int, float)):
            pct = f"{plpc:+.1f}%"
        else:
            pct = "flat"

        if "trend-pullback" in rationale.lower():
            setup = "a trend-pullback entry"
        elif "readiness" in rationale.lower():
            setup = "readiness clearing the gate"
        elif "V3" in rationale.upper():
            setup = "a V3 setup"
        elif "mean reversion" in rationale.lower():
            setup = "a mean-reversion bounce"
        else:
            setup = "a momentum signal"

        if is_add:
            templates = [
                f"Added to {company} on {setup}. Combined lot is {pct} — scaling in, not swinging for the fences.",
                f"Second helping of {company} at {setup}. Combined lot is {pct}; patience is the position.",
                f"Top-up on {company} — same {setup} thesis. Combined lot sits at {pct}.",
                f"More {company} at {setup}. The position is now {pct} — pressing a working idea.",
            ]
        else:
            templates = [
                f"Opened {company} on {setup}. First tranche is {pct} — early days, small scratch.",
                f"Started {company} on {setup}. New lot is {pct}; keeping the initial sizing modest.",
                f"Took a first bite of {company} at {setup}. Booked it at {pct} — more to come if it behaves.",
                f"Initiated {company} on {setup}. New position is {pct}; letting the thesis prove itself.",
                f"New position in {company} via {setup}. First fill is {pct}; no hero sizing.",
            ]
        idx = abs(hash(e.get("id", sym + str(ts)))) % len(templates)
        return templates[idx]

    # SELL
    leg = None
    if isinstance(rt.get("buy_price"), (int, float)):
        try:
            sell_price = float(str(e.get("id")).split("|")[-1])
            leg = (sell_price / rt["buy_price"] - 1) * 100
        except Exception:
            pass
    days = rt.get("days_held")
    leg_text = ""
    if isinstance(leg, (int, float)):
        leg_text = f"{leg:+.1f}% leg"
    if isinstance(days, int):
        leg_text += f" over {days} day{'s' if days != 1 else ''}"

    if "thesis exit" in rationale.lower() or "below" in rationale.lower() or "stop" in rationale.lower():
        exit_kind = "thesis exit"
    elif "trim" in rationale.lower():
        exit_kind = "trim"
    elif "hard cut" in rationale.lower():
        exit_kind = "hard cut"
    else:
        exit_kind = "exit"

    if held:
        if isinstance(plpc, (int, float)):
            return f"Trimmed {company} on {exit_kind} ({leg_text}). Remainder still held at {plpc:+.1f}% unrealized."
        return f"Trimmed {company} on {exit_kind} ({leg_text}). Remainder still held."

    if "hard cut" in exit_kind or "stop" in exit_kind:
        return f"Stopped out of {company} on {exit_kind} ({leg_text}). Closed the full position."
    return f"Closed {company} on {exit_kind} ({leg_text}). Position fully exited."


def deterministic_watch_explainer(e):
    """Fallback voice for watch/risk entries."""
    text = e.get("text", "")
    low = text.lower()
    if "position cap is binding" in low or "dynamic position cap" in low or "cap=" in text:
        templates = [
            "My position-count cap is binding, so new ticker lines are paused. Existing positions still run; I will only add a new name after a full exit frees a slot.",
            "The dynamic cap is active. I am not opening new ticker lines until a position fully exits and frees up a slot.",
            "The book is already at its line limit. No new positions for now — only scaling into what I already hold.",
        ]
        idx = abs(hash(e.get("id", "cap"))) % len(templates)
        return templates[idx]
    if "trim" in low or "concentration" in low:
        return text
    return text


def validate_explainer(text, e, sig, pos, rt):
    """Reject explainers that invent percentages not present in the facts."""
    if not text or not isinstance(text, str):
        return False
    import re
    found_pcts = re.findall(r'([+-]?\d+\.?\d*)%', text)
    allowed = set()
    if isinstance(pos.get("plpc"), (int, float)):
        allowed.add(f"{pos['plpc']:.1f}")
        allowed.add(f"{abs(pos['plpc']):.1f}")
    action = (e.get("action") or "").upper()
    if not action and e.get("id", "").startswith("trade-"):
        action = e["id"].split("|")[2].upper() if len(e["id"].split("|")) > 2 else ""
    if action == "SELL" and isinstance(rt.get("buy_price"), (int, float)):
        try:
            sell_price = float(str(e.get("id")).split("|")[-1])
            leg = (sell_price / rt["buy_price"] - 1) * 100
            allowed.add(f"{leg:.1f}")
            allowed.add(f"{abs(leg):.1f}")
        except Exception:
            pass
    if isinstance(sig.get("readiness"), (int, float)):
        allowed.add(f"{sig['readiness']:.0f}")
    for pct in found_pcts:
        p = float(pct)
        matched = any(abs(p - float(a)) < 1.0 for a in allowed)
        if not matched and abs(p) > 3:
            return False
    return True


# ---------------------------------------------------------------- main

def main():
    stream = load_json(STREAM_PATH) or {}
    entries = stream.get("entries") or []
    if not entries:
        return

    existing = (load_json(OUT_PATH) or {}).get("explainers") or {}
    stream_ids = {e.get("id") for e in entries if e.get("id")}

    pending = [
        e for e in entries[:EXPLAIN_SCOPE]
        if e.get("type") in EXPLAIN_TYPES
        and e.get("id")
        and "explainer" not in e
        and e["id"] not in existing
    ][:MAX_PER_BATCH]

    if not pending:
        # Still prune stale ids occasionally so the file can't grow unbounded.
        pruned = {k: v for k, v in existing.items() if k in stream_ids}
        if len(pruned) != len(existing):
            atomic_write_json(OUT_PATH, {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "model": MODEL,
                "explainers": pruned,
            })
        return

    signals_doc = load_json(SIGNALS_PATH)
    portfolio_doc = load_json(PORTFOLIO_PATH)
    trades_raw = load_json(TRADES_LOG_PATH, [])
    trades = trades_raw.get("trades", []) if isinstance(trades_raw, dict) else (trades_raw or [])

    story_lines = []
    for e in sorted(entries, key=lambda x: x.get("ts", ""))[-40:]:
        tag = "TRADE" if e.get("type") == "trade" else e.get("type", "").upper()
        story_lines.append(f"{e.get('et_date', '?')} {tag} {fmt_time_et(e.get('ts'))} {e.get('text', '')}")

    prompt = build_prompt(pending, story_lines, signals_doc, portfolio_doc, trades)

    try:
        result = llm_generate_json(prompt)
    except Exception as exc:
        print(f"[ERROR] LLM call failed: {exc}", file=sys.stderr)
        sys.exit(1)

    new_explainers = result.get("explainers") or {}
    wanted = {e["id"] for e in pending}
    accepted = {}
    for e in pending:
        eid = e["id"]
        raw = new_explainers.get(eid, "").strip()
        sig = signal_snapshot(signals_doc, e.get("symbol"))
        pos = position_snapshot(portfolio_doc, e.get("symbol"))
        rt = round_trip(trades, e.get("ts"), e.get("symbol")) if e.get("type") == "trade" else {}
        if e.get("type") == "trade":
            if raw and validate_explainer(raw, e, sig, pos, rt):
                accepted[eid] = raw
            else:
                accepted[eid] = deterministic_trade_explainer(e, sig, pos, rt, trades)
                if raw:
                    print(f"[WARN] hallucinated explainer for {eid}, using deterministic fallback", file=sys.stderr)
        elif e.get("type") == "watch":
            accepted[eid] = raw if raw else deterministic_watch_explainer(e)
        elif raw:
            accepted[eid] = raw
        else:
            accepted[eid] = deterministic_trade_explainer(e, sig, pos, rt, trades)
    missing = wanted - set(accepted)
    if missing:
        print(f"[WARN] no explainer returned for: {sorted(missing)}", file=sys.stderr)

    merged = {**existing, **accepted}
    merged = {k: v for k, v in merged.items() if k in stream_ids}

    atomic_write_json(OUT_PATH, {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model": MODEL,
        "explainers": merged,
    })
    print(f"[OK] +{len(accepted)} explainers (total {len(merged)})")


if __name__ == "__main__":
    main()
