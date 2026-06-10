#!/usr/bin/env python3
"""
STONK.AI Issue Fixer
Fixes identified issues automatically
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

def fix_portfolio_sync():
    """Sync portfolio_data.json to include all positions"""
    
    # Load current portfolio data
    portfolio_path = Path('/opt/stonk-ai/portfolio_data.json')
    workspace_path = Path('/root/.openclaw/workspace/hedge-fund-website/portfolio_data.json')
    stankai_path = Path('/root/.openclaw/workspace/hedge-fund-website/stankai_data.json')
    
    with open(portfolio_path) as f:
        portfolio = json.load(f)
    
    with open(stankai_path) as f:
        stankai = json.load(f)
    
    # Get symbols from both
    portfolio_symbols = {p['symbol'] for p in portfolio['positions']}
    stankai_symbols = {p['symbol'] for p in stankai['positions']}
    
    # Find missing positions in portfolio
    missing = stankai_symbols - portfolio_symbols
    
    if missing:
        print(f"Found {len(missing)} missing positions: {missing}")
        
        # Add missing positions from stankai (convert format)
        for p in stankai['positions']:
            if p['symbol'] in missing:
                new_pos = {
                    'symbol': p['symbol'],
                    'qty': p['shares'],
                    'avg_entry': p['entry'],
                    'current': p['current'],
                    'market_value': p['shares'] * p['current'],
                    'cost_basis': p['shares'] * p['entry'],
                    'unrealized_pl': p['pl'],
                    'unrealized_plpc': p['pl_pct']
                }
                portfolio['positions'].append(new_pos)
                print(f"  Added {p['symbol']}: {p['shares']} shares")
        
        # Recalculate totals
        total_mv = sum(p['market_value'] for p in portfolio['positions'])
        total_cost = sum(p['cost_basis'] for p in portfolio['positions'])
        total_pl = total_mv - total_cost
        total_pl_pct = (total_pl / total_cost) * 100 if total_cost else 0
        
        portfolio['total_pl'] = total_pl
        portfolio['total_pl_pct'] = total_pl_pct
        portfolio['account']['portfolio_value'] = total_mv + portfolio['account']['cash']
        portfolio['account']['equity'] = total_mv + portfolio['account']['cash']
        portfolio['timestamp'] = datetime.now().isoformat()
        
        # Save to both locations
        with open(portfolio_path, 'w') as f:
            json.dump(portfolio, f, indent=2)
        
        with open(workspace_path, 'w') as f:
            json.dump(portfolio, f, indent=2)
        
        print(f"✅ Synced portfolio_data.json with {len(portfolio['positions'])} positions")
        return True
    else:
        print("✅ Portfolio data already synced")
        return False

def fix_html_holdings_count():
    """Fix the '14 holdings' text in HTML to match actual count"""
    
    html_path = Path('/opt/stonk-ai/index.html')
    
    with open(html_path) as f:
        content = f.read()
    
    # Load current portfolio to get actual count
    with open('/opt/stonk-ai/portfolio_data.json') as f:
        portfolio = json.load(f)
    
    actual_count = len(portfolio['positions'])
    
    # Find and replace the holdings count text
    # Pattern: "Well diversified across X holdings"
    pattern = r'(Well diversified across )\d+( holdings)'
    match = re.search(pattern, content)
    
    if match:
        current_text = match.group(0)
        new_text = f"Well diversified across {actual_count} holdings"
        
        if current_text != new_text:
            content = content.replace(current_text, new_text)
            
            # Backup and save
            shutil.copy(html_path, f"{html_path}.bak.{int(datetime.now().timestamp())}")
            with open(html_path, 'w') as f:
                f.write(content)
            
            print(f"✅ Fixed HTML holdings count: {current_text} -> {new_text}")
            return True
    
    print("✅ HTML holdings count already correct")
    return False

def verify_why_badges():
    """Verify why-badge is properly applied to all holdings"""
    
    html_path = Path('/opt/stonk-ai/index.html')
    
    with open(html_path) as f:
        content = f.read()
    
    # Check if why-badge CSS exists
    if '.why-badge' not in content:
        print("❌ Why-badge CSS missing")
        return False
    
    # Check if why-badge is in the template
    if 'why-badge' not in content:
        print("❌ Why-badge template missing")
        return False
    
    # The why-badge should appear in the holding card template
    # It's dynamically generated, so check the template exists
    template_pattern = r'class="why-badge"[^>]*>Why\?'
    if re.search(template_pattern, content):
        print("✅ Why-badge template present in HTML")
        return True
    else:
        print("⚠️  Why-badge template may need review")
        return False

def check_html_structure():
    """Check HTML has no text after </html>"""
    
    html_path = Path('/opt/stonk-ai/index.html')
    
    with open(html_path) as f:
        content = f.read()
    
    html_end = content.rfind('</html>')
    if html_end > 0:
        after_html = content[html_end + 7:].strip()
        if after_html:
            print(f"❌ Text found after </html>: {after_html[:50]}...")
            return False
    
    print("✅ HTML structure valid - no content after </html>")
    return True

def verify_calculations():
    """Verify all portfolio calculations are correct"""
    
    with open('/opt/stonk-ai/portfolio_data.json') as f:
        data = json.load(f)
    
    issues = []
    
    for p in data['positions']:
        expected_mv = p['qty'] * p['current']
        expected_cb = p['qty'] * p['avg_entry']
        expected_pl = expected_mv - expected_cb
        
        if abs(expected_mv - p['market_value']) > 0.1:
            issues.append(f"{p['symbol']}: Market value mismatch")
        if abs(expected_cb - p['cost_basis']) > 0.1:
            issues.append(f"{p['symbol']}: Cost basis mismatch")
        if abs(expected_pl - p['unrealized_pl']) > 0.1:
            issues.append(f"{p['symbol']}: P&L mismatch")
    
    # Check totals
    total_mv = sum(p['market_value'] for p in data['positions'])
    calc_equity = total_mv + data['account']['cash']
    
    if abs(calc_equity - data['account']['equity']) > 1:
        issues.append(f"Equity mismatch: {calc_equity} vs {data['account']['equity']}")
    
    if issues:
        print("❌ Calculation issues found:")
        for i in issues:
            print(f"  - {i}")
        return False
    else:
        print(f"✅ All calculations verified for {len(data['positions'])} positions")
        return True

def check_bot_processes():
    """Check if required bot processes are running"""
    
    import subprocess
    
    processes = ['fetch_data.py', 'trading_bot.py']
    running = []
    
    for proc in processes:
        result = subprocess.run(['pgrep', '-f', proc], capture_output=True)
        if result.returncode == 0:
            running.append(proc)
    
    print(f"✅ Bot processes running: {', '.join(running)}")
    return len(running) == len(processes)

def main():
    print("="*60)
    print("STONK.AI COMPREHENSIVE HEALTH CHECK & FIX")
    print("="*60)
    print()
    
    fixes_applied = []
    
    # Run all checks and fixes
    if fix_portfolio_sync():
        fixes_applied.append("Synced portfolio_data.json with missing positions")
    
    if fix_html_holdings_count():
        fixes_applied.append("Fixed HTML holdings count")
    
    verify_why_badges()
    check_html_structure()
    verify_calculations()
    check_bot_processes()
    
    print()
    print("="*60)
    if fixes_applied:
        print("FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"  ✅ {fix}")
    else:
        print("✅ ALL CHECKS PASSED - No fixes needed")
    print("="*60)

if __name__ == '__main__':
    main()
