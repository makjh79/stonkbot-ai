#!/usr/bin/env python3
"""Check if sentiment data is fresh and alert if stale.

Run this via cron every 15 minutes to monitor sentiment data health.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SENTIMENT_DIR = Path("/var/www/hedge-fund-website/sentiment")
MAX_AGE_MINUTES = 75  # Alert if data older than 75 minutes (runs hourly + buffer)

def check_freshness():
    if not SENTIMENT_DIR.exists():
        print(f"ERROR: Sentiment directory {SENTIMENT_DIR} does not exist")
        return 1

    json_files = list(SENTIMENT_DIR.glob("*.json"))
    if not json_files:
        print(f"ERROR: No sentiment JSON files found in {SENTIMENT_DIR}")
        return 1

    now = datetime.now(timezone.utc)
    stale_files = []
    oldest_age = 0

    for f in json_files:
        try:
            data = json.loads(f.read_text())
            ts = data.get("timestamp")
            if not ts:
                stale_files.append(f"{f.stem}: no timestamp")
                continue
            file_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_minutes = (now - file_time).total_seconds() / 60
            oldest_age = max(oldest_age, age_minutes)

            if age_minutes > MAX_AGE_MINUTES:
                stale_files.append(f"{f.stem}: {int(age_minutes)}m old")
        except Exception as e:
            stale_files.append(f"{f.stem}: parse error ({e})")

    if stale_files:
        print(f"WARNING: {len(stale_files)} stale sentiment files (max age: {MAX_AGE_MINUTES}m):")
        for msg in stale_files[:5]:  # Show first 5
            print(f"  - {msg}")
        if len(stale_files) > 5:
            print(f"  ... and {len(stale_files) - 5} more")
        return 1

    print(f"OK: All {len(json_files)} sentiment files fresh (oldest: {int(oldest_age)}m)")
    return 0

if __name__ == "__main__":
    sys.exit(check_freshness())
