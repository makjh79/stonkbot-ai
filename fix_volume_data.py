#!/usr/bin/env python3
"""
Fix to add volume data to fetch_ai_watchlist.py

This script modifies the fetch_ai_watchlist.py to include volume and avg_volume fields.
"""

import re

# Read the current file
with open('/opt/stonk-ai/fetch_ai_watchlist.py', 'r') as f:
    content = f.read()

# Find the section where prices are saved and add volume data
# We need to find where symbol_bars is used and extract volume info

# First, let's add volume extraction after the bars data is fetched
old_bars_section = """            # Calculate RSI from Alpaca bars data (if available)
                    if symbol in bars_data:
                        symbol_bars = bars_data[symbol]
                        if len(symbol_bars) >= 15:
                            price_history = [bar['c'] for bar in symbol_bars]
                            rsi = calculate_rsi(price_history)"""

new_bars_section = """            # Calculate RSI from Alpaca bars data (if available)
            current_volume = None
            avg_volume = None
            if symbol in bars_data:
                symbol_bars = bars_data[symbol]
                if len(symbol_bars) >= 15:
                    price_history = [bar['c'] for bar in symbol_bars]
                    rsi = calculate_rsi(price_history)
                
                # Extract volume data from bars
                if len(symbol_bars) >= 2:
                    current_volume = symbol_bars[-1].get('v', 0)  # Latest bar volume
                    # Calculate average volume over available bars (up to 20 days)
                    avg_volume = sum(bar.get('v', 0) for bar in symbol_bars) / len(symbol_bars)"""

if old_bars_section in content:
    content = content.replace(old_bars_section, new_bars_section)
    print("✅ Added volume extraction from bars data")
else:
    print("⚠️ Could not find bars section to modify")

# Now add volume to the prices dictionary
old_prices_dict = """                    prices[symbol] = {
                        'price': round(current_price, 2),
                        'change_pct': round(change_pct, 2),
                        'change_amount': round(change_amount, 2),
                        'rsi': rsi,
                        'bid': round(float(quote_data.get('bp', 0)), 2) if quote_data.get('bp') else None,
                        'ask': round(float(quote_data.get('ap', 0)), 2) if quote_data.get('ap') else None,
                        'targets': targets,
                        'ai_score': ai_score,
                        'sentiment': sentiment,
                        'sentiment_label': sentiment_label,
                        'timestamp': datetime.now().isoformat()
                    }"""

new_prices_dict = """                    prices[symbol] = {
                        'price': round(current_price, 2),
                        'change_pct': round(change_pct, 2),
                        'change_amount': round(change_amount, 2),
                        'rsi': rsi,
                        'bid': round(float(quote_data.get('bp', 0)), 2) if quote_data.get('bp') else None,
                        'ask': round(float(quote_data.get('ap', 0)), 2) if quote_data.get('ap') else None,
                        'volume': current_volume,
                        'avg_volume': avg_volume,
                        'targets': targets,
                        'ai_score': ai_score,
                        'sentiment': sentiment,
                        'sentiment_label': sentiment_label,
                        'timestamp': datetime.now().isoformat()
                    }"""

if old_prices_dict in content:
    content = content.replace(old_prices_dict, new_prices_dict)
    print("✅ Added volume and avg_volume to prices dictionary")
else:
    print("⚠️ Could not find prices dictionary to modify")

# Write the updated file
with open('/opt/stonk-ai/fetch_ai_watchlist.py', 'w') as f:
    f.write(content)

print("\n✅ File updated successfully!")
print("\nNext steps:")
print("1. Restart the data fetcher: sudo systemctl restart data-fetcher")
print("2. Or run manually: python3 /opt/stonk-ai/fetch_ai_watchlist.py")
print("3. Wait ~30 seconds for fresh data with volume")
