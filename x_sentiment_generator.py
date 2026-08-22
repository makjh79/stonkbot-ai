#!/usr/bin/env python3
"""
X Sentiment Generator for StonkBOT holding popups.
Runs Mon–Sat after US close (00:30 HKT), queries xAI X Search
for each current holding, writes x_sentiment.json to the web root.
No trading decisions use this data. Site content only.

Output format per symbol:
  {
    "symbol": "AMZN",
    "mood": "Positive",
    "mood_color": "#22c55e",
    "label": "Positive",
    "one_liner": "Bulls cheer AWS reacceleration; bears warn AI spend may not pay off.",
    "threads": "Bulls: AWS reacceleration · Bears: AI capex ROI",
    "text": "Bulls cheer AWS reacceleration; bears warn AI spend may not pay off."
  }
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional

BASE_DIR = "/opt/stonk-ai"
WEB_DIR = "/var/www/hedge-fund-website"
XAI_BASE_URL = "https://api.x.ai/v1"
MODEL = "grok-4.20-0309-non-reasoning"

PROMPT = """Search X for what people are saying about ${symbol} right now.

Return ONLY compact JSON in this exact shape:
{
  "mood": "Positive|Mixed|Negative|Neutral",
  "one_liner": "One plain-English sentence, max 16 words, human voice. Use active verbs: bulls are bidding/cheering, bears are grumbling/warning, the crowd is split. No clichés, no war/battle language, no filler. Example: 'Azure +43% has bulls bidding; bears grumble AI capex is eating cash flow.'",
  "threads": "Bulls: <specific bullish thread> · Bears: <specific bearish/cautious thread>"
}

Rules for threads:
- Only include the threads field if you can extract BOTH a real bullish thread and a real bearish/cautious thread from X.
- Do NOT use placeholders like 'X' or 'Y'. Use real specific themes (e.g., 'AWS 37% growth', 'high PE', 'buyout premium', 'earnings risk').
- If one side is missing or unclear, set threads to an empty string.

