#!/usr/bin/env python3
"""
Upload watchlist to Alpaca
"""

import json
import requests
from pathlib import Path

# Watchlist from stock_monitor.py
WATCHLIST = {
    "NOW": {"name": "ServiceNow"},
    "HOOD": {"name": "Robinhood"},
    "SOFI": {"name": "SoFi Technologies"},
    "AVGO": {"name": "Broadcom"},
    "MSFT": {"name": "Microsoft"},
    "NFLX": {"name": "Netflix"},
    "UNH": {"name": "UnitedHealth"},
    "NVO": {"name": "Novo-Nordisk"},
    "NVOX": {"name": "Defiance 2X NVDA"},
    "META": {"name": "Meta Platforms"},
    "AMZN": {"name": "Amazon"},
    "WFC": {"name": "Wells Fargo"},
    "BABA": {"name": "Alibaba"},
    "JD": {"name": "JD.com"},
}

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

def load_alpaca_config():
    """Load Alpaca API credentials"""
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def upload_watchlist():
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found. Run stock_monitor setup first.")
        return False
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"],
        "Content-Type": "application/json"
    }
    
    base_url = config.get("trading_url", "https://paper-api.alpaca.markets")
    symbols = list(WATCHLIST.keys())
    
    print(f"📋 Uploading {len(symbols)} symbols to Alpaca...")
    print(f"   Symbols: {', '.join(symbols)}")
    
    # First, check if a watchlist named "Howie" already exists
    try:
        url = f"{base_url}/v2/watchlists"
        response = requests.get(url, headers=headers, timeout=15)
        
        existing_id = None
        if response.status_code == 200:
            watchlists = response.json()
            for wl in watchlists:
                if wl.get("name") == "Howie":
                    existing_id = wl.get("id")
                    print(f"   Found existing watchlist 'Howie' (ID: {existing_id})")
                    break
        
        # Prepare watchlist data
        watchlist_data = {
            "name": "Howie",
            "symbols": symbols
        }
        
        if existing_id:
            # Update existing watchlist
            url = f"{base_url}/v2/watchlists/{existing_id}"
            response = requests.put(url, headers=headers, json=watchlist_data, timeout=15)
            action = "Updated"
        else:
            # Create new watchlist
            url = f"{base_url}/v2/watchlists"
            response = requests.post(url, headers=headers, json=watchlist_data, timeout=15)
            action = "Created"
        
        if response.status_code in [200, 201]:
            result = response.json()
            print(f"\n✅ {action} watchlist 'Howie' in Alpaca!")
            print(f"   Watchlist ID: {result.get('id')}")
            print(f"   Symbols added: {len(result.get('assets', []))}")
            
            # Show what was added
            print(f"\n📊 Watchlist contents:")
            for asset in result.get('assets', []):
                symbol = asset.get('symbol')
                name = WATCHLIST.get(symbol, {}).get('name', asset.get('name', 'Unknown'))
                print(f"   • {symbol} - {name}")
            
            return True
        else:
            print(f"\n❌ Failed to upload watchlist")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"\n❌ Error uploading watchlist: {e}")
        return False

if __name__ == "__main__":
    upload_watchlist()
