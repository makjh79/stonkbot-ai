#!/usr/bin/env python3
"""
Hedge Fund Manager - Active Portfolio Management
$10,000 High-Beta Portfolio
Strategy: Beat S&P 500 with aggressive growth + active management
"""

import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")
PORTFOLIO_FILE = Path("/root/.openclaw/workspace/active_portfolio.json")

# Portfolio Configuration
PORTFOLIO = {
    "capital": 10000,
    "strategy": "High-Beta Growth",
    "objective": "Beat S&P 500 by 10%+",
    "risk_level": "HIGH",
    "rebalance_frequency": "weekly",
    "stop_loss_default": 0.15,  # -15% stop
    "take_profit_default": 0.25,  # +25% target
    "max_position_size": 0.30,  # 30% max in single stock
}

CURRENT_HOLDINGS = {
    "NVDA": {"shares": 12, "avg_cost": None, "stop_loss": None, "target": None},
    "PLTR": {"shares": 25, "avg_cost": None, "stop_loss": None, "target": None},
    "CRWD": {"shares": 3, "avg_cost": None, "stop_loss": None, "target": None},
    "APP": {"shares": 8, "avg_cost": None, "stop_loss": None, "target": None},
    "SOFI": {"shares": 100, "avg_cost": None, "stop_loss": None, "target": None},
    "AVGO": {"shares": 5, "avg_cost": None, "stop_loss": None, "target": None},
    "META": {"shares": 3, "avg_cost": None, "stop_loss": None, "target": None},
    "HOOD": {"shares": 25, "avg_cost": None, "stop_loss": None, "target": None},
    "SCHD": {"shares": 30, "avg_cost": None, "stop_loss": None, "target": None},
    "SGOV": {"shares": 15, "avg_cost": None, "stop_loss": None, "target": None},
}

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

def get_positions():
    """Get current positions"""
    config = load_alpaca_config()
    if not config:
        return []
    
    url = f"{config['base_url']}/v2/positions"
    try:
        resp = requests.get(url, headers=get_headers(config), timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error: {e}")
    return []

def get_account():
    """Get account info"""
    config = load_alpaca_config()
    if not config:
        return None
    
    url = f"{config['base_url']}/v2/account"
    try:
        resp = requests.get(url, headers=get_headers(config), timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error: {e}")
    return None

def place_stop_loss(symbol, qty, stop_price):
    """Place stop-loss order"""
    config = load_alpaca_config()
    if not config:
        return None
    
    url = f"{config['base_url']}/v2/orders"
    order = {
        "symbol": symbol,
        "qty": str(qty),
        "side": "sell",
        "type": "stop",
        "stop_price": str(stop_price),
        "time_in_force": "gtc"
    }
    
    try:
        resp = requests.post(url, headers=get_headers(config), json=order, timeout=15)
        if resp.status_code in [200, 201]:
            return resp.json()
    except Exception as e:
        print(f"Error placing stop: {e}")
    return None

def cancel_all_orders():
    """Cancel all open orders"""
    config = load_alpaca_config()
    if not config:
        return
    
    url = f"{config['base_url']}/v2/orders"
    try:
        resp = requests.delete(url, headers=get_headers(config), timeout=15)
        return resp.status_code == 200
    except:
        pass
    return False

def manage_portfolio():
    """Main portfolio management function"""
    print("=" * 70)
    print("🚀 HEDGE FUND MANAGER - ACTIVE PORTFOLIO")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get account status
    account = get_account()
    if not account:
        print("❌ Cannot access account")
        return
    
    equity = float(account.get('equity', 0))
    cash = float(account.get('cash', 0))
    
    print(f"💰 Portfolio Equity: ${equity:,.2f}")
    print(f"💵 Cash: ${cash:,.2f}")
    print()
    
    # Get positions
    positions = get_positions()
    
    if not positions:
        print("📭 No positions yet - waiting for market open")
        print("⏰ Market opens 9:30 AM ET (~30 minutes)")
        return
    
    print(f"📊 CURRENT HOLDINGS ({len(positions)}):")
    print("-" * 70)
    print(f"{'Symbol':<8} {'Qty':>8} {'Entry':>10} {'Current':>10} {'P&L':>12} {'P&L%':>8}")
    print("-" * 70)
    
    total_value = 0
    total_pl = 0
    actions = []
    
    for pos in positions:
        symbol = pos.get('symbol', 'N/A')
        qty = int(float(pos.get('qty', 0)))
        entry = float(pos.get('avg_entry_price', 0))
        current = float(pos.get('current_price', 0))
        pl = float(pos.get('unrealized_pl', 0))
        pl_pct = float(pos.get('unrealized_plpc', 0)) * 100
        market_value = float(pos.get('market_value', 0))
        
        total_value += market_value
        total_pl += pl
        
        emoji = "🟢" if pl >= 0 else "🔴"
        print(f"{emoji} {symbol:<8} {qty:>8} ${entry:>9.2f} ${current:>9.2f} ${pl:>10.2f} {pl_pct:>+.1f}%")
        
        # Check if stop-loss needed
        if symbol in CURRENT_HOLDINGS:
            stop_pct = 0.15  # -15% stop
            target_pct = 0.25  # +25% target
            
            stop_price = round(entry * (1 - stop_pct), 2)
            target_price = round(entry * (1 + target_pct), 2)
            
            if pl_pct <= -15:
                actions.append(f"🛑 Consider selling {symbol} - at stop loss")
            elif pl_pct >= 25:
                actions.append(f"🎯 {symbol} hit target - consider taking profits")
    
    print("-" * 70)
    print(f"{'TOTAL':<8} {'':>8} {'':>10} {'':>10} ${total_pl:>10.2f}")
    print(f"Market Value: ${total_value:,.2f}")
    
    # Actions
    if actions:
        print("\n📋 RECOMMENDED ACTIONS:")
        for action in actions:
            print(f"  {action}")
    else:
        print("\n✅ All positions within risk parameters")
    
    # Performance vs S&P
    print("\n📈 PERFORMANCE TARGET:")
    print(f"  Current P&L: ${total_pl:,.2f} ({(total_pl/total_value)*100 if total_value else 0:+.1f}%)")
    print(f"  Target: Beat S&P 500 by 10%+ over 3-6 months")
    print(f"  Strategy: High-beta growth with active management")
    
    print("\n" + "=" * 70)
    print("Next check: Monitor every 30 minutes during market hours")
    print("Auto-actions: Stop-loss alerts, profit-taking signals")
    print("=" * 70)

def set_initial_stops():
    """Set initial stop-losses after positions fill"""
    print("Setting initial stop-losses...")
    
    positions = get_positions()
    if not positions:
        print("No positions to set stops on")
        return
    
    for pos in positions:
        symbol = pos.get('symbol')
        qty = int(float(pos.get('qty', 0)))
        entry = float(pos.get('avg_entry_price', 0))
        
        # Set 15% stop loss
        stop_price = round(entry * 0.85, 2)
        
        result = place_stop_loss(symbol, qty, stop_price)
        if result:
            print(f"✅ Stop-loss set for {symbol} @ ${stop_price} (-15%)")
        else:
            print(f"❌ Failed to set stop for {symbol}")

if __name__ == "__main__":
    manage_portfolio()
