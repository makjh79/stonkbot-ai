import json
import numpy as np
from collections import defaultdict

records = json.load(open('/opt/stonk-ai/v3_rebuild/data/features_2yr.json'))

feature_cols = [
    'ret_5d', 'ret_10d', 'ret_20d',
    'vs_qqq_5d', 'vs_spy_5d',
    'dist_ema20', 'ema20_slope', 'dist_ema50', 'dist_ema200',
    'rsi14', 'vol_ratio', 'vol_trend', 'atr_pct', 'range_20d',
    'sector_breadth',
]

rows = [r for r in records if all(r.get(c) is not None for c in feature_cols)]
print(f'Usable rows: {len(rows)}')

# Time-based split: train 60%, val 20%, test 20
dates = sorted(set(r['date'] for r in rows))
train_cutoff = dates[int(len(dates)*0.6)]
val_cutoff = dates[int(len(dates)*0.8)]
train_rows = [r for r in rows if r['date'] <= train_cutoff]
val_rows = [r for r in rows if train_cutoff < r['date'] <= val_cutoff]
test_rows = [r for r in rows if r['date'] > val_cutoff]

print(f'Train: {len(train_rows)}, Val: {len(val_rows)}, Test: {len(test_rows)}')

def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -250, 250)))

def train_logreg(X_train, y_train, lr=0.05, epochs=3000):
    w = np.zeros(X_train.shape[1] + 1)
    Xb = np.hstack([np.ones((X_train.shape[0], 1)), X_train])
    for _ in range(epochs):
        p = sigmoid(Xb @ w)
        g = Xb.T @ (p - y_train) / len(y_train)
        w -= lr * g
    return w

def metrics(y_true, y_pred, proba):
    acc = (y_pred == y_true).mean()
    tp = ((y_pred == 1) & (y_true == 1)).sum()
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()
    prec = tp / (tp + fp) if (tp + fp) else 0
    rec = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    pos = proba[y_true == 1]
    neg = proba[y_true == 0]
    auc = (np.sum(pos[:, None] > neg[None, :]) + 0.5 * np.sum(pos[:, None] == neg[None, :])) / (len(pos) * len(neg)) if len(pos) and len(neg) else 0.5
    return {'accuracy': acc, 'precision': prec, 'recall': rec, 'f1': f1, 'auc': auc}

X_train = np.array([[r[c] for c in feature_cols] for r in train_rows])
y_train_1d = np.array([r['target_1d_up'] for r in train_rows])
y_train_5d = np.array([r['target_5d_up'] for r in train_rows])

mean, std = X_train.mean(0), X_train.std(0)
std[std == 0] = 1

def stdize(X):
    return (X - mean) / std

Xs_train = stdize(X_train)
w_1d = train_logreg(Xs_train, y_train_1d)
w_5d = train_logreg(Xs_train, y_train_5d)

# Validation to pick decision threshold
X_val = np.array([[r[c] for c in feature_cols] for r in val_rows])
Xs_val = stdize(X_val)
y_val_1d = np.array([r['target_1d_up'] for r in val_rows])
y_val_5d = np.array([r['target_5d_up'] for r in val_rows])

Xb_val = np.hstack([np.ones((Xs_val.shape[0], 1)), Xs_val])
proba_val_1d = sigmoid(Xb_val @ w_1d)
proba_val_5d = sigmoid(Xb_val @ w_5d)

print('\n=== Validation metrics (threshold 0.5) ===')
for name, y_val, proba in [('1d', y_val_1d, proba_val_1d), ('5d', y_val_5d, proba_val_5d)]:
    pred = (proba >= 0.5).astype(int)
    res = metrics(y_val, pred, proba)
    print(f'{name}: acc={res["accuracy"]:.3f} prec={res["precision"]:.3f} rec={res["recall"]:.3f} f1={res["f1"]:.3f} auc={res["auc"]:.3f} baseline={y_val.mean():.3f}')

# Test set
X_test = np.array([[r[c] for c in feature_cols] for r in test_rows])
Xs_test = stdize(X_test)
y_test_1d = np.array([r['target_1d_up'] for r in test_rows])
y_test_5d = np.array([r['target_5d_up'] for r in test_rows])

Xb_test = np.hstack([np.ones((Xs_test.shape[0], 1)), Xs_test])
proba_test_1d = sigmoid(Xb_test @ w_1d)
proba_test_5d = sigmoid(Xb_test @ w_5d)

print('\n=== Test metrics (threshold 0.5) ===')
for name, y_test, proba in [('1d', y_test_1d, proba_test_1d), ('5d', y_test_5d, proba_test_5d)]:
    pred = (proba >= 0.5).astype(int)
    res = metrics(y_test, pred, proba)
    print(f'{name}: acc={res["accuracy"]:.3f} prec={res["precision"]:.3f} rec={res["recall"]:.3f} f1={res["f1"]:.3f} auc={res["auc"]:.3f} baseline={y_test.mean():.3f}')

# Feature weights for 1d model
print('\n=== 1d model weights ===')
for c, wt in zip(['intercept'] + feature_cols, w_1d):
    print(f'  {c}: {wt:.3f}')

# Save model and predictions
with open('/opt/stonk-ai/v3_rebuild/reports/model_2yr.json', 'w') as f:
    json.dump({
        'feature_cols': feature_cols,
        'mean': mean.tolist(),
        'std': std.tolist(),
        'w_1d': w_1d.tolist(),
        'w_5d': w_5d.tolist(),
        'val_auc_1d': float(metrics(y_val_1d, (proba_val_1d >= 0.5).astype(int), proba_val_1d)['auc']),
        'test_auc_1d': float(metrics(y_test_1d, (proba_test_1d >= 0.5).astype(int), proba_test_1d)['auc']),
        'test_auc_5d': float(metrics(y_test_5d, (proba_test_5d >= 0.5).astype(int), proba_test_5d)['auc']),
    }, f, indent=2)
print('\nSaved model_2yr.json')
