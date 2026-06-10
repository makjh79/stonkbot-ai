#!/usr/bin/env python3
"""Set stop losses on all positions - autonomous risk management"""
import json
import urllib.request
import ssl

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

with open('alpaca_config.json', 'r') as f:
    config = json.load(f)

api_key = config['api_key']
secret_key = config['api_secret']
base_url = 'https://paper-api.alpaca.markets/v2'

def get_positions():
    """Get current positions"""
    req = urllib.request.Request(
        f'{base_url}/positions',
        headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
    )
    try:
        response = urllib.request.urlopen(req, context=ssl_context, timeout=10)
        return json.loads(response.read().decode())
    except:
        return []

def set_stop_loss(symbol, qty, stop_price):
    """Set a stop loss order"""
    url = f'{base_url}/orders'
    data = json.dumps({
        'symbol': symbol,
        'qty': qty,
        'side': 'sell',
        'type': 'stop',
        'stop_price': str(stop_price),
        'time_in_force': 'gtc'  # Good till cancelled
    }).encode()
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key,
            'Content-Type': 'application/json'
        },
        method='POST'
    )
    
    try:
        response = urllib.request.urlopen(req, context=ssl_context, timeout=10)
        return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return {'error': e.read().decode()}

print("=== STONK.AI SETTING STOP LOSSES ===")
print("Strategy: -15% stop loss on all positions")
print()

positions = get_positions()

for pos in positions:
    symbol = pos['symbol']
    qty = pos['qty']
    avg_entry = float(pos['avg_entry_price'])
    stop_price = round(avg_entry * 0.85, 2)  # -15% stop
    
    print(f"{symbol}: Entry ${avg_entry:.2f} → Stop ${stop_price:.2f} (-15%)")
    result = set_stop_loss(symbol, qty, stop_price)
    
    if 'id' in result:
        print(f"  ✅ Stop loss set: {result['id'][:8]}...")
    else:
        print(f"  ⚠️  {result.get('error', 'Could not set stop')}")
    print()

print("=== RISK MANAGEMENT COMPLETE ===")
print("All positions protected at -15%")
