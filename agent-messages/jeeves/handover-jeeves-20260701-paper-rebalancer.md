# Handover to Einstein — Paper Rebalancer Prototype (2026-07-01 16:51 HKT)

## What changed
Howie wants the trading bot to use readiness scores more directly for capital allocation. Jeeves built a paper prototype first, before touching live trading logic.

## New script
- `/opt/stonk-ai/paper_rebalancer.py`
- Reads `/opt/stonk-ai/signals.json` and `/var/www/hedge-fund-website/portfolio_data.json`
- Computes a target-weight allocation proportional to readiness score for all entry-eligible symbols
- Output: `/opt/stonk-ai/paper_rebalance_plan.json`
- Does **NOT** execute trades

## Schedule
- Runs every 15 minutes during US market hours (13:30–20:00 UTC, Mon–Fri) via `stonkai` cron
- Heartbeat recorded via `/opt/stonk-ai/heartbeat_tracker.py paper_rebalancer`

## Example plan (current state)
- Portfolio: $99,724
- Deployable (90%): $89,751
- Eligible symbols: 5
- Target allocations:
  - SOFI STRONG R80.4 → 18.4% (buy +$17.4K)
  - AMD STRONG R79.1 → 18.1% (buy +$12.4K)
  - UPST STRONG R78.6 → 18.0% (buy +$14.6K)
  - TER ACTIVE R77.6 → 17.8% (buy +$16.3K)
  - LRCX ACTIVE R77.0 → 17.6% (buy +$13.8K)

This is dramatically more aggressive than the current bot, which leaves 62% cash idle.

## Purpose
This gives Howie a view of what a readiness-aligned capital allocation would look like. After collecting plans for a few weeks, we can compare simulated vs. actual bot performance and decide whether to implement the logic live.

## Files changed
- `/opt/stonk-ai/paper_rebalancer.py`
- `/var/spool/cron/crontabs/stonkai`
- `/opt/stonk-ai/paper_rebalance_plan.json`

## Backup
- `/opt/stonk-ai/backups/comprehensive-20260701-0851.tar.gz`

## Note
No website changes. No live bot changes. This is paper-only analysis.
