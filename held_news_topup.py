#!/usr/bin/env python3
"""
STONK.AI Held Positions News Top-Up (NO-OP)

Legacy external news enrichment dependency removed 2026-07-14. This script is
kept as a no-op placeholder so any existing cron or systemd trigger exits cleanly.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger.info("held_news_topup.py is deprecated; legacy external news enrichment dependency removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
