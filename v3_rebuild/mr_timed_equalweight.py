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

def mr1d_score(r):
    s = max(0, -r['ret_5d'] * 3)
    if r['rsi14'] < 35:
        s += (35 - r['rsi14']) / 5
    if r['dist_ema20'] < 0:
        s += -r['dist_ema20'] * 2
    s += max(0, -r['vs_qqq_5d'])
    s += min((r['vol_ratio'] - 1) * 0.3, 1)
    return s

def run(selector, rebalance_days=5, max_positions=25, cost=0.001, start=100000):
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
            picks = selector(rows_by_date[d])
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
    return total * 100, maxdd * 100, trades

def mr_timed_selector_factory(thresh, k):
    def selector(day_rows):
        scores = [(mr1d_score(r), r['symbol'], r) for r in day_rows]
        if not scores:
            return []
        top_score = max(s for s, _, _ in scores)
        if top_score < thresh:
            return []
        return [r for _, _, r in sorted(scores, reverse=True)[:k]]
    return selector

print('=== MR-timed equal-weight ===')
for thresh in [0, 1, 2, 3, 4, 5]:
    ret, dd, trades = run(mr_timed_selector_factory(thresh, 25), 5, 25, 0.001, 100000)
    print(f"top score >= {thresh}, all 25: {ret:.1f}% dd {dd:.1f}% trades {trades}")

print('\n=== MR-timed top-10 ===')
for thresh in [0, 1, 2, 3, 4, 5]:
    ret, dd, trades = run(mr_timed_selector_factory(thresh, 10), 5, 10, 0.001, 100000)
    print(f"top score >= {thresh}, top 10: {ret:.1f}% dd {dd:.1f}% trades {trades}")

qqq_prices = [qqq_by_date[d] for d in dates if d in qqq_by_date]
qqq_ret = (qqq_prices[-1] - qqq_prices[0]) / qqq_prices[0] * 100
print(f"\nFull 2-year QQQ: {qqq_ret:.1f}%")
