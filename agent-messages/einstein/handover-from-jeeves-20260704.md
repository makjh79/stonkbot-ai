# Handover from Jeeves — 2026-07-04 23:45 HKT

## Summary
Completed a comprehensive end-to-end audit and cleanup of the StonkBOT pipeline, UI, and monitor. All changes are backed up to `/opt/stonk-ai/backups/20260704-2345-comprehensive/`.

## Key Changes

### Backend
- `readiness_score.py`: `compute_confirmation_count()` now counts `momentum_score >= 50` as a confirmation.
- `signal_engine.py`: `Signal.confirmation_count` is recomputed from `confirmations` before saving.
- `dynamic_watchlist_manager.py`:
  - Removed legacy `diversification` branch (non-PRIME symbols were appearing as Next Buys).
  - Recomputes `confirmation_count` from `confirmations`.
  - Added `WATCHING` tier for readiness 40–55.
  - Watchlist table now shows "Conf" (confirmations /10) instead of AI Score.
- `fetch_ai_watchlist.py`: recomputes `confirmation_count` from `confirmations`.
- `generate_popup_content_v3.py`: watchlist narratives now include `confirmations`, `confirmation_count`, `readiness_score`, `signal_tier`, `entry_eligible`.

### Frontend
- `index.html` (cache buster `stonkbot_v165`):
  - Next Buys section only shows PRIME `queued`/`add` candidates.
  - Watchlist "AI" column replaced with "Conf".
  - Conf badge colors align with tier badge colors.
  - Tier display uses `display_tier` (PRIME/BUILDING/WATCHING/TRACKING).
  - Popup confirmation counts use canonical `confirmation_count` and green chips match.
  - Added versioned JSON fetch to bypass Cloudflare cache (`?v=stonkbot_v165&_=${Date.now()}`).

### Monitor
- `comprehensive_monitor.py` overhauled with new checks:
  - `check_alignment_signals_vs_watchlist()` — tier/entry/readiness/conf consistency using readiness thresholds.
  - `check_trading_bot_entry_gate()` — only PRIME symbols pass the gate.
  - `check_alpaca_portfolio_sync()` — Alpaca ↔ popup_content ↔ portfolio_data.
  - `check_llm_narrative_freshness_and_validity()` — LLM narrative fields + freshness (market-hours only).
- Alerts silenced unless something is actually broken:
  - Removed semantic-contradiction false positives.
  - LLM stale alerts only during market hours.
  - Cron heartbeat stale alerts market-hours only (4× tolerance off-hours).
  - Missing `data-sources provenance` downgraded to silent.

## Current State
- `comprehensive_monitor.py` runs clean: `0` issues, `0` warnings.
- Only PRIME/entry-eligible symbols: **UBER, SNOW**.
- All 20 watchlist symbols have consistent confirmation counts across backend, table, and popups.

## Files Changed (see backup)
- `comprehensive_monitor.py`
- `dynamic_watchlist_manager.py`
- `readiness_score.py`
- `signal_engine.py`
- `fetch_ai_watchlist.py`
- `generate_popup_content_v3.py`
- `generate_popup_content_v3_full.py`
- `run_signal_engine.py`
- `/var/www/hedge-fund-website/index.html`
- `/var/www/hedge-fund-website/ai_watchlist_live.json`
- `/var/www/hedge-fund-website/popup_content.json`
- `/var/www/hedge-fund-website/watchlist_narratives.json`
- `/opt/stonk-ai/signals.json`
