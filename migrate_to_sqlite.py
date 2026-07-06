#!/usr/bin/env python3
"""
migrate_to_sqlite.py
--------------------
One-shot migration from JSON files to SQLite.
Safe to re-run (uses REPLACE/INSERT OR IGNORE where appropriate).

Usage:
    python3 migrate_to_sqlite.py [--check]

Steps:
    1. Creates stonkbot.db with WAL mode
    2. Reads existing JSONs from /opt/stonk-ai/
    3. Normalizes into typed SQLite tables
    4. Validates row counts match JSON entries
    5. Writes JSON export mirrors (read-only for website)

Before running:
    - Stop trading bot (prevent mid-migration writes)
    - Backup existing JSON files
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OPT_DIR = Path("/opt/stonk-ai")
DB_PATH = OPT_DIR / "stonkbot.db"
WEB_DIR = Path("/var/www/hedge-fund-website")

JSON_PATHS = {
    "signals": OPT_DIR / "signals.json",
    "portfolio_data": OPT_DIR / "portfolio_data.json",
    "portfolio_history": OPT_DIR / "portfolio_history.json",
    "ai_watchlist_live": OPT_DIR / "ai_watchlist_live.json",
}

SCHEMA_FILE = Path(__file__).with_name("stonkbot_schema_v1.sql")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def json_load(path: Path):
    if not path.exists():
        print(f"[!] Missing: {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def apply_schema(conn: sqlite3.Connection):
    if not SCHEMA_FILE.exists():
        print(f"[!] Schema file not found: {SCHEMA_FILE}")
        sys.exit(1)
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def parse_iso(ts):
    """Normalize timestamp string or return None."""
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        # Assume epoch seconds
        from datetime import datetime
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(ts) if "T" in str(ts) else None

from datetime import datetime, timezone  # noqa (ensure import)

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_default(ts):
    """parse_iso that falls back to _now_iso() if None."""
    return parse_iso(ts) if parse_iso(ts) else _now_iso()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def migrate_signals(conn: sqlite3.Connection, data, source: str = "opt") -> int:
    """Migrate signals.json → signals table."""
    if data is None:
        return 0

    # signals.json can be a list or a dict with metadata
    records = data if isinstance(data, list) else data.get("signals", [])

    cursor = conn.cursor()
    cursor.execute("DELETE FROM signals")

    for rec in records:
        tier = rec.get("tier", "")
        frontend_tier = {
            "STRONG_NOW": "PRIME",
            "NOW": "BUILDING",
            "WATCH": "WATCHING",
            "MONITOR": "TRACKING",
        }.get(tier, tier)

        confirmations = rec.get("confirmations", {}) or {}
        cursor.execute(
            """
            INSERT INTO signals (
                symbol, company_name, sector, industry,
                total_score, momentum_score, quality_score, risk_score, regime_score,
                readiness_score, backend_tier, frontend_tier, status,
                confirm_signal, confirm_sector, confirm_ema, confirm_rsi,
                confirm_iv_skew, confirm_market, confirm_outlook,
                confirm_analyst, confirm_momentum, confirm_trend,
                price, atr_14, daily_volume, position_size_usd,
                data_source, run_id, generated_at, expires_at,
                is_entry_eligible, extra_json
            ) VALUES (
                :symbol, :company_name, :sector, :industry,
                :total_score, :momentum_score, :quality_score, :risk_score, :regime_score,
                :readiness_score, :backend_tier, :frontend_tier, :status,
                :confirm_signal, :confirm_sector, :confirm_ema, :confirm_rsi,
                :confirm_iv_skew, :confirm_market, :confirm_outlook,
                :confirm_analyst, :confirm_momentum, :confirm_trend,
                :price, :atr_14, :daily_volume, :position_size_usd,
                :data_source, :run_id, :generated_at, :expires_at,
                :is_entry_eligible, :extra_json
            )
            """,
            {
                "symbol": rec.get("symbol"),
                "company_name": rec.get("company_name") or rec.get("name"),
                "sector": rec.get("sector"),
                "industry": rec.get("industry"),
                "total_score": rec.get("total_score"),
                "momentum_score": rec.get("momentum_score"),
                "quality_score": rec.get("quality_score"),
                "risk_score": rec.get("risk_score"),
                "regime_score": rec.get("regime_score"),
                "readiness_score": rec.get("readiness_score"),
                "backend_tier": tier,
                "frontend_tier": frontend_tier,
                "status": rec.get("status") or "not_ready",
                "confirm_signal": int(confirmations.get("signal", False)),
                "confirm_sector": int(confirmations.get("sector", False)),
                "confirm_ema": int(confirmations.get("ema", False)),
                "confirm_rsi": int(confirmations.get("rsi", False)),
                "confirm_iv_skew": int(confirmations.get("iv_skew", False)),
                "confirm_market": int(confirmations.get("market", False)),
                "confirm_outlook": int(confirmations.get("outlook", False)),
                "confirm_analyst": int(confirmations.get("analyst", False)),
                "confirm_momentum": int(confirmations.get("momentum", False)),
                "confirm_trend": int(confirmations.get("trend", False)),
                "price": rec.get("price"),
                "atr_14": rec.get("atr_14"),
                "daily_volume": rec.get("volume") or rec.get("avg_volume"),
                "position_size_usd": rec.get("position_size_usd"),
                "data_source": rec.get("data_source", "alpaca"),
                "run_id": rec.get("run_id"),
                "generated_at": parse_iso(rec.get("generated_at")) or _now_iso(),
                "expires_at": parse_iso(rec.get("expires_at")),
                "is_entry_eligible": 1 if rec.get("is_entry_eligible") else 0,
                "extra_json": json.dumps({k: v for k, v in rec.items()
                    if k not in {"symbol", "tier", "status", "price", "confirmations",
                                 "total_score", "momentum_score", "quality_score",
                                 "risk_score", "regime_score", "readiness_score"}}),
            },
        )
    conn.commit()
    return len(records)


def migrate_portfolio(conn: sqlite3.Connection, data) -> int:
    """Migrate portfolio_data.json → portfolio_snapshots + holdings."""
    if data is None:
        return 0

    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolio_snapshots")
    cursor.execute("DELETE FROM holdings")

    # Snapshot
    snap = data.get("summary", data)
    cursor.execute(
        """
        INSERT INTO portfolio_snapshots (
            cash_usd, equity_usd, total_value_usd,
            day_pnl_usd, day_pnl_pct, total_pnl_usd, total_pnl_pct,
            open_positions, max_positions, margin_used_pct, extra_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            snap.get("cash"),
            snap.get("equity"),
            snap.get("total_value"),
            snap.get("day_pnl"),
            snap.get("day_pnl_pct"),
            snap.get("total_pnl"),
            snap.get("total_pnl_pct"),
            snap.get("open_positions"),
            snap.get("max_positions", 12),
            snap.get("margin_used_pct"),
            json.dumps({k: v for k, v in snap.items()
                if k not in {"cash", "equity", "total_value", "day_pnl",
                             "day_pnl_pct", "total_pnl", "total_pnl_pct",
                             "open_positions", "max_positions"}}),
        ),
    )

    # Holdings
    holdings = data.get("holdings", data.get("positions", []))
    if isinstance(holdings, dict):
        holdings = list(holdings.values())

    for h in holdings:
        tier = h.get("tier", "")
        frontend_tier = {
            "STRONG_NOW": "PRIME",
            "NOW": "BUILDING",
            "WATCH": "WATCHING",
            "MONITOR": "TRACKING",
        }.get(tier, tier)

        cursor.execute(
            """
            INSERT INTO holdings (
                symbol, shares, avg_entry_price, current_price,
                market_value_usd, unrealized_pnl_usd, unrealized_pnl_pct,
                day_pnl_usd, day_pnl_pct, cost_basis_usd,
                stop_price, atr_14, backend_tier, frontend_tier,
                sector, added_at, updated_at, is_active, extra_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                h.get("symbol"),
                h.get("shares") or h.get("qty"),
                h.get("avg_entry_price") or h.get("avg_price"),
                h.get("current_price") or h.get("last_price"),
                h.get("market_value"),
                h.get("unrealized_pnl") or h.get("unrealized_pnl_usd"),
                h.get("unrealized_pnl_pct"),
                h.get("day_pnl") or h.get("day_pnl_usd"),
                h.get("day_pnl_pct"),
                h.get("cost_basis") or h.get("cost_basis_usd"),
                h.get("stop_price"),
                h.get("atr_14"),
                tier,
                frontend_tier,
                h.get("sector"),
                _parse_iso_default(h.get("added_at")),
                _parse_iso_default(h.get("updated_at")),
                1 if h.get("is_active", True) else 0,
                json.dumps({k: v for k, v in h.items()
                    if k not in {"symbol", "shares", "avg_entry_price",
                                 "current_price", "market_value", "unrealized_pnl",
                                 "tier", "sector", "added_at", "updated_at"}}),
            ),
        )
    conn.commit()
    return len(holdings)


def migrate_portfolio_history(conn: sqlite3.Connection, data) -> int:
    """Migrate portfolio_history.json → portfolio_history table."""
    if data is None:
        return 0

    records = data if isinstance(data, list) else data.get("history", [])
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolio_history")

    for rec in records:
        cursor.execute(
            """
            INSERT OR REPLACE INTO portfolio_history (
                date, cash, equity, total_value,
                day_pnl, total_pnl, positions, benchmark_value, notes
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                rec.get("date"),
                rec.get("cash"),
                rec.get("equity"),
                rec.get("total_value"),
                rec.get("day_pnl"),
                rec.get("total_pnl"),
                rec.get("positions"),
                rec.get("benchmark_value"),
                rec.get("notes"),
            ),
        )
    conn.commit()
    return len(records)


