#!/usr/bin/env python3
"""
Alpaca / SQLite holdings reconciler.

Permanent safety net: every 5 minutes, pull the live Alpaca paper account
positions and overwrite the SQLite `holdings` + `portfolio_snapshots` tables
to match. This fixes the Jul 6 migration gap where the live JSON pipeline
never wrote to the DB again.

Design:
- Read-only wrt. broker: no orders, no trades.
- Uses stonkbot_db.save_portfolio() under a transaction; safe to run
  concurrently with trading_bot.py which now also writes DB.
- Logs mismatches and writes a divergence report for the monitor.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from alpaca_data import get_data_hub
from stonkbot_db import save_portfolio, get_holdings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / "reconcile_alpaca_holdings.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("reconcile_alpaca_holdings")


def fetch_alpaca_truth():
    hub = get_data_hub()
    account = hub.get_account()
    positions = hub.get_positions()
    return account, positions


def normalize_alpaca_positions(positions, account):
    """Convert Alpaca position objects to the shape save_portfolio expects."""
    total_value = float(account.get("portfolio_value", 0) or 0)
    normalized = []
    for p in positions:
        qty = float(p.get("qty", 0))
        if qty <= 0:
            continue
        symbol = p.get("symbol") or p.get("asset_symbol")
        avg_entry = float(p.get("avg_entry_price", 0) or 0)
        current = float(p.get("current_price", 0) or 0)
        mv = float(p.get("market_value", 0) or current * qty)
        cb = float(p.get("cost_basis", 0) or avg_entry * qty)
        upl = float(p.get("unrealized_pl", 0) or 0)
        uplpc = float(p.get("unrealized_plpc", 0) or 0) * 100  # Alpaca is decimal
        normalized.append({
            "symbol": symbol,
            "shares": qty,
            "avg_entry_price": avg_entry,
            "current_price": current,
            "market_value": mv,
            "cost_basis_usd": cb,
            "unrealized_pnl_usd": upl,
            "unrealized_pnl_pct": uplpc,
            "is_active": True,
        })
    return normalized


def compute_divergence(db_positions, alpaca_positions):
    """Return (mismatch_count, detail_list)."""
    db_map = {p.get("symbol"): p.get("shares", p.get("qty", 0)) for p in db_positions}
    alp_map = {p.get("symbol"): p.get("shares", p.get("qty", 0)) for p in alpaca_positions}
    all_syms = set(db_map) | set(alp_map)
    details = []
    for sym in sorted(all_syms):
        db_qty = float(db_map.get(sym, 0) or 0)
        alp_qty = float(alp_map.get(sym, 0) or 0)
        if abs(db_qty - alp_qty) > 0.001:
            details.append(f"{sym}: DB={db_qty:.0f} Alpaca={alp_qty:.0f}")
    return len(details), details


def main():
    start = time.time()
    try:
        account, positions = fetch_alpaca_truth()
    except Exception as e:
        logger.error(f"Failed to fetch Alpaca truth: {e}")
        sys.exit(1)

    normalized = normalize_alpaca_positions(positions, account)
    summary = {
        "cash": float(account.get("cash", 0) or 0),
        "equity": float(account.get("equity", 0) or 0),
        "total_value": float(account.get("portfolio_value", 0) or 0),
        "open_positions": len(normalized),
        "max_positions": 12,
    }

    try:
        save_portfolio(summary, normalized)
    except Exception as e:
        logger.error(f"Failed to save portfolio to DB: {e}")
        sys.exit(1)

    try:
        db_positions = get_holdings()
        mismatch_count, details = compute_divergence(db_positions, normalized)
    except Exception as e:
        logger.warning(f"Could not verify post-save divergence: {e}")
        mismatch_count, details = -1, [str(e)]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "alpaca_positions": len(normalized),
        "db_positions": len(db_positions) if mismatch_count >= 0 else -1,
        "mismatches": mismatch_count,
        "detail": details[:20],
        "runtime_ms": int((time.time() - start) * 1000),
    }

    report_path = BASE_DIR / "run" / "alpaca_db_divergence.json"
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not write divergence report: {e}")

    if mismatch_count > 0:
        logger.warning(f"Alpaca/DB divergence detected: {mismatch_count} mismatches — {details[:5]}")
    else:
        logger.info(f"Reconciled {len(normalized)} Alpaca positions into DB (no divergence)")


if __name__ == "__main__":
    main()
