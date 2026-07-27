# StonkBOT.AI Entry Signal Redesign — 2026-07-27

## Status
Entries are halted via sentinel `/opt/stonk-ai/ENTRIES_HALTED` while the new signal is validated on paper. Existing positions continue to exit on their own stop/trim rules.

## Why
Factor attribution on the 23 snapshot-backed round trips showed the current composite readiness score has **no correlation with outcomes** (r = -0.012), and several core factors have **negative edge**:
- MACD turning: -19 pp
- RSI signal: -13 pp
- Bid-ask bullish (QBI): -25 pp
- Momentum score: -4 pp
- Intraday confirmed: -2 pp

Positive-edge factors were limited to:
- Volume/relvol confirmed: +31 pp (tiny n=2)
- Spread OK: +22.7 pp
- Options flow: +9.8 pp
- VWAP confirmed: +3.1 pp

Because the snapshotter refuses to backfill old trades honestly, the total evidence for factor edges is small. This redesign removes the provably inverted factors, reweights toward the positive-edge ones, and raises the gate while we accumulate a fresh, larger sample.

## Changes made 2026-07-27

### 1. `signal_rules.py`
- `ENTRY_READINESS_MIN`: 75.0 → **80.0**
- `ENTRY_MIN_CONFIRMATIONS`: 5 → **6**
- `ENTRY_MIN_HARD_CONFIRMATIONS`: 1 → **2**
- `HARD_CONFIRMATION_KEYS`: removed `macd_turning`, added `vwap_confirmed`
  - New set: `{volume_confirmed, intraday_confirmed, options_confirmed, vwap_confirmed, relvol_confirmed}`

### 2. `readiness_score.py`
Dropped or reduced weights with negative / zero edge, raised weights with positive edge:
- `WEIGHT_MACD`: 0.08 → **0.00** (attribution -19pp)
- `WEIGHT_RSI`: 0.10 → **0.00** (attribution -13pp)
- `WEIGHT_VOLUME`: 0.05 → **0.10** (volume/relvol +31pp)
- `WEIGHT_OPTIONS`: 0.05 → **0.10** (options flow +9.8pp)
- `WEIGHT_VWAP_DEV`: 0.05 → **0.10** (VWAP +3.1pp)
- `WEIGHT_INTRADAY`: 0.10 → **0.05** (intraday -2.2pp)
- `WEIGHT_SIGNAL`: 0.20 → **0.25** (compensate for removed factors)
- `WEIGHT_SECTOR`: 0.30 → **0.25** (stabilizer)

MACD and RSI components are still computed and logged in `confirmations` for UI/display purposes, but they no longer contribute to the readiness score or the entry gate.

### 3. `trading_bot.py`
- Sentinel halt message updated: "entries halted: signal redesign in progress"
- `ENTRIES_HALTED` remains in place until validation passes

## What does NOT change
- Existing 4 positions (AAPL, ELF, PAYO, ROKU) keep their current exits, stops, trims
- Exit logic, ATR stops, cooldowns, sector caps, earnings/implied-move gates all unchanged
- Paper trading mode unchanged
- Attribution pipeline (`entry_factor_snapshots.py`, `factor_attribution.py`, `trade_quality_report.py`) continues running and will snapshot new trades when entries eventually resume

## Validation protocol
1. **Keep entries halted** for 4–6 weeks minimum.
2. Monitor `signals.json` output of the new model daily. Confirm fewer false positives, higher average quality score.
3. When entries resume (initially at 0.5–1% position size), allow `entry_factor_snapshots.py` to capture ~50–100 honest snapshots.
4. Re-run `factor_attribution.py`. Success criteria before sizing up:
   - Profit factor > 1.0 on snapshot-backed trades
   - Win rate > 40%
   - Readiness score correlation with P&L > 0.10
   - No factor with edge < -10 pp
5. If criteria fail after 6 weeks, redesign again.

## Risks / caveats
- The evidence base is small (23 snapshot-backed round trips). The new weights are educated guesses, not a trained model.
- Dropping MACD/RSI may improve the composite, but the strategy could still have no edge if the remaining factors were spuriously positive in a small sample.
- Removing MACD/RSI from the score changes historical `readiness_score` values; backtests on old data are no longer directly comparable.

## How to resume entries later
```bash
# Only when validation passes and owner decides
cd /opt/stonk-ai
sudo -u stonkai rm ENTRIES_HALTED
sudo systemctl restart stonk-ai
```

## Files touched
- `/opt/stonk-ai/signal_rules.py`
- `/opt/stonk-ai/readiness_score.py`
- `/opt/stonk-ai/trading_bot.py`

## Backup
- `/opt/stonk-ai/signal_rules.py.bak-20260727-redesign`
- `/opt/stonk-ai/readiness_score.py.bak-20260727-redesign`

## Addendum 2026-07-27 15:20 HKT — OWNER RESUMED SAME DAY

Entries resumed by owner decision ~5h after halt. Sentinel removed, service restarted 15:20:30 HKT. New 80/6/2 gate + reweighted readiness score remain LIVE. Validation protocol continues in parallel: snapshots keep accumulating; attribution rerun still planned after 50-100 snapshot-backed round trips. Resume-at-tiny-size step skipped per owner; full caps apply (12% STRONG_NOW / 8% others).