def migrate_watchlist(conn: sqlite3.Connection, data) -> int:
    """Migrate ai_watchlist_live.json → watchlist table."""
    if data is None:
        return 0

    records = data if isinstance(data, list) else data.get("watchlist", data.get("items", []))
    if isinstance(records, dict):
        records = list(records.values())

    cursor = conn.cursor()
    cursor.execute("DELETE FROM watchlist")

    for rec in records:
        tier = rec.get("tier", "")
        frontend_tier = {
            "STRONG_NOW": "PRIME",
            "NOW": "BUILDING",
            "WATCH": "WATCHING",
            "MONITOR": "TRACKING",
        }.get(tier, tier)

        cursor.execute(
            """
            INSERT OR REPLACE INTO watchlist (
                symbol, company_name, sector,
                backend_tier, frontend_tier,
                readiness_score, status,
                price, daily_change_pct, volume_30d_avg,
                added_at, updated_at, data_source, narratives, extra_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rec.get("symbol"),
                rec.get("company_name") or rec.get("name"),
                rec.get("sector"),
                tier,
                frontend_tier,
                rec.get("readiness_score"),
                rec.get("status") or "hold",
                rec.get("price") or rec.get("last_price"),
                rec.get("daily_change_pct") or rec.get("change_pct"),
                rec.get("volume_30d_avg") or rec.get("avg_volume"),
                _parse_iso_default(rec.get("added_at")),
                _parse_iso_default(rec.get("updated_at")),
                rec.get("data_source", "alpaca"),
                json.dumps(rec.get("narratives", {})),
                json.dumps({k: v for k, v in rec.items()
                    if k not in {"symbol", "tier", "status", "price",
                                 "readiness_score", "sector", "added_at"}}),
            ),
        )
    conn.commit()
    return len(records)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_counts(conn: sqlite3.Connection, report: dict):
    """Print row counts and flag mismatches."""
    tables = {
        "signals": "signals",
        "portfolio_data": "holdings",  # holdings rows correspond to portfolio entries
        "portfolio_history": "portfolio_history",
        "ai_watchlist_live": "watchlist",
    }
    print("\n--- Validation ---")
    ok = True
    for json_key, table in tables.items():
        json_data = json_load(JSON_PATHS[json_key])
        expected = 0
        if json_data is not None:
            if isinstance(json_data, list):
                expected = len(json_data)
            elif isinstance(json_data, dict):
                expected = len(json_data.get("holdings", json_data.get("history",
                         json_data.get("watchlist", json_data.get("items", json_data)))))

        actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        match = "✅" if actual == expected else "⚠️"
        if actual != expected:
            ok = False
        print(f"  {match} {table}: {actual} rows (JSON expected: {expected})")
    return ok


# ---------------------------------------------------------------------------
# JSON Export mirrors (read-only for website)
# ---------------------------------------------------------------------------

def export_json_mirrors(conn: sqlite3.Connection):
    """Write JSON files from DB for website compatibility."""
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # Signals
    rows = conn.execute("SELECT * FROM signals ORDER BY total_score DESC").fetchall()
    signals_out = []
    for r in rows:
        rec = dict(r)
        if rec.get("extra_json"):
            rec.update(json.loads(rec["extra_json"]))
            del rec["extra_json"]
        signals_out.append(rec)
    with open(WEB_DIR / "signals.json", "w", encoding="utf-8") as f:
        json.dump(signals_out, f, indent=2)

    # Watchlist
    rows = conn.execute("SELECT * FROM watchlist ORDER BY readiness_score DESC").fetchall()
    watchlist_out = []
    for r in rows:
        rec = dict(r)
        if rec.get("extra_json"):
            rec.update(json.loads(rec["extra_json"]))
            del rec["extra_json"]
        watchlist_out.append(rec)
    with open(WEB_DIR / "watchlist.json", "w", encoding="utf-8") as f:
        json.dump(watchlist_out, f, indent=2)

    print(f"\n📁 JSON mirrors written to {WEB_DIR}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Migrate StonkBOT JSON files to SQLite")
    parser.add_argument("--check", action="store_true", help="Validate only, no migration")
    args = parser.parse_args()

    print("=" * 60)
    print("StonkBOT SQLite Migration")
    print("=" * 60)

    if not SCHEMA_FILE.exists():
        print(f"[!] Schema file must be in same directory: {SCHEMA_FILE}")
        sys.exit(1)

    conn = get_db()

    if args.check:
        validate_counts(conn, {})
        conn.close()
        return

    print(f"\n[1/4] Applying schema to {DB_PATH}")
    apply_schema(conn)

    print("[2/4] Loading JSON files...")
    data = {k: json_load(p) for k, p in JSON_PATHS.items()}

    print("[3/4] Migrating data...")
    total = 0
    total += migrate_signals(conn, data["signals"])
    total += migrate_portfolio(conn, data["portfolio_data"])
    total += migrate_portfolio_history(conn, data["portfolio_history"])
    total += migrate_watchlist(conn, data["ai_watchlist_live"])
    print(f"      Migrated {total} records")

    print("[4/4] Validating...")
    if validate_counts(conn, data):
        print("\n✅ All checks passed")
        export_json_mirrors(conn)
        print("\n📝 Next steps:")
        print("   1. Point scripts to use stonkbot.db")
        print("   2. Update writers to INSERT/UPDATE instead of json.dump()")
        print("   3. Keep JSON exports as read-only for website")
        print("   4. Restart trading bot")
    else:
        print("\n⚠️ Validation failed — review counts above")
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
