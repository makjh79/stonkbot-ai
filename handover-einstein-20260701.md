# Handover to Einstein — 2026-07-01 11:40 HKT

## What changed
Jeeves moved the LLM-driven popup narrative generator to the VPS so it no longer depends on Howie’s Mac being on.

## New VPS systemd timers
- `stonk-ai-popup-v6.timer` — every 2 minutes: refreshes base v2 popup data and overlays LLM narratives.
- `stonk-ai-llm-narrative.timer` — every 15 minutes: generates fresh LLM narratives for all holdings + watchlist.

## Files / paths
- `/opt/stonk-ai/generate_narratives_llm_batched.py` — batched generator (6 symbols per LLM call)
- `/opt/stonk-ai/stonk-ai-llm-narrative.service`
- `/opt/stonk-ai/stonk-ai-llm-narrative.timer`
- `/opt/stonk-ai/company_knowledge.json` — auto-extending cache for company notes/risks
- `/var/www/hedge-fund-website/popup_narratives.json`
- `/var/www/hedge-fund-website/watchlist_narratives_llm.json`

## Model / API
- Uses `openrouter/moonshotai/kimi-k2.6` via `openclaw infer model run`.
- Service runs as `root` because OpenClaw auth profiles live under `/root/.openclaw/`.
- Each LLM call is wrapped with `timeout -s KILL 240`.

## Health monitoring
- Added `check_llm_narrative_pipeline()` to `/opt/stonk-ai/comprehensive_monitor.py`.
- Monitors: timer active, service not failed, LLM output files valid + fresh (≤25 min), merged files contain narrative fields.
- Scheduled `comprehensive_monitor.py` in stonkai crontab:
  - Every 5 min during US market hours (09:00–16:59 ET, Mon–Fri)
  - Every 15 min pre/post-market and weekends
- Logs to `/opt/stonk-ai/logs/comprehensive_monitor.log`.

## Known noise
The semantic-contradiction check in `comprehensive_monitor.py` is currently flagging a few watchlist `whatTriggersBuy` texts as claiming a factor is missing when it is actually confirmed. This is pre-existing copy quality noise, not a pipeline failure.

## Backup
- Comprehensive backup: `/opt/stonk-ai/backups/comprehensive-20260701-0340.tar.gz` (51 MB)
- Key files also copied to `/opt/stonk-ai/backups/comprehensive-20260701-0340/extra/`

## No further action required
Everything is running end-to-end on the VPS. The Mac-side narrative generation pipeline can be considered retired.
