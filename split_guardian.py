#!/usr/bin/env python3
"""
Split Guardian — standalone script to detect and flag stock splits
that Alpaca may not have processed in the positions API.

Runs daily via cron. Compares avg_entry_price from Alpaca positions
against the snapshot-adjusted price. If a clean integer ratio is found,
logs a warning and optionally emits a Telegram alert.

Usage: python3 /opt/stonk-ai/split_guardian.py
Dependencies: requests, json (standard lib)
"""
import json
import logging
import sys
from pathlib import Path
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

BASE_DIR = Path("/opt/stonk-ai")
CONFIG_FILE = BASE_DIR / "alpaca_config.json"

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def get_headers(cfg):
    return {
        "APCA-API-KEY-ID": cfg["api_key"],
        "APCA-API-SECRET-KEY": cfg["api_secret"],
    }

def get_positions(cfg):
    url = f"{cfg['base_url']}/v2/positions"
    resp = requests.get(url, headers=get_headers(cfg), timeout=15)
    resp.raise_for_status()
    return resp.json()

def get_snapshots(symbols, cfg):
    if not symbols:
        return {}
    url = f"{cfg.get('data_url', 'https://data.alpaca.markets')}/v2/stocks/snapshots"
    params = {"symbols": ",".join(symbols), "feed": "sip"}
    resp = requests.get(url, params=params, headers=get_headers(cfg), timeout=15)
    if resp.status_code != 200:
        logger.warning(f"Snapshot fetch failed: {resp.status_code}")
        return {}
    data = resp.json()
    return data.get("snapshots", data)

def detect_split(symbol, qty, avg_entry, cost_basis, snap):
    snap_price = snap.get("latestTrade", {}).get("p") or snap.get("dailyBar", {}).get("c")
    if not snap_price or avg_entry <= 0:
        return None, None, None, None
    ratio = avg_entry / snap_price
    if ratio < 1.5:
        return None, None, None, None
    nearest_int = round(ratio)
    if abs(ratio - nearest_int) > 0.15 or nearest_int < 2 or nearest_int > 10:
        return None, None, None, None
    new_qty = int(qty * nearest_int)
    new_avg = avg_entry / nearest_int
    new_upl = (snap_price - new_avg) * new_qty
    new_pl_pct = ((snap_price / new_avg) - 1) * 100 if new_avg > 0 else 0
    return nearest_int, new_qty, new_avg, new_pl_pct

def main():
    try:
        cfg = load_config()
        positions = get_positions(cfg)
        symbols = [p.get("symbol", "") for p in positions]
        snaps = get_snapshots(symbols, cfg)
        split_found = False
        for p in positions:
            sym = p.get("symbol", "")
            qty = int(float(p.get("qty", 0)))
            avg_entry = float(p.get("avg_entry_price", 0))
            cost_basis = float(p.get("cost_basis", 0))
            current = float(p.get("current_price", 0))
            upl = float(p.get("unrealized_pl", 0))
            uplpc = float(p.get("unrealized_plpc", 0))
            snap = snaps.get(sym, {})
            factor, new_qty, new_avg, new_pl_pct = detect_split(sym, qty, avg_entry, cost_basis, snap)
            if factor:
                split_found = True
                logger.warning(
                    f"SPLIT FLAGGED {sym}: {factor}-for-1. "
                    f"Alpaca shows qty={qty} avg=${avg_entry:.2f}. "
                    f"Should be qty={new_qty} avg=${new_avg:.2f}. "
                    f"P&L should be ~{new_pl_pct:.1f}% instead of {uplpc*100:.1f}%.")
        if not split_found:
            logger.info("No unprocessed stock splits detected.")
    except Exception as e:
        logger.error(f"Split Guardian failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
