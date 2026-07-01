# Handover to Einstein — VPS Memory Maintenance (2026-07-01 13:20 HKT)

## What changed
Jeeves installed a VPS-based memory maintenance script as an alternative to OpenClaw's native "dreaming" (which runs on the Mac).

## Script
- Path: `/opt/stonk-ai/vps_memory_maintenance.py`
- Owner: `stonkai:stonkai`
- Runs as root cron because OpenClaw auth profiles live under `/root/.openclaw/`.

## What it does
1. Reads `MEMORY.md` and recent `memory/YYYY-MM-DD.md` files from `/opt/stonk-ai/jeeves-memory/`.
2. Uses `openclaw infer model run --model openrouter/moonshotai/kimi-k2.6` to analyze:
   - Suggested additions to long-term memory
   - Suggested removals of stale entries
   - Contradictions between old and new information
   - Low-priority items
3. Writes a human-readable report to `/opt/stonk-ai/jeeves-memory/DREAMS.md`.
4. Does **NOT** modify `MEMORY.md` unless run manually with `--apply`.

## Schedule
- Daily at 3:00 AM HKT (19:00 UTC) via root crontab.
- Logs to `/opt/stonk-ai/logs/vps_memory_maintenance.log`.

## First run output
The first report identified:
- **Suggested additions:** local Ollama primary config, Alpaca Premium Data backtest degradation, paper→live trading transition pending, Einstein sync artifact paths.
- **Suggested removals:** stale DeepInfra model references, outdated health-alert cron note, ephemeral open questions.
- **Contradictions:** DeepInfra vs Ollama config; old +102% backtest vs new +25.5%; Finnhub → Alpaca SIP → Premium SIP evolution.
- **Low priority:** memory search disabled, gateway restart flakiness, resolved Alpaca order issues.

## Important note
The Mac is the source of truth for `MEMORY.md` (synced one-way to the VPS at 3 AM HKT). The VPS maintenance script only *reports* suggestions; it does not auto-apply edits to avoid sync conflicts. If you want to apply changes, review `DREAMS.md` and edit `MEMORY.md` on the Mac.

## Backup
- `/opt/stonk-ai/backups/comprehensive-20260701-0520.tar.gz`
