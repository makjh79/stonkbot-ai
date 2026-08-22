import json, numpy as np

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_target_v2.json'))
feature_cols = ['ret_5d','ret_10d','ret_20d','vs_qqq_5d','dist_ema20','ema20_slope','dist_ema50','rsi14','vol_ratio','atr_pct','range_20d']
rows = [r for r in records if all(r.get(c) is not None for c in feature_cols)]
dates = sorted(set(r['date'] for r in rows))
train_cutoff = dates[int(len(dates)*0.6)]
val_cutoff = dates[int(len(dates)*0.8)]
train_rows = [r for r in rows if r['date'] <= train_cutoff]
val_rows = [r for r in rows if train_cutoff < r['date'] <= val_cutoff]
test_rows = [r for r in rows if r['date'] > val_cutoff]

# 1-day mean reversion score
def mr1d_score(r):
    s = 0
    # Heavily weight 1-day drop
    s += max(0, -r['ret_5d'] * 3)
    # RSI oversold
    if r['rsi14'] < 35:
        s += (35 - r['rsi14']) / 5
    # Below EMA20 adds score
    if r['dist_ema20'] < 0:
        s += -r['dist_ema20'] * 2
    # Underperforming QQQ adds score
    s += max(0, -r['vs_qqq_5d'])
    # Volume spike
    s += min((r['vol_ratio'] - 1) * 0.3, 1)
    return s

# Tune on validation set
val_scores = np.array([mr1d_score(r) for r in val_rows])
val_rets = np.array([r['ret_1d'] for r in val_rows])
best = None
for thresh in np.linspace(0.5, 5.0, 46):
    idx = np.where(val_scores >= thresh)[0]
    if len(idx) < 5: continue
    avg = val_rets[idx].mean()
    std = val_rets[idx].std()
    hr = (val_rets[idx] > 0).mean()
    sharpe = avg / (std + 1e-6)
    if best is None or sharpe > best[0]:
        best = (sharpe, thresh, avg, hr, len(idx), std)
print(f'Val best threshold {best[1]:.2f}: avg {best[2]:.3%}, hit {best[3]:.1%}, std {best[5]:.3%}, n={best[4]}')

# Test with best threshold
test_scores = np.array([mr1d_score(r) for r in test_rows])
test_rets = np.array([r['ret_1d'] for r in test_rows])
idx = np.where(test_scores >= best[1])[0]
print(f'Test threshold {best[1]:.2f}: n={len(idx)}, avg 1d ret {test_rets[idx].mean():.3%}, hit rate {(test_rets[idx]>0).mean():.1%}, std {test_rets[idx].std():.3%}')

# Daily top-5 walk-forward
test_dates = sorted(set(r['date'] for r in test_rows))
daily_pnl = []
for d in test_dates:
    day_rows = [r for r in test_rows if r['date'] == d]
    if not day_rows: continue
    sc = sorted([(mr1d_score(r), r['ret_1d']) for r in day_rows], reverse=True)
    daily_pnl.extend([ret for _, ret in sc[:5]])
arr = np.array(daily_pnl)
print(f'Daily top-5 MR-1d: avg {arr.mean():.3%}, std {arr.std():.3%}, hit {(arr>0).mean():.1%}, total {arr.sum():.2%}, n={len(arr)}')

# Proper round-based 1-day (non-overlapping, daily)
rounds = []
for d in test_dates:
    day_rows = [r for r in test_rows if r['date'] == d]
    if not day_rows: continue
    sc = sorted([(mr1d_score(r), r['ret_1d']) for r in day_rows], reverse=True)
    rounds.append(np.mean([ret for _, ret in sc[:5]]) - 0.002)
rounds = np.array(rounds)
total = np.prod(1 + rounds) - 1
print(f'Round-based daily MR-1d top-5: avg {rounds.mean():.3%}, std {rounds.std():.3%}, total {total:.2%}, n={len(rounds)}')

# Compare to buying best momentum (top 5d returners)
mo_pnl = []
for d in test_dates:
    day_rows = [r for r in test_rows if r['date'] == d]
    if not day_rows: continue
    sc = sorted([(r['ret_5d'], r['ret_1d']) for r in day_rows], reverse=True)
    mo_pnl.extend([ret for _, ret in sc[:5]])
mo_arr = np.array(mo_pnl)
print(f'Best 5d performers next day: avg {mo_arr.mean():.3%}, std {mo_arr.std():.3%}, hit {(mo_arr>0).mean():.1%}, n={len(mo_arr)}')

with open('/opt/stonk-ai/v3_rebuild/reports/mr_1d_backtest.json','w') as f:
    json.dump({
        'val_best_threshold': float(best[1]),
        'test_threshold_n': int(len(idx)),
        'test_threshold_avg': float(test_rets[idx].mean()),
        'test_threshold_hit': float((test_rets[idx]>0).mean()),
        'daily_top5_avg': float(arr.mean()),
        'daily_top5_total': float(arr.sum()),
        'round_based_total': float(total),
        'round_based_avg': float(rounds.mean()),
    }, f, indent=2)
print('Saved mr_1d_backtest.json')
