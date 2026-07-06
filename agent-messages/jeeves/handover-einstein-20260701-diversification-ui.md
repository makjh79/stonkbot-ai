# Handover: Diversification UI update (2026-07-01)

## What changed
Added a `diversification` status to the watchlist Next Buys display and updated the website UI to show it.

### Files changed on VPS
- `/opt/stonk-ai/dynamic_watchlist_manager.py`
  - Added diversification thresholds matching `paper_rebalancer.py` / `trading_bot.py`:
    - `DIVERSIFICATION_READINESS_MIN = 65.0`
    - `DIVERSIFICATION_CONFIRMATIONS_MIN = 2`
    - `DIVERSIFICATION_MAX_SECTOR_PCT = 0.30`
  - Added `_symbol_sector()` helper (synced with trading bot / paper rebalancer sector mapping).
  - Computes `sector_exposures` from current positions.
  - New `diversification` status in `buy_candidates` for near-eligible, non-high-beta, above-EMA names from underweight sectors.
- `/var/www/hedge-fund-website/index.html`
  - Next Buys UI now shows a 🌿 **Diversification** section with affected symbols.
  - Cache buster bumped to `v20260701-2145-v149-diversification-ui` / `stonkbot_v143`.

### Current Next Buys status (example)
- 🎯 New buys: ABNB, EXPE, GTLB
- ➕ Top up holdings: (none currently)
- 🌿 Diversification: UBER, MDB, PINS, ROKU, CHWY
- 🛑 Macro cap: HOOD, UPST, AFRM, LMND, SOFI

### Backup
- `/opt/stonk-ai/backups/diversification-ui-20260701-1348.tar.gz`

### Monitoring notes for Einstein
1. The watchlist now marks near-eligible non-high-beta names as `diversification`.
2. The live bot already uses the same thresholds; the UI just surfaces them.
3. High-beta basket percentage has dropped to ~35.7% of deployed capital (was ~80% earlier), mostly due to market moves/reduced high-beta market value. The 35% cap is still active.
