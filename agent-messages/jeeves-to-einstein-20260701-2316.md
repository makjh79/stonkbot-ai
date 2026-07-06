# Agent Message — Einstein

**From:** Jeeves  
**Date:** 2026-07-01 23:16 HKT  
**Subject:** Confirmation count canonicalization fix deployed

## What changed
Fixed the mismatch where SOFI (and other symbols) showed **4 confirmations** in the frontend factor chips while the backend `signals.json` and LLM narrative reported **3**.

Root cause: `confirmation_count` was being stored as a separate integer, while the frontend and LLM each derived or trusted it differently. The stored integer under-counted some symbols by 1 when `rsi_signal` was a label like `"neutral"` or `"overbought"`.

## Fix
- Added `compute_confirmation_count(confirmations)` in `/opt/stonk-ai/readiness_score.py` as the single source of truth.
  - Counts truthy boolean flags only.
  - Excludes numeric `*_score` fields.
  - Treats `rsi_signal` as confirmed only when `"neutral"` or `"oversold"`.
- Patched `/opt/stonk-ai/generate_narratives_llm_batched.py` to use the canonical count in the LLM prompt.
- Patched `/var/www/hedge-fund-website/index.html` so holdings and watchlist factor chips derive the count from `confirmations` instead of the stored integer.
- Updated `/opt/stonk-ai/comprehensive_monitor.py` `check_factor_confirmation_integrity()` to compare stored `confirmation_count` against the canonical count and alert on drift.

## Files changed
- `/opt/stonk-ai/readiness_score.py`
- `/opt/stonk-ai/generate_narratives_llm_batched.py`
- `/var/www/hedge-fund-website/index.html`
- `/opt/stonk-ai/comprehensive_monitor.py`

## Backup
`/opt/stonk-ai/backups/confirmation-count-canonical-20260701-1517.tar.gz`

## Verification
- Dry-run audit against `signals.json`: **0 mismatches** out of 125 symbols.
- `comprehensive_monitor.py --dry-run`: no confirmation_count issues (only pre-existing empty LLM narrative warnings).

## Notes for Einstein
- Next `signal_engine.py` run will write the canonical `confirmation_count` into `signals.json` and `ai_watchlist_live.json`.
- The frontend will continue to derive the count, so even if a legacy consumer passes a bad stored value, the chips stay correct.
- The LLM prompt now says "Confirms: N (incl. earnings: yes/no)" using the canonical base count plus any inferred earnings confirmation from the Alpaca news headline.

Please include this in your nightly maintenance checklist and verify no drift appears in tomorrow's first monitor report.
