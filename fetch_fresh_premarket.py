#!/usr/bin/env python3
"""
Fetch fresh premarket data using Finnhub
"""

import json
import requests
from datetime import datetime
from pathlib import Path

FINNHUB_API_KEY = 'd8gj61pr01qlgcujs6agd8gj61pr01qlgcujs6b0'

# All symbols we track
SYMBOLS = [
    'NOW', 'HOOD', 'SOFI', 'AVGO', 'MSFT', 'NFLX', 'UNH', 'NVO', 'NVOX',
    'META', 'AMZN', 'WFC', 'BABA', 'JD', 'NVDA', 'TSLA', 'PLTR', 'CRWD'
]

def fetch_finnhub(symbols):
    """Fetch real-time quotes from Finnhub"""
    data = {}
    print("📡 Fetching from Finnhub...")
    print("-" * 70)
    
    for symbol in symbols:
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token=***"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                quote = response.json()
                current = quote.get('c', 0)
                prev_close = quote.get('pc', current)
                change = current - prev_close
                change_pct = (change / prev_close) * 100 if prev_close else 0
                
                data[symbol] = {
                    'price': round(current, 2),
                    'prev_close': round(prev_close, 2),
                    'change': round(change, 2),
                    'change_pct': round(change_pct, 2),
                    'open': round(quote.get('o', current), 2),
                    'high': round(quote.get('h', current), 2),
                    'low': round(quote.get('l', current), 2),
                    'timestamp': datetime.now().isoformat()
                }
                
                # Determine session
                now_et = datetime.now().hour - 4  # Approx ET from UTC
                if 4 <= now_et < 9:
                    session = "PREMARKET"
                elif 9 <= now_et < 16:
                    session = "REGULAR"
                elif 16 <= now_et < 20:
                    session = "AFTER-HOURS"
                else:
                    session = "OVERNIGHT"
                
                data[symbol]['session'] = session
                
            else:
                print(f"❌ {symbol}: HTTP {response.status_code}")
        except Exception as e:
            print(f"❌ {symbol}: {e}")
    
    return data

def display_results(data):
    """Display results sorted by performance"""
    if not data:
        print("❌ No data fetched")
        return
    
    print(f"\n{'📊 PREMARKET SNAPSHOT':=^70}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ET (approx)")
    print(f"Data Source: Finnhub (Real-time)")
    print("-" * 70)
    
    # Sort by change %
    sorted_data = sorted(data.items(), key=lambda x: x[1]['change_pct'], reverse=True)
    
    # Gainers
    gainers = [(s, d) for s, d in sorted_data if d['change_pct'] > 0]
    if gainers:
        print("\n🟢 GAINERS:")
        for symbol, d in gainers:
            print(f"  {symbol:5} ${d['price']:>8.2f}  +${d['change']:>6.2f}  (+{d['change_pct']:>5.2f}%)  {d['session']}")
    
    # Decliners  
    decliners = [(s, d) for s, d in sorted_data if d['change_pct'] < 0]
    if decliners:
        print("\n🔴 DECLINERS:")
        for symbol, d in decliners:
            print(f"  {symbol:5} ${d['price']:>8.2f}  ${d['change']:>6.2f}  ({d['change_pct']:>5.2f}%)  {d['session']}")
    
    # Flat
    flat = [(s, d) for s, d in sorted_data if d['change_pct'] == 0]
    if flat:
        print("\n⚪ FLAT:")
        for symbol, d in flat:
            print(f"  {symbol:5} ${d['price']:>8.2f}  (0.00%)  {d['session']}")
    
    print("-" * 70)
    print(f"Total: {len(data)} symbols fetched")
    print("=" * 70)

def main():
    print(f"\n{'🚀 FRESH PREMARKET DATA':=^70}")
    
    # Fetch fresh data
    data = fetch_finnhub(SYMBOLS)
    
    # Display
    display_results(data)
    
    # Save to file
    DATA_FILE = Path("/root/.openclaw/workspace/stock_data.json")
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\n💾 Saved to {DATA_FILE}")
    
    return data

if __name__ == "__main__":
    main()
