"""
stonkbot_db.py
--------------
SQLite wrapper for StonkBOT core data.

Replaces JSON file reads/writes with ACID SQLite transactions.
All functions are safe for concurrent use (WAL mode).

Usage:
    from stonkbot_db import (
        save_signals, get_signals, get_entry_candidates,
        save_watchlist, get_watchlist,
        save_portfolio, get_portfolio, get_holdings,
        append_history, get_history,
        heartbeat, check_stale_jobs,
        export_json_mirrors,
    )
"""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path(os.environ.get("STONKBOT_DB", "/opt/stonk-ai/stonkbot.db"))
WEB_DIR = Path(os.environ.get("STONKBOT_WEB_DIR", "/var/www/hedge-fund-website"))

# Tier mappings
BACKEND_TO_FRONTEND = {
    "STRONG_NOW": "PRIME",
    "NOW": "BUILDING",
    "WATCH": "WATCHING",
    "MONITOR": "TRACKING",
}

FRONTEND_TO_BACKEND = {v: k for k, v in BACKEND_TO_FRONTEND.items()}

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def save_signals(
    signals: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> int:
    """
    Replace all signals with a fresh batch.
    Call this from signal_engine.py instead of writing signals.json.
    """
    with transaction() as conn:
        conn.execute("DELETE FROM signals")
        cursor = conn.cursor()

        for rec in signals:
            tier = rec.get("tier", "")
            frontend_tier = BACKEND_TO_FRONTEND.get(tier, tier)
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
                    "status": rec.get("status", ""),
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
                    "run_id": run_id or rec.get("run_id"),
                    "generated_at": generated_at or _now_iso(),
                    "expires_at": rec.get("expires_at"),
                    "is_entry_eligible": 1 if (rec.get("is_entry_eligible") or rec.get("entry_eligible")) else 0,
                    "extra_json": _json_extra(rec, {
                        "symbol", "tier", "status", "price", "confirmations",
                        "total_score", "momentum_score", "quality_score",
                        "risk_score", "regime_score", "readiness_score",
                        "run_id", "generated_at", "expires_at", "is_entry_eligible"
                    }),
                },
            )
        return len(signals)


def get_signals(
    tier: Optional[str] = None,
    entry_only: bool = False,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read signals with optional filters."""
    with _connect() as conn:
        wheres = ["1=1"]
        params = {}
        if tier:
            wheres.append("frontend_tier = :tier")
            params["tier"] = tier.upper()
        if entry_only:
            wheres.append("is_entry_eligible = 1")
        if status:
            wheres.append("status = :status")
            params["status"] = status

        sql = f"SELECT * FROM signals WHERE {' AND '.join(wheres)} ORDER BY total_score DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"

        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_entry_candidates(min_score: float = 70.0) -> List[Dict[str, Any]]:
    """Get PRIME/BUILDING candidates ready for entry."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE is_entry_eligible = 1
              AND frontend_tier IN ('PRIME', 'BUILDING')
              AND total_score >= :min_score
            ORDER BY total_score DESC
            """,
            {"min_score": min_score},
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def save_watchlist(items: List[Dict[str, Any]]) -> int:
    """Replace all watchlist entries."""
    with transaction() as conn:
        conn.execute("DELETE FROM watchlist")
        cursor = conn.cursor()
        for rec in items:
            tier = rec.get("tier", "")
            frontend_tier = BACKEND_TO_FRONTEND.get(tier, tier)
            cursor.execute(
                """
                INSERT INTO watchlist (
                    symbol, company_name, sector,
                    backend_tier, frontend_tier, readiness_score, status,
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
                    rec.get("status", ""),
                    rec.get("price") or rec.get("last_price"),
                    rec.get("daily_change_pct") or rec.get("change_pct"),
                    rec.get("volume_30d_avg") or rec.get("avg_volume"),
                    rec.get("added_at"),
                    _now_iso(),
                    rec.get("data_source", "alpaca"),
                    json.dumps(rec.get("narratives", {})),
                    _json_extra(rec, {"symbol", "tier", "status", "price",
                                      "readiness_score", "sector", "added_at"}),
                ),
            )
        return len(items)


