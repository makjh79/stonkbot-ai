import json, numpy as np
from collections import defaultdict

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_with_price.json'))
dates = sorted(set(r['date'] for r in records))
test_rows = [r for r in records if r['date'] > dates[int(len(dates)*0.8)]]

# QQQ test-period return
bars = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars.json'))
qqq = bars['QQQ']
qqq_by_date = {ts: c for ts, c in zip(qqq['timestamps'], qqq['closes'])}
test_dates = sorted(set(r['date'] for r in test_rows))
qqq_test_prices = [qqq_by_date[d] for d in test_dates if d in qqq_by_date]
qqq_total_ret = (qqq_test_prices[-1] - qqq_test_prices[0]) / qqq_test_prices[0]
print(f'QQQ test period ({test_dates[0][:10]} to {test_dates[-1][:10]}): {qqq_total_ret:.2%}')

# Universe equal-weight buy-and-hold, rebalanced daily into all available names (approx)
rows_by_date = defaultdict(list)
for r in records:
    rows_by_date[r['date']].append(r)

daily_rets = []
for d in test_dates:
    day_rets = [r['ret_1d'] for r in rows_by_date[d] if r['date'] == d]
    if day_rets:
        daily_rets.append(np.mean(day_rets))
universe_total_ret = np.prod(1 + np.array(daily_rets)) - 1
print(f'Universe equal-weight 1D cycle total: {universe_total_ret:.2%}')

with open('/opt/stonk-ai/v3_rebuild/reports/qqq_benchmark.json', 'w') as f:
    json.dump({
        'test_start': test_dates[0][:10],
        'test_end': test_dates[-1][:10],
        'qqq_total_return_pct': round(qqq_total_ret * 100, 2),
        'universe_total_return_pct': round(universe_total_ret * 100, 2),
    }, f, indent=2)
print('Saved qqq_benchmark.json')
