#!/usr/bin/env python3
"""
Generate LLM-driven popup narratives for StonkBOT holdings and watchlist.
Batched via openclaw infer; designed for VPS use with OpenRouter Kimi K2.6.
"""
from __future__ import annotations

import json
from stonk_utils import atomic_write_json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Import canonical confirmation counter
sys.path.insert(0, str(Path(__file__).resolve().parent))
from signal_rules import compute_confirmation_count, active_confirmation_labels, hard_confirmation_count, is_entry_eligible, CONFIRMATION_CHIPS

# Paths — env overrides for portability
BOT_DIR = Path(os.environ.get("STONKBOT_BOT_DIR", Path(__file__).resolve().parent))
DATA_DIR = Path(os.environ.get("STONKBOT_DATA_DIR", BOT_DIR))
WEB_DIR = Path(os.environ.get("STONKBOT_WEB_DIR", "/var/www/hedge-fund-website"))
SIGNALS_FILE = Path(os.environ.get("STONKBOT_SIGNALS_FILE", DATA_DIR / "signals.json"))
PORTFOLIO_FILE = Path(os.environ.get("STONKBOT_PORTFOLIO_FILE", DATA_DIR / "portfolio_data.json"))
WATCHLIST_FILE = Path(os.environ.get("STONKBOT_WATCHLIST_FILE", DATA_DIR / "ai_watchlist_live.json"))
POPUP_NARRATIVES_FILE = Path(os.environ.get("STONKBOT_POPUP_NARRATIVES_FILE", WEB_DIR / "popup_narratives.json"))
WATCHLIST_NARRATIVES_FILE = Path(os.environ.get("STONKBOT_WATCHLIST_NARRATIVES_FILE", WEB_DIR / "watchlist_narratives_llm.json"))
_COMPANY_KNOWLEDGE_FILE = Path(os.environ.get("STONKBOT_KNOWLEDGE_FILE", BOT_DIR / "company_knowledge.json"))

# Model selection
DEFAULT_MODEL = os.environ.get("STONKBOT_NARRATIVE_MODEL", "ollama/kimi-k2.7-code:cloud")
LLM_TIMEOUT = int(os.environ.get("STONKBOT_NARRATIVE_TIMEOUT", "180"))
BATCH_SIZE = int(os.environ.get("STONKBOT_NARRATIVE_BATCH_SIZE", "6"))


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Could not load {path}: {exc}", file=sys.stderr)
        return {}


def save_json(path: Path, data: dict) -> None:
    atomic_write_json(path, data)


def iv_scalar(iv: Any) -> float | None:
    if iv is None:
        return None
    if isinstance(iv, dict):
        return iv.get("iv_30d") or iv.get("options_implied_vol") or None
    try:
        return float(iv)
    except (TypeError, ValueError):
        return None


_COMPANY_NOTES: dict[str, str] = {}
_COMPANY_RISKS: dict[str, str] = {}