def get_watchlist(
    tier: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read watchlist with optional filters."""
    with _connect() as conn:
        wheres = ["1=1"]
        params = {}
        if tier:
            wheres.append("frontend_tier = :tier")
            params["tier"] = tier.upper()
        if status:
            wheres.append("status = :status")
            params["status"] = status

        rows = conn.execute(
            f"SELECT * FROM watchlist WHERE {' AND '.join(wheres)} ORDER BY readiness_score DESC",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def update_watchlist_item(symbol: str, updates: Dict[str, Any]) -> bool:
    """Patch a single watchlist entry (e.g., tier change, status update)."""
    allowed = {"status", "price", "readiness_score", "tier", "frontend_tier",
               "backend_tier", "daily_change_pct", "narratives"}
    cols = {k: v for k, v in updates.items() if k in allowed}
    if not cols:
        return False

    # Auto-map tier if provided
    if "tier" in cols and "frontend_tier" not in cols:
        cols["frontend_tier"] = BACKEND_TO_FRONTEND.get(cols["tier"], cols["tier"])
    if "tier" in cols and "backend_tier" not in cols:
        cols["backend_tier"] = cols["tier"]

    with transaction() as conn:
        set_clause = ", ".join(f"{k} = :{k}" for k in cols)
        cols["symbol"] = symbol
        cols["updated_at"] = _now_iso()
        conn.execute(
            f"UPDATE watchlist SET {set_clause}, updated_at = :updated_at WHERE symbol = :symbol",
            cols,
        )
        return conn.total_changes > 0


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def save_portfolio(summary: Dict[str, Any], holdings: List[Dict[str, Any]]) -> None:
    """Replace portfolio snapshot + holdings."""
    with transaction() as conn:
        # Snapshot
        snap = summary
        conn.execute("DELETE FROM portfolio_snapshots")
        conn.execute(
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
                _json_extra(snap, {"cash", "equity", "total_value", "day_pnl",
                                   "day_pnl_pct", "total_pnl", "total_pnl_pct",
                                   "open_positions", "max_positions"}),
            ),
        )

        # Holdings
        conn.execute("DELETE FROM holdings")
        for h in holdings:
            tier = h.get("tier", "")
            frontend_tier = BACKEND_TO_FRONTEND.get(tier, tier)
            conn.execute(
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
                    h.get("added_at"),
                    _now_iso(),
                    1 if h.get("is_active", True) else 0,
                    _json_extra(h, {"symbol", "shares", "avg_entry_price",
                                    "current_price", "market_value", "unrealized_pnl",
                                    "tier", "sector", "added_at"}),
                ),
            )


def get_portfolio() -> Dict[str, Any]:
    """Return current portfolio as a dict matching old portfolio_data.json shape."""
    with _connect() as conn:
        snap = conn.execute("SELECT * FROM portfolio_snapshots ORDER BY snapshot_at DESC LIMIT 1").fetchone()
        rows = conn.execute("SELECT * FROM holdings WHERE is_active = 1 ORDER BY symbol").fetchall()

        holdings = [_row_to_dict(r) for r in rows]
        summary = _row_to_dict(snap) if snap else {}
        # Drop internal columns for compatibility
        for key in list(summary.keys()):
            if key.startswith("snapshot_") or key == "id" or key == "extra_json":
                del summary[key]

        return {
            "summary": summary,
            "holdings": holdings,
            "timestamp": _now_iso(),
        }


def get_holdings(symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    with _connect() as conn:
        if symbol:
            rows = conn.execute("SELECT * FROM holdings WHERE symbol = ? AND is_active = 1", (symbol,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM holdings WHERE is_active = 1 ORDER BY symbol").fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def append_history(record: Dict[str, Any]) -> None:
    """Append a daily portfolio history row."""
    with transaction() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO portfolio_history (
                date, cash, equity, total_value,
                day_pnl, total_pnl, positions, benchmark_value, notes
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                record.get("date"),
                record.get("cash"),
                record.get("equity"),
                record.get("total_value"),
                record.get("day_pnl"),
                record.get("total_pnl"),
                record.get("positions"),
                record.get("benchmark_value"),
                record.get("notes"),
            ),
        )


def get_history(days: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM portfolio_history ORDER BY date DESC"
    params = ()
    if days:
        sql += " LIMIT ?"
        params = (int(days),)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Heartbeats / Monitor
# ---------------------------------------------------------------------------

def heartbeat(job_name: str, status: str = "ok", runtime_ms: Optional[int] = None, message: str = "") -> None:
    """Record a job heartbeat. Replaces writing heartbeat tracker files."""
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO heartbeats (job_name, status, runtime_ms, message, beat_at)
            VALUES (?,?,?,?,?)
            """,
            (job_name, status, runtime_ms, message, _now_iso()),
        )


