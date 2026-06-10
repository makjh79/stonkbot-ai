#!/usr/bin/env python3
"""
Execute trades via Alpaca API
"""

import json
import requests
from datetime import datetime
from pathlib import Path

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

def load_alpaca_config():
    with open(ALPACA_CONFIG_FILE) as f:
        return json.load(f)

def get_headers():
    config = load_alpaca_config()
    return {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"],
        "Content-Type": "application/json"
    }

def get_base_url():
    config = load_alpaca_config()
    base_url = config.get('base_url', 'https://paper-api.alpaca.markets')
    if not base_url.endswith('/v2'):
        base_url = base_url.rstrip('/') + '/v2'
    return base_url

def submit_order(symbol, qty, side, order_type="market", time_in_force="day"):
    """Submit a trade order"""
    url = f"{get_base_url()}/orders"
    headers = get_headers()
    
    payload = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code in [200, 201]:
            return resp.json()
        else:
            print(f"Error: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"Exception: {e}")
        return None

def get_account():
    """Get account info"""
    url = f"{get_base_url()}/account"
    headers = get_headers()
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print(f"Exception: {e}")
        return None

def main():
    # Check account
    acct = get_account()
    if acct:
        cash = float(acct.get('cash', 0))
        print(f"Available Cash: ${cash:,.2f}")
        
        # Trim losers, add to winners
        trades = [
            # Trim the biggest loser - APP down -2.51%
            {"symbol": "APP", "qty": 4, "side": "sell", "reason": "Trim loser, reallocate to stronger positions"},
            # Add to strongest winner - HOOD up +4.18%
            {"symbol": "HOOD", "qty": 40, "side": "buy", "reason": "Momentum play, crypto/retail strength"},
            # Add to CRWD - showing resilience
            {"symbol": "CRWD", "qty": 4, "side": "buy", "reason": "Cybersecurity leader, strong trend continuation"},
        ]
        
        print("\n=== EXECUTING TRADES ===\n")
        
        for trade in trades:
            print(f"\n{trade['side'].upper()} {trade['qty']} {trade['symbol']} - {trade['reason']}")
            result = submit_order(trade['symbol'], trade['qty'], trade['side'])
            if result:
                print(f"✅ Order submitted: {result.get('id')}")
                print(f"   Status: {result.get('status')}")
            else:
                print(f"❌ Failed to submit order")

if __name__ == "__main__":
    main()
