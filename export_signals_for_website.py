#!/usr/bin/env python3
"""
Export signal accuracy data for website display
Run every 5 minutes alongside watchlist updates
"""

import json
import sys
sys.path.insert(0, '/opt/stonk-ai')

from signal_tracker import export_for_website

def main():
    """Export signal data to website directory"""
    data = export_for_website()
    
    output_file = '/var/www/hedge-fund-website/signal_accuracy.json'
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Exported signal data to {output_file}")
    stats = data.get('stats', {})
    print(f"   Stats: {stats.get('win_rate', 0)}% win rate ({stats.get('completed_signals', 0)} completed)")

if __name__ == '__main__':
    main()
