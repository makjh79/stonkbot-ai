#!/usr/bin/env python3
"""
Volume Tracker - Stores 20-day rolling volume history
Run daily to build accurate average volume ratios
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

VOLUME_DB_FILE = Path('/var/www/hedge-fund-website/volume_history.json')

def load_volume_history():
    """Load existing volume history"""
    if VOLUME_DB_FILE.exists():
        with open(VOLUME_DB_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_volume_history(history):
    """Save volume history to file"""
    with open(VOLUME_DB_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def update_volume_data(watchlist_data):
    """Update volume history with today's data"""
    history = load_volume_history()
    today = datetime.now().strftime('%Y-%m-%d')
    
    for symbol, data in watchlist_data.get('prices', {}).items():
        if symbol not in history:
            history[symbol] = []
        
        # Check if we already have today's entry
        existing = [e for e in history[symbol] if e['date'] == today]
        if not existing and data.get('volume'):
            history[symbol].append({
                'date': today,
                'volume': data['volume'],
                'timestamp': datetime.now().isoformat()
            })
            # Keep only last 20 days
            history[symbol] = history[symbol][-20:]
    
    # Clean up old symbols
    symbols_to_keep = set(watchlist_data.get('prices', {}).keys())
    history = {k: v for k, v in history.items() if k in symbols_to_keep}
    
    save_volume_history(history)
    return history

def get_avg_volume(symbol, days=20):
    """Get average volume for a symbol"""
    history = load_volume_history()
    if symbol not in history or len(history[symbol]) < 2:
        return None
    
    # Use last N days
    entries = history[symbol][-days:]
    if len(entries) < 2:
        return None
    
    total_volume = sum(e['volume'] for e in entries)
    return total_volume / len(entries)

if __name__ == '__main__':
    # Load current watchlist data
    watchlist_path = Path('/var/www/hedge-fund-website/ai_watchlist_live.json')
    if watchlist_path.exists():
        with open(watchlist_path, 'r') as f:
            data = json.load(f)
        
        history = update_volume_data(data)
        print(f"Updated volume history for {len(history)} symbols")
        
        # Show sample data
        for symbol in list(history.keys())[:3]:
            entries = history[symbol]
            avg = sum(e['volume'] for e in entries) / len(entries) if entries else 0
            print(f"  {symbol}: {len(entries)} days, avg={avg:,.0f}")
    else:
        print("No watchlist data found")
