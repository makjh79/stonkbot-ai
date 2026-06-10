#!/usr/bin/env python3
"""
Update hedge fund website with live data
Run every minute during market hours
"""

import json
import requests
from datetime import datetime
from pathlib import Path

WEBSITE_DIR = Path("/root/.openclaw/workspace/hedge-fund-website")
DATA_FILE = WEBSITE_DIR / "portfolio_data.json"

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

def load_alpaca_config():
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE) as f:
            return json.load(f)
    return None

def get_portfolio_data():
    """Fetch live portfolio data"""
    config = load_alpaca_config()
    if not config:
        return None
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"]
    }
    
    base_url = config.get('base_url')
    
    data = {
        "timestamp": datetime.now().isoformat(),
        "positions": [],
        "account": {}
    }
    
    try:
        # Get account
        acct_resp = requests.get(f"{base_url}/v2/account", headers=headers, timeout=10)
        if acct_resp.status_code == 200:
            acct = acct_resp.json()
            data["account"] = {
                "equity": float(acct.get("equity", 0)),
                "cash": float(acct.get("cash", 0)),
                "buying_power": float(acct.get("buying_power", 0)),
                "portfolio_value": float(acct.get("portfolio_value", 0))
            }
        
        # Get positions
        pos_resp = requests.get(f"{base_url}/v2/positions", headers=headers, timeout=10)
        if pos_resp.status_code == 200:
            positions = pos_resp.json()
            for pos in positions:
                data["positions"].append({
                    "symbol": pos.get("symbol"),
                    "qty": int(float(pos.get("qty", 0))),
                    "avg_entry": float(pos.get("avg_entry_price", 0)),
                    "current": float(pos.get("current_price", 0)),
                    "market_value": float(pos.get("market_value", 0)),
                    "unrealized_pl": float(pos.get("unrealized_pl", 0)),
                    "unrealized_plpc": float(pos.get("unrealized_plpc", 0)) * 100
                })
        
        return data
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def save_data(data):
    """Save portfolio data for website"""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Data saved: {DATA_FILE}")

def main():
    print("📊 Updating Hedge Fund Website...")
    data = get_portfolio_data()
    if data:
        save_data(data)
        print(f"✅ Updated at {datetime.now().strftime('%H:%M:%S')}")
        print(f"   Equity: ${data['account'].get('equity', 0):,.2f}")
        print(f"   Positions: {len(data['positions'])}")
    else:
        print("❌ Failed to fetch data")

if __name__ == "__main__":
    main()
