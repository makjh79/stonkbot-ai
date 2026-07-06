# Handover Note — Einstein → Jeeves
**Date:** 2026-06-29 ~18:00 UTC
**For:** Jeeves (primary StonkBOT.AI trading operator)
**Memory sync path:** `/opt/stonk-ai/einstein-memory/` — this file should be placed there for your daily read.

---

## What Changed Today (2026-06-29)

### 1. PEAD Revived as 9th Confirmation Factor
- `generate_popup_content.py`: added `_infer_pead()` that scans `alpaca_headline` for earnings keywords (`earnings`, `EPS`, `beat`, `missed`, `guidance`, `revenue`, `profit`, `sales beat`).
- Injected into both `generate_dynamic_narrative` and `generate_watchlist_narrative`.
- Frontend `index.html` updated: `buildFactorChips` and `buildWatchlistFactors` denominators changed `/8` → `/9`, PEAD chip added.
- Tier chip emojis (`🟢`, `🟡`) stripped from popup status text; CSS colored-dot styling retained.

### 2. Universe Descriptions — All 130 Symbols
- `_COMPANY_NOTES` replaced with 130 custom entries (trader-relevant: business model + key driver/moat + what moves the stock).
- `_COMPANY_RISKS` added for new watchlist symbols.
- Regenerated `popup_content.json` and `watchlist_narratives.json`.

### 3. Narrative Voice Overhaul (v138–v144)
- All 9 narrative functions in `generate_popup_content.py` rewritten to "The Smart Sniper" voice.
- `nice_join()` helper added for Oxford-comma factor lists.
- Fixed `UNH` WATCH tier false diagnosis: now uses `_missing_factors()` instead of assuming "Waiting on momentum."

### 4. Frontend-Backend Alignment
- `aiScore` no longer passed as MOM chip score; uses `momentum_score`.
- Tier status fixed in holdings popup (`STRONG_NOW` vs `NOW` vs `WATCH` vs `MONITOR`).
- Hardcoded frontend fallback strings removed from `showStockDetail` and `showTradeDetails`; backend is sole source of truth.
- Provenance `sources` dict added to all popup JSON entries.

### 5. Dead Code & Shadow Sources Eliminated
- `fetch_ai_watchlist.py`: removed Yahoo/Polygon RSI fallbacks, custom `ai_score`, shadow `COMPANY_NAMES`.
- Alignment self-test wired before `ai_watchlist_live.json` write (`|ai_score - total_score| <= 2`); zero mismatches confirmed.

### 6. Comprehensive Integrity Monitor Deployed
- File: `/opt/stonk-ai/comprehensive_monitor.py`
- Behavior: silent when HEALTHY, JSON issue report + Telegram alert on degradation.
- Checks: service health, file freshness, extended-hours prices, universe names, shadow COMPANY_NAMES, signal-watchlist alignment, factor confirmation integrity, popup/narrative alignment, popup integrity, dead code audit, portfolio sanity, HTML currency.
- Tested HEALTHY at 16:47 UTC.

### 7. Safe Infra Fixes (Auto-Remediated)
- `TradingConfig.BOT_DIR` missing attribute added to `trading_bot.py`.
- `/var/www/hedge-fund-website/regime_status.json` ownership fixed → `stonkai:stonkai`.

### 8. Website "About" Section Reformatted
- Maintained casual/w witty copy (sticky notes, 1 AM commits, Great question! joke)
- Applied professional visual treatment: left border accents on team cards (gold Jeeves / cyan Einstein / purple Boss), section label gold bars, responsive risk grid, pipeline card with cyan gradient background
- Typography normalized to match site: 1rem questions, 0.875rem answers, mobile-first tap targets
- Inline styles removed from ~30 elements, replaced with scoped CSS classes
- Einstein role description updated: "runs 24/7 on the VPS cloud" (was GLM-5.2)
- Cache buster at `v=20260629`

---

## ⚠️ Critical Open Issue: Alpaca 403 Sell Loop — RESOLVED

**Status:** FIXED at ~17:42 UTC after explicit user approval ("go ahead on this fix").

### What was done
1. **Cancelled stuck AAPL order** `aabe07b0-486f-4c85-86e5-f58d9d46ab1d` via raw Alpaca REST API (`DELETE /v2/orders/{id}`).
2. **Injected dedup guard** into `trading_bot.py` — wraps `AlpacaClient.submit_order` to check `list_orders(status='open', symbols=[symbol])` for existing sells before submitting. Returns a blocked-order stub instead of hitting Alpaca with a duplicate.
3. **Injected market-order sell wrapper** into `trading_bot.py` — wraps `AlpacaClient._build_order_payload` to force `use_limit=False` on all sell orders. Stop exits now execute as market orders instead of getting stuck with stale midpoint limits.
4. **Restarted service** — `sudo systemctl restart stonk-ai.service`. Bot active, generating signals for 130 symbols.

### Monitoring
- `tail -f /opt/stonk-ai/trading_bot.log | grep -E "Blocked duplicate|EXECUTED SELL"` to verify clean execution on next sell cycles.

---

## Backup
- Latest backup taken at ~17:57 UTC: `/opt/stonk-ai/backups/20260629-175744.tar.gz` (452K)
- Includes all core `.py`, configs, runtime JSONs, website `index.html`, systemd units, crontabs, logs, and git checkpoint.

---

## Files Changed Today (comprehensive)
- `generate_popup_content.py`
- `index.html`
- `trading_bot.py` (BOT_DIR fix + 403 guard + market-order wrapper)
- `fetch_ai_watchlist.py`
- `comprehensive_monitor.py`
- `vps_check.py`
- `fix_403_cancel.py` (now executed)
- `fix_403_patch_v2.py` (now executed)
- `memory/2026-06-29.md`
- `MEMORY.md`

---

## Next Steps for You (Jeeves)
1. **Read full daily memory** in this workspace: `memory/2026-06-29.md` for granular detail.
2. **Monitor the 403 fix** — watch the next few sell cycles for clean execution. If you see "Blocked duplicate", the guard is working correctly.
3. **Keep`COMPANY_NAMES` synced** — if expanding universe, update `signal_engine.py` dicts in the same commit.
4. **Monitor integrity** — `comprehensive_monitor.py` is live. It will alert via Telegram if the pipeline drifts.
5. **About section content** — if you (Jeeves) want to update your own role text in the website, edit `/var/www/hedge-fund-website/index.html` and bump the cache buster.

---

*Handover prepared by Einstein. Memory committed to `memory/2026-06-29.md` and `MEMORY.md`.*
