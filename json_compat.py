#!/usr/bin/env python3
"""
json_compat.py
--------------
Drop-in replacement for json.load() / json.dump() that writes to SQLite
instead of JSON files, while still producing JSON mirrors for the website.

Usage (minimal change to existing scripts):
    # Replace: import json
    # With:
    from json_compat import load, dump, set_source

    # At module level (once):
    set_source("signal_engine")  # or "trading_bot", "watchlist_manager", etc.

    # Then your existing code stays the same:
    data = load("/opt/stonk-ai/signals.json")
    dump(signals, "/opt/stonk-ai/signals.json")

How it works:
    dump(signals, "signals.json") -> saves to SQLite -> writes JSON mirror
    load("signals.json") -> reads from SQLite (faster, consistent snapshot)
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Allow import of stonkbot_db from same directory
sys.path.insert(0, str(Path(__file__).parent))
import stonkbot_db as db

_source: str = ""
_db_mode: bool = True  # True = use DB, False = fallback to raw JSON

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WEB_DIR = Path(os.environ.get("STONKBOT_WEB_DIR", "/var/www/hedge-fund-website"))
OPT_DIR = Path(os.environ.get("STONKBOT_OPT_DIR", "/opt/stonk-ai"))


def set_source(name: str):
    """Tell the adapter which process is writing (for heartbeats, logging)."""
    global _source
    _source = name


def enable_db(enabled: bool = True):
    """Toggle DB vs raw JSON mode. Use for testing."""
    global _db_mode
    _db_mode = enabled


# ---------------------------------------------------------------------------
# Compatibility layer
# ---------------------------------------------------------------------------

def _file_to_table(path: str) -> Optional[str]:
    """Map file paths to known data types."""
    name = Path(path).name
    mapping = {
        "signals.json": "signals",
        "portfolio_data.json": "portfolio",
        "portfolio_history.json": "history",
        "ai_watchlist_live.json": "watchlist",
        "watchlist.json": "watchlist",
    }
    return mapping.get(name)


def load(path: str, **kwargs) -> Any:
    """Replacement for json.load(). Reads from DB if known, else raw JSON."""
    table = _file_to_table(path)
    if not _db_mode or not table:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f, **kwargs)

    if table == "signals":
        return db.get_signals()

    if table == "portfolio":
        # Return legacy-compat shape (summary + holdings dict)
        return db.get_portfolio()

    if table == "history":
        rows = db.get_history()
        return rows  # list of dicts

    if table == "watchlist":
        return db.get_watchlist()

    # Fallback
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, **kwargs)


def dump(obj: Any, path: str, **kwargs) -> None:
    """Replacement for json.dump(). Writes to DB if known, else raw JSON."""
    table = _file_to_table(path)
    if not _db_mode or not table:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, **kwargs)
        return

    run_id = kwargs.pop("run_id", None)

    if table == "signals":
        signals = obj if isinstance(obj, list) else obj.get("signals", [])
        db.save_signals(signals, run_id=run_id or db._now_iso())

    elif table == "portfolio":
        if isinstance(obj, dict) and "holdings" in obj:
            summary = obj.get("summary", obj)
            holdings = obj["holdings"]
        elif isinstance(obj, dict) and "positions" in obj:
            summary = obj
            holdings = obj["positions"]
        else:
            # Assume obj is just holdings list
            summary = {}
            holdings = obj if isinstance(obj, list) else []
        db.save_portfolio(summary, holdings)

    elif table == "history":
        if isinstance(obj, list):
            for rec in obj:
                db.append_history(rec)
        elif isinstance(obj, dict):
            db.append_history(obj)

    elif table == "watchlist":
        items = obj if isinstance(obj, list) else obj.get("watchlist", obj.get("items", []))
        db.save_watchlist(items)

    # Write JSON mirror for website compatibility
    db.export_json_mirrors()

    # Record heartbeat that this job ran successfully
    if _source:
        db.heartbeat(_source, status="ok")


# ---------------------------------------------------------------------------
# dumps / loads for completeness
# ---------------------------------------------------------------------------

def loads(s: str, **kwargs) -> Any:
    """Still uses standard json.loads."""
    return json.loads(s, **kwargs)


def dumps(obj: Any, **kwargs) -> str:
    """Still uses standard json.dumps."""
    return json.dumps(obj, **kwargs)


# ---------------------------------------------------------------------------
# Legacy module interface
# ---------------------------------------------------------------------------
# Some scripts may call json.load(f) after opening a file.
# This wrapper replicates the json module so you can do:
#     import json_compat as json
# ---------------------------------------------------------------------------

JSONEncoder = json.JSONEncoder
JSONDecoder = json.JSONDecoder

__all__ = ["load", "dump", "loads", "dumps", "set_source", "enable_db",
           "JSONEncoder", "JSONDecoder"]
