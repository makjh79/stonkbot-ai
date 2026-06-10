#!/usr/bin/env python3
"""
Update hedge fund website data ONLY - saves to portfolio_data.json
Does NOT regenerate index.html - HTML design is finalized
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
    """Fetch live portfolio data from Alpaca"""
    config = load_alpaca_config()
    if not config:
        return None
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"]
    }
    
    base_url = config.get('base_url', 'https://paper-api.alpaca.markets')
    # Ensure v2 path is included
    if not base_url.endswith('/v2'):
        base_url = base_url.rstrip('/') + '/v2'
    
    data = {
        "timestamp": datetime.now().isoformat(),
        "positions": [],
        "account": {},
        "status": "live"
    }
    
    try:
        # Get account
        acct_resp = requests.get(f"{base_url}/account", headers=headers, timeout=10)
        if acct_resp.status_code == 200:
            acct = acct_resp.json()
            data["account"] = {
                "equity": float(acct.get("equity", 0)),
                "cash": float(acct.get("cash", 0)),
                "buying_power": float(acct.get("buying_power", 0)),
                "portfolio_value": float(acct.get("portfolio_value", 0))
            }
        
        # Get positions
        pos_resp = requests.get(f"{base_url}/positions", headers=headers, timeout=10)
        if pos_resp.status_code == 200:
            positions = pos_resp.json()
            total_pl = 0
            total_cost = 0
            for pos in positions:
                qty = int(float(pos.get("qty", 0)))
                entry = float(pos.get("avg_entry_price", 0))
                current = float(pos.get("current_price", 0))
                pl = float(pos.get("unrealized_pl", 0))
                pl_pct = float(pos.get("unrealized_plpc", 0)) * 100
                mv = float(pos.get("market_value", 0))
                cost = qty * entry
                total_pl += pl
                total_cost += cost
                
                data["positions"].append({
                    "symbol": pos.get("symbol"),
                    "qty": qty,
                    "avg_entry": entry,
                    "current": current,
                    "market_value": mv,
                    "cost_basis": cost,
                    "unrealized_pl": pl,
                    "unrealized_plpc": pl_pct
                })
            
            data["total_pl"] = total_pl
            data["total_pl_pct"] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        return data
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Updating portfolio data...")
    data = get_portfolio_data()
    if data:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✅ Saved: {DATA_FILE}")
        print(f"   Equity: ${data['account'].get('equity', 0):,.2f}")
        print(f"   Positions: {len(data['positions'])}")
    else:
        print("❌ Failed")

if __name__ == "__main__":
    main()