def _load_company_knowledge() -> None:
    global _COMPANY_NOTES, _COMPANY_RISKS
    if _COMPANY_KNOWLEDGE_FILE.exists():
        data = json.loads(_COMPANY_KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        for sym, entry in data.items():
            _COMPANY_NOTES[sym] = entry.get("note", "")
            _COMPANY_RISKS[sym] = entry.get("risk", "")


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


def _load_openrouter_key() -> str | None:
    auth_file = Path(os.environ.get("HOME", "/home/stonkai")) / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        return data.get("profiles", {}).get("openrouter:default", {}).get("key")
    except Exception:
        return None


def llm_generate_json(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Call LLM with JSON output. Uses direct OpenRouter API for openrouter/* models
    to avoid openclaw max_tokens/context-length defaults that exceed provider limits."""

    # Ollama path with retry/backoff to handle Ollama Cloud 429 rate limits
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

    # Fallback to openclaw for other providers
    cmd = [
        "timeout", "-s", "KILL", str(LLM_TIMEOUT),
        "openclaw",
        "infer", "model", "run",
        "--model", model,
        "--json",
        "--prompt", prompt,
    ]
    env = os.environ.copy()
    env["OPENCLAW_QUIET"] = "1"
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=LLM_TIMEOUT + 15, env=env)
    if result.returncode == 124:
        raise RuntimeError(f"openclaw infer killed after {LLM_TIMEOUT}s timeout")
    if result.returncode != 0:
        stderr = result.stderr.strip() or "(no stderr)"
        raise RuntimeError(f"openclaw infer failed ({result.returncode}): {stderr}")
    parsed = json.loads(result.stdout)
    outputs = parsed.get("outputs", [{}])
    text = outputs[0].get("text", "") if outputs else ""
    return _extract_json(text)


def _lookup_company(symbol: str) -> tuple[str, str]:
    if symbol in _COMPANY_NOTES and symbol in _COMPANY_RISKS:
        return _COMPANY_NOTES[symbol], _COMPANY_RISKS[symbol]

    prompt = f"""Briefly describe the publicly traded company {symbol} and list 2-3 concise business risks.
Output ONLY a JSON object with keys: note (one sentence on what the company does), risk (one sentence, comma-separated risks).
No markdown, no commentary. Example:
{{"note": "Semiconductor equipment supplier to chip fabs.", "risk": "Capex cycle downturn, China export restrictions, customer concentration"}}"""
    try:
        result = llm_generate_json(prompt, model=DEFAULT_MODEL)
        note = str(result.get("note", "") or "").strip()
        risk = str(result.get("risk", "") or "").strip()
    except Exception as exc:
        print(f"[WARN] LLM lookup failed for {symbol}: {exc}", file=sys.stderr)
        note, risk = "", ""

    if not note:
        note = "Publicly traded company. No detailed note available."
    if not risk:
        risk = "Standard market, execution, and business-model risk."

    _COMPANY_NOTES[symbol] = note
    _COMPANY_RISKS[symbol] = risk

    try:
        cache = json.loads(_COMPANY_KNOWLEDGE_FILE.read_text(encoding="utf-8")) if _COMPANY_KNOWLEDGE_FILE.exists() else {}
        cache[symbol] = {"note": note, "risk": risk}
        _COMPANY_KNOWLEDGE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[WARN] Could not cache {symbol} knowledge: {exc}", file=sys.stderr)

    return note, risk




_EARNINGS_RE = re.compile(
    r"\b(earnings|EPS|beat estimates|missed estimates|guidance (upgrade|cut)|revenue surge|profit surge|sales beat)\b",
    re.IGNORECASE,
)


def _get_confirmations(signal: dict) -> tuple[dict, int]:
    """Return canonical confirmations and count. No PEAD inference, pure data only."""
    conf = dict(signal.get("confirmations", {}))
    count = compute_confirmation_count(conf)
    return conf, count


def _factor_chip_summary(conf: dict) -> tuple[int, int, str]:
    """Return (active, total, label_string) matching the popup factor chips."""
    labels = active_confirmation_labels(conf)
    return len(labels), len(CONFIRMATION_CHIPS), ", ".join(labels)


def _entry_gate_reason(signal: dict, conf: dict, active_count: int) -> str:
    """Explain why the symbol is or is not entry-eligible, using the canonical gate."""
    readiness = signal.get("readiness_score", 0) or 0
    above_ema = bool(conf.get("above_ema"))
    hard = hard_confirmation_count(conf)
    eligible = is_entry_eligible(readiness, active_count, above_ema, hard)
    if eligible:
        return "Entry gate is open; waiting on portfolio cash or sizing rules."
    reasons = []
    if not above_ema:
        reasons.append("price is below the 20-day EMA")
    if readiness < 75:
        reasons.append(f"readiness is {readiness:.1f} (needs 75+)")
    if active_count < 5:
        reasons.append(f"only {active_count} active chips (needs 5+)")
    if hard < 1:
        reasons.append(f"no hard confirmations from volume/MACD/intraday/options/relvol (needs 1+)")
    if reasons:
        return "Not entry eligible: " + "; ".join(reasons) + "."
    return "Entry gate is closed due to a rule not captured above."

def _company_note(symbol: str) -> str:
    if symbol not in _COMPANY_NOTES:
        note, _ = _lookup_company(symbol)
    return _COMPANY_NOTES.get(symbol, "Publicly traded company. No detailed note available.")


def _company_risk(symbol: str) -> str:
    if symbol not in _COMPANY_RISKS:
        _, risk = _lookup_company(symbol)
    return _COMPANY_RISKS.get(symbol, "Standard market, execution, and business-model risk.")


_load_company_knowledge()


def _stops_for_symbol(position: dict, signal_data: dict, risk_config: dict) -> dict:
    avg_entry = position.get("avg_entry", 0) or 0
    hard_stop = avg_entry * (1 + risk_config.get("hard_stop_loss_pct", -0.10))
    trailing_stop = avg_entry * (1 + risk_config.get("trailing_stop_pct", -0.10))
    vwap = signal_data.get("daily_vwap")
    return {
        "hard_stop": round(hard_stop, 2),
        "trailing_stop": round(trailing_stop, 2),
        "vwap": round(vwap, 2) if vwap else None,
    }


def _build_holdings_block(symbol: str, position: dict, signal: dict, risk_config: dict) -> str:
    stops = _stops_for_symbol(position, signal, risk_config)
    conf, conf_count = _get_confirmations(signal)
    active_count, total_count, active_labels = _factor_chip_summary(conf)
    entry_gate = _entry_gate_reason(signal, conf, active_count)
    iv = iv_scalar(signal.get("options_implied_vol"))
    news = signal.get("news") or {}
    headline = news.get("alpaca_headline") or news.get("headline") or ""
    return f"""--- SYMBOL: {symbol} ---
COMPANY: {signal.get('company') or symbol}
SECTOR: {signal.get('sector', 'Other')}
TIER: {signal.get('display_tier') or signal.get('tier', 'MONITOR')}
P&L%: {position.get('unrealized_plpc', 0):.2f}% | Price: ${position.get('current', 0):.2f} | Entry: ${position.get('avg_entry', 0):.2f}
Stop: ${stops['hard_stop']:.2f} | Trailing: ${stops['trailing_stop']:.2f} | VWAP: {f"${stops['vwap']:.2f}" if stops.get('vwap') else "n/a"}
Momentum 20d: {signal.get('momentum_20d', 0):.2%} | RSI: {signal.get('rsi14', 0):.1f} | MACD: {'+ve' if conf.get('macd_turning') else '-ve'} | Vol: {'yes' if conf.get('volume_confirmed') else 'no'} | RVOL: {'yes' if conf.get('relvol_confirmed') else 'no'} | EMA: {'above' if conf.get('above_ema') else 'below'} | VWAP: {'above' if conf.get('vwap_confirmed') else 'below'}
Readiness: {signal.get('readiness_score', 0):.1f} | Active Factors: {active_count}/{total_count} ({active_labels})
Entry gate: {entry_gate}
NOTE: Only mention the ACTIVE factors listed above. Do not discuss inactive factors. | Volatility: {signal.get('volatility_20d', 0):.2%} | IV30: {f"{iv*100:.1f}%" if iv else "n/a"}
NOTE: Only mention the ACTIVE factors listed above. Do not discuss inactive factors.
Headline: {headline or 'None'}
Note: {_company_note(symbol)}
Risk: {_company_risk(symbol)}
"""


def _build_watchlist_block(symbol: str, signal: dict, watch: dict) -> str:
    conf, conf_count = _get_confirmations(signal)
    active_count, total_count, active_labels = _factor_chip_summary(conf)
    entry_gate = _entry_gate_reason(signal, conf, active_count)
    iv = iv_scalar(signal.get("options_implied_vol"))
    news = signal.get("news") or {}
    headline = news.get("alpaca_headline") or news.get("headline") or ""
    price = watch.get("price") or signal.get("price", 0)
    return f"""--- SYMBOL: {symbol} ---
COMPANY: {signal.get('company') or watch.get('company') or symbol}
SECTOR: {signal.get('sector') or watch.get('sector', 'Other')}
TIER: {watch.get('display_tier') or watch.get('signal_tier') or signal.get('display_tier') or signal.get('tier', 'MONITOR')} | Entry eligible: {'yes' if watch.get('entry_eligible') or signal.get('entry_eligible') else 'no'}
Price: ${price:.2f} | Readiness: {signal.get('readiness_score', 0):.1f} | Total: {signal.get('total_score', 0):.1f} | Active Factors: {active_count}/{total_count} ({active_labels})
Entry gate: {entry_gate}
NOTE: Only mention the ACTIVE factors listed above. Do not discuss inactive factors.
Momentum 20d: {signal.get('momentum_20d', 0):.2%} | RSI: {signal.get('rsi14', 0):.1f} | MACD: {'+ve' if conf.get('macd_turning') else '-ve'} | Vol: {'yes' if conf.get('volume_confirmed') else 'no'} | RVOL: {'yes' if conf.get('relvol_confirmed') else 'no'} | EMA: {'above' if conf.get('above_ema') else 'below'} | VWAP: {'above' if conf.get('vwap_confirmed') else 'below'}
Volatility: {signal.get('volatility_20d', 0):.2%} | IV30: {f"{iv*100:.1f}%" if iv else "n/a"}
Headline: {headline or 'None'}
Note: {_company_note(symbol)}
Risk: {_company_risk(symbol)}
"""


def _build_holdings_prompt(items: dict[str, dict]) -> str:
    intro = """You are a seasoned, plain-speaking equity trader writing short popup copy for a portfolio tracking app. No jargon, no templates, no repetition.

For EACH holding below, generate these fields. Output ONLY a single JSON object where each TOP-LEVEL KEY is the SYMBOL (e.g. "AAPL") and the value is an object with:
{"whatItIs": "1 sentence", "whyWeOwnIt": "2-4 sentences", "howItsDoing": "1-2 sentences", "catalyst": "1-2 sentences", "risk": "2-3 sentences"}

Example for two symbols:
{"AAPL": {"whatItIs": "Consumer electronics giant...", "whyWeOwnIt": "...", "howItsDoing": "...", "catalyst": "...", "risk": "..."}, "TSLA": {"whatItIs": "EV maker...", ...}}

No markdown, no commentary."""
    blocks = [_build_holdings_block(sym, ctx["position"], ctx["signal"], ctx["risk_config"]) for sym, ctx in items.items()]
    return intro + "\n\n" + "\n\n".join(blocks)


def _build_watchlist_prompt(items: dict[str, dict]) -> str:
    intro = """You are a seasoned, plain-speaking equity trader writing short popup copy for a watchlist tracking app. No jargon, no templates, no repetition.

For EACH watchlist symbol below, generate these fields. Output ONLY a single JSON object where each TOP-LEVEL KEY is the SYMBOL (e.g. "AAPL") and the value is an object with:
{"whatItIs": "1 sentence", "whyOnWatchlist": "2-3 sentences", "whatTriggersBuy": "1-2 sentences", "catalyst": "1-2 sentences", "risk": "2-3 sentences"}

Rules:
- whyOnWatchlist MUST use the exact "Active Factors: X/15" count and the exact list of active labels provided.
- whatTriggersBuy MUST reflect the "Entry gate" line: if not entry eligible, explicitly state which gate is blocking (e.g. missing hard confirmation from volume/MACD/intraday/options/relvol, or readiness below 75).
- DO NOT mention inactive factors or claim more active factors than listed.
- DO NOT say "entry eligible" if the prompt says "Entry eligible: no".
- Keep numbers consistent with the prompt.

Example for two symbols:
{"AAPL": {"whatItIs": "Consumer electronics giant...", "whyOnWatchlist": "...", "whatTriggersBuy": "...", "catalyst": "...", "risk": "..."}, "TSLA": {"whatItIs": "EV maker...", ...}}

No markdown, no commentary."""
    blocks = [_build_watchlist_block(sym, ctx["signal"], ctx["watchlist"]) for sym, ctx in items.items()]
    return intro + "\n\n" + "\n\n".join(blocks)


def _chunk_dict(d: dict[str, Any], size: int) -> list[dict[str, Any]]:
    items = list(d.items())
    return [dict(items[i : i + size]) for i in range(0, len(items), size)]


WATCHLIST_FIELDS = {"whatItIs", "whyOnWatchlist", "whatTriggersBuy", "catalyst", "risk"}
HOLDINGS_FIELDS = {"whatItIs", "whyWeOwnIt", "howItsDoing", "catalyst", "risk"}


def _normalize_holdings_result(result: Any, chunk_symbols: list[str]) -> dict[str, dict]:
    """Ensure result is {symbol: {fields}}. Handle common malformed outputs."""
    if not isinstance(result, dict):
        return {}
    # If the LLM returned flat field keys and there was exactly one symbol, wrap it.
    if HOLDINGS_FIELDS.issubset(set(result.keys())) and len(chunk_symbols) == 1:
        return {chunk_symbols[0]: result}
    # If it returned {symbol: {fields}} correctly, filter out non-dict values
    normalized: dict[str, dict] = {}
    for sym, data in result.items():
        if isinstance(data, dict) and HOLDINGS_FIELDS.issubset(set(data.keys())):
            normalized[sym] = data
    return normalized


def _normalize_watchlist_result(result: Any, chunk_symbols: list[str]) -> dict[str, dict]:
    """Ensure result is {symbol: {fields}}. Handle common malformed outputs."""
    if not isinstance(result, dict):
        return {}
    if WATCHLIST_FIELDS.issubset(set(result.keys())) and len(chunk_symbols) == 1:
        return {chunk_symbols[0]: result}
    normalized: dict[str, dict] = {}
    for sym, data in result.items():
        if isinstance(data, dict) and WATCHLIST_FIELDS.issubset(set(data.keys())):
            normalized[sym] = data
    return normalized


def generate_holdings_narratives(holdings: dict[str, dict], chunk_size: int = None) -> dict:
    chunk_size = chunk_size or BATCH_SIZE
    if DEFAULT_MODEL.startswith("ollama/"):
        chunk_size = 1
    results: dict[str, dict] = {}
    chunks = _chunk_dict(holdings, chunk_size)
    for idx, chunk in enumerate(chunks, 1):
        print(f"[LLM] Holdings batch {idx}/{len(chunks)} ({len(chunk)} symbols)...", file=sys.stderr)
        try:
            result = llm_generate_json(_build_holdings_prompt(chunk))
            chunk_symbols = list(chunk.keys())
            normalized = _normalize_holdings_result(result, chunk_symbols)
            if normalized:
                results.update(normalized)
            else:
                print(f"[WARN] Holdings batch {idx} returned no usable symbol-keyed narratives", file=sys.stderr)
        except Exception as exc:
            print(f"[ERROR] Holdings batch {idx} failed: {exc}", file=sys.stderr)
        if DEFAULT_MODEL.startswith("ollama/"):
            time.sleep(1)
    return results


def generate_watchlist_narratives(items: dict[str, dict], chunk_size: int = None) -> dict:
    chunk_size = chunk_size or BATCH_SIZE
    if DEFAULT_MODEL.startswith("ollama/"):
        chunk_size = 1
    results: dict[str, dict] = {}
    chunks = _chunk_dict(items, chunk_size)
    for idx, chunk in enumerate(chunks, 1):
        print(f"[LLM] Watchlist batch {idx}/{len(chunks)} ({len(chunk)} symbols)...", file=sys.stderr)
        try:
            result = llm_generate_json(_build_watchlist_prompt(chunk))
            chunk_symbols = list(chunk.keys())
            normalized = _normalize_watchlist_result(result, chunk_symbols)
            if normalized:
                results.update(normalized)
            else:
                print(f"[WARN] Watchlist batch {idx} returned no usable symbol-keyed narratives", file=sys.stderr)
        except Exception as exc:
            print(f"[ERROR] Watchlist batch {idx} failed: {exc}", file=sys.stderr)
        if DEFAULT_MODEL.startswith("ollama/"):
            time.sleep(1)
    return results


def load_contexts() -> tuple[dict, list, dict, dict]:
    signals_data = load_json(SIGNALS_FILE)
    if isinstance(signals_data, list):
        signals = signals_data
    else:
        signals = signals_data.get("signals", []) or signals_data.get("data", {}).get("signals", [])
    signals_map = {s["symbol"]: s for s in signals if isinstance(s, dict) and "symbol" in s}
    portfolio = load_json(PORTFOLIO_FILE)
    watchlist = load_json(WATCHLIST_FILE).get("prices", {})
    risk_config = load_json(BOT_DIR / "risk_config.json") or {
        "hard_stop_loss_pct": -0.10,
        "trailing_stop_pct": -0.10,
    }
    return signals_map, portfolio.get("positions", []), watchlist, risk_config


def main() -> None:
    global BATCH_SIZE
    signals_map, positions, watchlist, risk_config = load_contexts()
    if DEFAULT_MODEL.startswith("ollama/"):
        BATCH_SIZE = 1
    print(f"[LLM] Loaded {len(signals_map)} signals, {len(positions)} positions, {len(watchlist)} watchlist symbols.", file=sys.stderr)
    print(f"[LLM] Using model {DEFAULT_MODEL} with timeout {LLM_TIMEOUT}s, batch size {BATCH_SIZE}", file=sys.stderr)

    holdings_contexts = {
        p["symbol"]: {"position": p, "signal": signals_map.get(p["symbol"], {}), "risk_config": risk_config}
        for p in positions if p.get("symbol") and signals_map.get(p["symbol"])
    }
    watchlist_contexts = {
        sym: {"watchlist": w, "signal": signals_map.get(sym, {})}
        for sym, w in watchlist.items() if signals_map.get(sym)
    }

    holdings_llm = generate_holdings_narratives(holdings_contexts)
    watchlist_llm = generate_watchlist_narratives(watchlist_contexts)

    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_json(POPUP_NARRATIVES_FILE, {"timestamp": ts, "holdings": holdings_llm})
    save_json(WATCHLIST_NARRATIVES_FILE, {"timestamp": ts, "narratives": watchlist_llm})

    print(f"[DONE] Saved {len(holdings_llm)} holdings, {len(watchlist_llm)} watchlist narratives")


if __name__ == "__main__":
    main()
