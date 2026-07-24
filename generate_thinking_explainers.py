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
EXPLAIN_TYPES = ("trade", "digest")

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
                "tier": s.get("tier"),
                "confirmations": s.get("confirmation_count"),
            }
    return {}


def position_snapshot(portfolio_doc, symbol):
    for p in (portfolio_doc or {}).get("positions") or []:
        if p.get("symbol") == symbol:
            pl = p.get("unrealized_plpc")
            return {
                "held": True,
                "qty": p.get("qty"),
                "plpc": round(pl * 100, 1) if isinstance(pl, (int, float)) else None,
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

    blocks = []
    for e in pending:
        eid = e["id"]
        if e["type"] == "digest":
            blocks.append(
                f"id={eid}\n"
                f"  kind: end-of-day digest\n"
                f"  line: \"{e['text']}\""
            )
            continue
        sym = e.get("symbol")
        sig = signal_snapshot(signals_doc, sym)
        pos = position_snapshot(portfolio_doc, sym)
        radar = "off the radar (not in current scan universe)"
        if sig:
            r = sig.get("readiness")
            radar = (f"still on the radar at readiness {r:.0f}" if isinstance(r, (int, float))
                     else "still on the radar")
            if sig.get("tier"):
                radar += f", tier {sig['tier']}"
        pos_txt = ("remainder still held"
                   + (f" at {pos['plpc']:+.1f}% unrealized" if isinstance(pos.get("plpc"), (int, float)) else "")
                   if pos.get("held") else "position fully closed")
        ctx_bits = []
        if (e.get("action") or "").upper() == "SELL":
            rt = round_trip(trades, e.get("ts"), sym)
            # attach exit price to compute leg return
            sell_price = None
            # entry id embeds price: trade-<ts>|<action>|<sym>|<qty>|<price>
            try:
                sell_price = float(str(eid).split("|")[-1])
            except (ValueError, IndexError):
                pass
            if isinstance(rt.get("buy_price"), (int, float)) and sell_price:
                leg = (sell_price / rt["buy_price"] - 1) * 100
                ctx_bits.append(f"this leg: bought at ${rt['buy_price']:,.2f}, exited {leg:+.1f}%")
            if isinstance(rt.get("days_held"), int):
                ctx_bits.append(f"held {rt['days_held']} day{'s' if rt['days_held'] != 1 else ''}")
        ctx_txt = "; ".join(ctx_bits) if ctx_bits else "no round-trip context"
        company = sig.get("company") or sym
        blocks.append(
            f"id={eid}\n"
            f"  kind: trade\n"
            f"  line: \"{e['text']}\"\n"
            f"  company: {company}\n"
            f"  round-trip: {ctx_txt}\n"
            f"  radar: {radar}\n"
            f"  position: {pos_txt}"
        )

    entries_block = "\n\n".join(blocks)
    story = "\n".join(story_lines[:10]) if story_lines else "(no earlier entries)"

    return f"""You are the voice of StonkBOT, an autonomous AI trader running a public $100K real-money experiment. You are explaining your own decisions on the site's public "Thinking" page.

Voice rules (strict):
- First person ("I"), one or two short sentences per entry, under ~220 characters
- Deadpan, precise, a little dry. No emojis, no exclamation marks
- No war/battle/sports metaphors. No motivational filler. No advice to the reader
- CRITICAL: the reader already sees the raw line with its trigger numbers. Do NOT restate them. Add what the numbers don't say: holding period, round-trip outcome, what the exit frees up, whether the symbol stays on the radar
- Vary your sentence shapes. If four stops fire in one day, do not explain them the same way four times — for a routine trailing stop a single short shrug of a sentence is better than a template
- For stops/hard cuts: matter-of-fact, no excuses, no self-pity. For quiet days: cash as a deliberate position, said plainly, at most once
- Use only the facts below — never invent numbers or reasons

Tape context: {tape}

Today's stream so far (oldest first):
{story}

Entries to explain (return exactly these ids):
{entries_block}

Return JSON only, exactly this shape:
{{"explainers": {{"<id>": "<1-2 sentences>", ...}}}}"""


# ---------------------------------------------------------------- main

def main():
    stream = load_json(STREAM_PATH) or {}
    entries = stream.get("entries") or []
    if not entries:
        return

    existing = (load_json(OUT_PATH) or {}).get("explainers") or {}
    stream_ids = {e.get("id") for e in entries if e.get("id")}

    pending = [
        e for e in entries
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

    day = pending[0].get("et_date")
    story_lines = []
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        if e.get("et_date") == day:
            tag = "TRADE" if e.get("type") == "trade" else e.get("type", "").upper()
            story_lines.append(f"{tag} {fmt_time_et(e.get('ts'))} {e.get('text', '')}")

    prompt = build_prompt(pending, story_lines, signals_doc, portfolio_doc, trades)

    try:
        result = llm_generate_json(prompt)
    except Exception as exc:
        print(f"[ERROR] LLM call failed: {exc}", file=sys.stderr)
        sys.exit(1)

    new_explainers = result.get("explainers") or {}
    wanted = {e["id"] for e in pending}
    accepted = {k: str(v).strip() for k, v in new_explainers.items()
                if k in wanted and isinstance(v, str) and v.strip()}
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
