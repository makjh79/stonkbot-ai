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
from datetime import datetime
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
            "timestamp": datetime.now().isoformat(),
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
        
        # Calculate portfolio_value as sum of market values (gross exposure)
        # This matches the sum shown in the positions table
        data["account"]["portfolio_value"] = sum(p["market_value"] for p in data["positions"])
        
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
        
        # Update history
        update_history(data)
        
        # Sync trades log
        sync_trades_log()
        
        return True
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return False

def update_history(data):
    """Append current data to portfolio history"""
    try:
        history = {"checks": [], "last_check": datetime.now().isoformat()}
        
        # Load existing history
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
        
        # Create check entry
        check = {
            "timestamp": data.get("timestamp", datetime.now().isoformat()),
            "portfolio_value": data.get("account", {}).get("portfolio_value", 0),
            "cash": data.get("account", {}).get("cash", 0),
            "total_pl": data.get("total_pl", 0),
            "total_pl_pct": data.get("total_pl_pct", 0),
            "notified": False
        }
        
        # Add to history (keep last 500 entries)
        history["checks"].append(check)
        history["checks"] = history["checks"][-500:]
        history["last_check"] = check["timestamp"]
        
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

if __name__ == "__main__":
    logger.info("STONK.AI Data Fetcher Starting")
    while True:
        fetch_and_save()
        time.sleep(30)
