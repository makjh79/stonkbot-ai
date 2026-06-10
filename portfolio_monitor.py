#!/usr/bin/env python3
"""
Portfolio Monitor with 10% Drawdown Protection
Alerts when portfolio drops by set thresholds
"""

import json
import requests
from pathlib import Path
from datetime import datetime

ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")
PORTFOLIO_FILE = Path("/root/.openclaw/workspace/portfolio_baseline.json")

# Alert thresholds
DRAWDOWN_ALERTS = [0.05, 0.10, 0.15]  # 5%, 10%, 15%

def load_alpaca_config():
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def get_account():
    config = load_alpaca_config()
    if not config:
        return None
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"]
    }
    
    url = f"{config.get('base_url')}/v2/account"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error: {e}")
    return None

def get_positions():
    config = load_alpaca_config()
    if not config:
        return []
    
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"]
    }
    
    url = f"{config.get('base_url')}/v2/positions"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error: {e}")
    return []

def load_baseline():
    """Load initial portfolio value for drawdown calc"""
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, 'r') as f:
            return json.load(f)
    return None

def save_baseline(value):
    """Save initial portfolio value"""
    data = {
        "initial_value": value,
        "timestamp": datetime.now().isoformat(),
        "alerts_triggered": []
    }
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def update_alerts(triggered_alert):
    """Record that an alert was triggered"""
    data = load_baseline() or {}
    alerts = data.get("alerts_triggered", [])
    if triggered_alert not in alerts:
        alerts.append(triggered_alert)
        data["alerts_triggered"] = alerts
        with open(PORTFOLIO_FILE, 'w') as f:
            json.dump(data, f, indent=2)

def check_drawdown(current_value):
    """Check if drawdown thresholds hit"""
    baseline = load_baseline()
    if not baseline:
        print(f"📊 Setting baseline: ${current_value:,.2f}")
        save_baseline(current_value)
        return []
    
    initial = baseline.get("initial_value", current_value)
    drawdown = (initial - current_value) / initial
    
    alerts = []
    triggered = baseline.get("alerts_triggered", [])
    
    for threshold in DRAWDOWN_ALERTS:
        if drawdown >= threshold and threshold not in triggered:
            alerts.append({
                "threshold": threshold,
                "drawdown": drawdown,
                "initial": initial,
                "current": current_value
            })
            update_alerts(threshold)
    
    return alerts

def main():
    print("📊 PORTFOLIO MONITOR")
    print("=" * 50)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get account info
    account = get_account()
    if not account:
        print("❌ Could not fetch account")
        return
    
    equity = float(account.get("equity", 0))
    cash = float(account.get("cash", 0))
    
    print(f"💰 Portfolio Equity: ${equity:,.2f}")
    print(f"💵 Cash: ${cash:,.2f}")
    
    # Get positions
    positions = get_positions()
    
    if positions:
        print(f"\n📈 Positions ({len(positions)}):")
        total_pl = 0
        for pos in positions:
            symbol = pos.get("symbol")
            qty = int(float(pos.get("qty", 0)))
            entry = float(pos.get("avg_entry_price", 0))
            current = float(pos.get("current_price", 0))
            pl = float(pos.get("unrealized_pl", 0))
            pl_pct = float(pos.get("unrealized_plpc", 0)) * 100
            total_pl += pl
            
            emoji = "🟢" if pl >= 0 else "🔴"
            print(f"  {emoji} {symbol}: {qty} @ ${entry:.2f} → ${current:.2f} ({pl_pct:+.1f}%)")
        
        print(f"\n📊 Total P&L: ${total_pl:,.2f}")
    else:
        print("\n📭 No positions yet")
    
    # Check drawdown
    drawdown_alerts = check_drawdown(equity)
    
    if drawdown_alerts:
        print("\n" + "🚨" * 25)
        print("⚠️  DRAWDOWN ALERTS TRIGGERED!")
        print("🚨" * 25)
        for alert in drawdown_alerts:
            threshold_pct = int(alert["threshold"] * 100)
            current_dd = alert["drawdown"] * 100
            print(f"\n🔴 {threshold_pct}% DRAWDOWN THRESHOLD HIT!")
            print(f"   Initial: ${alert['initial']:,.2f}")
            print(f"   Current: ${alert['current']:,.2f}")
            print(f"   Drawdown: {current_dd:.1f}%")
        print("\n🛡️ Stop-losses should trigger soon if not already")
    
    # Show baseline
    baseline = load_baseline()
    if baseline:
        initial = baseline.get("initial_value", equity)
        change = ((equity - initial) / initial) * 100
        emoji = "🟢" if change >= 0 else "🔴"
        print(f"\n📊 Since Baseline: {emoji} {change:+.1f}%")
        print(f"   Baseline: ${initial:,.2f} on {baseline.get('timestamp', 'N/A')[:10]}")
    
    print("\n" + "=" * 50)
    print("✅ Monitor complete")

if __name__ == "__main__":
    main()
