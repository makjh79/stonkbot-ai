import json
import numpy as np
from collections import defaultdict

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_2yr.json'))
rows_by_date = defaultdict(list)
for r in records:
    rows_by_date[r['date']].append(r)
dates = sorted(rows_by_date.keys())
qqq = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json'))['QQQ']
qqq_by_date = {ts: c for ts, c in zip(qqq['timestamps'], qqq['closes'])}

def trend_pullback_score(r):
    s = 0.0
    if r['dist_ema200'] > 0: s += 1.0
    if r['dist_ema50'] > 0: s += 1.0
    if r['dist_ema20'] > 0: s += 0.5
    if r['ret_5d'] < 0: s += max(0, -r['ret_5d'] * 3)
    if r['rsi14'] < 45: s += (45 - r['rsi14']) / 10
    s += max(0, -r['vs_qqq_5d'])
    s += min((r['vol_ratio'] - 1) * 0.3, 1)
    return s

def run(hold_days, rebalance_days, max_positions=15, cost=0.001, start=100000):
    cash = start
    positions = []
    equity = []
    trades = 0
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
            trades += 1
        if i % rebalance_days == 0 and cash > 1000:
            scores = [(trend_pullback_score(r), r['symbol'], r) for r in rows_by_date[d]]
            picks = [r for _, _, r in sorted(scores, reverse=True)[:max_positions]]
            if picks:
                n = min(len(picks), max_positions)
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
                    positions.append({'symbol': r['symbol'], 'shares': shares, 'entry_price': price, 'exit_i': i + hold_days})
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
    return total * 100, maxdd * 100, trades

print('=== Hold period test (top-15, rebalance every hold_days) ===')
for hold in [1, 3, 5, 10, 20]:
    ret, dd, trades = run(hold, hold, 15, 0.001, 100000)
    print(f"hold {hold:2d}d: {ret:6.1f}% dd {dd:5.1f}% trades {trades}")

print('\n=== Rebalance frequency test (5d hold) ===')
for rebalance in [1, 3, 5, 10]:
    ret, dd, trades = run(5, rebalance, 15, 0.001, 100000)
    print(f"rebal {rebalance:2d}d: {ret:6.1f}% dd {dd:5.1f}% trades {trades}")

qqq_prices = [qqq_by_date[d] for d in dates if d in qqq_by_date]
qqq_ret = (qqq_prices[-1] - qqq_prices[0]) / qqq_prices[0] * 100
print(f"\nFull 2-year QQQ: {qqq_ret:.1f}%")

results = []
for hold in [1, 3, 5, 10, 20]:
    ret, dd, trades = run(hold, hold, 15, 0.001, 100000)
    results.append({'hold_days': hold, 'return_pct': ret, 'max_dd_pct': dd, 'trades': trades})
with open('/opt/stonk-ai/v3_rebuild/reports/hold_period_test.json', 'w') as f:
    json.dump({'qqq_return_pct': round(qqq_ret, 2), 'results': results}, f, indent=2)
print('Saved hold_period_test.json')
