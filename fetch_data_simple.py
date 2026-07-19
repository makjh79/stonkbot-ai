#!/usr/bin/env python3
"""
STONK.AI Data Fetcher - Simple and Reliable
Uses Alpaca for everything (proven working)
Updates every 30 seconds
"""

import os
import math
import json
import time
import logging
from alpaca_data import get_data_hub
from datetime import datetime, timezone
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_fetcher.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

ALPACA_CONFIG_FILE = Path(__file__).parent / "alpaca_config.json"
OUTPUT_FILE = Path(__file__).parent / 'portfolio_data.json'
WEBSITE_OUTPUT = Path('/var/www/hedge-fund-website/portfolio_data.json')
HISTORY_FILE = Path(__file__).parent / 'portfolio_history.json'
WEBSITE_HISTORY = Path('/var/www/hedge-fund-website/portfolio_history.json')
TRADES_FILE = Path(__file__).parent / 'trades_log.json'
WEBSITE_TRADES = Path('/var/www/hedge-fund-website/trades_log.json')

# Company name cache — dynamically fetched from Alpaca asset API
# Falls back to symbol if lookup fails. Cache persists in company_names.json
COMPANY_NAMES_CACHE_FILE = Path(__file__).parent / 'company_names.json'

def load_name_cache():
    """Load cached company names from disk."""
    if COMPANY_NAMES_CACHE_FILE.exists():
        try:
            return json.loads(COMPANY_NAMES_CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_name_cache(cache):
    """Save company name cache to disk."""
    try:
        COMPANY_NAMES_CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception as e:
        logger.warning(f"Could not save name cache: {e}")

def clean_company_name(raw_name, symbol):
    """Clean Alpaca's verbose names to short display form."""
    if not raw_name or raw_name == symbol:
        return symbol
    name = raw_name.strip()
    # Strip everything after ' Class ' or ' Common' or ' subordinate' or ' Common stock'
    for marker in [' Class A subordinate', ' Class B subordinate', ' Class C subordinate',
                   ' Class A Common', ' Class B Common', ' Class C Common',
                   ' Common Stock', ' Common stock', ' common stock', ' common shares',
                   ' Class A', ' Class B', ' Class C']:
        idx = name.find(marker)
        if idx > 5:
            name = name[:idx].strip()
            break
    # Strip trailing commas
    name = name.rstrip(',').strip()
    return name if name and len(name) >= 2 else symbol

def load_alpaca_config():
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def fetch_and_save():
    """Fetch from Alpaca and save to both locations"""
    try:
        hub = get_data_hub()
        config = load_alpaca_config()
        
        # Use hub for account and positions
        account = hub.get_account()
        positions = hub.get_positions()
        
        if not account:
            logger.error("Could not fetch account from Alpaca")
            return False
        
        # Enrich positions with VWAP/snapshot data from hub
        position_symbols = [p.get("symbol", "") for p in positions]
        snaps = {}
        if position_symbols:
            try:
                snaps = hub.get_snapshots(position_symbols)
            except Exception as _e:
                logger.debug(f"Snapshot enrichment failed: {_e}")

        # Company name cache
        name_cache = load_name_cache()
        symbols_needed = [p.get("symbol") for p in positions if p.get("symbol") not in name_cache or name_cache.get(p.get("symbol")) == p.get("symbol")]
        if symbols_needed:
            logger.info(f"Fetching company names for {len(symbols_needed)} new symbols: {symbols_needed}")
            # Try to get asset names from Alpaca
            import requests
            headers = {"APCA-API-KEY-ID": config.get("api_key"), "APCA-API-SECRET-KEY": config.get("api_secret")}
            for sym in symbols_needed:
                try:
                    r = requests.get(f"https://paper-api.alpaca.markets/v2/assets/{sym}", headers=headers, timeout=10)
                    if r.status_code == 200:
                        asset_name = r.json().get("name", sym)
                        cleaned = clean_company_name(asset_name, sym)
                        name_cache[sym] = cleaned
                        logger.info(f"  {sym}: {cleaned}")
                    else:
                        name_cache[sym] = sym
                except Exception as e:
                    logger.warning(f"  {sym}: name lookup failed ({e})")
                    name_cache[sym] = sym
            save_name_cache(name_cache)
        
        # Build data
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "status": "live",
            "account": {
                "portfolio_value": 0,  # Will be calculated from positions
                "cash": float(account.get("cash", 0)),
                "buying_power": float(account.get("buying_power", 0)),
                "equity": float(account.get("equity", 0))
            },
            "positions": []
        }
        
        total_pl = 0
        for pos in positions:
            sym = pos.get("symbol", "")
            # Determine sector
            try:
                from signal_engine import SignalEngine
                _sector = SignalEngine._sector(sym)
            except Exception:
                _sector = "Other"

            # Get VWAP/snapshot data
            snap = snaps.get(sym, {})
            # --- AUTO-SPLIT DETECTION ---
            _raw_qty = float(pos.get("qty", 0))
            _raw_avg = float(pos.get("avg_entry_price", 0))
            _raw_current = float(pos.get("current_price", 0))
            if _raw_current and _raw_avg and _raw_current > 0:
                _ratio = _raw_avg / _raw_current
                if 1.8 < _ratio < 10.5:
                    _nearest = round(_ratio)
                    if abs(_ratio - _nearest) < 0.15:
                        _logger.info(f"SPLIT FIX ({sym}): detected {_nearest}-for-1 split -- adjusting qty, avg, stops")
                        _factor = _nearest
                        _raw_qty = _raw_qty * _factor
                        _raw_avg = _raw_avg / _factor
                        snap["prev_close"] = (snap.get("prev_close", 0) or 0) / _factor
                        snap["daily_vwap"] = (snap.get("daily_vwap", 0) or 0) / _factor
            # --- FALLBACK: compute price from market_value/qty when snapshot is stale ---
            _market_value = float(pos.get("market_value", 0))
            if (not _raw_current or _raw_current == 0) and _raw_qty and _market_value:
                _raw_current = round(_market_value / _raw_qty, 2)
            # --- LOCAL P&L RECOMPUTE: block impossible Alpaca values (-200%) ---
            if _raw_qty and _raw_avg and _raw_current:
                _unrealized_pl = (_raw_current - _raw_avg) * _raw_qty
                _unrealized_plpc = (_raw_current - _raw_avg) / _raw_avg
            else:
                _unrealized_pl = float(pos.get("unrealized_pl", 0))
                _unrealized_plpc = float(pos.get("unrealized_plpc", 0))
            p = {
                "symbol": sym,
                "name": name_cache.get(sym, sym),
                "qty": int(_raw_qty),
                "avg_entry": _raw_avg,
                "current": _raw_current,
                "market_value": _market_value,
                "cost_basis": float(pos.get("cost_basis", 0)),
                "unrealized_pl": _unrealized_pl,
                "unrealized_plpc": _unrealized_plpc * 100,
                "sector": _sector,
                "daily_vwap": snap.get("daily_vwap"),
                "prev_close": snap.get("prev_close"),
                "intraday_vwap": snap.get("minute_vwap"),
                "minute_volume": snap.get("minute_volume"),
            }
            # Auto-detect stock splits where Alpaca positions API lags
            snap_price = snap.get("price", 0)
            if snap_price and p["avg_entry"] > 0:
                ratio = p["avg_entry"] / snap_price
                if ratio >= 1.5:
                    nearest_int = round(ratio)
                    if abs(ratio - nearest_int) <= 0.15 and 2 <= nearest_int <= 10:
                        old_qty = p["qty"]
                        old_avg = p["avg_entry"]
                        p["qty"] = old_qty * nearest_int
                        p["avg_entry"] = old_avg / nearest_int
                        p["market_value"] = p["qty"] * p["current"]
                        p["unrealized_pl"] = p["market_value"] - p["cost_basis"]
                        p["unrealized_plpc"] = (p["market_value"] / p["cost_basis"] - 1) * 100 if p["cost_basis"] else 0
                        # Also adjust snapshot-derived historical bars
                        for bar_key in ["daily_vwap", "prev_close"]:
                            val = snap.get(bar_key)
                            if isinstance(val, (int, float)) and val > 0:
                                snap[bar_key] = val / nearest_int
                        # Refresh post-adjustment
                        p["daily_vwap"] = snap.get("daily_vwap")
                        p["prev_close"] = snap.get("prev_close")
                        logger.warning(
                            f"SPLIT DETECTED {sym}: {nearest_int}-for-1. "
                            f"Old: qty={old_qty} avg=${old_avg:.2f}. "
                            f"New: qty={p['qty']} avg=${p['avg_entry']:.2f}. "
                            f"P&L corrected: {p['unrealized_plpc']:.1f}%."
                        )
            data["positions"].append(p)
            total_pl += p["unrealized_pl"]
        
        # Use Alpaca's portfolio_value directly (includes positions + cash)
        data["account"]["portfolio_value"] = float(account.get("portfolio_value", 0))
        
        # Calculate day change from Alpaca's last_equity (yesterday's close)
        try:
            last_equity = float(account.get("last_equity", 0))
            current_equity = float(account.get("equity", 0))
            if last_equity > 0:
                data["day_change"] = ((current_equity - last_equity) / last_equity) * 100
            else:
                data["day_change"] = 0
        except:
            data["day_change"] = 0
        
        data["total_pl"] = total_pl
        # Calculate total_pl_pct based on actual cost basis, not fixed 100000
        total_cost = sum(p["cost_basis"] for p in data["positions"])
        data["total_pl_pct"] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        # fetch_data_simple.py no longer writes portfolio_data.json;
        # trading_bot.py is the single writer of canonical portfolio state.
        pass
        
        logger.info(f"Updated: ${float(account.get("portfolio_value", 0)):,.2f} ({data['total_pl_pct']:+.2f}%)")
        
        # Update history (with benchmark data via hub)
        update_history(data)
        
        # Sync trades log
        sync_trades_log()
        
        return True
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return False

