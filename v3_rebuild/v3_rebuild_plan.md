# STONK.AI v3 Rebuild Plan

**Date:** 2026-08-22 (late night session)  
**Status:** Park mode active — `ENTRIES_HALTED` sentinel in place.  
**Author:** Einstein (OpenClaw agent)  
**Location:** `/opt/stonk-ai/v3_rebuild/`

---

## 1. Why v3 is needed

The v2.5 readiness-driven momentum engine has failed to show edge:
- Total live P&L: −6.1% over hundreds of trades.
- Factor attribution showed `readiness_score` correlation with outcomes ≈ 0.
- The entry gate (readiness ≥ 75/65, ≥ 5/3 confirmations, above_EMA hard veto) filtered out nearly all candidates in the current tape.
- Recent winners came from exits/trims, not entry selection.

The engine is effectively a capital-preservation mode dressed up as a strategy.

---

## 2. What we did tonight

### 2.1 Park mode
- Created `/opt/stonk-ai/ENTRIES_HALTED` sentinel.
- Bot continues to run: exits, stops, trims, monitoring active.
- No new entries or averaging-in until the sentinel is removed.
- Fixed a latent `has_required_positive_edge` import bug in `trading_bot.py` that was exposed during an earlier failed Option B patch attempt.

### 2.2 Data and modeling
- Pulled **2 years** of daily Alpaca SIP bars for 63 universe symbols (507 bars each, 2024-08-14 to 2026-08-21).
- Built clean feature set: 5d/10d/20d returns, QQQ-relative return, EMA20/50/200 distance, RSI(14), volume ratio, sector breadth.
- Total feature rows: 27,063.
- Ran realistic walk-forward backtests with costs (10bps one-way).

### 2.3 Key findings

#### Momentum is dead
Logistic regression direction models on 2-year data:
- 1d forward AUC: **0.484** (worse than random)
- 5d forward AUC: **0.468** (worse than random)

No feature engineering rescued it.

#### Trend pullback is the first real edge
A simple heuristic buying strong stocks on short-term weakness beats QQQ out-of-sample with lower drawdown:

| Strategy | Full 2yr | 2024 Aug-Dec | 2025 Q1 | 2025 Q2-Q4 | 2026 Apr-Aug |
|---|---|---|---|---|---|
| Trend pullback top-15 (5d hold) | **+67.5%** | +4.8% | −4.2% | +34.4% | **+28.5%** |
| QQQ | +49.8% | +4.0% | −8.0% | +30.4% | +20.8% |
| Drawdown | 32.5% | 10.3% | 20.2% | 16.4% | 11.3% |

It’s not magic, but it captures most of the upside and protects better in drawdowns.

#### Costs matter
- 1d hold: **−16.2%** (6765 trades, 0.2% round-trip costs destroy edge)
- **5d hold: +67.5%** (1350 trades)
- 10d hold: +88.2% but fewer trades

**Realistic implementation: 5-day hold / 5-day rebalance cycle.**

#### Mean reversion alone is not enough
MR-1D had positive returns but underperformed equal-weight and was not deployable.

---

## 3. v3 strategy: Trend Pullback Bounce

**Core idea:** Buy stocks in established long-term and medium-term uptrends that are experiencing a short-term pullback. Exit after 5 days or on stop/take-profit.

### 3.1 Signal weights
| Feature | Weight | Direction |
|---|---|---|
| dist_ema200 > 0 | +1.0 | Long-term trend intact |
| dist_ema50 > 0 | +1.0 | Medium trend intact |
| dist_ema20 > 0 | +0.5 | Short trend intact |
| ret_5d negative | +3 × | Recent decline |
| RSI < 45 | +0.1 × | Oversold |
| vs_qqq_5d negative | +1.0 × | Underperforming QQQ |
| vol_ratio > 1 | +0.3 capped | Volume confirmation |

### 3.2 Hard filters
- RSI < 75 (no extreme overbought)
- dist_ema200 > −15% (trend not broken)
- QQQ 5d return > −8% (no meltdown entry)
- Within 5 days of earnings: skip

### 3.3 Entry gate
- v3_score ≥ 0.5 (default; can be raised to 3.0 for higher-conviction)
- Max 15 positions (or 8 for concentrated version)
- Max 3% position size
- 20% cash floor

### 3.4 Exit
- Hold 5 trading days, then rebalance.
- Hard stop at −6%.
- Profit take at +12%.
- Existing ATR stops and trims still apply.

### 3.5 Position/risk
- 3% per name.
- 25% sector cap.
- 20% cash floor.
- Pause new entries if portfolio drawdown > 8% from high water mark.

