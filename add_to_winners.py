#!/usr/bin/env python3
"""Add to winning positions - autonomous trading"""
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

def place_order(symbol, qty, side='buy', order_type='market'):
    """Place an order with Alpaca"""
    url = f'{base_url}/orders'
    data = json.dumps({
        'symbol': symbol,
        'qty': qty,
        'side': side,
        'type': order_type,
        'time_in_force': 'day'
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
        result = json.loads(response.read().decode())
        return result
    except Exception as e:
        return {'error': str(e)}

# Strategy: Add to winners (averaging up)
# SOFI leading at +2.85% - add 100 more shares
# META strong at +2.01% - add 2 more shares  
# NVDA AI play at +0.70% - add 5 more shares

orders = [
    {'symbol': 'SOFI', 'qty': 100, 'reason': 'Leading +2.85%, averaging up'},
    {'symbol': 'META', 'qty': 2, 'reason': 'Strong +2.01%, momentum play'},
    {'symbol': 'NVDA', 'qty': 5, 'reason': 'AI thesis intact +0.70%'},
]

print("=== STONK.AI AUTONOMOUS TRADES ===")
print(f"Deploying capital into winners...")
print()

for order in orders:
    print(f"Buying {order['qty']} {order['symbol']} - {order['reason']}")
    result = place_order(order['symbol'], order['qty'])
    if 'id' in result:
        print(f"  ✅ Order placed: {result['id']}")
    else:
        print(f"  ❌ Error: {result.get('error', 'Unknown')}")
    print()

print("=== TRADES COMPLETE ===")
print("New positions will reflect in portfolio within minutes")
