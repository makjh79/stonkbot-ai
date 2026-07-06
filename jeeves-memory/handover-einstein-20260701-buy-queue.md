# Handover to Einstein — Buy Queue Add/Hold Split (2026-07-01 13:05 HKT)

## What changed
Jeeves refined the watchlist "Next Buys" section so it reflects actual capital-deployment intent, not just entry eligibility.

## Backend
- `/opt/stonk-ai/dynamic_watchlist_manager.py` now loads `portfolio_data.json` and computes each held symbol's portfolio weight.
- `buy_candidates` statuses:
  - `queued` — new buy (not held, entry-eligible)
  - `add` — held, underweight (< 6%), still entry-eligible
  - `hold` — held, at/above threshold or not eligible to add
  - `not_ready` — readiness/confirmation gate not met
  - `tier_too_low` — tier below entry gate
  - `no_price` — missing live price
- `weight_pct` included in each candidate record.
- `ADD_WEIGHT_THRESHOLD = 6.0` (percent of portfolio). Adjust if the bot's target weight changes.

## Frontend
- `/var/www/hedge-fund-website/index.html` "Next Buys" section now shows:
  - 🎯 New buys
  - ➕ Add to position
  - ✓ Hold
  - 🚫 Not ready
- Watchlist popups still append "Bot status: ..." to `whatTriggersBuy` via the v6 merge script.

## Files changed
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
- `/opt/stonk-ai/generate_popup_content_narrative_v6_server.py`
- `/var/www/hedge-fund-website/index.html`
- `/var/www/hedge-fund-website/ai_watchlist_live.json`
- `/var/www/hedge-fund-website/watchlist_narratives.json`

## Current state (example)
- `add`: SOFI (2.5%), TER (3.8%)
- `hold`: MU (11.8%), AMD (15.0%), HD (20.0%), etc.
- `not_ready`: KLAC, LMND, PAYO, UNP, RELY, LLY, TMO, JPM, V
- Health monitor: HEALTHY, no failed units.

## Backup
- `/opt/stonk-ai/backups/comprehensive-20260701-0509.tar.gz`
