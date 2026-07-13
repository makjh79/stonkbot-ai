#!/usr/bin/env python3
"""Fetch Alpaca clock and write market_status.json to /opt/stonk-ai and web root."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE = Path('/opt/stonk-ai')
WEB = Path('/var/www/hedge-fund-website')

with open(BASE / 'alpaca_config.json') as f:
    cfg = json.load(f)

url = cfg.get('base_url', 'https://paper-api.alpaca.markets').rstrip('/') + '/v2/clock'
headers = {
    'APCA-API-KEY-ID': cfg['api_key'],
    'APCA-API-SECRET-KEY': cfg['api_secret'],
}

try:
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    out = {
        'is_open': bool(data.get('is_open')),
        'mode': 'open' if data.get('is_open') else 'closed',
        'next_open': data.get('next_open'),
        'next_close': data.get('next_close'),
        'timestamp': data.get('timestamp') or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
except Exception as exc:
    out = {
        'is_open': False,
        'mode': 'error',
        'error': str(exc),
        'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }

for dest in [BASE / 'market_status.json', WEB / 'market_status.json']:
    with open(dest, 'w') as f:
        json.dump(out, f, indent=2)
    os.chmod(dest, 0o644)
    os.chown(dest, 1001, 1001)  # stonkai:stonkai

print(out['timestamp'], 'is_open=' + str(out['is_open']), 'mode=' + out['mode'])
