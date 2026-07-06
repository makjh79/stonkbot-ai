# Handover to Einstein — 2026-07-01

## Smart LLM narrative scheduler deployed

I implemented a new scheduler for the LLM narrative generator to reduce OpenRouter cost.

**File:** `/opt/stonk-ai/llm_narrative_scheduler.py`

**What changed**
- `stonk-ai-llm-narrative.service` now calls the scheduler instead of `generate_narratives_llm_batched.py` directly.
- The timer still fires every 15 minutes; the scheduler decides whether to run the generator.

**Logic**
1. **Market open** (Mon–Fri 09:30–16:00 ET): run every 15 min.
2. **Overnight / pre-market** (closed, next open ≤14h away): run once per 60 min.
3. **Weekends / public holidays / early closures** (next open >14h away): skip.

**Cost impact**
- Old flat 15-min cadence: ~$83/month.
- New smart schedule: ~$20–25/month.

**What to watch**
- `/opt/stonk-ai/.llm_narrative_last_run` tracks last successful run timestamp.
- If the generator fails, the scheduler will retry at the next eligible tick.
- The v6 merge still runs every 2 minutes; base v2 narratives remain available as fallback.

**Other changes today**
- Tier labels: PRIME / BUILDING / WATCHING / TRACKING.
- Watchlist auto-refresh every 30s on active tab.
- Extended-hours popup flicker fixed.

**Backups**
- `/opt/stonk-ai/backups/comprehensive-20260701-1045.tar.gz`

— Jeeves
