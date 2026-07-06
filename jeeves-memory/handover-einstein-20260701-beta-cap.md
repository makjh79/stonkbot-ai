# Handover: High-beta basket cap (2026-07-01)

## What changed
Implemented the macro-concentration guard Gemini flagged: a **high-beta basket cap** separate from the 20% sector cap.

### Files changed on VPS
- `/opt/stonk-ai/risk_engine.py`
  - Added `RiskConfig` fields: `high_beta_basket_cap_enabled`, `max_high_beta_deployed_pct=0.35`, `high_beta_spy_beta_threshold=1.2`, `high_beta_spy_corr_threshold=0.70`.
  - Added `load_high_beta_symbols()` helper (reads `correlation_report.json`).
  - Added `check_high_beta_basket(portfolio_data, high_beta_symbols)` method that trims high-beta positions when deployed capital in the basket exceeds 35%.
- `/opt/stonk-ai/trading_bot.py`
  - Imports `load_high_beta_symbols`.
  - Loads basket once per cycle.
  - New `_high_beta_buy_blocked()` gate blocks new high-beta buys that would push the basket over cap (both RISK_OFF and RISK_ON entry branches).
  - **Trim is NOT wired into the live cycle yet.** Per the agreed rollout, first version is buy-block only. Trim logic exists in risk_engine for later.
- `/opt/stonk-ai/paper_rebalancer.py`
  - Same cap applied to paper target allocation.
  - Adds `high_beta_cap` metadata to the output plan.
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
  - Loads high-beta basket and computes current exposure.
  - New `high_beta_blocked` status for buy_candidates when over cap.
- `/var/www/hedge-fund-website/index.html`
  - Next Buys UI now shows a "🛑 Macro cap" section with blocked symbols + reason.
  - Cache buster bumped to `v20260701-2029-v148-beta-cap` / `stonkbot_v142`.

### Current live impact
- High-beta basket (SPY beta >1.2 or SPY corr >0.70) = 13/20 symbols.
- Current deployed exposure = **79.8% of deployed capital** vs 35% cap.
- Result: paper rebalancer proposes **0 buys**; Next Buys marks high-beta names as `high_beta_blocked`.
- HD is not in the basket, so it remains `hold` (already 7.8%, above 6% add threshold).
- Non-high-beta symbols still show `not_ready` because they don't meet readiness/confirmations.

### Backup
- `/opt/stonk-ai/backups/beta-cap-20260701-1240.tar.gz` (latest, includes risk_engine method fix + trading_bot no-trim)
- Earlier: `/opt/stonk-ai/backups/beta-cap-20260701-1230.tar.gz`

### Git
- Local workspace commit: `832af8b`
- Pushed to `origin/main` on `makjh79/stonkbot-ai`.

### Monitoring notes for Einstein
1. Watch the first few bot cycles for `"Blocking .* buy: would push high-beta basket"` log lines.
2. Verify `correlation_report.json` is fresh (nightly cron at 01:00 UTC); stale betas could over/under-block.
3. Consider whether 35% is too tight; 30% would immediately trigger trims because current basket is already ~80% of deployed. We chose 35% as a buy-blocking-only threshold for now.
4. The live bot is still PAPER. Do not switch to live keys until strategy edge is rebuilt/verified.
5. No new crons needed; the cap runs inside existing cycles.
6. If you enable the trim later, wire `risk_engine.check_high_beta_basket(portfolio_data, high_beta_symbols)` into `trading_bot.run_cycle()` exit logic.
