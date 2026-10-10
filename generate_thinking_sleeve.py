#!/usr/bin/env python3
"""
Sleeve-era thinking stream generator.

The old stream narrated the intraday strategy (tier caps, trims, cycles) which
no longer exists. This generator matches the actual strategy cadence:
monthly-rebalanced momentum with dual-threshold hysteresis (buy rank <= 8,
held until rank > 12, basket of 10).

Entry types (deterministic, no LLM):
  digest   - daily note after the morning scoring: rank movers, boundary
             watch, book state, and whether anything crossed a decision line
  boundary - event: a name crosses a decision boundary (buy zone #8,
             top 10, exit buffer #11-12, exit line >#12)
  decision - event: real executions from trades_log.json, grouped by day
  gate     - event: DM-6 regime flip (risk-on <-> defensive)

Reads:  dm_paper/sleeve_watchlist.json  (rank, prev_rank, buy_status)
        dm_paper/sleeve_state.json      (equity, cash, holdings, gate)
        dm_paper/sleeve_rebalance_signal.json
        /var/www/hedge-fund-website/trades_log.json
Writes: website/thinking_stream.json + web root copy (atomic).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE = Path(os.environ.get("STONKBOT_BOT_DIR", "/opt/stonk-ai"))
DATA = Path(os.environ.get("STONKBOT_DATA_DIR", BASE))
WEB = Path(os.environ.get("STONKBOT_WEB_DIR", "/var/www/hedge-fund-website"))

WATCHLIST = DATA / "dm_paper" / "sleeve_watchlist.json"
STATE = DATA / "dm_paper" / "sleeve_state.json"
SIGNAL = DATA / "dm_paper" / "sleeve_rebalance_signal.json"
TRADES = WEB / "trades_log.json"
OUT_REPO = BASE / "website" / "thinking_stream.json"
OUT_WEB = WEB / "thinking_stream.json"
DIARY_REPO = BASE / "website" / "diary.json"
DIARY_WEB = WEB / "diary.json"

ERA = "sleeve-v2"
SLEEVE_ERA_START = "2026-09-28"  # paper account migrated to the momentum sleeve
BUY_LINE = 8
EXIT_LINE = 12
TOP_N = 10
MAX_ENTRIES = 400

MODEL = os.environ.get("STONKBOT_LLM_MODEL", "kimi-k2.7-code:cloud")
LLM_BASE = os.environ.get("STONKBOT_LLM_BASE", "https://ollama.com/v1")
BANNED_TOKENS = [
    "rsi", "macd", "vwap", "ema", "moving average", "relative strength",
    "histogram", "overbought", "oversold", "dm-6", "readiness", "confirmation",
]


def load_llm_key() -> str | None:
    """Key file follows the configured provider (Ollama Cloud since 2026-10-05;
    SiliconFlow 2026-10-02; OpenRouter before that)."""
    candidates = []
    if os.environ.get("STONKBOT_LLM_KEY_FILE"):
        candidates.append(os.environ["STONKBOT_LLM_KEY_FILE"])
    candidates.append("/opt/stonk-ai/.secrets/ollama.key" if "ollama" in LLM_BASE
                      else "/opt/stonk-ai/.secrets/siliconflow.key")
    for p in candidates:
        try:
            return Path(p).read_text(encoding="utf-8").strip() or None
        except Exception:
            continue
    return None


def llm_day_note(facts: dict, prior_notes: list[str]) -> str | None:
    """Free-flowing analyst voice for the daily note. None on any failure."""
    api_key = load_llm_key()
    if not api_key:
        return None
    prior = "\n".join(f"- {n}" for n in prior_notes[:3]) or "(none yet)"
    prompt = f"""You are the portfolio analyst for a public $100K momentum-investing experiment at stonkbot.ai. Write today's short closing note for a retail-investor audience.

Voice (this matters most): casual, conversational, and genuinely human. Write like you're texting a smart friend after the market closes — short sentences, contractions, one plain observation up front. Avoid analyst stiffness. Do not start with the date, "As of today", "The portfolio", "It is worth noting", or "Overall". No emojis, no hashtags.

How the strategy works (never name indicators): we keep a leaderboard of 25 stocks ranked by momentum; we buy a name once it reaches the top 8, we keep holding until one falls past 12, and we review monthly. The book holds 10 names.

