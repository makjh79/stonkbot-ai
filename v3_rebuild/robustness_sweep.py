import json, numpy as np
from collections import defaultdict

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_with_price.json'))
dates = sorted(set(r['date'] for r in records))
train_cutoff = dates[int(len(dates)*0.6)]
test_rows = [r for r in records if r['date'] > dates[int(len(dates)*0.8)]]

def mr1d_score(r):
    s = 0.0
    s += max(0.0, -r['ret_5d'] * 3.0)
    if r['rsi14'] < 35:
        s += (35.0 - r['rsi14']) / 5.0
    if r['dist_ema20'] < 0:
        s += -r['dist_ema20'] * 2.0
    s += max(0.0, -r['vs_qqq_5d'])
    s += min((r['vol_ratio'] - 1.0) * 0.3, 1.0)
    return s

def backtest(strategy, rows, start_value=100000.0, max_positions=8,
             position_pct=0.03, cost=0.001, hold_days=1, top_k=5):
    rows_by_date = defaultdict(list)
    for r in rows:
        rows_by_date[r['date']].append(r)
    dates = sorted(rows_by_date.keys())
    cash = start_value
    positions = []
    equity_curve = []
    trades = []
    for i, d in enumerate(dates):
        matured = [p for p in positions if i >= p['exit_i']]
        positions = [p for p in positions if i < p['exit_i']]
        for p in matured:
            exit_price = None
            exit_rows = rows_by_date.get(dates[min(p['exit_i'], len(dates)-1)], [])
            for er in exit_rows:
                if er['symbol'] == p['symbol']:
                    exit_price = er['price']
                    break
            if exit_price is None:
                exit_price = p['entry_price']
            gross = p['shares'] * exit_price
            proceeds = gross * (1 - cost)
            cash += proceeds
            pnl = proceeds - p['entry_cost']
            trades.append({'pnl_pct': pnl / p['entry_cost']})
        day_rows = rows_by_date.get(d, [])
        open_slots = max_positions - len(positions)
        if open_slots > 0 and cash > 1000 and day_rows:
            scored = [(strategy(r), r) for r in day_rows]
            scored.sort(reverse=True)
            picks = [r for _, r in scored[:min(top_k, open_slots)]]
            for r in picks:
                if cash < 1000: break
                target_value = min(cash * position_pct, cash / max(1, len(picks)))
                if target_value < 1000: continue
                price = r['price']
                shares = int(target_value / price)
                if shares < 1: continue
                entry_cost = shares * price * (1 + cost)
                if entry_cost > cash:
                    shares = max(1, int(cash / (price * (1 + cost))))
                    entry_cost = shares * price * (1 + cost)
                if entry_cost > cash or shares < 1: continue
                positions.append({
                    'symbol': r['symbol'], 'shares': shares,
                    'entry_price': price, 'entry_cost': entry_cost,
                    'exit_i': i + hold_days,
                })
                cash -= entry_cost
        market_value = cash
        for p in positions:
            for cr in day_rows:
                if cr['symbol'] == p['symbol']:
                    market_value += p['shares'] * cr['price']
                    break
            else:
                market_value += p['entry_cost']
        equity_curve.append(market_value)
    final_equity = cash + sum(p['shares'] * p['entry_price'] for p in positions)
    eq_vals = np.array(equity_curve)
    total_ret = final_equity / start_value - 1.0
    max_dd = 0.0
    peak = start_value
    for v in eq_vals:
        if v > peak: peak = v
        dd = (peak - v) / peak
        if dd > max_dd: max_dd = dd
    winning = [t for t in trades if t['pnl_pct'] > 0]
    losing = [t for t in trades if t['pnl_pct'] <= 0]
    return {
        'total_return_pct': round(total_ret * 100, 2),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'n_trades': len(trades),
        'win_rate': round(len(winning) / len(trades), 3) if trades else 0,
        'avg_win_pct': round(np.mean([t['pnl_pct'] for t in winning]) * 100, 2) if winning else 0,
        'avg_loss_pct': round(np.mean([t['pnl_pct'] for t in losing]) * 100, 2) if losing else 0,
    }

print('=== Parameter sweep for MR-1D ===')
results = []
for top_k in [3, 5, 8, 10]:
    for pos_pct in [0.02, 0.03, 0.05]:
        for max_pos in [5, 8, 10]:
            res = backtest(mr1d_score, test_rows, max_positions=max_pos,
                          position_pct=pos_pct, cost=0.001, hold_days=1, top_k=top_k)
            res['top_k'] = top_k
            res['pos_pct'] = pos_pct
            res['max_pos'] = max_pos
            results.append(res)

# Sort by total return
results.sort(key=lambda x: -x['total_return_pct'])
print('Top 10 configs by total return:')
for r in results[:10]:
    print(f"  top_k={r['top_k']} pos_pct={r['pos_pct']} max_pos={r['max_pos']}: ret={r['total_return_pct']}% dd={r['max_drawdown_pct']}% win={r['win_rate']} n={r['n_trades']}")

with open('/opt/stonk-ai/v3_rebuild/reports/robustness_sweep.json', 'w') as f:
    json.dump(results, f, indent=2)
print('\nSaved robustness_sweep.json')
