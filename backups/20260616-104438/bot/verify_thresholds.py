#!/usr/bin/env python3
"""
Verify RSI and volume thresholds are consistent across all components
"""
import re
import sys

def extract_from_file(filepath, patterns):
    """Extract values from file using regex patterns"""
    results = {}
    try:
        with open(filepath) as f:
            content = f.read()
        for name, pattern in patterns.items():
            matches = re.findall(pattern, content)
            if matches:
                results[name] = matches[0] if isinstance(matches[0], str) else matches[0][0]
    except Exception as e:
        print(f"⚠️  Could not read {filepath}: {e}")
    return results

def verify_thresholds():
    """Check all components use same thresholds"""
    errors = []
    
    # Extract from Trading Bot
    bot_patterns = {
        'rsi_entry': r'RSI_ENTRY_THRESHOLD\s*=\s*(\d+\.?\d*)',
        'volume_mult': r'VOLUME_MULTIPLIER\s*=\s*(\d+\.?\d*)',
        'stop_loss': r'stop.*loss.*-?(\d+)%|STOP_LOSS.*=.*?(-?\d+)',
    }
    bot_values = extract_from_file('/opt/stonk-ai/trading_bot.py', bot_patterns)
    
    # Extract from Watchlist Manager
    manager_patterns = {
        'remove_rsi_above': r"'remove_rsi_above':\s*(\d+)",
        'remove_rsi_below': r"'remove_rsi_below':\s*(\d+)",
        'add_rsi_min': r"'add_rsi_min':\s*(\d+)",
        'add_rsi_max': r"'add_rsi_max':\s*(\d+)",
    }
    manager_values = extract_from_file('/opt/stonk-ai/dynamic_watchlist_manager.py', manager_patterns)
    
    # Extract from Website
    web_patterns = {
        'rsi_display': r'RSI\s*<\s*(\d+)|RSI\s*&lt;\s*(\d+)',
        'volume_display': r'(\d+\.?\d*)x\s*average|volume',
    }
    web_values = extract_from_file('/var/www/hedge-fund-website/index.html', web_patterns)
    
    # Check consistency
    print("="*60)
    print("THRESHOLD CONSISTENCY CHECK")
    print("="*60)
    
    print("\n📊 Bot Entry Criteria:")
    if 'rsi_entry' in bot_values:
        print(f"   RSI Entry: < {bot_values['rsi_entry']}")
    if 'volume_mult' in bot_values:
        print(f"   Volume: {bot_values['volume_mult']}x average")
    
    print("\n📊 Manager Criteria:")
    if 'remove_rsi_above' in manager_values:
        print(f"   Remove when RSI > {manager_values['remove_rsi_above']}")
    if 'remove_rsi_below' in manager_values:
        print(f"   Remove when RSI < {manager_values['remove_rsi_below']}")
    if 'add_rsi_min' in manager_values and 'add_rsi_max' in manager_values:
        print(f"   Add when RSI {manager_values['add_rsi_min']}-{manager_values['add_rsi_max']}")
    
    print("\n📊 Website Display:")
    if 'rsi_display' in web_values:
        print(f"   Shows RSI < {web_values['rsi_display']}")
    
    # Verify no conflicts
    print("\n" + "="*60)
    
    # Check: Bot entry (RSI < X) shouldn't conflict with manager removal (RSI < Y)
    if 'rsi_entry' in bot_values and 'remove_rsi_below' in manager_values:
        bot_rsi = float(bot_values['rsi_entry'])
        manager_remove = float(manager_values['remove_rsi_below'])
        
        if bot_rsi <= manager_remove:
            errors.append(f"❌ CONFLICT: Bot buys at RSI <{bot_rsi}, but Manager removes at RSI <{manager_remove}")
            errors.append("   Fix: Lower manager's 'remove_rsi_below' or raise bot's 'RSI_ENTRY_THRESHOLD'")
        else:
            buffer = bot_rsi - manager_remove
            print(f"✅ RSI Buffer: {buffer} points (Bot <{bot_rsi}, Manager removes <{manager_remove})")
    
    # Check: Manager addition range should overlap with bot entry
    if 'add_rsi_min' in manager_values and 'rsi_entry' in bot_values:
        add_min = float(manager_values['add_rsi_min'])
        bot_rsi = float(bot_values['rsi_entry'])
        
        if add_min > bot_rsi:
            errors.append(f"❌ GAP: Manager adds at RSI >{add_min}, but Bot buys at <{bot_rsi}")
            errors.append("   Fix: Lower 'add_rsi_min' to catch oversold stocks before bot buys")
    
    # Summary
    if errors:
        print("❌ THRESHOLD CONFLICTS:")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)
    else:
        print("✅ ALL THRESHOLDS CONSISTENT")
        sys.exit(0)

if __name__ == '__main__':
    verify_thresholds()
