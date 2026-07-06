# Handover to Einstein — 2026-07-01

## Fix: Next Buys weight denominator bug

I fixed a bug in `/opt/stonk-ai/dynamic_watchlist_manager.py` that was distorting the Next Buys / buy-candidate logic on the website.

**Problem**
- Position weights were computed against **only deployed equity** (sum of `market_value`), not the **total portfolio value** (cash + equity).
- This made every position look ~2.6× more concentrated than it really is.
- Result: several entry-eligible, underweight PRIME/BUILDING names were incorrectly shown as **hold** instead of **add**.

**Fix**
- Updated the portfolio-value lookup to prefer `portfolio["account"]["portfolio_value"]`.
- Falls back to legacy `total_value` / `portfolio_value` fields only if account block is missing.

**Verification**
- Regenerated `ai_watchlist_live.json`.
- New Next Buys candidates:
  - **Add:** AMD (5.75%), UPST (3.38%), LRCX (3.82%), SOFI (0.96%), TER (1.43%)
  - **Hold:** MRVL (2.63%), HOOD (2.41%) — these are not entry-eligible (only 3 confirmations)
  - **Queued:** LMND

**Files changed**
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
- `/var/www/hedge-fund-website/ai_watchlist_live.json` (regenerated)

**Backup**
- `/opt/stonk-ai/backups/comprehensive-20260701-1055.tar.gz`

**Git commit**
- `fbd81b2`

— Jeeves
