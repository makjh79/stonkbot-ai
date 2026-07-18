# StonkBOT.AI File Ownership & Single-Writer Rules

This document is the source of truth for which process owns each critical file.

## Goal

Prevent race conditions, permission drift, and regressions by ensuring each
critical file has exactly one writer. Readers are allowed from anywhere.

## Single-Writer Registry

| File | Single Writer | Writer Script | Notes |
|------|--------------|---------------|-------|
| `/opt/stonk-ai/signals.json` | Signal Engine | `signal_engine.py` | `run_signal_engine.py` may also fix in place |
| `/opt/stonk-ai/ai_watchlist_live.json` | Dynamic Watchlist Manager | `dynamic_watchlist_manager.py` | Sole writer since 2026-07-06 |
| `/var/www/hedge-fund-website/ai_watchlist_live.json` | Dynamic Watchlist Manager | `dynamic_watchlist_manager.py` | Sole writer; mirrored from opt |
| `/opt/stonk-ai/portfolio_data.json` | Trading Bot | `trading_bot.py` | Canonical bot portfolio state |
| `/var/www/hedge-fund-website/portfolio_data.json` | Trading Bot | `trading_bot.py` | Mirrored copy |
| `/opt/stonk-ai/portfolio_history.json` | History Reconstructor | `reconstruct_portfolio_history.py` (+ daily appends by `health_check.py`) | Daily reconstruct; health_check appends the 17:59 UTC snapshot |
| `/var/www/hedge-fund-website/portfolio_history.json` | History Reconstructor | `reconstruct_portfolio_history.py` | Mirrored copy |
| `/var/www/hedge-fund-website/popup_content.json` | Popup Generator | `generate_popup_content_narrative_v6_server.py` | v6 narrative merge |
| `/var/www/hedge-fund-website/watchlist_narratives.json` | LLM Narrative Generator | `generate_narratives_llm_batched.py` | Batched LLM narratives |
| `/opt/stonk-ai/signal_rules.py` | Shared rules module | n/a (import-only) | Single source of truth for tiers/entry; edit intentionally |
| `/opt/stonk-ai/dead_factor_lint.py` | Maintenance lint | cron or manual | Detects zombie references to removed data sources (PEAD and the 3 deprecated external APIs) |

| `/opt/stonk-ai/signal_outcomes.json` | Outcome Tracker | `outcome_tracker.py` | Model/trade outcome measurement state |
| `/var/www/hedge-fund-website/signal_accuracy.json` | Outcome Tracker | `outcome_tracker.py` | Website export of outcome stats |
| `/opt/stonk-ai/company_names.json` | Signal Engine data file | `signal_engine.py` (reads), `fetch_company_names.py` (rebuilds) | Generated from Alpaca assets; merged at import to expand `COMPANY_NAMES` |
| `/opt/stonk-ai/pnl_attribution.json` | Outcome Tracker | `outcome_tracker.py` | Realized P&L by decision type |
| `/var/www/hedge-fund-website/pnl_attribution.json` | Outcome Tracker | `outcome_tracker.py` | Website mirror of P&L attribution |

## Shared Write Helper

All writers must use `stonk_utils.atomic_write_json()` which:

- Writes to a temp file in the same directory
- Atomically renames into place
- `chmod 0644`s the result
- Enforces the single-writer registry above
- Cleans up the temp file on failure
- **Post-write assertions (new 2026-07-14):** checks size > 0, mtime within `max_age_seconds`, expected owner/mode, and immutable flag. Failing any assertion raises so stale data cannot silently propagate.

## Permission & Process Monitoring

`comprehensive_monitor.py` checks every cycle:

1. Critical files are owned by `stonkai:stonkai` with mode `0644`
2. No stonk-ai process is running as `root`
3. No duplicate instances of the same stonk-ai script
4. Tier/entry alignment between `signals.json` and `ai_watchlist_live.json` via `signal_rules.py` (single source of truth)
5. Dead-factor lint is available via `dead_factor_lint.py` and should be wired into the deploy pipeline

## Do Not

- Run stonk-ai scripts manually as `root`
- Add a second writer for any file in the registry without updating this doc
- Write to these files without using `stonk_utils.atomic_write_json()`
- Set `+i` (immutable) on any file a non-root cron needs to update

## ⚠️ Known Architecture Debt

### ai_watchlist_live.json — Single Writer (fixed 2026-07-06)
`dynamic_watchlist_manager.py` is now the sole writer.
`fetch_ai_watchlist.py` has been stopped and disabled; its systemd service `stonk-ai-watchlist.service` is inactive.
Both `/opt/stonk-ai/ai_watchlist_live.json` and `/var/www/hedge-fund-website/ai_watchlist_live.json` are written by DWM.
DWM writes the `watchlist` array + `prices` dict + `buy_candidates` + `targets` with correct upside targets.
The web file is canonical; the opt copy is a mirror for downstream monitors.

### Redundant Timers
- `stonk-ai-watchlist.service` was DISABLED and stopped on 2026-07-06
- `stonk-ai-watchlist.path` trigger was also disabled
- If watchlist live pricing is ever needed again, refactor `fetch_ai_watchlist.py` to only update `live_prices.json` and let DWM keep sole ownership of `ai_watchlist_live.json`
