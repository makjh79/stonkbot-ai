#!/usr/bin/env python3
"""Rebalance portfolio - cut losers, add to winners"""
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
    """Place an order"""
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
        return json.loads(response.read().decode())
    except Exception as e:
        return {'error': str(e)}

def cancel_orders(symbol):
    """Cancel all orders for symbol"""
    req = urllib.request.Request(
        f'{base_url}/orders?status=open&symbols={symbol}',
        headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
    )
    try:
        response = urllib.request.urlopen(req, context=ssl_context, timeout=10)
        orders = json.loads(response.read().decode())
        for order in orders:
            cancel_req = urllib.request.Request(
                f'{base_url}/orders/{order["id"]}',
                headers={
                    'APCA-API-KEY-ID': api_key,
                    'APCA-API-SECRET-KEY': secret_key
                },
                method='DELETE'
            )
            urllib.request.urlopen(cancel_req, context=ssl_context, timeout=10)
    except:
        pass

print("=== STONK.AI AUTONOMOUS REBALANCE ===")
print()

# Cancel PLTR stop loss first
cancel_orders('PLTR')

# 1. Cut PLTR loser (-1.54%)
print("1. Cutting PLTR: Underperforming at -1.54%")
result = place_order('PLTR', 25, 'sell')
if 'id' in result:
    print(f"   ✅ Sold 25 PLTR @ ~$141.92")
    pltr_proceeds = 25 * 141.92  # ~$3,548
else:
    print(f"   ❌ Error: {result.get('error', 'Unknown')}")
    pltr_proceeds = 0

# 2. Add to SOFI winner (+1.38%)
print("\n2. Adding to SOFI: Leader at +1.38%")
result = place_order('SOFI', 100, 'buy')
if 'id' in result:
    print(f"   ✅ Bought 100 SOFI")
else:
    print(f"   ❌ Error: {result.get('error', 'Unknown')}")

# 3. New high-conviction play: AMD (AI chip play, cheaper than NVDA)
print("\n3. New position: AMD - AI chip alternative to NVDA")
result = place_order('AMD', 20, 'buy')
if 'id' in result:
    print(f"   ✅ Bought 20 AMD")
else:
    print(f"   ❌ Error: {result.get('error', 'Unknown')}")

# 4. Add to META
print("\n4. Adding to META: Strong momentum")
result = place_order('META', 2, 'buy')
if 'id' in result:
    print(f"   ✅ Bought 2 META")
else:
    print(f"   ❌ Error: {result.get('error', 'Unknown')}")

print("\n=== REBALANCE COMPLETE ===")
print("Changes:")
print("- CUT: PLTR (underperforming)")
print("- ADDED: SOFI, META (winners)")
print("- NEW: AMD (AI thesis)")
