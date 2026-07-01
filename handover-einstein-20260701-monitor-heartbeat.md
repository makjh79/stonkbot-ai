# Handover: Monitor heartbeat alert fix (2026-07-01)

## Problem
`comprehensive_monitor.py` was firing a DEGRADED alert because several cron jobs were "stale" in the heartbeat tracker, even though the jobs themselves were running.

## Root cause
The jobs had no heartbeat recording logic. The monitor expected fresh heartbeats, but the scripts never called `heartbeat_tracker.py` on success.

## Files changed on VPS
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
  - Added `_record_heartbeat()` at end of `__main__` block.
- `/opt/stonk-ai/update_iv_summaries.py`
  - Added `_record_heartbeat()` at end of `__main__` block.
- `/opt/stonk-ai/comprehensive_monitor.py`
  - Added `_record_heartbeat()` after `main()` returns.
  - Bumped `signals.json` freshness threshold from 600s to 1200s (signal refresh ~15 min).
  - Made `update_iv_summaries` heartbeat expectation market-hours-aware: 30 min during market, 2880 min otherwise.
  - Bumped `daily_liquidity_report_am` and `daily_liquidity_report_pm` thresholds to 1500 min (daily reports).
- `/opt/stonk-ai/daily_liquidity_report.py`
  - Added `_record_heartbeat()` at end of `__main__` block (records as `daily_liquidity_report_am`; same binary runs both AM and PM).

## Verification
- Ran monitor dry-run: `ISSUES: 0`, `WARNINGS: 2` (pre-existing ROKU semantic contradictions in `whatTriggersBuy` text).
- No Telegram alert should fire unless real issues appear.

## Backup
- `/opt/stonk-ai/backups/monitor-heartbeat-fix-20260701-1435.tar.gz`

## Monitoring notes for Einstein
1. Heartbeats are now self-reported by each job on success.
2. If a job fails silently, its heartbeat will still age out — monitor will catch it.
3. `daily_liquidity_report.py` records only `daily_liquidity_report_am`; if we want separate AM/PM heartbeats later, split the record call based on UTC hour.
4. Remaining 2 warnings are narrative-generation semantic issues on ROKU, not monitor/heartbeat related.
