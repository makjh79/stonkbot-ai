#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/stonk-ai')
from readiness_score import compute_confirmation_count
from stonk_utils import atomic_write_json
import json

# Load and fix signals.json in-place
with open('/opt/stonk-ai/signals.json', 'r') as f:
    data = json.load(f)

fixed = 0
for sig in data.get('signals', []):
    confs = sig.get('confirmations', {})
    canonical = compute_confirmation_count(confs)
    baked = sig.get('confirmation_count', canonical)
    if baked != canonical:
        sig['confirmation_count'] = canonical
        fixed += 1

print(f'Fixed {fixed} signals')

atomic_write_json('/opt/stonk-ai/signals.json', data)
web_path = '/var/www/hedge-fund-website/signals.json'
try:
    atomic_write_json(web_path, data)
    print(f'  mirrored to {web_path}')
except Exception as e:
    print(f'  (mirror skipped: {e})')
print('Saved signals.json')
