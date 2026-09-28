# Handover: Bot Thinking (Phase 1) — from Einstein, 2026-07-24

## What landed
New decision-stream feature is LIVE. Commits `51fe533` + `2343c1f`.

**You will see new files — do not touch their writers:**
- `/opt/stonk-ai/thinking_journal.py` — sidecar, stonkai cron `*/5 * * * *` (24/7)
- `/opt/stonk-ai/thinking_state.json` — its cursor state (sole writer: thinking_journal.py)
- `/var/www/hedge-fund-website/thinking_stream.json` — public stream (sole writer: same)
- `/var/www/hedge-fund-website/thinking.html` — public page
- `/opt/stonk-ai/logs/thinking_journal.log` — cron log

## Contract
- The sidecar is **read-only** on bot state (trades_log.json, signals.json,
  portfolio_data.json). It does not act, does not affect decisions.
- Experiment freeze (EXPERIMENT.md, Jul 22 → Aug 15) is untouched — entry/exit
  logic, stops, caps all unchanged. This is observer-only.
- `GATE_READINESS=77` / `GATE_CONFIRMATIONS=5` are hardcoded in
  thinking_journal.py to explain near-misses in scan text. **If the bot's entry
  gate ever changes, update those two constants** or the explainer text drifts.

## If it breaks
- Stream stale >20 min during market hours → comprehensive_monitor alerts.
- Teaser strip on the site hides itself if generated_at >30 min old — a dead
  pipeline is invisible to visitors, so take monitor alerts seriously.
- Safe to delete thinking_state.json + thinking_stream.json and re-run: first
  run re-bootstraps (swallows trade history, emits only same-ET-day trades).
- Revert frontend: teaser strip + More-menu link are additive-only in index.html;
  delete the marked blocks. Page is standalone — delete thinking.html +
  its deploy.yml cp step.

## LLM voice layer (added same day, ddaf8fc)
- generate_thinking_explainers.py (stonkai cron `*/5`) writes
  /opt/stonk-ai/thinking_llm.json; thinking_journal.py merges it into the
  stream. Model: ollama/kimi-k2.7-code:cloud via localhost:11434 (env
  STONKBOT_THINKING_MODEL overrides). Explainers are keyed by entry id and
  pruned to the live stream. If the voice ever reads template-y, the prompt is
  in build_prompt() — tune there, wipe thinking_llm.json, re-run to regenerate.
