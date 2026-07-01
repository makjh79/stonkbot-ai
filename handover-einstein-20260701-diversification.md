# Handover: Sector-aware diversification (2026-07-01)

## What changed
Added a sector-aware diversification allocator to both the **paper rebalancer** and the **live trading bot**.

### Motivation
- The high-beta basket was blocking all new buys because the basket was ~80% of deployed capital vs the 35% cap.
- This left the bot sitting on ~62% cash while only high-beta ideas crossed the tightened entry gate.
- The new allocator deploys remaining capital into **near-eligible, non-high-beta names from underweight sectors**.

### New parameters (paper_rebalancer.py + trading_bot.py)
- `DIVERSIFICATION_READINESS_MIN = 65.0`
- `DIVERSIFICATION_CONFIRMATIONS_MIN = 2`
- `DIVERSIFICATION_MAX_SECTOR_PCT = 0.30`
- `DIVERSIFICATION_TARGET_PCT = 0.045` (~4.5% per div name)
- `MAX_SECTOR_PCT = 0.30`
- `MAX_SINGLE_TARGET_PCT = 0.08` in paper rebalancer (aligns with live bot's 8% per-position cap)

### Files changed on VPS
- `/opt/stonk-ai/paper_rebalancer.py`
  - Computes sector exposure, caps per-sector allocation, excludes high-beta from div pool, prioritizes non-high-beta eligible names first.
  - Output now shows 17 buys (from 0 before), 0 trims.
- `/opt/stonk-ai/trading_bot.py`
  - Imports `load_high_beta_symbols`.
  - New helpers: `_symbol_sector()`, `_sector_exposures()`, `_add_diversification_entries()`.
  - Diversification pass runs after the core entry queue when **cash > 40% of portfolio**.
  - Candidates must be non-high-beta, readiness ≥65, ≥2 confirmations, above EMA, from underweight sectors.
  - Respects high-beta buy gate, sector cap, and 8% single-stock cap.
  - Tested: queues 11 div entries across Healthcare, Financials, Industrials, Fintech, Consumer/Platform.
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
  - Unchanged; still uses `high_beta_blocked` for over-cap names.
- `/var/www/hedge-fund-website/index.html`
  - Cache buster remains `v20260701-2029-v148-beta-cap`.

### Current paper plan output
- Portfolio value: $99,110.84
- Deployable value: $89,199.76
- Eligible symbols: 6
- **Buys: 17**, Trims: 0
- Diversification names targeted: LLY, JNJ, TMO, ABBV, UNH, ILMN, BMY (Healthcare); JPM, V, BAC, SCHW (Financials); UNP, CAT, RTX (Industrials); ABNB (Consumer/Platform); PAYO (Fintech); FTNT (Cybersecurity).
- High-beta names (AMD, LRCX, UPST, TER, SOFI, HOOD) are **held at current size** — no new high-beta capital added.

### Backup
- `/opt/stonk-ai/backups/diversification-20260701-1343.tar.gz`

### Monitoring notes for Einstein
1. The live bot is still PAPER. Watch the first few cycles for `"DIV ENTRY queued"` log lines.
2. Verify diversification buys respect the 8% single-stock cap and do not push any sector above 30% of portfolio.
3. Watch for unexpected interaction with the high-beta cap. The `_high_beta_buy_blocked` gate is applied to div entries too.
4. If the bot starts buying too many low-readiness names, raise `DIVERSIFICATION_READINESS_MIN` or lower `DIVERSIFICATION_TARGET_PCT`.
5. If cash stays above 40% for multiple days, the pass will keep adding div candidates each cycle. This is intentional but could lead to over-trading; monitor total number of positions.

### Known next step
- Update the website's Next Buys UI to show a new `diversification` status (currently only shows `queued`/`add`/`high_beta_blocked`). Not blocking for live bot operation.
