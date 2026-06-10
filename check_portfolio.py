#!/usr/bin/env python3
import json
import alpaca_trade_api as tradeapi

# Load API keys
with open('alpaca_config.json', 'r') as f:
    config = json.load(f)

api = tradeapi.REST(config['api_key'], config['secret_key'], config['base_url'])

# Get account info
account = api.get_account()
print('=== ACCOUNT STATUS ===')
print(f'Account ID: {account.id}')
print(f'Portfolio Value: ${float(account.portfolio_value):,.2f}')
print(f'Cash: ${float(account.cash):,.2f}')
print(f'Buying Power: ${float(account.buying_power):,.2f}')
print(f'Equity: ${float(account.equity):,.2f}')
print()

# Get positions
positions = api.list_positions()
print('=== POSITIONS ===')
if positions:
    print(f'Total positions: {len(positions)}')
    print()
    for pos in positions:
        pnl = float(pos.unrealized_pl)
        pnl_pct = float(pos.unrealized_plpc) * 100
        print(f'{pos.symbol}: {pos.qty} shares @ ${float(pos.avg_entry_price):.2f}')
        print(f'  Current: ${float(pos.current_price):.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)')
        print()
else:
    print('No positions yet - orders pending fill')

# Get orders
orders = api.list_orders(status='open')
print('=== OPEN ORDERS ===')
if orders:
    for order in orders:
        print(f'{order.symbol}: {order.qty} shares - {order.side} @ {order.type}')
else:
    print('No open orders')

# Get last 5 filled orders
print()
print('=== RECENT FILLS ===')
filled = api.list_orders(status='closed', limit=10)
if filled:
    for order in filled:
        if order.filled_qty and int(order.filled_qty) > 0:
            print(f'{order.symbol}: {order.filled_qty}/{order.qty} filled @ ${float(order.filled_avg_price or 0):.2f}')
else:
    print('No filled orders yet')
