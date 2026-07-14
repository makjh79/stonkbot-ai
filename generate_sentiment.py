#!/usr/bin/env python3
"""
STONK.AI Sentiment Generator (NO-OP)

External news-sentiment dependency removed 2026-07-14.
This script is kept as a no-op placeholder so any existing cron or trigger exits cleanly.
"""

import logging

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger.info("generate_sentiment.py is deprecated; external Finnhub dependency removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
