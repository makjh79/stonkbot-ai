#!/usr/bin/env python3
"""
Fetch earnings dates from Yahoo Finance
Lightweight scraper for watchlist earnings alerts
"""

import json
import requests
from datetime import datetime, timedelta
import re
import os

# Watchlist symbols
WATCHLIST_SYMBOLS = ['COIN', 'DKNG', 'NET', 'PATH', 'ROKU', 'SHOP', 'SNOW', 'SQ', 'SQQQ', 'TQQQ', 'UPST', 'XLE']

def fetch_earnings_date(symbol):
    """Fetch earnings date from Yahoo Finance"""
    try:
        url = f"https://finance.yahoo.com/quote/{symbol}/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            html = response.text
            
            # Look for earnings date patterns
            # Pattern 1: "Earnings Date" field
            patterns = [
                r'Earnings Date.*?([A-Z][a-z]{2} \d{1,2},? \d{4})',
                r'"earningsDate":\s*\["(\d{4}-\d{2}-\d{2})"',
                r'earningsDate.*?([A-Z][a-z]{2} \d{1,2})',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html)
                if match:
                    date_str = match.group(1)
                    # Parse various date formats
                    try:
                        if '-' in date_str:  # ISO format
                            return datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
                        else:  # Month Day, Year format
                            return datetime.strptime(date_str, '%b %d, %Y').strftime('%Y-%m-%d')
                    except:
                        try:
                            return datetime.strptime(date_str, '%b %d').replace(year=datetime.now().year).strftime('%Y-%m-%d')
                        except:
                            continue
        
        return None
    except Exception as e:
        print(f"Error fetching earnings for {symbol}: {e}")
        return None

def get_cached_earnings():
    """Get cached earnings data if fresh (< 24 hours)"""
    cache_file = '/opt/stonk-ai/earnings_cache.json'
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cache = json.load(f)
            
            cache_time = datetime.fromisoformat(cache.get('timestamp', '2000-01-01'))
            if datetime.now() - cache_time < timedelta(hours=24):
                return cache.get('data', {})
        except:
            pass
    
    return {}

def save_earnings_cache(data):
    """Save earnings data to cache"""
    cache_file = '/opt/stonk-ai/earnings_cache.json'
    
    cache = {
        'timestamp': datetime.now().isoformat(),
        'data': data
    }
    
    with open(cache_file, 'w') as f:
        json.dump(cache, f, indent=2)

def fetch_all_earnings():
    """Fetch earnings for all watchlist symbols"""
    # Check cache first
    cached = get_cached_earnings()
    
    earnings_data = {}
    
    for symbol in WATCHLIST_SYMBOLS:
        if symbol in cached:
            earnings_data[symbol] = cached[symbol]
            print(f"✓ {symbol}: {cached[symbol]} (cached)")
        else:
            date = fetch_earnings_date(symbol)
            if date:
                earnings_data[symbol] = date
                print(f"✓ {symbol}: {date}")
            else:
                print(f"✗ {symbol}: Not found")
    
    # Save to cache
    save_earnings_cache(earnings_data)
    
    # Also save to web directory for frontend access
    output = {
        'timestamp': datetime.now().isoformat(),
        'earnings': earnings_data
    }
    
    with open('/var/www/hedge-fund-website/earnings_data.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✓ Saved earnings data for {len(earnings_data)} stocks")
    return earnings_data

if __name__ == '__main__':
    fetch_all_earnings()
