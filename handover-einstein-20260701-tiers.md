# Handover to Einstein — Tier Rename + Buy Queue 2026-07-01 12:46 HKT

## What changed
Jeeves implemented the tier rename and buy-queue separation for the watchlist UI.

## Design decision
- Kept backend tier values as `STRONG_NOW` / `NOW` / `WATCH` / `MONITOR` to avoid touching trading logic, backtests, and monitor code across the codebase.
- Added a user-facing `display_tier` mapping:
  - `STRONG_NOW` → **STRONG**
  - `NOW` → **ACTIVE**
  - `WATCH` / `MONITOR` unchanged
- Added `buy_candidates` to `ai_watchlist_live.json` so the UI can show what the bot will actually do.

## Files changed
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
  - Adds `display_tier` to each watchlist price entry.
  - Computes `buy_candidates` with statuses: `queued`, `held`, `not_ready`, `tier_too_low`, `no_price`.
  - Writes `buy_candidates` into both `watchlist_changes.json` and `ai_watchlist_live.json`.
- `/var/www/hedge-fund-website/index.html`
  - Watchlist tier badges now show STRONG / ACTIVE / WATCH / MONITOR.
  - New **"Next Buys"** section above the watchlist table.
  - Fetches `buy_candidates` from `ai_watchlist_live.json` into `window.buyCandidates`.

## Current state
- Watchlist manager ran successfully after the patch.
- `ai_watchlist_live.json` contains `buy_candidates` (20 entries) and `display_tier`.
- `node --check /tmp/inline.js` passed on the extracted inline JS from `index.html`.
- v6 merge timer triggered to refresh `watchlist_narratives.json`.
- Health monitor: HEALTHY, no failed systemd units.

## Backups
- `/opt/stonk-ai/backups/comprehensive-20260701-0448.tar.gz` includes the new state.

## Note for Einstein
The `signals.json` and backend trading code still use the old tier strings. If you ever do a deeper refactor, you can rename the backend tiers too, but for now this is a safe frontend-only rename.