def fetch_spy_benchmark(api=None):
    """Fetch SPY price for benchmark comparison via Alpaca hub"""
    try:
        hub = get_data_hub()
        price = hub.get_latest_price('SPY')
        return float(price) if price else None
    except Exception as e:
        logger.warning(f"Could not fetch SPY benchmark: {e}")
        return None

# July 7, 2026 SPY baseline price (bot reset date — matches RESET_PRICES in fetch_market_indices.py)
SPY_RESET_PRICE = 747.71

def update_history(data, api=None):
    """Append current data to portfolio history."""
    # api param kept for backwards compat but not used — hub is used directly

    try:
        history = {
            "checks": [],
            "last_check": data.get("timestamp", datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')),
        }

        # Load existing history (preserve reconstructed flag if present)
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)

        # Fetch SPY benchmark if API available
        benchmark_value = None
        benchmark_symbol = None
        spy_price = None
        if api:
            spy_price = fetch_spy_benchmark(api)
            if spy_price:
                benchmark_symbol = "SPY"
                # Calculate benchmark value normalized to $100K starting value
                # Using July 7, 2026 SPY price as baseline (post-reset)
                benchmark_value = round((spy_price / SPY_RESET_PRICE) * 100000.0, 2)

        # Create check entry
        check = {
            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')),
            "portfolio_value": data.get("account", {}).get("portfolio_value", 0),
            "cash": data.get("account", {}).get("cash", 0),
            "total_pl": data.get("total_pl", 0),
            "total_pl_pct": data.get("total_pl_pct", 0),
            "notified": False,
        }

        # Add benchmark data if available
        if benchmark_value and benchmark_symbol:
            check["benchmark_value"] = benchmark_value
            check["benchmark_symbol"] = benchmark_symbol

        # Merge into daily snapshots: keep the check closest to noon UTC for each day.
        # All live micro-checks are retained for the current day only.
        from collections import defaultdict

        def parse_ts(ts):
            if ts.endswith("Z"):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)

        def seconds_from_noon(ts, day):
            noon = datetime.fromisoformat(day + "T12:00:00+00:00")
            return abs((parse_ts(ts) - noon).total_seconds())

        # Group all checks (existing + new) by day and keep the best daily snapshot
        by_day = defaultdict(list)
        for c in history.get("checks", []):
            by_day[c["timestamp"][:10]].append(c)
        by_day[check["timestamp"][:10]].append(check)

        daily_checks = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for day, entries in sorted(by_day.items()):
            if day == today:
                # For the current trading day, keep the latest live check so the chart
                # and stats reflect real-time values, but still use the one nearest noon
                # if the latest is far from market close.
                best = min(entries, key=lambda c: seconds_from_noon(c["timestamp"], day))
                latest = max(entries, key=lambda c: parse_ts(c["timestamp"]))
                chosen = latest if latest != best and seconds_from_noon(latest["timestamp"], day) <= 6 * 3600 else best
                daily_checks.append(chosen)
            else:
                best = min(entries, key=lambda c: seconds_from_noon(c["timestamp"], day))
                daily_checks.append(best)

        # Keep a rolling window of the most recent 180 daily snapshots (~6 months)
        daily_checks = daily_checks[-180:]

        history["checks"] = daily_checks
        history["last_check"] = check["timestamp"]
        if "reconstructed" not in history:
            history["reconstructed"] = False

        # Save to both locations
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)

        WEBSITE_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with open(WEBSITE_HISTORY, 'w') as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        logger.error(f"History update error: {e}")

