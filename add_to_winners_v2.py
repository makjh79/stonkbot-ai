#!/usr/bin/env python3
"""Add to winners - autonomous capital deployment"""
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

def place_order(symbol, qty, side='buy'):
    url = f'{base_url}/orders'
    data = json.dumps({
        'symbol': symbol,
        'qty': qty,
        'side': side,
        'type': 'market',
        'time_in_force': 'day'
    }).encode()
    
    req = urllib.request.Request(
        url, data=data,
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
    except Exception as e:
        return {'error': str(e)}

print("=== STONK.AI ADDING TO WINNERS ===")
print()

# Deploy $5K more into winners
trades = [
    ('SOFI', 150, 'Leader +1.38%, strong momentum'),
    ('APP', 5, 'High conviction AI play +1.50%'),
    ('AMD', 25, 'NEW: AI chip value play (cheaper than NVDA)'),
]

for symbol, qty, reason in trades:
    print(f"Buying {qty} {symbol} - {reason}")
    result = place_order(symbol, qty)
    if 'id' in result:
        print(f"  ✅ Order: {result['id'][:8]}...")
    else:
        print(f"  ❌ {result.get('error', 'Failed')}")
    print()

print("=== CAPITAL DEPLOYED ===")
print("~$6K deployed into winners + new AMD position")
