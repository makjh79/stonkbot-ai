# Handover to Einstein — End-to-End Tier / Readiness Alignment (2026-07-01 15:45 HKT)

## What changed
Howie asked to ensure tiers and readiness scores are aligned end-to-end and across the pipeline. Jeeves found and fixed the core mismatch.

## The problem
The backend entry gate is:
- `readiness_score >= 75`
- `confirmation_count >= 4`
- `above_ema = True`

But `signal_engine.py` still assigns tiers using readiness score bands only (STRONG_NOW ≥78, NOW ≥72). So a symbol with readiness 82 but only 3 confirmations would show `STRONG` on the website even though the bot cannot buy it.

## The fix
- Updated `dynamic_watchlist_manager.py` so `display_tier` reflects actual entry eligibility:
  - `STRONG`: `signal_tier == STRONG_NOW` AND `entry_eligible` AND readiness ≥78
  - `ACTIVE`: `signal_tier == NOW` AND `entry_eligible`
  - `WATCH`: `signal_tier` in (`STRONG_NOW`, `NOW`, `WATCH`) but NOT `entry_eligible`
  - `MONITOR`: `signal_tier` in (`MONITOR`, `TRACKING`)
- Updated `buy_candidates` display tier to use the same logic.
- Updated the watchlist tier tooltip in `index.html` to explain the new semantics.
- No backend `signal_engine.py` tier assignment changed — that remains readiness-band based for internal use.

## Example current state
| Symbol | Signal tier | Display tier | Ready score | Conf | Above EMA | Entry eligible | Buy status |
|--------|-------------|----------------|-------------|------|-----------|----------------|------------|
| SOFI   | STRONG_NOW  | STRONG         | 80.4        | 4    | True      | True           | add        |
| AMD    | STRONG_NOW  | STRONG         | 79.7        | 4    | True      | True           | hold       |
| MU     | STRONG_NOW  | WATCH          | 82.0        | 3    | True      | False          | hold       |
| HD     | NOW         | WATCH          | 77.6        | 3    | True      | False          | hold       |
| TER    | NOW         | ACTIVE         | 77.6        | 4    | True      | True           | add        |
| KLAC   | NOW         | WATCH          | 74.4        | 3    | True      | False          | not_ready  |

## Validation
- `dynamic_watchlist_manager.py` runs successfully.
- `ai_watchlist_live.json` updated with aligned `display_tier`.
- `node --check` passed.
- v6 merge triggered.

## Files changed
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
- `/var/www/hedge-fund-website/index.html`
- `/var/www/hedge-fund-website/ai_watchlist_live.json`

## Backup
- `/opt/stonk-ai/backups/comprehensive-20260701-0746.tar.gz`
