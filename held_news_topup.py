#!/usr/bin/env python3
"""
STONK.AI Held Positions News Top-Up

Lightweight intraday refresh: fetches latest news + sentiment only for symbols
currently held in the portfolio. Updates signal_enrichment.json in place.

Runs every hour during US market hours to keep popup theses fresh.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from signal_enricher import (
    load_finnhub_key,
    refresh_news_for_symbols,
    load_enrichment,
    save_enrichment,
)

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = Path("/var/www/hedge-fund-website/portfolio_data.json")
ENRICHMENT_FILE = Path("/opt/stonk-ai/signal_enrichment.json")


def is_us_market_hours() -> bool:
    """US market hours in UTC: 14:30 - 21:00, Mon-Fri."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=14, minute=30, second=0, microsecond=0)
    end = now.replace(hour=21, minute=0, second=0, microsecond=0)
    return start <= now <= end


def load_held_symbols() -> list:
    if not PORTFOLIO_FILE.exists():
        logger.warning("No portfolio file found")
        return []
    try:
        data = json.loads(PORTFOLIO_FILE.read_text())
        return [p.get("symbol") for p in data.get("positions", []) if p.get("symbol")]
    except Exception as e:
        logger.warning(f"Could not load portfolio: {e}")
        return []


def main():
    logging.basicConfig(level=logging.INFO)
    if not is_us_market_hours():
        logger.info("Outside US market hours; skipping held-news top-up")
        return 0

    api_key = load_finnhub_key()
    if not api_key:
        logger.error("No Finnhub API key found")
        return 1

    held = load_held_symbols()
    if not held:
        logger.info("No held positions; skipping")
        return 0

    logger.info(f"Refreshing news for {len(held)} held positions: {held}")
    enrichment = load_enrichment(ENRICHMENT_FILE)
    updated = refresh_news_for_symbols(held, api_key, enrichment)
    save_enrichment(updated, ENRICHMENT_FILE)
    logger.info("Held-news top-up complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
