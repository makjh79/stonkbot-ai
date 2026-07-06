#!/usr/bin/env python3
"""
Smart scheduler for the LLM narrative generator.

Runs the generator:
- Every 15 minutes while US equity markets are open (Mon-Fri 09:30-16:00 ET).
- Once per 60 minutes during overnight/pre-market closures.
- Skips weekends and public holidays (detected via Alpaca market clock).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ALPACA_CONFIG = Path(os.environ.get("STONKBOT_ALPACA_CONFIG", "/opt/stonk-ai/alpaca_config.json"))
LAST_RUN_FILE = Path(os.environ.get("STONKBOT_LLM_LAST_RUN", "/opt/stonk-ai/.llm_narrative_last_run"))
# Treat a gap >14 hours to the next open as a weekend/public holiday.
HOLIDAY_GAP_HOURS = 14
# Minimum seconds between off-hours runs.
OFF_HOURS_INTERVAL = 3600


def load_alpaca_config() -> dict:
    with open(ALPACA_CONFIG) as f:
        return json.load(f)


def get_market_clock(config: dict) -> dict:
    url = config.get("base_url", "https://paper-api.alpaca.markets").rstrip("/") + "/v2/clock"
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"],
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def read_last_run() -> float:
    try:
        return float(LAST_RUN_FILE.read_text().strip())
    except Exception:
        return 0.0


def write_last_run(ts: float) -> None:
    LAST_RUN_FILE.write_text(str(ts))


def should_run(clock: dict) -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    is_open = bool(clock.get("is_open"))

    if is_open:
        return True, "market open"

    next_open = parse_ts(clock["next_open"])
    hours_to_open = (next_open - now).total_seconds() / 3600

    if hours_to_open > HOLIDAY_GAP_HOURS:
        return False, f"weekend/holiday ({hours_to_open:.1f}h to next open)"

    last_run = read_last_run()
    elapsed = now.timestamp() - last_run
    if elapsed < OFF_HOURS_INTERVAL:
        return False, f"off-hours, {elapsed:.0f}s since last run (<{OFF_HOURS_INTERVAL}s)"

    return True, "off-hours, interval elapsed"


def run_generator() -> int:
    script = Path(os.environ.get("STONKBOT_BOT_DIR", "/opt/stonk-ai")) / "generate_narratives_llm_batched.py"
    result = subprocess.run([sys.executable, str(script)], env=os.environ.copy())
    return result.returncode


def main() -> int:
    try:
        config = load_alpaca_config()
        clock = get_market_clock(config)
        run, reason = should_run(clock)
        print(
            f"[llm-sched] is_open={clock.get('is_open')} next_open={clock.get('next_open')} -> {reason}",
            flush=True,
        )
        if not run:
            return 0

        rc = run_generator()
        if rc == 0:
            write_last_run(datetime.now(timezone.utc).timestamp())
        return rc
    except Exception as exc:
        print(f"[llm-sched] ERROR: {exc}", file=sys.stderr, flush=True)
        # Fail open: run generator anyway if we can't determine market state.
        return run_generator()


if __name__ == "__main__":
    sys.exit(main())
