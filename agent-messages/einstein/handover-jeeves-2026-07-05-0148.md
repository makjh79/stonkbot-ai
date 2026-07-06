# Handover: Jeeves → Einstein | 2026-07-05 ~01:48 UTC (Sun)

## Changes made today (Jeeves)

### 1. Confirmation-count drift fix
- **Root cause:** `fetch_ai_watchlist.py` service had been running since Jul 4 and held an old-format `ai_watchlist_live.json` in memory; never reloaded the new-format watchlist from `dynamic_watchlist_manager.py`.
- **Action:** Restarted `stonk-ai-watchlist.service`.
- **Result:** `/var/www/hedge-fund-website/ai_watchlist_live.json` now has `confirmations` and `confirmation_count` fields. All 20 symbols have consistent confirmation counts.

### 2. New entry-gate rule: hard confirmations
- **Why:** DUOL and ETSY were showing PRIME with 5 confirmations but 0 hard (dynamic) confirms.
- **Files changed:**
  - `/opt/stonk-ai/readiness_score.py` — added `ENTRY_MIN_HARD_CONFIRMATIONS = 2`; `entry_eligible` now requires >=2 of (volume_confirmed, macd_turning, intraday_confirmed, options_confirmed, relvol_confirmed).
  - `/opt/stonk-ai/trading_bot.py` — paper fallback updated to enforce the same rule.
- **Action:** Restarted `stonk-ai.service`; regenerated `/opt/stonk-ai/signals.json`; ran `dynamic_watchlist_manager.py`.
- **Result:** PRIME symbols reduced from 4 to 2 — only **UBER** and **SNOW** remain PRIME. DUOL/ETSY demoted to BUILDING.
- **Backup:** `/opt/stonk-ai/backups/2026-07-05-hard-confirmation-gate.tar.gz`

### 3. Disabled redundant VPS cron job
- **Job:** `StonkBOT Pipeline Monitor` (id `602a812a-e297-4dfb-910f-be75fc7e0479`) in `/root/.openclaw/cron/jobs.json`.
- **Why:** Was failing with "Agent couldn't generate a response" due to model-call timeouts in isolated sessions; overlaps with `comprehensive_monitor.py` which already runs every 5/15 min.
- **Action:** Set `enabled: false`.

## Files to know about
- `/opt/stonk-ai/readiness_score.py` — new hard-confirmation gate
- `/opt/stonk-ai/trading_bot.py` — paper fallback updated
- `/opt/stonk-ai/signals.json` — regenerated with new gate
- `/var/www/hedge-fund-website/ai_watchlist_live.json` — regenerated, new format
- `/opt/stonk-ai/backups/2026-07-05-hard-confirmation-gate.tar.gz` — backup of above

## Watchlist state (post-change)
PRIME: UBER, SNOW
BUILDING: DUOL, ETSY, UPST, PINS, MDB, SOFI, NET, HD, NKE, DDOG, SPOT, ABNB, SHOP, PATH, GTLB
WATCH: ROKU, APP, EXPE

## Revert
To remove the hard-confirmation gate, revert `entry_eligible` in `/opt/stonk-ai/readiness_score.py` and the paper fallback in `/opt/stonk-ai/trading_bot.py`, then regenerate signals/watchlist.

— Jeeves
