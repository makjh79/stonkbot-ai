#!/usr/bin/env python3
"""
Daily script to update signal performance
Run by cron daily at market close to check if targets were hit
"""

import json
import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, '/opt/stonk-ai')

from signal_tracker import load_signal_history, save_signal_history, update_signal_performance

def fetch_current_prices(symbols):
    """Fetch current prices for symbols - uses same method as trading bot"""
    prices = {}
    try:
        import yfinance as yf
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                prices[symbol] = info.get('regularMarketPrice', 0)
            except Exception as e:
                print(f"Could not fetch price for {symbol}: {e}")
                prices[symbol] = 0
    except ImportError:
        print("yfinance not available, using fallback")
    return prices

def main():
    """Update all pending signals with current performance"""
    print("📊 Updating Signal Performance...")
    
    signals = load_signal_history()
    pending = [s for s in signals if s['outcome'] == 'pending']
    
    if not pending:
        print("No pending signals to update")
        return
    
    print(f"Found {len(pending)} pending signals")
    
    # Get unique symbols
    symbols = list(set(s['symbol'] for s in pending))
    
    # Fetch current prices
    prices = fetch_current_prices(symbols)
    
    # Update each pending signal
    today = datetime.now().strftime('%Y-%m-%d')
    updated = 0
    
    for signal in pending:
        symbol = signal['symbol']
        if symbol in prices and prices[symbol] > 0:
            update_signal_performance(symbol, prices[symbol], today)
            updated += 1
    
    print(f"✅ Updated {updated} signals")
    
    # Calculate and display stats
    from signal_tracker import get_signal_stats
    stats = get_signal_stats(days=30)
    print(f"\n📈 Last 30 Days Performance:")
    print(f"   Total Signals: {stats['total_signals']}")
    print(f"   Completed: {stats['completed_signals']}")
    print(f"   Win Rate: {stats['win_rate']}%")
    print(f"   Avg Return: {stats['avg_return']}%")
    print(f"   Pending: {stats['pending_signals']}")

if __name__ == '__main__':
    main()
