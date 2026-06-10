#!/usr/bin/env python3
"""
Buy the dip - Average down on high-conviction AI positions
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

def get_positions():
    """Get current positions"""
    url = f"{get_base_url()}/positions"
    headers = get_headers()
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print(f"Exception: {e}")
        return None

def main():
    print("=" * 60)
    print("💎🙌 BUYING THE DIP - Diamond Hands Strategy")
    print("=" * 60)
    
    # Check account
    acct = get_account()
    if not acct:
        print("❌ Failed to get account info")
        return
    
    cash = float(acct.get('cash', 0))
    print(f"\n💰 Available Cash: ${cash:,.2f}")
    
    # Current positions from our data
    positions_data = {
        "AMD": {"current": 482.75, "unrealized_plpc": -6.71, "qty": 25},
        "PLTR": {"current": 137.34, "unrealized_plpc": -4.72, "qty": 25},
        "SOFI": {"current": 15.985, "unrealized_plpc": -5.04, "qty": 200},
        "AVGO": {"current": 394.59, "unrealized_plpc": -3.71, "qty": 5},
    }
    
    print("\n📉 Current Dips:")
    for sym, data in positions_data.items():
        print(f"   {sym}: {data['unrealized_plpc']:+.2f}% (${data['current']:.2f})")
    
    # Define dip-buying strategy
    # Averaging down on high-conviction AI plays
    trades = [
        {
            "symbol": "AMD", 
            "qty": 10,  # ~$4,800 at current price
            "side": "buy", 
            "reason": "Buy the dip -6.7%, AI chip leader, MI300 ramping"
        },
        {
            "symbol": "PLTR", 
            "qty": 20,  # ~$2,700 at current price
            "side": "buy", 
            "reason": "Buy the dip -4.7%, gov AI contracts sticky, AIP growing"
        },
    ]
    
    total_cost = sum(t['qty'] * positions_data[t['symbol']]['current'] for t in trades)
    
    print(f"\n🎯 EXECUTING DIP BUYS:")
    print(f"   Total deployment: ~${total_cost:,.0f}")
    print(f"   Cash remaining: ~${cash - total_cost:,.0f}")
    print()
    
    executed = []
    failed = []
    
    for trade in trades:
        symbol = trade['symbol']
        qty = trade['qty']
        price = positions_data[symbol]['current']
        cost = qty * price
        
        print(f"\n📈 BUY {qty} {symbol} @ ~${price:.2f} = ${cost:,.0f}")
        print(f"   Reason: {trade['reason']}")
        
        result = submit_order(symbol, qty, trade['side'])
        if result:
            print(f"   ✅ Order submitted: {result.get('id')}")
            print(f"   Status: {result.get('status')}")
            executed.append({
                "symbol": symbol,
                "qty": qty,
                "side": "buy",
                "timestamp": datetime.now().isoformat(),
                "reason": trade['reason'],
                "estimated_cost": cost
            })
        else:
            print(f"   ❌ Failed to submit order")
            failed.append(symbol)
    
    # Log the trades
    log_file = Path("/root/.openclaw/workspace/hedge-fund-website/TRADES_LOG.md")
    with open(log_file, "a") as f:
        f.write(f"\n\n---\n\n## {datetime.now().strftime('%B %d, %Y - %I:%M %p UTC')} - BUYING THE DIP 💎🙌\n\n")
        f.write(f"**Decision:** Average down on high-conviction AI positions during market pullback\n\n")
        f.write(f"**Market Context:**\n")
        f.write(f"- Portfolio down -2.76% (-$1,588)\n")
        f.write(f"- Cash available: ${cash:,.2f}\n")
        f.write(f"- Strategy: Diamond hands, buy weakness in strong thesis plays\n\n")
        f.write(f"**Trades Executed:**\n\n")
        for t in executed:
            f.write(f"| {t['symbol']} | BUY | {t['qty']} | ${t['estimated_cost']:,.0f} | {t['reason']} | ✅ |\n")
        f.write(f"\n**Rationale:**\n")
        f.write(f"- AMD: Core AI position, MI300 chips gaining traction, temporary pullback\n")
        f.write(f"- PLTR: Government AI contracts provide stability, AIP commercial growing\n")
        f.write(f"- Avoided SOFI: Most speculative, already 200 shares, let it ride\n")
        f.write(f"- Avoided AVGO: Smaller position, less conviction vs AMD/PLTR\n")
        f.write(f"\n**Cash after deployment:** ~${cash - total_cost:,.0f}\n")
    
    print("\n" + "=" * 60)
    print(f"✅ EXECUTED: {len(executed)} orders")
    print(f"❌ FAILED: {len(failed)} orders")
    print("=" * 60)
    
    return executed

if __name__ == "__main__":
    main()
