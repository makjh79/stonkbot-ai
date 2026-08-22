import json, numpy as np

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_target_v2.json'))
feature_cols = ['ret_5d','ret_10d','ret_20d','vs_qqq_5d','dist_ema20','ema20_slope','dist_ema50','rsi14','vol_ratio','atr_pct','range_20d']
rows = [r for r in records if all(r.get(c) is not None for c in feature_cols)]
dates = sorted(set(r['date'] for r in rows))
train_cutoff = dates[int(len(dates)*0.6)]
val_cutoff = dates[int(len(dates)*0.8)]
train_rows = [r for r in rows if r['date'] <= train_cutoff]
test_rows = [r for r in rows if r['date'] > val_cutoff]

def mr_score(r):
    s = max(0, -r['ret_5d']*5)
    if r['rsi14'] < 35: s += (35 - r['rsi14'])/10
    if r['dist_ema20'] < 0: s += -r['dist_ema20']*3
    s += max(0, -r['vs_qqq_5d'])
    s += min((r['vol_ratio']-1)*0.5, 1)
    return s

test_dates = sorted(set(r['date'] for r in test_rows))

def round_returns(picker):
    rounds = []
    for i in range(0, len(test_dates)-5, 5):
        d = test_dates[i]
        day_rows = [r for r in test_rows if r['date'] == d]
        if not day_rows: continue
        picks = picker(day_rows)
        if picks:
            rounds.append(np.mean(picks) - 0.002)
    return np.array(rounds)

mr_rounds = round_returns(lambda rows: [r['ret_5d_target'] for _, r in sorted([(mr_score(r), r) for r in rows], reverse=True)[:5]])
mr_total = np.prod(1 + mr_rounds) - 1
print(f'MR top-5 rounds: avg {mr_rounds.mean():.3%}, std {mr_rounds.std():.3%}, total {mr_total:.2%}, n={len(mr_rounds)}')

X_train = np.array([[r[c] for c in feature_cols] for r in train_rows])
y_train = np.array([r['target_5d_up'] for r in train_rows])
X_test = np.array([[r[c] for c in feature_cols] for r in test_rows])
mean, std = X_train.mean(0), X_train.std(0); std[std==0]=1
Xs_test = (X_test-mean)/std
def sigmoid(z): return 1/(1+np.exp(-np.clip(z,-250,250)))
w = np.zeros(Xs_test.shape[1]+1)
Xb_train = np.hstack([np.ones((X_train.shape[0],1)), (X_train-mean)/std])
for _ in range(2000):
    p = sigmoid(Xb_train@w)
    g = Xb_train.T@(p-y_train)/len(y_train)
    w -= 0.1*g
Xb_test = np.hstack([np.ones((Xs_test.shape[0],1)), Xs_test])
proba = sigmoid(Xb_test @ w)

def momentum_picker(day_rows):
    day_idx = [i for i,r in enumerate(test_rows) if r in day_rows]
    pr = sorted([(proba[i], r) for i,r in zip(day_idx, day_rows)], reverse=True)
    return [r['ret_5d_target'] for _, r in pr[:5]]

mo_rounds = round_returns(momentum_picker)
mo_total = np.prod(1 + mo_rounds) - 1
print(f'MO top-5 rounds: avg {mo_rounds.mean():.3%}, std {mo_rounds.std():.3%}, total {mo_total:.2%}, n={len(mo_rounds)}')

univ_rounds = round_returns(lambda rows: [r['ret_5d_target'] for r in rows[:5]])
univ_total = np.prod(1 + univ_rounds) - 1
print(f'Universe first-5 rounds: avg {univ_rounds.mean():.3%}, std {univ_rounds.std():.3%}, total {univ_total:.2%}, n={len(univ_rounds)}')

all_rounds = round_returns(lambda rows: [r['ret_5d_target'] for r in rows])
all_total = np.prod(1 + all_rounds) - 1
print(f'Universe equal-weight rounds: avg {all_rounds.mean():.3%}, std {all_rounds.std():.3%}, total {all_total:.2%}, n={len(all_rounds)}')

with open('/opt/stonk-ai/v3_rebuild/reports/proper_backtest.json','w') as f:
    json.dump({
        'mr_top5': {'avg': float(mr_rounds.mean()), 'std': float(mr_rounds.std()), 'total': float(mr_total), 'n': int(len(mr_rounds))},
        'mo_top5': {'avg': float(mo_rounds.mean()), 'std': float(mo_rounds.std()), 'total': float(mo_total), 'n': int(len(mo_rounds))},
        'univ_first5': {'avg': float(univ_rounds.mean()), 'std': float(univ_rounds.std()), 'total': float(univ_total), 'n': int(len(univ_rounds))},
        'univ_equal': {'avg': float(all_rounds.mean()), 'std': float(all_rounds.std()), 'total': float(all_total), 'n': int(len(all_rounds))},
    }, f, indent=2)
print('Saved proper_backtest.json')
