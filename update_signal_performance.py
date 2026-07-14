#!/usr/bin/env python3
"""
Daily script to update signal performance.
Run by cron daily at market close to check if targets were hit.

Uses Alpaca data hub only. No external data sources.
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, '/opt/stonk-ai')

from signal_tracker import load_signal_history, save_signal_history, update_signal_performance, get_signal_stats
from alpaca_data import get_data_hub


def fetch_current_prices(symbols):
    """Fetch current prices via Alpaca data hub"""
    hub = get_data_hub()
    return hub.get_latest_prices(symbols)


def main():
    """Update all pending signals with current performance"""
    print("📊 Updating Signal Performance...")

    signals = load_signal_history()
    pending = [s for s in signals if s['outcome'] == 'pending']

    if not pending:
        print("No pending signals to update")
        return

    print(f"Found {len(pending)} pending signals")

    symbols = list(set(s['symbol'] for s in pending))
    prices = fetch_current_prices(symbols)

    today = datetime.now().strftime('%Y-%m-%d')
    updated = 0

    for signal in pending:
        symbol = signal['symbol']
        if symbol in prices and prices[symbol] > 0:
            update_signal_performance(symbol, prices[symbol], today)
            updated += 1

    print(f"✅ Updated {updated} signals")

    stats = get_signal_stats(days=30)
    print(f"\n📈 Last 30 Days Performance:")
    print(f"   Total Signals: {stats['total_signals']}")
    print(f"   Completed: {stats['completed_signals']}")
    print(f"   Win Rate: {stats['win_rate']}%")
    print(f"   Avg Return: {stats['avg_return']}%")
    print(f"   Pending: {stats['pending_signals']}")


if __name__ == '__main__':
    main()