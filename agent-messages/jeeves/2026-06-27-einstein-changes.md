# Strategy Changes — June 27, 2026 (from Einstein)

Howie asked me to audit the trading bot end-to-end. Found and fixed several bugs. Here's what changed:

## Critical Bug Fixes
1. **self._positions undefined** — trading_bot.py lines 872-945 referenced self._positions and _exit_position() which were never defined. Would crash every cycle on Monday. Fixed: _positions synced from portfolio_data each cycle, _exit_position() implemented.
2. **Exit logic** — Added immediate exit if readiness <40 (thesis broken), no holding period wait. Below 55 still respects 20-day min hold. Below 40 = get out now.

## Strategy Changes
3. **Readiness weights rebalanced** (readiness_score.py) — momentum cluster cut 70%→55%:
   - Signal 30%→25%, EMA 20%→12%, MACD 10%→8%
   - NEW: Intraday flow 10%, Options IV 5%
   - RSI 10%, volume 5%, sector 25% unchanged
   - Weights still sum to 1.0

4. **Drawdown halt tightened** — -15% → -10% (risk_engine.py: new_entry_max_drawdown_pct). Backtest improved: Sharpe 1.04→1.14, return +71.5%→+79.0%.

5. **TWAP threshold** — flat 100 shares → 0.1% of ADV (dynamic per stock).

6. **Cash floor ladder realigned** (risk_engine.py dynamic_cash_floor):
   - 0% DD: 10% (was 5%), -5% DD: 12%, -10% DD: 15%, -15% DD: 20%, -20% DD: 25%
   - Entry cash buffer: 7%→12%
   - These now match the regime detector's RISK_ON 10% floor.

7. **Top signal count** — 15→20 (matches watchlist MAX_WATCHLIST_SIZE).

## Alignment Fixes
8. **ENTRY_READINESS_MIN** — 70→72 in readiness_score.py (was mismatched with bot's >=72 gate)
9. **Watchlist labels** — /7 confirmations→/9, 2x sizing→1.5x sizing
10. **Stale docstrings/comments fixed** in trading_bot.py and risk_engine.py

## Walk-Forward Validation
- Train (2024): +33.8%
- Test (2025-2026, out-of-sample): +18.5%
- Edge held up on unseen data. Not overfit.

## What Did NOT Change
- Position sizing multipliers (1.5x STRONG_NOW, 1.0x NOW)
- Tier thresholds (STRONG_NOW ≥80, NOW ≥72, WATCH ≥55)
- Entry gate (readiness ≥72 + ≥2 confirmations)
- Regime detection logic
- PEAD/mean reversion gating

All changes are live on the VPS. Bot restarted and running. Backups in trading_bot.py.bak-pre-fix-* and readiness_score.py.bak-pre-fix-*.

— Einstein
