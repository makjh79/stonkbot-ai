import json
import numpy as np
from collections import defaultdict

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_2yr.json'))
rows_by_date = defaultdict(list)
for r in records:
    rows_by_date[r['date']].append(r)
dates = sorted(rows_by_date.keys())

# Score distribution
all_scores = []
daily_top = []
ema200_pos = 0
ema200_total = 0
for d in dates:
    day_rows = rows_by_date[d]
    for r in day_rows:
        if r['dist_ema200'] is not None:
            ema200_total += 1
            if r['dist_ema200'] > 0:
                ema200_pos += 1
    sc = []
    for r in day_rows:
        s = 0.0
        if r['dist_ema200'] > 0: s += 1.0
        if r['dist_ema50'] > 0: s += 1.0
        if r['dist_ema20'] > 0: s += 0.5
        if r['ret_5d'] < 0: s += max(0, -r['ret_5d'] * 3)
        if r['rsi14'] < 45: s += (45 - r['rsi14']) / 10
        s += max(0, -r['vs_qqq_5d'])
        s += min((r['vol_ratio'] - 1) * 0.3, 1)
        sc.append(s)
    all_scores.extend(sc)
    if sc:
        daily_top.append(max(sc))

print(f'Score mean: {np.mean(all_scores):.2f}, std: {np.std(all_scores):.2f}')
print(f'Daily top score mean: {np.mean(daily_top):.2f}, min: {np.min(daily_top):.2f}, max: {np.max(daily_top):.2f}')
print(f'% days top score >= 1.5: {np.mean([1 if x >= 1.5 else 0 for x in daily_top]):.1%}')
print(f'% days top score >= 2.0: {np.mean([1 if x >= 2.0 else 0 for x in daily_top]):.1%}')
print(f'EMA200 positive: {ema200_pos}/{ema200_total} = {ema200_pos/ema200_total:.1%}')

# Check symbols with EMA200 coverage
symbol_counts = defaultdict(int)
for r in records:
    if r['dist_ema200'] is not None:
        symbol_counts[r['symbol']] += 1
print(f'Symbols with EMA200 data: {len(symbol_counts)}')

# Quick EMA200-only backtest top-8
def run_simple(selector, rebalance_days=5, max_pos=8, cost=0.001, start=100000):
    cash = start
    positions = []
    equity = []
    for i, d in enumerate(dates):
        matured = [p for p in positions if i >= p['exit_i']]
        positions = [p for p in positions if i < p['exit_i']]
        for p in matured:
            ep = None
            for er in rows_by_date.get(dates[min(p['exit_i'], len(dates)-1)], []):
                if er['symbol'] == p['symbol']:
                    ep = er['price']
                    break
            if ep is None:
                ep = p['entry_price']
            cash += p['shares'] * ep * (1 - cost)
        if i % rebalance_days == 0 and cash > 1000:
            picks = selector(rows_by_date[d])
            if picks:
                n = min(len(picks), max_pos)
                alloc = cash / n
                for r in picks[:n]:
                    if cash < 1000:
                        break
                    price = r['price']
                    shares = int(alloc / price)
                    if shares < 1:
                        continue
                    ec = shares * price * (1 + cost)
                    if ec > cash:
                        shares = max(1, int(cash / (price * (1 + cost))))
                        ec = shares * price * (1 + cost)
                    if ec > cash or shares < 1:
                        continue
                    positions.append({'symbol': r['symbol'], 'shares': shares, 'entry_price': price, 'exit_i': i + rebalance_days})
                    cash -= ec
        mv = cash
        for p in positions:
            for cr in rows_by_date[d]:
                if cr['symbol'] == p['symbol']:
                    mv += p['shares'] * cr['price']
                    break
            else:
                mv += p['entry_price'] * p['shares']
        equity.append(mv)
    final = cash + sum(p['shares'] * p['entry_price'] for p in positions)
    eq = np.array(equity)
    total = final / start - 1
    peak = start
    maxdd = 0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > maxdd:
            maxdd = dd
    return total * 100, maxdd * 100

ret, dd = run_simple(lambda rows: [r for r in rows if r['dist_ema200'] > 0][:8])
print(f'\nEMA200-only top-8: {ret:.1f}% dd {dd:.1f}%')

ret, dd = run_simple(lambda rows: sorted([r for r in rows if r['dist_ema200'] > 0], key=lambda r: -r['ret_5d'])[:8])
print(f'EMA200-only + best past 5d top-8: {ret:.1f}% dd {dd:.1f}%')

ret, dd = run_simple(lambda rows: sorted([r for r in rows if r['dist_ema200'] > 0], key=lambda r: r['ret_5d'])[:8])
print(f'EMA200-only + worst past 5d top-8: {ret:.1f}% dd {dd:.1f}%')
