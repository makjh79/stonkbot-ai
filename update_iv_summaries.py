"""
update_iv_summaries.py — Cron job to pre-fetch IV term structure for watchlist + holdings.

Run every 15 minutes during market hours, or daily pre-market.
Reads ai_watchlist_live.json and portfolio_state.json to determine symbols.
Writes iv_summaries.json and appends to per-symbol IV history for rank calculation.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import options_iv_analytics

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}")
        return {}


def get_target_symbols() -> set:
    symbols = set()

    watchlist = _load_json("/var/www/hedge-fund-website/ai_watchlist_live.json")
    # ai_watchlist_live.json uses either top-level 'watchlist' list or 'prices' dict
    for item in watchlist.get("watchlist", []):
        sym = item.get("symbol")
        if sym:
            symbols.add(sym)
    for sym in watchlist.get("prices", {}):
        symbols.add(sym)

    portfolio = _load_json("/var/www/hedge-fund-website/portfolio_data.json")
    if portfolio is None:
        portfolio = _load_json("/opt/stonk-ai/portfolio_state.json")
    positions = portfolio.get("positions", [])
    if isinstance(positions, dict):
        positions = positions.values()
    for pos in positions:
        sym = pos.get("symbol")
        if sym:
            symbols.add(sym)

    # Fallback universe if files missing
    if not symbols:
        universe = _load_json("/opt/stonk-ai/signals.json")
        symbols = set(universe.keys())

    return symbols


def main():
    symbols = get_target_symbols()
    if not symbols:
        logger.warning("No target symbols found; exiting.")
        return

    logger.info(f"Updating IV summaries for {len(symbols)} symbols...")
    summaries = {}
    for sym in sorted(symbols):
        try:
            summary = options_iv_analytics.iv_summary(sym)
            summaries[sym] = summary
            # Record for rank history
            options_iv_analytics.record_iv_snapshot(sym)
            logger.info(f"{sym}: iv_30d={summary.get('iv_30d')}, skew={summary.get('iv_skew')}")
        except Exception as e:
            logger.warning(f"Failed IV summary for {sym}: {e}")

    out_path = Path("/opt/stonk-ai/iv_summaries.json")
    try:
        with open(out_path, "w") as f:
            json.dump(summaries, f, indent=2, default=str)
        logger.info(f"Wrote {out_path}")
    except Exception as e:
        logger.error(f"Failed to write {out_path}: {e}")


def _record_heartbeat():
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/python3", "/opt/stonk-ai/heartbeat_tracker.py", "update_iv_summaries"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
    _record_heartbeat()
