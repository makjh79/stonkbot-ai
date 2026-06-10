#!/usr/bin/env python3
"""
Fix equity calculation in portfolio_data.json
Recalculates all derived values to ensure accuracy
"""

import json
from datetime import datetime

def fix_portfolio_data(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    positions = data['positions']
    
    # Recalculate each position
    total_market_value = 0
    total_cost_basis = 0
    
    for pos in positions:
        qty = pos['qty']
        avg_entry = pos['avg_entry']
        current = pos['current']
        
        # Calculate values
        pos['cost_basis'] = round(qty * avg_entry, 2)
        pos['market_value'] = round(qty * current, 2)
        pos['unrealized_pl'] = round(pos['market_value'] - pos['cost_basis'], 2)
        pos['unrealized_plpc'] = round((pos['unrealized_pl'] / pos['cost_basis']) * 100, 3) if pos['cost_basis'] != 0 else 0
        
        total_market_value += pos['market_value']
        total_cost_basis += pos['cost_basis']
    
    # Update account totals
    cash = data['account']['cash']
    data['account']['equity'] = round(total_market_value + cash, 2)
    data['account']['portfolio_value'] = data['account']['equity']
    
    # Update total P&L
    data['total_pl'] = round(total_market_value - total_cost_basis, 2)
    data['total_pl_pct'] = round((data['total_pl'] / total_cost_basis) * 100, 3) if total_cost_basis != 0 else 0
    
    # Update timestamp
    data['timestamp'] = datetime.now().isoformat()
    
    # Save back
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Fixed {filepath}")
    print(f"  Total Market Value: ${total_market_value:,.2f}")
    print(f"  Cash: ${cash:,.2f}")
    print(f"  Equity: ${data['account']['equity']:,.2f}")
    print(f"  Total P&L: ${data['total_pl']:,.2f} ({data['total_pl_pct']:.2f}%)")
    
    return data

# Fix both files
print("Fixing portfolio data calculations...\n")

web_data = fix_portfolio_data('/root/.openclaw/workspace/hedge-fund-website/portfolio_data.json')
root_data = fix_portfolio_data('/root/.openclaw/workspace/portfolio_data.json')

print("\n✅ Equity calculations fixed in both files!")