---

## 4. Minimum deployment bar

Before removing `ENTRIES_HALTED`:
1. v3 paper-trade for 20+ sessions with positive P&L.
2. Out-of-sample walk-forward return > QQQ + 2 percentage points over equivalent period.
3. Max drawdown < 15% (this strategy has 30%+ historical DD).
4. Win rate > 50% with positive expectancy.
5. At least 100 out-of-sample trades.
6. Strategy document signed off by owner.
7. Rollback plan tested.

**Note:** The 32% historical max DD is much higher than the 5% originally hoped for. This is a growth strategy, not a low-volatility one.

---

## 5. Implementation path

### Phase 1: Validate signal engine side-by-side (now)
- `/opt/stonk-ai/v3_rebuild/v3_signal_engine.py` is built.
- Run it every cycle alongside current engine in `trading_bot.py`.
- Log v3 scores but do not trade on them yet.
- Compare v3 top picks to current readiness-driven picks.

### Phase 2: Paper validation
- Add `V3_ENABLED` config flag to `trading_bot.py`.
- When `V3_ENABLED=True` and `ENTRIES_HALTED` absent, use v3 signal for entries in paper mode.
- Run for 20+ sessions.
- Measure paper P&L vs backtest expectations.

### Phase 3: Live deployment
- Owner approval.
- Set position caps: 3% per name, 15 max positions.
- Remove `ENTRIES_HALTED`.
- Run live with tight monitoring.
- Rollback if underperforms after 20 sessions or hits 15% drawdown.

### Phase 4: Rollback
```bash
# Emergency stop
touch /opt/stonk-ai/ENTRIES_HALTED
# Restore code from backup
cp backups/trading_bot-pre-v3-*.py trading_bot.py
# Restart bot
```

---

## 6. Files and artifacts created

### Data
- `/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json`
- `/opt/stonk-ai/v3_rebuild/data/features_2yr.json`
- `/opt/stonk-ai/v3_rebuild/data/universe.json`

### Scripts
- `/opt/stonk-ai/v3_rebuild/build_features_2yr.py`
- `/opt/stonk-ai/v3_rebuild/model_2yr.py`
- `/opt/stonk-ai/v3_rebuild/equal_weight_backtest_fixed.py`
- `/opt/stonk-ai/v3_rebuild/mr_timed_equalweight.py`
- `/opt/stonk-ai/v3_rebuild/trend_pullback.py`
- `/opt/stonk-ai/v3_rebuild/trend_pullback_oos.py`
- `/opt/stonk-ai/v3_rebuild/regime_test.py`
- `/opt/stonk-ai/v3_rebuild/hold_period_test.py`
- `/opt/stonk-ai/v3_rebuild/sanity_trend_pullback.py`
- `/opt/stonk-ai/v3_rebuild/v3_signal_engine.py`
- `/opt/stonk-ai/v3_rebuild/v3_sidecar.py`
- `/opt/stonk-ai/v3_rebuild/validate_v3_engine_fixed.py`

### Reports
- `/opt/stonk-ai/v3_rebuild/reports/model_2yr.json`
- `/opt/stonk-ai/v3_rebuild/reports/equal_weight_backtest_fixed.json`
- `/opt/stonk-ai/v3_rebuild/reports/trend_pullback.json`
- `/opt/stonk-ai/v3_rebuild/reports/trend_pullback_oos.json`
- `/opt/stonk-ai/v3_rebuild/reports/regime_test.json`
- `/opt/stonk-ai/v3_rebuild/reports/hold_period_test.json`
- `/opt/stonk-ai/v3_rebuild/reports/qqq_benchmark.json`
- `/opt/stonk-ai/v3_rebuild/reports/v3_engine_validation.json`
- Plus earlier 6mo artifacts.

---

## 7. Handover to Jeeves / Einstein

- Bot is in **park mode**. No entries will fire.
- **v3 signal engine is built** and ready for side-by-side logging.
- **Momentum is dead.** Trend pullback is the working hypothesis.
- **Do not remove `ENTRIES_HALTED`** until paper validation and owner sign-off.
- Next actions: integrate v3_signal_engine.py into trading_bot.py for side-by-side logging; run paper mode; iterate on score weights.

---

## 8. Park mode recovery

To resume entries:
```bash
rm /opt/stonk-ai/ENTRIES_HALTED
```
Then restart the bot.

To deploy v3 when ready:
1. Enable `V3_ENABLED` in config.
2. Remove sentinel.
3. Monitor for 20 sessions.
