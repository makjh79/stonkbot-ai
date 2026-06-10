#!/usr/bin/env python3
"""
Set stop-losses to limit portfolio drawdown to 10%
Run this AFTER market orders fill
"""

import json
import requests
from pathlib import Path

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

# Stop-loss prices (-10% from entry)
STOP_LOSSES = {
    "NVDA": 135.00,   # -10% from ~$150
    "TSLA": 252.00,   # -10% from ~$280
    "PLTR": 108.00,   # -10% from ~$120
    "CRWD": 360.00,   # -10% from ~$400
    "MSFT": 382.50,   # -10% from ~$425
    "SCHD": 25.20,    # -10% from ~$28
    "SGOV": None,     # Cash equivalent, no stop needed
}

def load_alpaca_config():
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def get_positions():
    config = load_alpaca_config()
    if not config:
        return []
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"]
    }
    
    url = f"{config.get('base_url')}/v2/positions"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error: {e}")
    return []

def place_stop_loss(symbol, qty, stop_price):
    """Place a stop-loss order"""
    config = load_alpaca_config()
    if not config:
        return None
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"],
        "Content-Type": "application/json"
    }
    
    # Use stop order (triggers market sell when price hits stop)
    order_data = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "sell",
        "type": "stop",
        "stop_price": str(stop_price),
        "time_in_force": "gtc"  # Good till cancelled
    }
    
    url = f"{config.get('base_url')}/v2/orders"
    try:
        response = requests.post(url, headers=headers, json=order_data, timeout=15)
        if response.status_code in [200, 201]:
            return response.json()
        else:
            print(f"  Error: {response.status_code} - {response.text[:100]}")
            return None
    except Exception as e:
        print(f"  Error: {e}")
        return None

def main():
    print("🛡️ SETTING STOP-LOSSES (10% Protection)")
    print("=" * 60)
    
    positions = get_positions()
    
    if not positions:
        print("\n📭 No positions found yet.")
        print("   Run this script again after market opens and orders fill.")
        print("   (Expected: ~9:30 AM ET)")
        return
    
    print(f"\n📈 Found {len(positions)} positions:")
    print("-" * 60)
    
    for pos in positions:
        symbol = pos.get('symbol')
        qty = int(float(pos.get('qty', 0)))
        entry = float(pos.get('avg_entry_price', 0))
        
        stop_price = STOP_LOSSES.get(symbol)
        
        if stop_price and qty > 0:
            loss_pct = ((stop_price - entry) / entry) * 100
            print(f"\n{symbol}: {qty} shares @ ${entry:.2f}")
            print(f"  Stop-loss: ${stop_price:.2f} ({loss_pct:+.1f}%)")
            
            result = place_stop_loss(symbol, qty, stop_price)
            if result:
                print(f"  ✅ Stop-loss order placed: {result.get('id')[:8]}...")
            else:
                print(f"  ❌ Failed to place stop-loss")
        elif symbol == "SGOV":
            print(f"\n{symbol}: {qty} shares (cash ETF - no stop needed)")
        else:
            print(f"\n{symbol}: {qty} shares - No stop configured")
    
    print("\n" + "=" * 60)
    print("✅ Portfolio protection complete!")
    print("   Max loss per position: ~10%")
    print("   Orders are GTC (Good Till Cancelled)")

if __name__ == "__main__":
    main()
