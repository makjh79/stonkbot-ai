import json, numpy as np
from datetime import datetime
from collections import defaultdict

bars = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars.json'))
spy = bars.get('SPY', {})
qqq = bars.get('QQQ', {})

qqq_returns = {}
if qqq:
    for i in range(1, len(qqq['timestamps'])):
        qqq_returns[qqq['timestamps'][i]] = (qqq['closes'][i] - qqq['closes'][i-1]) / qqq['closes'][i-1]

def ema(values, period):
    if len(values) < period: return None
    mult = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = (v - e) * mult + e
    return e

def rsi(closes, period=14):
    if len(closes) < period + 1: return None
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0: return 100
    return 100 - 100 / (1 + ag / al)

records = []
for sym, data in bars.items():
    if sym in ('SPY','QQQ'): continue
    if len(data.get('timestamps', [])) < 60: continue
    ts = data['timestamps']
    c = data['closes']; v = data['volumes']; h = data['highs']; lo = data['lows']
    for i in range(26, len(c) - 5):
        price = c[i]
        past_c = c[:i+1]; past_v = v[:i+1]
        date = ts[i]
        ret_1d = (c[i+1] - price) / price
        ret_3d = (c[i+3] - price) / price
        ret_5d_target = (c[i+5] - price) / price
        mkt_ret_5d = sum(qqq_returns.get(ts[j], 0) for j in range(i-4, i+1))
        ret5 = (price - c[i-5]) / c[i-5]
        ret10 = (price - c[i-10]) / c[i-10]
        ret20 = (price - c[i-20]) / c[i-20]
        vs_qqq_5d = ret5 - mkt_ret_5d
        ema20 = ema(past_c, 20)
        dist_ema20 = (price - ema20) / ema20 if ema20 else 0
        ema20_slope = (ema20 - ema(past_c[:-1], 20)) / ema20 if ema20 else 0
        ema50 = ema(past_c, 50)
        dist_ema50 = (price - ema50) / ema50 if ema50 else 0
        rsi14 = rsi(past_c, 14)
        avg_vol_20 = sum(past_v[-20:]) / 20
        vol_ratio = past_v[-1] / avg_vol_20 if avg_vol_20 else 1
        atr = sum(max(h[j], c[j-1]) - min(lo[j], c[j-1]) for j in range(i-13, i+1)) / 14
        atr_pct = atr / price
        range_20d = (max(c[i-20:i+1]) - min(c[i-20:i+1])) / price
        records.append({
            'symbol': sym, 'date': date, 'price': price,
            'ret_1d': ret_1d, 'ret_3d': ret_3d, 'ret_5d_target': ret_5d_target,
            'target_1d_up': 1 if ret_1d > 0 else 0,
            'target_3d_up': 1 if ret_3d > 0 else 0,
            'target_5d_up': 1 if ret_5d_target > 0 else 0,
            'ret_5d': ret5, 'ret_10d': ret10, 'ret_20d': ret20,
            'vs_qqq_5d': vs_qqq_5d,
            'dist_ema20': dist_ema20, 'ema20_slope': ema20_slope,
            'dist_ema50': dist_ema50,
            'rsi14': rsi14, 'vol_ratio': vol_ratio, 'atr_pct': atr_pct,
            'range_20d': range_20d,
        })

print(f'Total samples with price: {len(records)}')
with open('/opt/stonk-ai/v3_rebuild/data/features_with_price.json', 'w') as f:
    json.dump(records, f)
print('Saved features_with_price.json')
