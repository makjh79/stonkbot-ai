# Handover to Einstein — Readiness Threshold UI Alignment (2026-07-01 15:30 HKT)

## What changed
Howie noticed the website still showed old readiness entry thresholds. Jeeves aligned all frontend copy with the tightened entry gate.

## Current backend entry gate
- `readiness_score >= 75`
- `confirmation_count >= 4`
- `above_ema = True`

## Frontend updates in `/var/www/hedge-fund-website/index.html`
- **Trade log / bot rationale**: updated from "≥72 + 3+ confirmations" to "≥75 + 4+ confirmations + above EMA".
- **Readiness tooltip thresholds**:
  - ≥78: Strong conviction (eligible for full entries)
  - ≥75: High conviction (4+ confirmations + above EMA)
  - 55-74: Fading / watching
  - <55: Low / trim candidate
- **Watchlist tier tooltip**: updated labels to STRONG / ACTIVE / WATCH / MONITOR and thresholds.
- **Watchlist popup fallback** for `whatTriggersBuy`: updated to "Readiness >= 75 with 4+ confirmations and above EMA."
- All stale "72" references in readiness context removed.

## Validation
- `node --check` passed.
- v6 merge triggered to refresh popup narratives.
- File ownership set to `www-data:www-data`.

## No changes to trading logic
Backend tiers remain `STRONG_NOW` / `NOW` / `WATCH` / `MONITOR`. Only display labels and copy were updated.
