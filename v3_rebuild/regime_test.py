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

# Top-15 selector with default 0 threshold
def top15_selector(day_rows):
    scores = [(trend_pullback_score(r), r['symbol'], r) for r in day_rows]
    if not scores:
        return []
    return [r for _, _, r in sorted(scores, reverse=True)[:15]]

# Top-8 selector with threshold 3.0
def top8_thresh3_selector(day_rows):
    scores = [(trend_pullback_score(r), r['symbol'], r) for r in day_rows]
    if not scores:
        return []
    top_score = max(s for s, _, _ in scores)
    if top_score < 3.0:
        return []
    return [r for _, _, r in sorted(scores, reverse=True)[:8]]

# Test by calendar year and major regimes
periods = [
    ('2024', '2024-08-14', '2024-12-31'),
    ('2025', '2025-01-01', '2025-12-31'),
    ('2026 YTD', '2026-01-01', '2026-08-21'),
    ('2024 Aug-Dec', '2024-08-14', '2024-12-31'),
    ('2025 Q1', '2025-01-01', '2025-03-31'),
    ('2025 Q2-Q4', '2025-04-01', '2025-12-31'),
    ('2026 Apr-Aug (test period)', '2026-04-08', '2026-08-21'),
]

results = []
for label, start, end in periods:
    period_dates = [d for d in dates if d[:10] >= start and d[:10] <= end]
    if len(period_dates) < 5:
        continue
    period_rows_by_date = {d: rows_by_date[d] for d in period_dates}
    
    def period_run(selector):
        cash = 100000
        positions = []
        equity = []
        local_idx = {d: i for i, d in enumerate(period_dates)}
        for i, d in enumerate(period_dates):
            matured = [p for p in positions if i >= p['exit_i']]
            positions = [p for p in positions if i < p['exit_i']]
            for p in matured:
                ep = None
                exit_d = period_dates[min(p['exit_i'], len(period_dates)-1)]
                for er in period_rows_by_date.get(exit_d, []):
                    if er['symbol'] == p['symbol']:
                        ep = er['price']
                        break
                if ep is None:
                    ep = p['entry_price']
                cash += p['shares'] * ep * 0.999
            if i % 5 == 0 and cash > 1000:
                picks = selector(period_rows_by_date.get(d, []))
                if picks:
                    n = min(len(picks), 15)
                    alloc = cash / n
                    for r in picks[:n]:
                        if cash < 1000:
                            break
                        price = r['price']
                        shares = int(alloc / price)
                        if shares < 1:
                            continue
                        ec = shares * price * 1.001
                        if ec > cash:
                            shares = max(1, int(cash / (price * 1.001)))
                            ec = shares * price * 1.001
                        if ec > cash or shares < 1:
                            continue
                        positions.append({'symbol': r['symbol'], 'shares': shares, 'entry_price': price, 'exit_i': i + 5})
                        cash -= ec
            mv = cash
            for p in positions:
                for cr in period_rows_by_date.get(d, []):
                    if cr['symbol'] == p['symbol']:
                        mv += p['shares'] * cr['price']
                        break
                else:
                    mv += p['entry_price'] * p['shares']
            equity.append(mv)
        final = cash + sum(p['shares'] * p['entry_price'] for p in positions)
        eq = np.array(equity)
        total = final / 100000 - 1
        peak = 100000
        maxdd = 0
        for v in eq:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > maxdd:
                maxdd = dd
        return total * 100, maxdd * 100
    
    ret15, dd15 = period_run(top15_selector)
    ret8, dd8 = period_run(top8_thresh3_selector)
    qqq_period_prices = [qqq_by_date[d] for d in period_dates if d in qqq_by_date]
    qqq_ret = (qqq_period_prices[-1] - qqq_period_prices[0]) / qqq_period_prices[0] * 100 if len(qqq_period_prices) > 1 else 0
    print(f"{label:30s} top15={ret15:6.1f}% dd={dd15:5.1f}% | top8t3={ret8:6.1f}% dd={dd8:5.1f}% | QQQ={qqq_ret:6.1f}%")
    results.append({
        'label': label,
        'top15_return_pct': ret15, 'top15_dd_pct': dd15,
        'top8_thresh3_return_pct': ret8, 'top8_thresh3_dd_pct': dd8,
        'qqq_return_pct': qqq_ret,
    })

with open('/opt/stonk-ai/v3_rebuild/reports/regime_test.json', 'w') as f:
    json.dump(results, f, indent=2)
print('\nSaved regime_test.json')
