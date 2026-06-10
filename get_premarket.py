#!/usr/bin/env python3
"""
Fetch real-time premarket data using Finnhub
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

def fetch_quote(symbol):
    """Fetch quote from Finnhub using curl"""
    try:
        cmd = f"curl -s 'https://finnhub.io/api/v1/quote?symbol={symbol}&token=d8gji8pr01qlgcujuqdgd8gji8pr01qlgcujuqe0'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            if 'c' in data:
                return {
                    'price': data['c'],
                    'prev_close': data['pc'],
                    'change': data['d'],
                    'change_pct': data['dp'],
                    'high': data['h'],
                    'low': data['l'],
                    'open': data['o'],
                    'timestamp': data['t']
                }
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
    return None

def main():
    # Portfolio + watchlist symbols
    symbols = ['NVDA', 'PLTR', 'MSFT', 'CRWD', 'SCHD', 'SGOV', 'TSLA', 'HOOD', 'AVGO', 'NOW', 'SOFI']
    
    print("=" * 70)
    print("📊 REAL-TIME PREMARKET DATA (Finnhub)")
    print("=" * 70)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()
    
    data = {}
    
    for symbol in symbols:
        quote = fetch_quote(symbol)
        if quote:
            data[symbol] = {
                'price': round(quote['price'], 2),
                'prev_close': round(quote['prev_close'], 2),
                'change': round(quote['change'], 2),
                'change_pct': round(quote['change_pct'], 2)
            }
            
            emoji = "🟢" if quote['change_pct'] >= 0 else "🔴"
            print(f"{emoji} {symbol:6}  ${quote['price']:>8.2f}  {quote['change']:>+7.2f}  ({quote['change_pct']:>+5.2f}%)")
    
    print("\n" + "=" * 70)
    print(f"✅ Fetched {len(data)} symbols")
    
    # Save to file
    DATA_FILE = Path("/root/.openclaw/workspace/stock_data.json")
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"💾 Saved to {DATA_FILE}")
    
    # Portfolio summary
    print("\n📊 YOUR PENDING ORDERS:")
    portfolio = {
        'NVDA': 10, 'PLTR': 20, 'MSFT': 3, 'CRWD': 2, 'SCHD': 25, 'SGOV': 12
    }
    
    total_value = 0
    for symbol, qty in portfolio.items():
        if symbol in data:
            d = data[symbol]
            emoji = "🟢" if d['change_pct'] >= 0 else "🔴"
            value = qty * d['price']
            total_value += value
            print(f"  {emoji} BUY {qty:2} {symbol:5} @ ${d['price']:.2f} ({d['change_pct']:+.2f}%) = ${value:,.2f}")
    
    print(f"\n💰 Total Portfolio Value: ${total_value:,.2f}")
    
    # Summary stats
    gainers = sum(1 for d in data.values() if d['change_pct'] >= 0)
    decliners = sum(1 for d in data.values() if d['change_pct'] < 0)
    
    print("\n📈 SUMMARY:")
    print(f"  🟢 Gainers: {gainers}")
    print(f"  🔴 Decliners: {decliners}")
    print("=" * 70)

if __name__ == "__main__":
    main()
