# Handover to Einstein — Health Monitor Consolidation (2026-07-01 14:36 HKT)

## What changed
Howie asked to optimize health monitoring and scheduler coverage on the VPS. Jeeves consolidated and added cron heartbeat tracking.

## Changes made

### 1. Reduced `comprehensive_monitor.py` cadence
- Was: every 5 min during market hours, every 15 min off-hours.
- Now: every 15 minutes all the time.
- Reason: 5 min was overkill and overlapping with `stonk_health_check.py`.

### 2. Added heartbeat tracker
- New script: `/opt/stonk-ai/heartbeat_tracker.py`
- Critical cron jobs now record a heartbeat after successful run.
- Heartbeats stored in `/opt/stonk-ai/heartbeats/<job_name>.json`.
- Jobs with heartbeats:
  - `dynamic_watchlist_manager`
  - `reconstruct_portfolio_history`
  - `signal_enricher_full_am` / `pm`
  - `signal_enricher_news_*`
  - `watchlist_feedback`
  - `fetch_price_history`
  - `sync_alpaca_trades`
  - `update_iv_summaries`
  - `daily_liquidity_report_am` / `pm`
  - `comprehensive_monitor`
  - `stonk_health_check`
  - `auto_recovery`
  - `signal_engine_run`
  - `vps_memory_maintenance`
  - `analyze_options_skew_signal`

### 3. Added cron heartbeat check to comprehensive monitor
- New function: `check_cron_heartbeats()`
- Warns if a job's heartbeat is older than expected threshold.
- Missing heartbeats are currently ignored during rollout to avoid noise.

### 4. Cron files updated
- `/var/spool/cron/crontabs/stonkai`
- `/var/spool/cron/crontabs/root`

## Files changed
- `/opt/stonk-ai/heartbeat_tracker.py` (new)
- `/opt/stonk-ai/comprehensive_monitor.py` (added `check_cron_heartbeats()`)
- `/var/spool/cron/crontabs/stonkai`
- `/var/spool/cron/crontabs/root`

## Backup
- `/opt/stonk-ai/backups/comprehensive-20260701-0636.tar.gz`

## Note
No website changes were made. `stonk_health_check.py` remains the lightweight public-status writer; `comprehensive_monitor.py` is now less frequent but tracks scheduler liveness.