Today's facts ({facts['label']} close):
- Book: {facts['n_held']} names, equity ${facts['equity_k']}, cash {facts['cash_pct']}%, market regime: {facts['gate_txt']}
- Leaderboard moves: {facts['movers'] or 'none — every name held its position'}
- Boundary events: {facts['boundaries'] or 'none'}
- Trades executed today: {facts['trades'] or 'none'}

Rules:
- 2-4 sentences. Lead with the one thing that actually moved or mattered today.
- Plain language only. Never use: {', '.join(BANNED_TOKENS)}. Talk about the leaderboard, momentum, pace, earning a spot, the exit line.
- If nothing happened, say so plainly — honesty over drama. Quiet days are the strategy working.
- Mention specific tickers when they moved or sit near a decision line; skip the rest.
- Do not reuse openings or phrasing from recent notes:
{prior}

Return JSON: {{"note": "..."}}"""
    try:
        resp = requests.post(
            LLM_BASE + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.7, "max_tokens": 6000, "response_format": {"type": "json_object"}},
            timeout=300,
        )
        if resp.status_code != 200:
            print(f"[WARN] day-note LLM HTTP {resp.status_code}: {resp.text[:160]}", file=sys.stderr)
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        note = (json.loads(m.group(0)).get("note") or "").strip() if m else ""
        low = note.lower()
        if not (60 <= len(note) <= 600):
            return None
        if any(tok in low for tok in BANNED_TOKENS):
            print("[WARN] day-note LLM used banned jargon; falling back", file=sys.stderr)
            return None
        return note
    except Exception as exc:
        print(f"[WARN] day-note LLM failed: {exc}", file=sys.stderr)
        return None

ET = timezone(timedelta(hours=-4))  # display only; et_date comes from data files


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default if default is not None else {}


def atomic_write(path: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o644)
    try:
        os.chown(path, 999, 999)  # stonkai
    except PermissionError:
        pass


def write_diary(note_text: str, today: str, now_iso: str, n_trades: int,
                equity: float, cash_pct: float) -> None:
    """The Bot Diary card on thinking.html — same analyst note as the stream
    digest. New era only: legacy-voice entries (no era flag) are dropped."""
    diary = load_json(DIARY_WEB, default={})
    keep = [e for e in diary.get("entries", [])
            if e.get("era") == ERA and e.get("date") != today]
    entry = {
        "date": today,
        "generated_at": now_iso,
        "era": ERA,
        "body": note_text,
        "stats": {
            "trades": n_trades,
            "pv": round(equity) if equity else None,
            "cash_pct": round(cash_pct, 1),
        },
    }
    payload = {"entries": [entry] + keep[:59]}
    atomic_write(DIARY_REPO, payload)
    atomic_write(DIARY_WEB, payload)


def et_date_of(ts: str) -> str:
    """UTC ISO -> ET calendar date."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(ET).date().isoformat()
    except Exception:
        return ts[:10]


