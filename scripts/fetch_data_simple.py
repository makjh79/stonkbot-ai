#!/usr/bin/env python3
"""
STONK.AI Data Fetcher - Simple and Reliable
Uses Alpaca for everything (proven working)
Updates every 30 seconds
"""

import os
import json
import time
import logging
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

def load_alpaca_config():
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def fetch_and_save():
    """Fetch from Alpaca and save to both locations"""
    try:
        import alpaca_trade_api as tradeapi
        config = load_alpaca_config()
        
        api = tradeapi.REST(
            key_id=config.get('api_key'),
            secret_key=config.get('api_secret'),
            base_url=config.get('base_url', 'https://paper-api.alpaca.markets')
        )
        
        account = api.get_account()
        positions = api.list_positions()
        
        # Build data
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "status": "live",
            "account": {
                "portfolio_value": 0,  # Will be calculated from positions
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "equity": float(account.equity)
            },
            "positions": []
        }
        
        total_pl = 0
        for pos in positions:
            p = {
                "symbol": pos.symbol,
                "qty": int(pos.qty),
                "avg_entry": float(pos.avg_entry_price),
                "current": float(pos.current_price),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
                "unrealized_pl": float(pos.unrealized_pl),
                "unrealized_plpc": float(pos.unrealized_plpc) * 100
            }
            data["positions"].append(p)
            total_pl += p["unrealized_pl"]
        
        # Use Alpaca's portfolio_value directly (includes positions + cash)
        data["account"]["portfolio_value"] = float(account.portfolio_value)
        
        # Calculate day change from Alpaca's last_equity (yesterday's close)
        try:
            last_equity = float(account.last_equity)
            current_equity = float(account.equity)
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
        
        # Save to both locations
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        WEBSITE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with open(WEBSITE_OUTPUT, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Updated: ${float(account.portfolio_value):,.2f} ({data['total_pl_pct']:+.2f}%)")
        
        # Update history (with benchmark data)
        update_history(data, api)
        
        # Sync trades log
        sync_trades_log()
        
        return True
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return False

def fetch_spy_benchmark(api):
    """Fetch SPY price for benchmark comparison"""
    try:
        # Get SPY latest price
        spy_quote = api.get_latest_quote('SPY')
        spy_price = spy_quote.ap if spy_quote.ap > 0 else spy_quote.bp
        return float(spy_price)
    except Exception as e:
        logger.warning(f"Could not fetch SPY benchmark: {e}")
        return None

# June 4, 2026 SPY baseline price (experiment start)
SPY_JUNE_4_PRICE = 757.09

def update_history(data, api=None):
    """Append current data to portfolio history, preserving one snapshot per day."""
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
                # Using June 4, 2026 SPY price as baseline
                benchmark_value = round((spy_price / SPY_JUNE_4_PRICE) * 100000.0, 2)

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
            time.sleep(60)  # Refresh every 60 seconds during market hours
        else:
            logger.debug("Markets closed - sleeping 5 minutes")
            time.sleep(300)  # Check every 5 minutes when closed