Do not include "X says", markdown, or explanation outside the JSON."""

MOOD_COLORS = {
    "Positive": "#22c55e",
    "Mixed": "#f59e0b",
    "Negative": "#ef4444",
    "Neutral": "#7a8098",
}


def _load_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _get_xai_key() -> str:
    secret_path = os.path.join(BASE_DIR, ".secrets", "xai.key")
    try:
        with open(secret_path, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    except Exception:
        pass
    cfg = _load_json("/root/.openclaw/openclaw.json") or {}
    key = cfg.get("env", {}).get("XAI_API_KEY", "")
    if not key:
        key = cfg.get("models", {}).get("providers", {}).get("xai", {}).get("apiKey", "")
    if not key:
        key = os.getenv("XAI_API_KEY", "")
    if not key:
        raise RuntimeError("XAI_API_KEY not found in .secrets/xai.key, openclaw.json, or env")
    return key


def _fetch_portfolio_symbols() -> List[str]:
    data = _load_json(os.path.join(WEB_DIR, "portfolio_data.json"))
    if not data:
        data = _load_json(os.path.join(BASE_DIR, "portfolio_data.json"))
    if not data:
        raise RuntimeError("Could not load portfolio_data.json")
    symbols = []
    for p in data.get("positions", []):
        qty = p.get("qty", 0)
        sym = p.get("symbol", "")
        if sym and (isinstance(qty, (int, float)) and qty > 0):
            symbols.append(sym)
    return sorted(set(symbols))


def _extract_json(text: str) -> Optional[dict]:
    """Find and parse the first JSON object in the response text."""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except Exception:
            pass
    # sometimes markdown code fences
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r"(\{.*?\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


def _query_x_sentiment(symbol: str, api_key: str) -> Dict:
    payload = {
        "model": MODEL,
        "input": [
            {"role": "user", "content": PROMPT.replace("${symbol}", symbol)}
        ],
        "tools": [{"type": "x_search"}],
    }
    start = time.time()
    try:
        r = requests.post(
            f"{XAI_BASE_URL}/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return {
            "symbol": symbol,
            "mood": "Neutral",
            "mood_color": MOOD_COLORS["Neutral"],
            "one_liner": "",
            "text": "",
            "error": str(e),
            "cost_usd": 0.0,
            "tool_calls": 0,
        }

    texts = []
    tool_calls = 0
    for item in d.get("output", []):
        t = item.get("type", "")
        if t == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    texts.append(c.get("text", ""))
        elif t not in ("reasoning",):
            tool_calls += 1

    raw_text = " ".join(texts).strip()
    parsed = _extract_json(raw_text) or {}
    mood = (parsed.get("mood") or "Neutral").strip().title()
    if mood not in MOOD_COLORS:
        mood = "Neutral"
    one_liner = (parsed.get("one_liner") or "").strip().strip('"').strip("'")
    threads = (parsed.get("threads") or "").strip().strip('"').strip("'")
    # drop if either half is empty or malformed
    # drop placeholder / malformed thread lines
    if threads and ('X' in threads.split('·')[0] or 'Y' in threads.split('·')[1] or 'specific' in threads.lower() or '<' in threads):
        threads = ""
    if threads:
        halves = re.split(r"\s*·\s*", threads)
        if len(halves) != 2 or not halves[0].strip().lower().startswith("bulls:") or not halves[1].strip().lower().startswith("bears:") or not halves[0].split(":", 1)[1].strip() or not halves[1].split(":", 1)[1].strip():
            threads = ""
    if not one_liner and raw_text:
        # fallback: use first sentence, stripped
        one_liner = raw_text.split(".")[0].strip()
        one_liner = re.sub(r"\*\*X says:\*\*\s*", "", one_liner)
        one_liner = one_liner[:140]

    label = "Quiet" if mood == "Neutral" else mood
    composed = f"{one_liner}" if one_liner else ""

    u = d.get("usage", {})
    cost = tool_calls * 0.005 + u.get("input_tokens", 0) * 1.25e-6 + u.get("output_tokens", 0) * 2.5e-6
    return {
        "symbol": symbol,
        "mood": mood,
        "mood_color": MOOD_COLORS[mood],
        "label": label,
        "one_liner": one_liner,
        "threads": threads,
        "text": composed,
        "tool_calls": tool_calls,
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cost_usd": round(cost, 6),
        "elapsed_s": round(time.time() - start, 2),
        "model": MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _atomic_write_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    os.chmod(path, 0o644)
    os.chmod(path, 0o644)


def main(force: bool = False) -> int:
    now = datetime.now(timezone.utc)
    if now.weekday() == 6 and not force:  # skip Sunday only (timer runs Mon–Sat; 2026-08-23)
        print("Skipping: Sunday")
        return 0

    api_key = _get_xai_key()
    symbols = _fetch_portfolio_symbols()
    if not symbols:
        print("No holdings found; skipping")
        return 0

    results: Dict[str, dict] = {}
    total_cost = 0.0
    for sym in symbols:
        print(f"Querying X sentiment for {sym} ...")
        res = _query_x_sentiment(sym, api_key)
        results[sym] = res
        total_cost += res.get("cost_usd", 0.0)
        time.sleep(0.5)

    payload = {
        "generated_at": now.isoformat(),
        "model": MODEL,
        "symbols": symbols,
        "sentiments": results,
        "total_cost_usd": round(total_cost, 6),
    }

    # Fail-open: if most queries errored, do not overwrite the previous file with
    # a fresh-but-empty result. This keeps stale-but-valid data visible and lets
    # the monitor flag the auth/API failure instead of silently degrading.
    error_count = sum(1 for s in results.values() if s.get("error"))
    if error_count >= len(symbols) // 2:
        print(
            f"Refusing to overwrite x_sentiment.json: {error_count}/{len(symbols)} "
            f"queries failed (total cost ${total_cost:.4f})"
        )
        return 2

    # Fail-open: if most queries errored, do not overwrite the previous file with
    # a fresh-but-empty result. This keeps stale-but-valid data visible and lets
    # the monitor flag the auth/API failure instead of silently degrading.
    error_count = sum(1 for s in results.values() if s.get("error"))
    if error_count >= len(symbols) // 2:
        print(
            f"Refusing to overwrite x_sentiment.json: {error_count}/{len(symbols)} "
            f"queries failed (total cost ${total_cost:.4f})"
        )
        return 2

    _atomic_write_json(os.path.join(WEB_DIR, "x_sentiment.json"), payload)
    _atomic_write_json(os.path.join(BASE_DIR, "x_sentiment.json"), payload)
    print(f"Wrote x_sentiment.json for {len(symbols)} symbols; total cost ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(force="--force" in sys.argv))
