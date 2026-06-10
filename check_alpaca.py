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

# Account
req = urllib.request.Request(
    f'{base_url}/account',
    headers={
        'APCA-API-KEY-ID': api_key,
        'APCA-API-SECRET-KEY': secret_key
    }
)

try:
    response = urllib.request.urlopen(req, context=ssl_context, timeout=10)
    data = json.loads(response.read().decode())
    print('=== ACCOUNT STATUS ===')
    print(f"Account ID: {data.get('id', 'N/A')}")
    print(f"Portfolio Value: ${float(data.get('portfolio_value', 0)):,.2f}")
    print(f"Cash: ${float(data.get('cash', 0)):,.2f}")
    print(f"Buying Power: ${float(data.get('buying_power', 0)):,.2f}")
    print(f"Equity: ${float(data.get('equity', 0)):,.2f}")
    print(f"Status: {data.get('status', 'N/A')}")
    print()
    
    # Positions
    req2 = urllib.request.Request(
        f'{base_url}/positions',
        headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
    )
    response2 = urllib.request.urlopen(req2, context=ssl_context, timeout=10)
    positions = json.loads(response2.read().decode())
    
    print('=== POSITIONS ===')
    if positions:
        print(f"Total positions: {len(positions)}")
        print()
        for pos in positions:
            pnl = float(pos.get('unrealized_pl', 0))
            pnl_pct = float(pos.get('unrealized_plpc', 0)) * 100
            print(f"{pos.get('symbol', 'N/A')}: {pos.get('qty', '0')} shares @ ${float(pos.get('avg_entry_price', 0)):.2f}")
            print(f"  Current: ${float(pos.get('current_price', 0)):.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
            print()
    else:
        print("No positions yet - orders pending fill")
        print()
    
    # Orders
    req3 = urllib.request.Request(
        f'{base_url}/orders?status=open',
        headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
    )
    response3 = urllib.request.urlopen(req3, context=ssl_context, timeout=10)
    orders = json.loads(response3.read().decode())
    
    print('=== OPEN ORDERS ===')
    if orders:
        for order in orders:
            print(f"{order.get('symbol', 'N/A')}: {order.get('qty', '0')} shares - {order.get('side', 'N/A')} @ {order.get('type', 'N/A')}")
    else:
        print("No open orders")
        print()
    
    # Recent fills
    req4 = urllib.request.Request(
        f'{base_url}/orders?status=closed&limit=10',
        headers={
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
    )
    response4 = urllib.request.urlopen(req4, context=ssl_context, timeout=10)
    filled = json.loads(response4.read().decode())
    
    print('=== RECENT FILLS ===')
    filled_orders = [o for o in filled if o.get('filled_qty') and int(o.get('filled_qty', 0)) > 0]
    if filled_orders:
        for order in filled_orders[:5]:
            print(f"{order.get('symbol', 'N/A')}: {order.get('filled_qty', '0')}/{order.get('qty', '0')} filled @ ${float(order.get('filled_avg_price') or 0):.2f}")
    else:
        print("No filled orders yet")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
