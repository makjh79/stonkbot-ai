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


def merge_watchlist_narratives(watchlist_content: dict, llm_narratives: dict) -> dict:
    narrative_fields = {"whatItIs", "whyOnWatchlist", "whatTriggersBuy", "catalyst", "risk"}
    narratives = watchlist_content.setdefault("narratives", {})
    for symbol, fields in (llm_narratives.get("narratives") or {}).items():
        if symbol not in narratives:
            continue
        for field in narrative_fields:
            val = fields.get(field)
            if val and isinstance(val, str) and val.strip():
                narratives[symbol][field] = val.strip()
    return watchlist_content


def main() -> None:
    # Step 1: run base generator for fresh data
    base_ok = run_base_generator()

    # Step 2: load fresh base files + Mac-uploaded LLM narratives
    popup_content = load_json(POPUP_FILE)
    watchlist_content = load_json(WATCHLIST_FILE)
    llm_holdings = load_json(LLM_HOLDINGS_FILE)
    llm_watchlist = load_json(LLM_WATCHLIST_FILE)

    if not base_ok and not popup_content and not watchlist_content:
        print("[ERROR] No base files and base generator failed; aborting", file=sys.stderr)
        return

    # Step 3: merge LLM copy over data-driven base
    if llm_holdings or llm_watchlist:
        print(f"[INFO] Merging LLM narratives: holdings={len(llm_holdings.get('holdings', {}))}, watchlist={len(llm_watchlist.get('narratives', {}))}")
        popup_content = merge_holdings_narratives(popup_content, llm_holdings)
        watchlist_content = merge_watchlist_narratives(watchlist_content, llm_watchlist)
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
