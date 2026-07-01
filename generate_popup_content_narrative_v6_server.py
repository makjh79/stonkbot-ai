#!/usr/bin/env python3
"""
VPS-side v6 narrative merge.
Runs every 2 minutes via cron/timer.
1. Generates fresh base popup files using the installed v2 wrapper (data-driven).
2. Overlays LLM-generated narrative fields uploaded from the Mac.
3. Writes merged files back to /var/www/hedge-fund-website/.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOT_DIR = Path("/opt/stonk-ai")
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)

WEB_DIR = Path("/var/www/hedge-fund-website")
POPUP_FILE = WEB_DIR / "popup_content.json"
WATCHLIST_FILE = WEB_DIR / "watchlist_narratives.json"
LLM_HOLDINGS_FILE = WEB_DIR / "popup_narratives.json"
LLM_WATCHLIST_FILE = WEB_DIR / "watchlist_narratives_llm.json"
WATCHLIST_LIVE_FILE = WEB_DIR / "ai_watchlist_live.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Could not load {path}: {exc}", file=sys.stderr)
        return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_base_generator() -> bool:
    """Run the installed v2 wrapper to refresh data-driven popup files."""
    try:
        import generate_popup_content_narrative_v2 as v2
        v2.generate_popup_content()
        print("[INFO] Base v2 generator completed")
        return True
    except Exception as exc:
        print(f"[ERROR] Base v2 generator failed: {exc}", file=sys.stderr)
        return False


def merge_holdings_narratives(popup_content: dict, llm_narratives: dict) -> dict:
    narrative_fields = {"whatItIs", "whyWeOwnIt", "howItsDoing", "catalyst", "risk"}
    holdings = popup_content.setdefault("holdings", {})
    for symbol, fields in (llm_narratives.get("holdings") or {}).items():
        if symbol not in holdings:
            continue
        for field in narrative_fields:
            val = fields.get(field)
            if val and isinstance(val, str) and val.strip():
                holdings[symbol][field] = val.strip()
    return popup_content


def merge_watchlist_narratives(watchlist_content: dict, llm_narratives: dict, buy_status_map: dict) -> dict:
    narrative_fields = {"whatItIs", "whyOnWatchlist", "whatTriggersBuy", "catalyst", "risk"}
    narratives = watchlist_content.setdefault("narratives", {})
    DISPLAY_TIER = {
        "STRONG_NOW": "PRIME",
        "NOW": "BUILDING",
        "WATCH": "WATCHING",
        "MONITOR": "TRACKING",
        "TRACKING": "TRACKING",
    }
    for symbol, fields in (llm_narratives.get("narratives") or {}).items():
        if symbol not in narratives:
            continue
        for field in narrative_fields:
            val = fields.get(field)
            if val and isinstance(val, str) and val.strip():
                narratives[symbol][field] = val.strip()
        # Always ensure a display_tier is set, falling back from buy info to tier mapping
        buy_info = buy_status_map.get(symbol)
        if buy_info:
            narratives[symbol]["buy_status"] = buy_info.get("status", "")
            narratives[symbol]["buy_reason"] = buy_info.get("reason", "")
            narratives[symbol]["display_tier"] = buy_info.get("display_tier") or DISPLAY_TIER.get(narratives[symbol].get("tier"), "TRACKING")
        else:
            narratives[symbol]["display_tier"] = DISPLAY_TIER.get(narratives[symbol].get("tier"), "TRACKING")

        # Incorporate bot intent into whatTriggersBuy narrative
        base_trigger = narratives[symbol].get("whatTriggersBuy", "")
        status = narratives[symbol].get("buy_status", "")
        reason = narratives[symbol].get("buy_reason", "")
        if status == "queued":
            suffix = f" Bot status: queued for a new buy — {reason}."
        elif status == "add":
            suffix = f" Bot status: add to existing position — {reason}."
        elif status == "hold":
            suffix = f" Bot status: hold current position — {reason}."
        elif status == "not_ready":
            suffix = f" Bot status: not yet ready to buy — {reason}."
        elif status == "tier_too_low":
            suffix = f" Bot status: tier too low to trigger a buy — {reason}."
        elif status == "no_price":
            suffix = f" Bot status: cannot evaluate — {reason}."
        else:
            suffix = ""
        if suffix and not base_trigger.rstrip().endswith("."):
            suffix = " " + suffix.lstrip()
        if suffix:
            narratives[symbol]["whatTriggersBuy"] = (base_trigger + suffix).strip()
    # Final pass: ensure every narrative has a display_tier
    for symbol, data in narratives.items():
        if not data.get("display_tier"):
            data["display_tier"] = DISPLAY_TIER.get(data.get("tier"), "TRACKING")
    return watchlist_content


def main() -> None:
    # Step 1: run base generator for fresh data
    base_ok = run_base_generator()

    # Step 2: load fresh base files + LLM narratives + live watchlist buy status
    popup_content = load_json(POPUP_FILE)
    watchlist_content = load_json(WATCHLIST_FILE)
    llm_holdings = load_json(LLM_HOLDINGS_FILE)
    llm_watchlist = load_json(LLM_WATCHLIST_FILE)
    watchlist_live = load_json(WATCHLIST_LIVE_FILE)
    buy_status_map = {
        c["symbol"]: c
        for c in (watchlist_live.get("buy_candidates") or [])
        if c.get("symbol")
    }
    print(f"[INFO] Loaded buy status for {len(buy_status_map)} watchlist symbols")

    if not base_ok and not popup_content and not watchlist_content:
        print("[ERROR] No base files and base generator failed; aborting", file=sys.stderr)
        return

    # Step 3: merge LLM copy over data-driven base
    if llm_holdings or llm_watchlist:
        print(f"[INFO] Merging LLM narratives: holdings={len(llm_holdings.get('holdings', {}))}, watchlist={len(llm_watchlist.get('narratives', {}))}")
        popup_content = merge_holdings_narratives(popup_content, llm_holdings)
        watchlist_content = merge_watchlist_narratives(watchlist_content, llm_watchlist, buy_status_map)
    else:
        print("[INFO] No Mac-uploaded LLM narratives found; serving v2 base copy")

    # Step 4: update timestamp / version
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    popup_content["timestamp"] = ts
    popup_content["narrative_version"] = "v6"
    watchlist_content["timestamp"] = ts
    watchlist_content["narrative_version"] = "v6"

    # Step 5: write merged files
    save_json(POPUP_FILE, popup_content)
    save_json(WATCHLIST_FILE, watchlist_content)
    print(f"[DONE] Merged v6 narratives deployed at {ts}")


if __name__ == "__main__":
    main()