def check_stale_jobs(stale_minutes: int = 20) -> List[Dict[str, Any]]:
    """Return jobs that haven't checked in within stale_minutes."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT job_name, MAX(beat_at) as last_beat,
                 (strftime('%s', 'now') - strftime('%s', MAX(beat_at))) / 60 as minutes_ago
            FROM heartbeats
            GROUP BY job_name
            HAVING minutes_ago > ? OR last_beat IS NULL
            ORDER BY minutes_ago DESC
            """,
            (stale_minutes,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def log_event(level: str, source: str, message: str, context: Optional[Dict] = None) -> None:
    """Structured logging to DB."""
    with transaction() as conn:
        conn.execute(
            "INSERT INTO system_log (level, source, message, context_json, created_at) VALUES (?,?,?,?,?)",
            (level, source, message, json.dumps(context) if context else None, _now_iso()),
        )


# ---------------------------------------------------------------------------
# JSON Export Mirrors (read-only for website)
# ---------------------------------------------------------------------------

def export_json_mirrors() -> None:
    """Write JSON files from DB for website compatibility."""
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    # Signals
    signals = get_signals()
    _write_json(WEB_DIR / "signals.json", signals)

    # Watchlist
    watchlist = get_watchlist()
    _write_json(WEB_DIR / "watchlist.json", watchlist)

    log_event("info", "stonkbot_db", f"Exported JSON mirrors to {WEB_DIR}")


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_extra(rec: Dict[str, Any], known_keys: set) -> str:
    extra = {k: v for k, v in rec.items() if k not in known_keys}
    return json.dumps(extra) if extra else "{}"


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    # Expand extra_json inline
    if "extra_json" in d and d["extra_json"]:
        try:
            extra = json.loads(d["extra_json"])
            if isinstance(extra, dict):
                d.update(extra)
            del d["extra_json"]
        except (json.JSONDecodeError, TypeError):
            pass
    # Expand narratives
    if "narratives" in d and d["narratives"]:
        try:
            d["narratives"] = json.loads(d["narratives"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


# ---------------------------------------------------------------------------
# CLI / quick checks
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Quick health check")
    parser.add_argument("--export", action="store_true", help="Export JSON mirrors")
    args = parser.parse_args()

    if args.check:
        with _connect() as conn:
            counts = {
                "signals": conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
                "watchlist": conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0],
                "holdings": conn.execute("SELECT COUNT(*) FROM holdings WHERE is_active=1").fetchone()[0],
                "portfolio_snapshots": conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0],
                "portfolio_history": conn.execute("SELECT COUNT(*) FROM portfolio_history").fetchone()[0],
                "heartbeats": conn.execute("SELECT COUNT(*) FROM heartbeats").fetchone()[0],
            }
            for k, v in counts.items():
                print(f"  {k}: {v}")
            stale = check_stale_jobs()
            if stale:
                print(f"\n  ⚠️ Stale jobs: {len(stale)}")
                for s in stale[:5]:
                    print(f"     {s['job_name']}: {s.get('minutes_ago', 'unknown')} min ago")
            else:
                print("\n  ✅ No stale jobs")

    if args.export:
        export_json_mirrors()
        print(f"  ✅ Exported to {WEB_DIR}")
        sys.exit(0)

    if not args.check and not args.export:
        parser.print_help()
