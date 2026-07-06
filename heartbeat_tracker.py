"""
Simple heartbeat tracker for cron-based StonkBOT jobs.

Jobs call this after successful completion:
    python3 heartbeat_tracker.py <job_name>

Comprehensive monitor checks /opt/stonk-ai/heartbeats/*.json for freshness.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_DIR = Path("/opt/stonk-ai/heartbeats")


def record(job_name: str) -> None:
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "job": job_name,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "ok",
    }
    path = HEARTBEAT_DIR / f"{job_name}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: heartbeat_tracker.py <job_name>")
        sys.exit(1)
    record(sys.argv[1])
