# Handover: Anti-churn v2 (Einstein, 2026-07-22 ~09:25 HKT)

**Commits:** 7c288c2 (risk_engine.py, trading_bot.py, comprehensive_monitor.py) + 52cb035 (startup log line). Deployed, stonk-ai.service restarted 09:21 HKT while market closed.

## What broke yesterday (Jul 21)
LCID: STRONG_NOW entry 1543 sh (target $11,267 ≈ 11.8% pv) → concentration trim 365 sh 2 min later → avg-in 393 sh 2 min after → hard stop 1571 sh 20 min later. AAPL similar (avg-in → trim → avg-in → trim).
Root cause: concentration trimmer used FLAT 10% cap (trigger 10.5% incl. band) while STRONG_NOW entries size to the 12% tier cap. Every STRONG_NOW entry auto-tripped the trimmer; avg-in immediately re-bought. Two subsystems fighting.

## Changes
1. `risk_engine.check_concentration(portfolio_data, force=False, tier_map=None)` — new optional tier_map param (bot passes `{symbol: tier}` from `self._signals`). Effective per-position cap = max(10% backstop, tier cap). STRONG_NOW → 12%. Other tiers unchanged. Sector branch untouched.
2. Tier caps now single-sourced in `risk_engine.tier_max_position_pct()` (12/8/5/3). `trading_bot._tier_max_position_pct` delegates.
3. New 4h sell re-entry cooldown: after ANY non-stop sell (trim/rotation/thesis/profit), entries AND avg-ins on that symbol blocked 4h. Stop-losses still use the 20h stop-out path. State: `risk_state.json` → `sell_cooldowns`. API: `record_nonstop_sell()`, `in_sell_reentry_cooldown()`. Gates: `_check_anti_churn_gates` + avg-in path. Recording: `_execute_sell` (catches all sell paths).
4. Monitor `check_trade_churn` rewritten: counts same-symbol BUY↔SELL flips/day (issue ≥5, warn ≥3) + >50 raw-trade backstop. Old >20/day raw threshold gone — it false-fired on healthy rotation.

## Watch tomorrow (Wed session)
- First STRONG_NOW entries should NO LONGER be instantly concentration-trimmed (if sized ≤12%).
- Log lines to grep: "SELL COOLDOWN recorded", "sell re-entry cooldown active", "Skipping avg-in .* sell re-entry".
- trades_log rationale strings are UNRELIABLE (sync inference mis-tags) — use logs/trading_bot.log for ground truth on why a trade happened.
