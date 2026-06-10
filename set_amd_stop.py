#!/usr/bin/env python3
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

def place_order(symbol, qty, side, order_type, stop_price=None):
    url = f'{base_url}/orders'
    order_data = {
        'symbol': symbol,
        'qty': qty,
        'side': side,
        'type': order_type,
        'time_in_force': 'gtc'
    }
    if stop_price:
        order_data['stop_price'] = str(stop_price)
    
    data = json.dumps(order_data).encode()
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

print("Setting stop loss on AMD...")
# AMD ~$125, stop at $106 (-15%)
result = place_order('AMD', 25, 'sell', 'stop', 106.25)
if 'id' in result:
    print(f"✅ AMD stop loss set at $106.25")
else:
    print(f"Error: {result.get('error', 'Unknown')}")