def sync_trades_log():
    """Sync trades_log.json to website folder"""
    try:
        if TRADES_FILE.exists():
            with open(TRADES_FILE, 'r') as f:
                trades_data = json.load(f)
            
            WEBSITE_TRADES.parent.mkdir(parents=True, exist_ok=True)
            with open(WEBSITE_TRADES, 'w') as f:
                json.dump(trades_data, f, indent=2)
            
            logger.debug(f"Synced trades_log.json: {trades_data.get('trade_count', 0)} trades")
    except Exception as e:
        logger.error(f"Trades log sync error: {e}")

def is_market_open():
    """Check if US stock market is currently open (NYSE/NASDAQ schedule)"""
    now = datetime.now()
    
    # Check if weekend
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Check US market holidays for 2026
    market_holidays_2026 = [
        (1, 1),   # New Year's Day
        (1, 19),  # Martin Luther King Jr. Day
        (2, 16),  # Presidents' Day
        (4, 3),   # Good Friday
        (5, 25),  # Memorial Day
        (6, 19),  # Juneteenth
        (7, 4),   # Independence Day
        (9, 7),   # Labor Day
        (10, 12), # Columbus Day
        (11, 11), # Veterans Day
        (11, 26), # Thanksgiving
        (12, 25), # Christmas
    ]
    
    today = (now.month, now.day)
    if today in market_holidays_2026:
        return False
    
    return True

if __name__ == "__main__":
    logger.info("STONK.AI Data Fetcher Starting")
    # Run an initial fetch on startup regardless of market hours
    try:
        fetch_and_save()
    except Exception as e:
        logger.error(f"Initial fetch failed: {e}")
    while True:
        if is_market_open():
            fetch_and_save()
            time.sleep(5)   # Refresh every 5 seconds during market hours
        else:
            logger.debug("Markets closed - sleeping 5 minutes")
            time.sleep(300)  # Check every 5 minutes when closed
