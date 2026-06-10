#!/usr/bin/env python3
"""
Premarket data fetcher
Tries multiple sources for best premarket/after-hours data
"""

import json
import requests
from datetime import datetime

def get_finnhub_premarket(symbol, api_key):
    """Try Finnhub for premarket data"""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                'current': data.get('c'),
                'open': data.get('o'),
                'high': data.get('h'),
                'low': data.get('l'),
                'previous_close': data.get('pc'),
                'change_pct': ((data.get('c', 0) / data.get('pc', 1)) - 1) * 100 if data.get('pc') else None
            }
    except Exception as e:
        print(f"Finnhub error: {e}")
    return None

def get_stockdata_premarket(symbol, api_key):
    """Try StockData.org for premarket data"""
    try:
        url = f"https://api.stockdata.org/v1/data/quote?symbols={symbol}&api_token={api_key}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data'):
                quote = data['data'][0]
                return {
                    'current': quote.get('price'),
                    'open': quote.get('day_open'),
                    'high': quote.get('day_high'),
                    'low': quote.get('day_low'),
                    'previous_close': quote.get('previous_close_price'),
                    'change_pct': quote.get('price_change_percentage')
                }
    except Exception as e:
        print(f"StockData error: {e}")
    return None

def display_premarket(symbol):
    """Display premarket data from best available source"""
    print(f"\n📊 {symbol} Premarket Data")
    print("-" * 40)
    
    # Try free sources (no API key needed for some)
    sources = []
    
    # Note: These require API keys for production use
    # For now, document the best approach
    
    print("Sources to implement:")
    print("  1. Finnhub (free tier: 60 calls/min)")
    print("  2. StockData.org (free: 100 calls/day)")  
    print("  3. EODHD WebSocket (paid, best premarket)")
    print("  4. Alpaca v1beta1/overnight feed")
    print("\nRecommended: EODHD WebSocket for real-time premarket")
    print("  URL: wss://ws.eodhistoricaldata.com/ws/us")
    print("  Covers: 4:00 AM - 8:00 PM ET (pre, regular, after)")

if __name__ == "__main__":
    symbols = ["AVGO", "HOOD", "NVDA", "TSLA", "PLTR", "MSFT", "CRWD"]
    
    print("📈 PREMARKET DATA SOURCES")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()
    
    for symbol in symbols:
        display_premarket(symbol)
