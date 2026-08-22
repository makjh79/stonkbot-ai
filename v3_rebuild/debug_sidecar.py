import sys, json, math
sys.path.insert(0, '/opt/stonk-ai')
from alpaca_data import get_data_hub
from v3_rebuild.v3_signal_engine import score_universe, compute_trend_pullback_score

hub = get_data_hub()
universe = json.load(open('/opt/stonk-ai/v3_rebuild/data/universe.json'))
bars = hub.get_daily_bars(list(set(universe) | {'QQQ'}), days=220)
print('bars symbols', len(bars))
print('QQQ bars', len(bars['QQQ']['closes']))
for s in list(bars.keys())[:3]:
    print(s, 'closes len', len(bars[s]['closes']), 'volumes len', len(bars[s].get('volumes', [])))

symbol_bars = {s: {'closes': d['closes'], 'volumes': d['volumes']} for s, d in bars.items() if s not in ('SPY', 'QQQ') and 'closes' in d and 'volumes' in d}
print('symbol_bars', len(symbol_bars))
qqq = bars['QQQ']['closes']
qqq_5d = (qqq[-1] - qqq[-6]) / qqq[-6]
print('qqq_5d', qqq_5d)

sample_sym = list(symbol_bars.keys())[0]
print('sample', sample_sym, 'closes len', len(symbol_bars[sample_sym]['closes']))
score, blocked = compute_trend_pullback_score(symbol_bars[sample_sym]['closes'], symbol_bars[sample_sym]['volumes'], qqq_5d)
print('sample score', score, 'blocked', blocked)

signals = score_universe(symbol_bars, qqq)
print('signals', len(signals))
if signals:
    print('top', signals[:5])
else:
    nan_count = 0
    valid_count = 0
    for s, d in symbol_bars.items():
        score, blocked = compute_trend_pullback_score(d['closes'], d['volumes'], qqq_5d)
        if math.isnan(score):
            nan_count += 1
        else:
            valid_count += 1
    print(f'nan={nan_count}, valid={valid_count}')
