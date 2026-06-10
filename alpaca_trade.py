#!/usr/bin/env python3
"""
Alpaca Trading Module for Howie
Place orders, manage positions, check account
"""

import json
import sys
import requests
from pathlib import Path
from datetime import datetime

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

def load_alpaca_config():
    """Load Alpaca API credentials"""
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def get_headers(config):
    """Get API headers"""
    return {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"],
        "Content-Type": "application/json"
    }

def get_account():
    """Get account information"""
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found")
        return None
    
    url = f"{config.get('trading_url', config.get('base_url'))}/v2/account"
    try:
        response = requests.get(url, headers=get_headers(config), timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def get_positions():
    """Get current positions"""
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found")
        return []
    
    url = f"{config.get('trading_url', config.get('base_url'))}/v2/positions"
    try:
        response = requests.get(url, headers=get_headers(config), timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def place_order(symbol, qty, side="buy", order_type="market", limit_price=None, time_in_force="day"):
    """
    Place an order
    
    Args:
        symbol: Stock symbol (e.g., "AAPL")
        qty: Number of shares
        side: "buy" or "sell"
        order_type: "market", "limit", "stop", "stop_limit"
        limit_price: Required for limit/stop_limit orders
        time_in_force: "day", "gtc", "opg", "cls", "ioc", "fok"
    """
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found")
        return None
    
    url = f"{config.get('trading_url', config.get('base_url'))}/v2/orders"
    
    order_data = {
        "symbol": symbol.upper(),
        "qty": str(qty),
        "side": side.lower(),
        "type": order_type.lower(),
        "time_in_force": time_in_force.lower()
    }
    
    if order_type.lower() in ["limit", "stop_limit"]:
        if limit_price is None:
            print("❌ limit_price required for limit orders")
            return None
        order_data["limit_price"] = str(limit_price)
    
    if order_type.lower() in ["stop", "stop_limit"]:
        if limit_price is None:
            print("❌ stop_price required for stop orders")
            return None
        order_data["stop_price"] = str(limit_price)
    
    try:
        response = requests.post(url, headers=get_headers(config), json=order_data, timeout=15)
        if response.status_code in [200, 201]:
            result = response.json()
            print(f"✅ Order placed!")
            print(f"   ID: {result.get('id')}")
            print(f"   {result.get('side').upper()} {result.get('qty')} {result.get('symbol')} @ {result.get('type')}")
            print(f"   Status: {result.get('status')}")
            return result
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"   {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def get_orders(status="open"):
    """Get orders"""
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found")
        return []
    
    url = f"{config.get('trading_url', config.get('base_url'))}/v2/orders?status={status}"
    try:
        response = requests.get(url, headers=get_headers(config), timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def cancel_order(order_id):
    """Cancel an order"""
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found")
        return False
    
    url = f"{config.get('trading_url', config.get('base_url'))}/v2/orders/{order_id}"
    try:
        response = requests.delete(url, headers=get_headers(config), timeout=15)
        if response.status_code == 200:
            print(f"✅ Order {order_id} cancelled")
            return True
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def close_position(symbol):
    """Close a position (sell all shares)"""
    config = load_alpaca_config()
    if not config:
        print("❌ Alpaca config not found")
        return None
    
    url = f"{config.get('trading_url', config.get('base_url'))}/v2/positions/{symbol.upper()}"
    try:
        response = requests.delete(url, headers=get_headers(config), timeout=15)
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Position closed: {symbol}")
            return result
        else:
            print(f"❌ Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def show_account():
    """Display account summary"""
    account = get_account()
    if not account:
        return
    
    print("=" * 50)
    print(f"📊 ALPACA ACCOUNT - {account.get('account_number', 'N/A')}")
    print("=" * 50)
    print(f"Status: {account.get('status', 'Unknown')}")
    print(f"Currency: {account.get('currency', 'USD')}")
    print(f"Cash: ${float(account.get('cash', 0)):,.2f}")
    print(f"Portfolio Value: ${float(account.get('portfolio_value', 0)):,.2f}")
    print(f"Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
    print(f"Equity: ${float(account.get('equity', 0)):,.2f}")
    print(f"Day Trade Count: {account.get('daytrade_count', 0)} / {account.get('daytrading_buying_power', 'N/A')}")
    print(f"Pattern Day Trader: {account.get('pattern_day_trader', False)}")
    print(f"Trade Multiplier: {account.get('multiplier', 1)}x")
    
    if account.get('trading_blocked'):
        print("\n⚠️ TRADING IS BLOCKED")
    if account.get('account_blocked'):
        print("⚠️ ACCOUNT IS BLOCKED")
    
    return account

def show_positions():
    """Display positions"""
    positions = get_positions()
    
    if not positions:
        print("\n📭 No positions")
        return
    
    print(f"\n📈 POSITIONS ({len(positions)}):")
    print("-" * 80)
    print(f"{'Symbol':<8} {'Qty':>8} {'Entry':>10} {'Current':>10} {'P&L':>12} {'P&L %':>8}")
    print("-" * 80)
    
    total_value = 0
    total_pl = 0
    
    for pos in positions:
        symbol = pos.get('symbol', 'N/A')[:6]
        qty = int(float(pos.get('qty', 0)))
        entry = float(pos.get('avg_entry_price', 0))
        current = float(pos.get('current_price', 0))
        pl = float(pos.get('unrealized_pl', 0))
        pl_pct = float(pos.get('unrealized_plpc', 0)) * 100
        market_value = float(pos.get('market_value', 0))
        
        total_value += market_value
        total_pl += pl
        
        emoji = "🟢" if pl >= 0 else "🔴"
        print(f"{symbol:<8} {qty:>8} ${entry:>9.2f} ${current:>9.2f} {emoji} ${pl:>10.2f} {pl_pct:>+.1f}%")
    
    print("-" * 80)
    emoji = "🟢" if total_pl >= 0 else "🔴"
    print(f"{'TOTAL':<8} {'':>8} {'':>10} {'':>10} {emoji} ${total_pl:>10.2f}")
    print(f"Market Value: ${total_value:,.2f}")

def show_orders(status="open"):
    """Display orders"""
    orders = get_orders(status)
    
    if not orders:
        print(f"\n📭 No {status} orders")
        return
    
    print(f"\n📋 {status.upper()} ORDERS ({len(orders)}):")
    print("-" * 80)
    
    for order in orders:
        symbol = order.get('symbol', 'N/A')
        side = order.get('side', 'N/A').upper()
        qty = order.get('qty', 'N/A')
        order_type = order.get('type', 'N/A').upper()
        status = order.get('status', 'N/A').upper()
        limit = order.get('limit_price', '')
        created = order.get('created_at', 'N/A')[:10]
        
        price_str = f"@ ${limit}" if limit else ""
        print(f"  [{status}] {side} {qty} {symbol} {order_type} {price_str} ({created})")
        print(f"        ID: {order.get('id', 'N/A')[:20]}...")

def trade(symbol, side, qty, order_type="market", limit_price=None):
    """Simple trade helper"""
    print(f"\n🔄 PLACING ORDER")
    print(f"   {side.upper()} {qty} shares of {symbol.upper()} ({order_type})")
    if limit_price:
        print(f"   Limit price: ${limit_price}")
    print()
    
    confirm = input("Confirm? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        print("❌ Cancelled")
        return None
    
    return place_order(symbol, qty, side, order_type, limit_price)

def main():
    """CLI for Alpaca trading"""
    if len(sys.argv) < 2:
        print("Alpaca Trading CLI")
        print()
        print("Usage:")
        print(f"  {sys.argv[0]} account          # Show account info")
        print(f"  {sys.argv[0]} positions        # Show positions")
        print(f"  {sys.argv[0]} orders           # Show open orders")
        print(f"  {sys.argv[0]} buy SYMBOL QTY [TYPE] [PRICE]  # Buy shares")
        print(f"  {sys.argv[0]} sell SYMBOL QTY [TYPE] [PRICE] # Sell shares")
        print(f"  {sys.argv[0]} close SYMBOL     # Close position")
        print(f"  {sys.argv[0]} cancel ORDER_ID  # Cancel order")
        print()
        print("Order types: market, limit, stop, stop_limit")
        print()
        print("Examples:")
        print(f"  {sys.argv[0]} buy HOOD 10")
        print(f"  {sys.argv[0]} buy SOFI 100 limit 15.50")
        print(f"  {sys.argv[0]} sell AVGO 5")
        print(f"  {sys.argv[0]} close META")
        return 0
    
    cmd = sys.argv[1].lower()
    
    if cmd == "account":
        show_account()
        show_positions()
        show_orders()
        
    elif cmd == "positions":
        show_positions()
        
    elif cmd == "orders":
        show_orders("open")
        
    elif cmd == "buy":
        if len(sys.argv) < 4:
            print("Usage: buy SYMBOL QTY [TYPE] [PRICE]")
            return 1
        symbol = sys.argv[2].upper()
        qty = sys.argv[3]
        order_type = sys.argv[4] if len(sys.argv) > 4 else "market"
        price = float(sys.argv[5]) if len(sys.argv) > 5 else None
        trade(symbol, "buy", qty, order_type, price)
        
    elif cmd == "sell":
        if len(sys.argv) < 4:
            print("Usage: sell SYMBOL QTY [TYPE] [PRICE]")
            return 1
        symbol = sys.argv[2].upper()
        qty = sys.argv[3]
        order_type = sys.argv[4] if len(sys.argv) > 4 else "market"
        price = float(sys.argv[5]) if len(sys.argv) > 5 else None
        trade(symbol, "sell", qty, order_type, price)
        
    elif cmd == "close":
        if len(sys.argv) < 3:
            print("Usage: close SYMBOL")
            return 1
        symbol = sys.argv[2].upper()
        close_position(symbol)
        
    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("Usage: cancel ORDER_ID")
            return 1
        cancel_order(sys.argv[2])
        
    else:
        print(f"Unknown command: {cmd}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
