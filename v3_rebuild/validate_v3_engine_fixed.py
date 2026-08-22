"""Validate v3_signal_engine reproduces the manual backtest results.

Uses score_row() on pre-computed features_2yr.json rows — avoids the bar
index-mapping bug that broke validate_v3_engine.py.
"""

import sys
import json
import numpy as np
from collections import defaultdict

sys.path.insert(0, '/opt/stonk-ai')
from v3_rebuild.v3_signal_engine import score_row

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_2yr.json'))
rows_by_date = defaultdict(list)
for r in records:
    rows_by_date[r['date']].append(r)
dates = sorted(rows_by_date.keys())

cash = 100000
positions = []
equity = []
trades = 0

for i, d in enumerate(dates):
    # Mature positions
    matured = [p for p in positions if i >= p['exit_i']]
    positions = [p for p in positions if i < p['exit_i']]
    for p in matured:
        ep = None
        exit_d = dates[min(p['exit_i'], len(dates) - 1)]
        for er in rows_by_date.get(exit_d, []):
            if er['symbol'] == p['symbol']:
                ep = er['price']
                break
        if ep is None:
            ep = p['entry_price']
        cash += p['shares'] * ep * 0.999
        trades += 1

    if i % 5 == 0 and cash > 1000:
        day_rows = rows_by_date[d]
        scored = []
        for r in day_rows:
            score, hard_blocked = score_row(r)
            if np.isnan(score):
                continue
            # For backtest we ignore hard_blocked; just rank by score
            scored.append((score, r))
        scored.sort(reverse=True, key=lambda x: x[0])
        picks = [r for _, r in scored[:15]]

        if picks:
            n = len(picks)
            alloc = cash / n
            for r in picks:
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

    # Mark to market
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
total = final / 100000 - 1
peak = 100000
maxdd = 0
for v in eq:
    if v > peak:
        peak = v
    dd = (peak - v) / peak
    if dd > maxdd:
        maxdd = dd

print('=== v3_signal_engine end-to-end validation ===')
print(f'Total return: {total*100:.1f}%')
print(f'Max drawdown: {maxdd*100:.1f}%')
print(f'Trades: {trades}')
print(f'Final equity: ${final:,.0f}')
print(f'\nTarget (manual trend_pullback.py top-15): +67.5%, dd 32.5%')

# Save result
with open('/opt/stonk-ai/v3_rebuild/reports/v3_engine_validation.json', 'w') as f:
    json.dump({
        'return_pct': round(total * 100, 2),
        'max_dd_pct': round(maxdd * 100, 2),
        'trades': trades,
        'final_equity': round(final, 2),
        'target_return_pct': 67.5,
        'target_dd_pct': 32.5,
    }, f, indent=2)
print('Saved v3_engine_validation.json')
