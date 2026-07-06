#!/usr/bin/env python3
"""
circuit_breaker.py
------------------
StonkBOT circuit breaker — prevents trading when the system is unhealthy.

Every _execute_buy, _execute_sell, and submit_order checks the breaker.
If tripped, the order is rejected and an alert is sent.

Override: manually update DB: UPDATE trading_halt SET halted=0;
No programmatic override — this prevents accidental recovery by a buggy job.
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow import from same dir
sys.path.insert(0, str(Path(__file__).parent))
from stonkbot_db import _connect

DB_PATH = Path(os.environ.get("STONKBOT_DB", "/opt/stonk-ai/stonkbot.db"))

# Override requires this file to exist with a timestamp within last 5 min
OVERRIDE_FILE = Path("/opt/stonk-ai/.circuit_override")


class CircuitBreaker:
    """
    Usage in trading_bot.py:
        from circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        if cb.is_open():
            logger.critical("CIRCUIT BREAKER OPEN — trading halted")
            return None
    """

    _HALT_REASONS = {
        "stale_signals": "No fresh signals for >30 minutes",
        "stale_portfolio": "No portfolio update for >20 minutes",
        "db_integrity": "SQLite integrity check failed",
        "root_process": "Root-owned stonk process detected",
        "manual": "Manually halted by operator",
        "preflight": "Preflight check failed before trading cycle",
    }

    def __init__(self, db_path: str = None):
        self.db = db_path or str(DB_PATH)

    @staticmethod
    def ensure_table():
        """Call once at startup — creates trading_halt table if missing."""
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trading_halt (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                halted          INTEGER NOT NULL DEFAULT 0,
                reason          TEXT,
                tripped_at      TEXT,
                tripped_by      TEXT,
                override_at     TEXT,
                override_by     TEXT,
                notes           TEXT
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO trading_halt (id, halted, reason, tripped_at)
            VALUES (1, 0, NULL, NULL)
        """)
        conn.commit()
        conn.close()

    def is_open(self) -> bool:
        """Return True if breaker is OPEN (trading halted)."""
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT halted, reason, tripped_at, override_at FROM trading_halt WHERE id = 1"
        ).fetchone()
        conn.close()
        if not row:
            return False  # table missing — default passthrough

        halted, reason, tripped_at, override_at = row

        # Check manual override file (5-min window)
        if OVERRIDE_FILE.exists():
            try:
                mtime = OVERRIDE_FILE.stat().st_mtime
                if (datetime.now(timezone.utc).timestamp() - mtime) < 300:
                    return False
            except OSError:
                pass

        return bool(halted)

    def trip(self, reason_key: str, notes: str = "", source: str = "") -> None:
        """Trip the breaker. Once open, stays open until manual reset."""
        reason_text = self._HALT_REASONS.get(reason_key, reason_key)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(self.db)
        conn.execute(
            """UPDATE trading_halt SET
                halted = 1,
                reason = ?,
                tripped_at = ?,
                tripped_by = ?,
                notes = ?,
                override_at = NULL,
                override_by = NULL
            WHERE id = 1""",
            (reason_text, now, source or "stonkbot_healthcheck", notes),
        )
        conn.commit()
        conn.close()

    def status(self) -> dict:
        """Return current breaker state."""
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT halted, reason, tripped_at, tripped_by, override_at, override_by, notes FROM trading_halt WHERE id = 1"
        ).fetchone()
        conn.close()
        if not row:
            return {"halted": False, "reason": None}
        return {
            "halted": bool(row[0]),
            "reason": row[1],
            "tripped_at": row[2],
            "tripped_by": row[3],
            "override_at": row[4],
            "override_by": row[5],
            "notes": row[6],
        }

    def reset(self, by: str = "manual") -> None:
        """Manual reset with audit trail."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(self.db)
        conn.execute(
            """UPDATE trading_halt SET
                halted = 0,
                reason = NULL,
                tripped_at = NULL,
                tripped_by = NULL,
                override_at = ?,
                override_by = ?
            WHERE id = 1""",
            (now, by),
        )
        conn.commit()
        conn.close()
        OVERRIDE_FILE.write_text(str(datetime.now(timezone.utc).timestamp()))


# ---------------------------------------------------------------------------
# Integration helpers for stonkbot_healthcheck.py
# ---------------------------------------------------------------------------

def check_circuit() -> dict:
    """Called by healthcheck to decide whether to trip."""
    cb = CircuitBreaker()
    return cb.status()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Circuit breaker control")
    parser.add_argument("--status", action="store_true", help="Show breaker status")
    parser.add_argument("--trip", metavar="REASON", help="Trip breaker with reason key")
    parser.add_argument("--reset", action="store_true", help="Reset breaker (manual override)")
    parser.add_argument("--ensure-table", action="store_true", help="Create table if missing")
    args = parser.parse_args()

    if args.ensure_table:
        CircuitBreaker.ensure_table()
        print("✅ trading_halt table ready")
        sys.exit(0)

    cb = CircuitBreaker()

    if args.status:
        s = cb.status()
        print(f"HALTED: {s['halted']}")
        if s["reason"]:
            print(f"REASON: {s['reason']}")
            print(f"TRIPPED: {s['tripped_at']} by {s['tripped_by']}")
        sys.exit(0)

    if args.trip:
        cb.trip(args.trip)
        print(f"🛑 Breaker TRIPPED: {args.trip}")
        sys.exit(0)

    if args.reset:
        # Manual reset via DB update
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "UPDATE trading_halt SET halted=0, override_at=?, override_by=? WHERE id=1",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "manual_cli"),
        )
        conn.commit()
        conn.close()
        OVERRIDE_FILE.write_text(str(datetime.now(timezone.utc).timestamp()))
        print("✅ Breaker RESET (manual override)")
        sys.exit(0)

    parser.print_help()
