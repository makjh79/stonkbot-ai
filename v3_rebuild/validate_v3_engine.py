"""Validate v3_signal_engine reproduces the manual backtest results."""

import sys
import json
import numpy as np
from collections import defaultdict

sys.path.insert(0, '/opt/stonk-ai')
from v3_rebuild.v3_signal_engine import score_universe

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_2yr.json'))
rows_by_date = defaultdict(list)
for r in records:
    rows_by_date[r['date']].append(r)
dates = sorted(rows_by_date.keys())

# Use the same symbol_bars format as sidecar
bars_2yr = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json'))

# Run v3_signal_engine each day and collect top-15 picks
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
        exit_d = dates[min(p['exit_i'], len(dates)-1)]
        for er in rows_by_date.get(exit_d, []):
            if er['symbol'] == p['symbol']:
                ep = er['price']
                break
        if ep is None:
            ep = p['entry_price']
        cash += p['shares'] * ep * 0.999
        trades += 1

    if i % 5 == 0 and cash > 1000:
        # Build symbol_bars from bars_2yr, restricted to symbols present today
        day_rows = rows_by_date[d]
        symbol_bars = {}
        for r in day_rows:
            sym = r['symbol']
            if sym not in bars_2yr:
                continue
            b = bars_2yr[sym]
            # Find index of today's close in bars_2yr (they align by construction)
            # Use all bars up to today
            idx_in_bars = len(b['closes']) - (len(dates) - i)
            if idx_in_bars < 200:
                continue
            symbol_bars[sym] = {
                'closes': b['closes'][:idx_in_bars],
                'volumes': b['volumes'][:idx_in_bars],
            }
        if 'QQQ' not in bars_2yr:
            continue
        qqq_bars = bars_2yr['QQQ']
        qqq_idx = len(qqq_bars['closes']) - (len(dates) - i)
        qqq_closes = qqq_bars['closes'][:qqq_idx]

        signals = score_universe(symbol_bars, qqq_closes)
        picks = [s['symbol'] for s in signals[:15]]

        # Map picks to day_rows for price
        pick_rows = [r for r in day_rows if r['symbol'] in picks]
        if pick_rows:
            n = len(pick_rows)
            alloc = cash / n
            for r in pick_rows:
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

print(f'v3_signal_engine end-to-end backtest:')
print(f'  Total return: {total*100:.1f}%')
print(f'  Max drawdown: {maxdd*100:.1f}%')
print(f'  Trades: {trades}')
print(f'  Final equity: ${final:,.0f}')
print(f'\nCompare to manual trend_pullback.py top-15: +67.5%, dd 32.5%')
