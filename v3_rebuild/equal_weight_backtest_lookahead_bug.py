import json
import numpy as np
from collections import defaultdict

bars = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json'))
qqq = bars['QQQ']
qqq_by_date = {ts: c for ts, c in zip(qqq['timestamps'], qqq['closes'])}

# Build per-date rows with forward 1d and 5d returns
universe = sorted([s for s in bars.keys() if s not in ('SPY', 'QQQ')])

def ema(values, period):
    if len(values) < period: return None
    mult = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = (v - e) * mult + e
    return e

def rsi(closes, period=14):
    if len(closes) < period + 1: return None
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0: return 100
    return 100 - 100 / (1 + ag / al)

records = []
for sym in universe:
    data = bars[sym]
    if len(data.get('timestamps', [])) < 60: continue
    ts = data['timestamps']
    c = data['closes']; v = data['volumes']; h = data['highs']; lo = data['lows']
    for i in range(50, len(c) - 5):
        price = c[i]
        past_c = c[:i+1]
        ret_1d = (c[i+1] - price) / price
        ret_5d = (c[i+5] - price) / price
        ema20 = ema(past_c, 20)
        dist_ema20 = (price - ema20) / ema20 if ema20 else 0
        rsi14 = rsi(past_c, 14)
        records.append({
            'symbol': sym, 'date': ts[i], 'price': price,
            'ret_1d': ret_1d, 'ret_5d': ret_5d,
            'dist_ema20': dist_ema20, 'rsi14': rsi14,
        })

rows_by_date = defaultdict(list)
for r in records:
    rows_by_date[r['date']].append(r)

dates = sorted(rows_by_date.keys())

def run_strategy(selector, rebalance_days=5, max_positions=25, target_positions=20,
                  cost=0.001, start_value=100000.0, use_5d=True):
    """
    selector(day_rows, current_portfolio) -> list of symbols to buy.
    Hold for rebalance_days, then liquidate and re-enter.
    """
    cash = start_value
    positions = []  # list of dicts: symbol, shares, entry_price, entry_cost, exit_i
    equity_curve = []
    trades = []
    
    for i, d in enumerate(dates):
        # Mature positions
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
        
        # Rebalance entry
        if i % rebalance_days == 0 and cash > 1000:
            day_rows = rows_by_date.get(d, [])
            picks = selector(day_rows)
            if picks:
                n = min(len(picks), max_positions)
                allocation = cash / n
                for r in picks[:n]:
                    if cash < 1000: break
                    price = r['price']
                    shares = int(allocation / price)
                    if shares < 1: continue
                    entry_cost = shares * price * (1 + cost)
                    if entry_cost > cash:
                        shares = max(1, int(cash / (price * (1 + cost))))
                        entry_cost = shares * price * (1 + cost)
                    if entry_cost > cash or shares < 1: continue
                    positions.append({
                        'symbol': r['symbol'], 'shares': shares,
                        'entry_price': price, 'entry_cost': entry_cost,
                        'exit_i': i + rebalance_days,
                    })
                    cash -= entry_cost
        
        # Mark to market
        market_value = cash
        for p in positions:
            for cr in rows_by_date[d]:
                if cr['symbol'] == p['symbol']:
                    market_value += p['shares'] * cr['price']
                    break
            else:
                market_value += p['entry_cost']
        equity_curve.append({'date': d, 'equity': market_value})
    
    # Final liquidation
    final_date = dates[-1]
    for p in positions:
        gross = p['shares'] * p['entry_price']
        proceeds = gross * (1 - cost)
        cash += proceeds
        pnl = proceeds - p['entry_cost']
        trades.append({'pnl_pct': pnl / p['entry_cost']})
    final_equity = cash
    
    eq_vals = np.array([e['equity'] for e in equity_curve])
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
        'final_equity': round(final_equity, 2),
    }

# Split dates
train_cutoff = dates[int(len(dates)*0.6)]
test_dates = [d for d in dates if d > dates[int(len(dates)*0.8)]]
test_start, test_end = test_dates[0], test_dates[-1]

# Strategy 1: Equal-weight all available names
def all_equal_selector(day_rows):
    return day_rows

# Strategy 2: Only names above 20d EMA
def above_ema_selector(day_rows):
    return [r for r in day_rows if r['dist_ema20'] > 0]

# Strategy 3: Only names below 20d EMA (mean reversion basket)
def below_ema_selector(day_rows):
    return [r for r in day_rows if r['dist_ema20'] < 0]

# Strategy 4: Avoid extreme RSI overbought
rsi_threshold = 75
def rsi_filter_selector(day_rows):
    return [r for r in day_rows if r['rsi14'] < rsi_threshold]

# Strategy 5: Equal-weight but skip the worst 5d losers (no falling knives)
def no_falling_knife_selector(day_rows):
    sorted_rows = sorted(day_rows, key=lambda r: r['ret_5d'] if 'ret_5d' in r else 0, reverse=True)
    return [r for r in sorted_rows if r.get('ret_5d', 0) > -0.20]

# Run all
configs = [
    ('All equal-weight', all_equal_selector),
    ('Above EMA20', above_ema_selector),
    ('Below EMA20', below_ema_selector),
    ('RSI < 75 filter', rsi_filter_selector),
    ('No falling knife', no_falling_knife_selector),
]

results = []
for name, selector in configs:
    res = run_strategy(selector, rebalance_days=5, max_positions=25, target_positions=20, cost=0.001)
    res['name'] = name
    results.append(res)
    print(f"{name}: ret={res['total_return_pct']}% dd={res['max_drawdown_pct']}% win={res['win_rate']} n={res['n_trades']}")

# QQQ benchmark over test period
qqq_test_prices = [qqq_by_date[d] for d in test_dates if d in qqq_by_date]
qqq_total_ret = (qqq_test_prices[-1] - qqq_test_prices[0]) / qqq_test_prices[0] if len(qqq_test_prices) > 1 else 0
print(f"\nQQQ test period ({test_start[:10]} to {test_end[:10]}): {qqq_total_ret:.2%}")

with open('/opt/stonk-ai/v3_rebuild/reports/equal_weight_backtest.json', 'w') as f:
    json.dump({
        'test_period': {'start': test_start[:10], 'end': test_end[:10]},
        'qqq_return_pct': round(qqq_total_ret * 100, 2),
        'strategies': results,
    }, f, indent=2)
print('Saved equal_weight_backtest.json')
