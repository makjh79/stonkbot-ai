import json
d = json.load(open('/opt/stonk-ai/signals.json'))
print('keys', list(d.keys()))
sigs = d['signals']
print('count', len(sigs))
if sigs:
    s = sigs[0]
    print('sample keys', sorted(s.keys()))
    keys_to_check = ["symbol", "tier", "readiness_score", "confirmation_count", "price", "above_ema", "rsi14", "atr14", "options_implied_vol", "ret_5d", "dist_ema20", "dist_ema50", "dist_ema200", "vol_ratio", "vs_qqq_5d", "current_price", "sector"]
    print('available values:')
    for k in keys_to_check:
        if k in s:
            print(f'  {k}: {s[k]}')
        else:
            print(f'  {k}: MISSING')

# Check coverage across all signals
print('\ncoverage:')
for k in keys_to_check:
    present = sum(1 for sig in sigs if k in sig and sig[k] is not None)
    print(f'  {k}: {present}/{len(sigs)}')
