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
spy = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json'))['SPY']
spy_by_date = {ts: c for ts, c in zip(spy['timestamps'], spy['closes'])}

# Compute trend pullback score:
# - Want intermediate trend positive (price above EMA20, EMA20 above EMA50)
# - Want short-term pullback (ret_5d negative)
# - Want oversold RSI
# - Want above EMA200 (long-term trend intact)

def trend_pullback_score(r):
    s = 0.0
    # Long-term trend
    if r['dist_ema200'] > 0:
        s += 1.0
    # Medium trend
    if r['dist_ema50'] > 0:
        s += 1.0
    # Short trend but pullback
    if r['dist_ema20'] > 0:
        s += 0.5
    # Short-term pullback is good
    if r['ret_5d'] < 0:
        s += max(0, -r['ret_5d'] * 3)
    # RSI oversold
    if r['rsi14'] < 45:
        s += (45 - r['rsi14']) / 10
    # Relative to QQQ underperform adds
    s += max(0, -r['vs_qqq_5d'])
    # Volume confirmation
    s += min((r['vol_ratio'] - 1) * 0.3, 1)
    return s

def run(selector, rebalance_days=5, max_positions=15, cost=0.001, start=100000):
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

print('=== Trend pullback strategy ===')
for thresh in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    def selector_factory(t):
        def selector(day_rows):
            scores = [(trend_pullback_score(r), r['symbol'], r) for r in day_rows]
            if not scores:
                return []
            top_score = max(s for s, _, _ in scores)
            if top_score < t:
                return []
            return [r for _, _, r in sorted(scores, reverse=True)[:15]]
        return selector
    ret, dd, trades = run(selector_factory(thresh), 5, 15, 0.001, 100000)
    print(f"thresh {thresh}: {ret:.1f}% dd {dd:.1f}% trades {trades}")

print('\n=== Trend pullback top-8 ===')
for thresh in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
    def selector_factory(t):
        def selector(day_rows):
            scores = [(trend_pullback_score(r), r['symbol'], r) for r in day_rows]
            if not scores:
                return []
            top_score = max(s for s, _, _ in scores)
            if top_score < t:
                return []
            return [r for _, _, r in sorted(scores, reverse=True)[:8]]
        return selector
    ret, dd, trades = run(selector_factory(thresh), 5, 8, 0.001, 100000)
    print(f"thresh {thresh}: {ret:.1f}% dd {dd:.1f}% trades {trades}")

qqq_prices = [qqq_by_date[d] for d in dates if d in qqq_by_date]
qqq_ret = (qqq_prices[-1] - qqq_prices[0]) / qqq_prices[0] * 100
print(f"\nFull 2-year QQQ: {qqq_ret:.1f}%")

with open('/opt/stonk-ai/v3_rebuild/reports/trend_pullback.json', 'w') as f:
    json.dump({'qqq_return_pct': round(qqq_ret, 2)}, f, indent=2)
