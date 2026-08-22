import json
import numpy as np
from collections import defaultdict

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_with_price.json'))
dates = sorted(set(r['date'] for r in records))
train_cutoff = dates[int(len(dates)*0.6)]
val_cutoff = dates[int(len(dates)*0.8)]
train_rows = [r for r in records if r['date'] <= train_cutoff]
val_rows = [r for r in records if train_cutoff < r['date'] <= val_cutoff]
test_rows = [r for r in records if r['date'] > val_cutoff]

# 1-day mean reversion score
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

# Momentum model
def train_momentum_model(train_rows):
    feature_cols = ['ret_5d','ret_10d','ret_20d','vs_qqq_5d','dist_ema20','ema20_slope','dist_ema50','rsi14','vol_ratio','atr_pct','range_20d']
    X_train = np.array([[r[c] for c in feature_cols] for r in train_rows])
    y_train = np.array([r['target_5d_up'] for r in train_rows])
    mean, std = X_train.mean(0), X_train.std(0)
    std[std == 0] = 1.0
    Xs_train = (X_train - mean) / std
    def sigmoid(z):
        return 1.0 / (1.0 + np.exp(-np.clip(z, -250, 250)))
    w = np.zeros(Xs_train.shape[1] + 1)
    Xb = np.hstack([np.ones((Xs_train.shape[0], 1)), Xs_train])
    for _ in range(2000):
        p = sigmoid(Xb @ w)
        g = Xb.T @ (p - y_train) / len(y_train)
        w -= 0.1 * g
    return w, mean, std, sigmoid

w, mean, std, sigmoid = train_momentum_model(train_rows)

def momentum_proba(row):
    feature_cols = ['ret_5d','ret_10d','ret_20d','vs_qqq_5d','dist_ema20','ema20_slope','dist_ema50','rsi14','vol_ratio','atr_pct','range_20d']
    x = np.array([[row[c] for c in feature_cols]])
    xs = (x - mean) / std
    xb = np.hstack([np.ones((1, 1)), xs])
    return float(sigmoid(xb @ w)[0])

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
        # Liquidate matured positions
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
            trades.append({
                'symbol': p['symbol'],
                'entry_date': p['entry_date'],
                'exit_date': d,
                'shares': p['shares'],
                'entry_price': p['entry_price'],
                'exit_price': exit_price,
                'pnl': pnl,
                'pnl_pct': pnl / p['entry_cost'],
            })
        
        # Enter new positions
        day_rows = rows_by_date.get(d, [])
        open_slots = max_positions - len(positions)
        if open_slots > 0 and cash > 1000 and day_rows:
            scored = [(strategy(r), r) for r in day_rows]
            scored.sort(reverse=True)
            picks = [r for _, r in scored[:min(top_k, open_slots)]]
            for r in picks:
                if cash < 1000:
                    break
                target_value = min(cash * position_pct, cash / max(1, len(picks)))
                if target_value < 1000:
                    continue
                price = r['price']
                shares = int(target_value / price)
                if shares < 1:
                    continue
                entry_cost = shares * price * (1 + cost)
                if entry_cost > cash:
                    shares = max(1, int(cash / (price * (1 + cost))))
                    entry_cost = shares * price * (1 + cost)
                if entry_cost > cash or shares < 1:
                    continue
                positions.append({
                    'symbol': r['symbol'],
                    'shares': shares,
                    'entry_price': price,
                    'entry_cost': entry_cost,
                    'entry_date': d,
                    'exit_i': i + hold_days,
                })
                cash -= entry_cost
        
        # Mark to market
        market_value = cash
        for p in positions:
            for cr in day_rows:
                if cr['symbol'] == p['symbol']:
                    market_value += p['shares'] * cr['price']
                    break
            else:
                market_value += p['entry_cost']
        equity_curve.append({'date': d, 'equity': market_value})
    
    # Liquidate remaining positions at last price
    final_date = dates[-1]
    for p in positions:
        gross = p['shares'] * p['entry_price']
        proceeds = gross * (1 - cost)
        cash += proceeds
        trades.append({
            'symbol': p['symbol'],
            'entry_date': p['entry_date'],
            'exit_date': final_date,
            'shares': p['shares'],
            'entry_price': p['entry_price'],
            'exit_price': p['entry_price'],
            'pnl': proceeds - p['entry_cost'],
            'pnl_pct': (proceeds - p['entry_cost']) / p['entry_cost'],
        })
    final_equity = cash
    
    eq_vals = np.array([e['equity'] for e in equity_curve])
    total_ret = final_equity / start_value - 1.0
    max_dd = 0.0
    peak = start_value
    for v in eq_vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    winning_trades = [t for t in trades if t['pnl'] > 0]
    losing_trades = [t for t in trades if t['pnl'] <= 0]
    stats = {
        'start_value': start_value,
        'final_equity': round(final_equity, 2),
        'total_return_pct': round(total_ret * 100, 2),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'n_trades': len(trades),
        'win_rate': round(len(winning_trades) / len(trades), 3) if trades else 0,
        'avg_win_pct': round(np.mean([t['pnl_pct'] for t in winning_trades]) * 100, 2) if winning_trades else 0,
        'avg_loss_pct': round(np.mean([t['pnl_pct'] for t in losing_trades]) * 100, 2) if losing_trades else 0,
    }
    return {'stats': stats, 'equity_curve': equity_curve, 'trades': trades}

# Run strategies
print('=== MR-1D walk-forward ===')
mr_result = backtest(mr1d_score, test_rows, max_positions=8, position_pct=0.03, cost=0.001, hold_days=1, top_k=5)
print(mr_result['stats'])

print('\n=== Momentum 5D walk-forward ===')
mo_result = backtest(momentum_proba, test_rows, max_positions=8, position_pct=0.03, cost=0.001, hold_days=5, top_k=5)
print(mo_result['stats'])

print('\n=== Universe buy-and-hold 1D walk-forward ===')
def universe_score(r):
    return np.random.random()
np.random.seed(42)
univ_result = backtest(universe_score, test_rows, max_positions=8, position_pct=0.03, cost=0.001, hold_days=1, top_k=5)
print(univ_result['stats'])

with open('/opt/stonk-ai/v3_rebuild/reports/walkforward_backtest.json', 'w') as f:
    json.dump({
        'mr_1d': mr_result['stats'],
        'momentum_5d': mo_result['stats'],
        'universe_1d': univ_result['stats'],
    }, f, indent=2)
print('\nSaved walkforward_backtest.json')