def main() -> None:
    wl_doc = load_json(WATCHLIST)
    state = load_json(STATE)
    signal = load_json(SIGNAL)
    watchlist = wl_doc.get("watchlist", [])
    if not watchlist:
        print("[thinking-sleeve] no watchlist data; skipping")
        return

    today = wl_doc.get("date") or signal.get("date") or ""
    now_iso = datetime.now(timezone.utc).isoformat()

    stream = load_json(OUT_REPO, default={})
    meta = stream.get("meta", {})
    if meta.get("era") != ERA:
        entries = []  # fresh start: legacy intraday backlog cleared
        meta = {"era": ERA, "last_gate": None}
    else:
        entries = stream.get("entries", [])

    existing_ids = {e.get("id") for e in entries}
    new_entries = []

    def add(entry_id: str, type_: str, text: str, symbol=None, ts=None):
        if entry_id in existing_ids:
            return
        new_entries.append({
            "id": entry_id,
            "ts": ts or now_iso,
            "et_date": et_date_of(ts) if ts else today,
            "type": type_,
            **({"symbol": symbol} if symbol else {}),
            "text": text,
        })

    by_sym = {i["symbol"]: i for i in watchlist if i.get("symbol")}
    boundary_facts: list[str] = []

    # ---- boundary transitions -------------------------------------------------
    for i in watchlist:
        sym, rank, prev = i.get("symbol"), i.get("rank"), i.get("prev_rank")
        held = i.get("buy_status") == "hold"
        if not sym or not rank or prev is None or prev == rank:
            continue
        d = f"{today}-{sym}"
        if held and prev <= TOP_N < rank <= EXIT_LINE:
            txt = (f"{sym} slipped into the exit buffer at #{rank} (was #{prev}). "
                   f"Held names leave the basket if they fall past #{EXIT_LINE}.")
            boundary_facts.append(f"{sym} (held) slipped to #{rank}, inside the exit buffer")
            add(f"boundary-buffer-{d}", "boundary", txt, sym)
        elif held and rank > EXIT_LINE and prev <= EXIT_LINE:
            txt = (f"{sym} crossed the exit line at #{rank} (was #{prev}). "
                   f"It leaves the basket at the next execution.")
            boundary_facts.append(f"{sym} (held) crossed the exit line to #{rank}")
            add(f"boundary-exit-{d}", "boundary", txt, sym)
        elif not held and prev > BUY_LINE >= rank:
            txt = (f"{sym} entered the buy zone at #{rank} (was #{prev}) — "
                   f"qualifies for entry at the next review.")
            boundary_facts.append(f"{sym} reached #{rank}, inside the buy zone")
            add(f"boundary-buyzone-{d}", "boundary", txt, sym)
        elif not held and prev <= BUY_LINE < rank:
            txt = f"{sym} left the buy zone (#{prev} → #{rank})."
            boundary_facts.append(f"{sym} left the buy zone, now #{rank}")
            add(f"boundary-buyzone-out-{d}", "boundary", txt, sym)
        elif not held and prev > TOP_N >= rank:
            txt = (f"{sym} entered the top 10 at #{rank} (was #{prev}) — "
                   f"the buy line is #{BUY_LINE}.")
            boundary_facts.append(f"{sym} moved into the top 10 at #{rank} (buy line is #{BUY_LINE})")
            add(f"boundary-top10-{d}", "boundary", txt, sym)
        elif not held and prev <= TOP_N < rank:
            txt = f"{sym} dropped out of the top 10 (#{prev} → #{rank})."
            boundary_facts.append(f"{sym} dropped out of the top 10 to #{rank}")
            add(f"boundary-top10-out-{d}", "boundary", txt, sym)

    # ---- decisions (real executions, grouped by ET day) -----------------------
    trades_doc = load_json(TRADES, default=[])
    trades = trades_doc if isinstance(trades_doc, list) else trades_doc.get("trades", [])
    by_day: dict[str, dict] = {}
    for t in trades:
        ts = t.get("timestamp") or t.get("ts") or ""
        if not ts:
            continue
        day = et_date_of(ts)
        if day < SLEEVE_ERA_START:
            continue  # legacy intraday era — not part of the sleeve story
        slot = by_day.setdefault(day, {"BUY": [], "SELL": [], "first_ts": ts})
        act = str(t.get("action", "")).upper()
        if act in ("BUY", "SELL"):
            sym = str(t.get("symbol", "?"))
            if sym not in slot[act]:
                slot[act].append(sym)
            slot["first_ts"] = min(slot["first_ts"], ts)
    for day, grp in sorted(by_day.items()):
        if not grp["BUY"] and not grp["SELL"]:
            continue
        bits = []
        if grp["SELL"]:
            bits.append("sold " + ", ".join(grp["SELL"]))
        if grp["BUY"]:
            bits.append("bought " + ", ".join(grp["BUY"]))
        n_held = len([s for s in state.get("holdings", {}) if s != "CASH"])
        add(f"decision-{day}", "decision",
            f"Executed: {'; '.join(bits)}. Book stands at {n_held} names.",
            ts=grp["first_ts"])

    # ---- gate flips -----------------------------------------------------------
    gate = state.get("gate") or signal.get("gate")
    if gate:
        if meta.get("last_gate") and meta["last_gate"] != gate:
            direction = "risk-on" if gate == "QQQ" else f"defensive ({gate})"
            add(f"gate-{today}", "gate",
                f"DM-6 gate flipped to {direction}. "
                + ("The book can stay fully invested." if gate == "QQQ"
                   else "New buys pause; the book de-risks at the next execution."))
        meta["last_gate"] = gate

    # ---- day note -------------------------------------------------------------
    movers = []
    for i in watchlist:
        sym, rank, prev = i.get("symbol"), i.get("rank"), i.get("prev_rank")
        if not sym or not rank or prev is None or prev == rank:
            continue
        delta = prev - rank  # positive = climbed
        movers.append((abs(delta), delta, sym, rank, prev, i.get("buy_status") == "hold"))
    movers.sort(reverse=True)

    mover_bits = []
    for _, delta, sym, rank, prev, held in movers[:4]:
        verb = "climbed" if delta > 0 else "slipped"
        bit = f"{sym} {verb} {prev}→{rank}"
        if held and rank >= TOP_N + 1:
            spots = EXIT_LINE - rank + 1
            bit += f" — {spots} spot{'s' if spots != 1 else ''} from the exit edge"
        elif not held and BUY_LINE < rank <= EXIT_LINE:
            bit += f", {rank - BUY_LINE} spot{'s' if rank - BUY_LINE != 1 else ''} from the buy line"
        elif not held and rank <= BUY_LINE:
            bit += " — inside the buy line"
        mover_bits.append(bit)

    n_held = len([s for s in state.get("holdings", {}) if s != "CASH"])
    cash = state.get("cash") or 0
    equity = state.get("equity") or 0
    cash_pct = (cash / equity * 100) if equity else 0
    gate_txt = "risk-on" if gate == "QQQ" else (f"defensive ({gate})" if gate else "—")

    try:
        label = datetime.fromisoformat(today).strftime("%b %-d")
    except Exception:
        label = today
    parts = [f"{label} close: "]
    parts.append((". ".join(mover_bits) + ". ") if mover_bits
                 else "Ranks unchanged across the 25-name universe. ")
    parts.append(f"Book: {n_held} names, cash {cash_pct:.1f}%, gate {gate_txt}. ")
    if signal.get("signal"):
        inc, out = signal.get("incoming") or [], signal.get("outgoing") or []
        act = []
        if out:
            act.append("sell " + ", ".join(out))
        if inc:
            act.append("buy " + ", ".join(inc))
        parts.append("Action queued for next execution: " + "; ".join(act) + ".")
    else:
        parts.append("No action: nothing crossed a decision boundary.")
    movers_txt = "; ".join(mover_bits)
    trades_today = by_day.get(today)
    trades_txt = ""
    if trades_today:
        tt = []
        if trades_today["SELL"]:
            tt.append("sold " + ", ".join(trades_today["SELL"]))
        if trades_today["BUY"]:
            tt.append("bought " + ", ".join(trades_today["BUY"]))
        trades_txt = "; ".join(tt)

    det_text = "".join(parts)
    existing_digest = next((e for e in entries if e.get("id") == f"digest-{today}"), None)
    if existing_digest:
        # Already narrated today: reuse the same note for the diary so the
        # diary card and the stream digest stay identical (and skip the LLM call).
        note_text = existing_digest.get("text", det_text)
        print("[thinking-sleeve] day note: reused existing digest")
    else:
        prior_notes = [e.get("text", "") for e in entries if e.get("type") == "digest"]
        facts = {
            "label": label, "n_held": n_held, "cash_pct": f"{cash_pct:.1f}",
            "equity_k": f"{equity/1000:.1f}K" if equity else "—", "gate_txt": gate_txt,
            "movers": movers_txt, "boundaries": "; ".join(boundary_facts), "trades": trades_txt,
        }
        llm_text = llm_day_note(facts, prior_notes)
        note_text = llm_text or det_text
        if llm_text:
            add(f"digest-{today}", "digest", llm_text)
            for e in new_entries:
                if e["id"] == f"digest-{today}":
                    e["rule_text"] = det_text  # audit: keep the deterministic version
            print("[thinking-sleeve] day note: LLM voice")
        else:
            add(f"digest-{today}", "digest", det_text)
            print("[thinking-sleeve] day note: deterministic fallback")

    n_trades_today = len(trades_today["BUY"]) + len(trades_today["SELL"]) if trades_today else 0
    write_diary(note_text, today, now_iso, n_trades_today, equity, cash_pct)

    # ---- write ----------------------------------------------------------------
    entries = sorted(entries + new_entries, key=lambda e: e.get("ts", ""), reverse=True)[:MAX_ENTRIES]
    payload = {
        "generated_at": now_iso,
        "generated_at_ts": int(datetime.now(timezone.utc).timestamp()),
        "meta": meta,
        "entries": entries,
    }
    atomic_write(OUT_REPO, payload)
    atomic_write(OUT_WEB, payload)
    print(f"[thinking-sleeve] {len(new_entries)} new entries, {len(entries)} total, era {ERA}")


if __name__ == "__main__":
    main()
