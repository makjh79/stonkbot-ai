# HANDOVER NOTE — Einstein → Jeeves
## Full Session Summary + Next Steps
**Date:** 2026-06-27 09:05 UTC
**From:** Einstein (🎩, Telegram)
**To:** Jeeves (VPS agent, StonkBOT primary)
**Re:** Complete session handover — Alpaca integration, Phase 2, optimization, website overhaul, universe expansion

---

## Session Overview

This was a massive session. Howie upgraded to Alpaca paid data and I spent ~7 hours doing a full end-to-end integration, optimization, and website overhaul. Here's everything that happened:

## Phase 1: Alpaca Paid Data Integration

### alpaca_data.py (NEW — 380+ lines)
Unified data hub — ALL data flows through this:
- Snapshots (price, VWAP, prev_close, bid/ask, minute bars)
- Daily bars (batch 15, pagination)
- Intraday 15Min bars
- News (Alpaca paid news API)
- Options snapshots (implied vol, options volume)
- Market clock, account, positions
- Composite fetch (daily + snapshots + intraday in parallel)

### Components patched
- **signal_engine.py**: hub composite fetch, removed Yahoo/synthetic, options IV for all symbols, 7 regime symbols (SPY/QQQ/VIXY/SHY/TLT/LQD/HYG)
- **readiness_score.py**: 7 confirmations, intraday momentum, options sentiment, volume fix (up-volume vs down-volume)
- **risk_engine.py**: VWAP stops (-2% below), VWAP-enhanced trailing, max position 8%, halt at -15% DD, ATR 2.0
- **trading_bot.py**: VWAP injection into positions (was silently inactive!), intraday entry timing, IV sizing, limit orders at midpoint, TWAP splitting, STRONG_NOW 2x sizing
- **generate_popup_content.py**: VWAP stop, Alpaca news, options IV, momentum, regime, always-generate 24/7
- **signal_enricher.py**: Alpaca news integration (fetch_alpaca_news + keyword sentiment)
- **fetch_ai_watchlist.py**: RSI from signals.json + hub (Yahoo/Polygon removed)
- **fetch_data_simple.py**: hub replaces alpaca_trade_api, VWAP + intraday in portfolio_data
- **fetch_market_indices.py**: hub + regime data (VIXY, yield curve, credit spreads)
- **dynamic_watchlist_manager.py**: hub prices, all Alpaca fields, STRONG_NOW tier, MAX=20

### Key discovery
- **Volume confirmation was NEGATIVELY correlated with wins** (-0.231). Volume spikes on falling prices = selling pressure, not breakout. Fixed: now distinguishes up-volume vs down-volume.

## Phase 2: Pro Toolkit (Jeeves built, I fixed + integrated)

### backtest.py — 3 bugs fixed + optimized
- Missing Tuple import, wrong static method calls, zero-trade threshold
- Added anti-churning: 10-day min hold, sell at readiness <40
- **After optimization: Sharpe 0.64 → 1.26, return +26.5% → +65.2%, max DD -40.6% → -26.9%**

### Backtest-driven optimization
Readiness weights recalibrated based on 38 live trades:
- **Before:** momentum 40%, RSI 15%, volume 15%, MACD 10%, EMA 10%, sector 10%
- **After:** momentum 30%, RSI 10%, volume 5%, MACD 10%, EMA 20%, sector 25%
- EMA up (strongest predictor +0.593), sector up (+0.502), volume down (NEGATIVE -0.231)
- Tiers raised: NOW ≥72 (was 70), WATCH ≥55 (was 50), added STRONG_NOW ≥80 (2x sizing)

### performance_attribution.py — 2 bugs fixed
- portfolio_history dict handling (was list)
- signal_map fallback by symbol (signals.json has no generated_at)
- **7 factor correlations now computed** (was 0). above_ema strongest at +0.593.

### stress_test.py — works as-is
- Correlation matrix, VaR, 4 scenarios, concentration risk

### monitor.py — service name fixed
- stonk-ai-bot → stonk-ai. Cron: every 5 min during market hours.

### Phase 2 audit: 53/53 ✅

## Phase 3: Website Overhaul

### Stale data cleanup
- Removed 8 stale JSON files (crowd_sentiment, trending_sentiment, earnings_data, company_info, price_verification, watchlist_meta, recovery_status, nginx-cache)
- Removed all fetch references to deleted files

### Website fixes
- Confirmation counts /5 → /7 everywhere
- Tagline: "$100K AI trading experiment"
- Tier reason: removed "Demoted/Promoted" language
- VWAP row in holdings popups + watchlist popups
- VWAP stop shown in popup when losing
- Options IV badge in popup signal chips (shows "IV —" when no data)
- prev_close-based change% in portfolio table
- All popup content fields: optionsImpliedVol, momentum20d, momentum50d, regimeScore, strategyType, volatility20d, spyCorr20d, atr14
- Regime data in market_indices.json (VIXY, yield curve ratio, credit spread ratio)

### STRONG_NOW tier — full end-to-end
Multiple rounds of debugging to get this working:
1. `preGenerated` scope error killed watchlist popup → fixed with `wlOptionsIV`
2. `buildWatchlistFromLiveData` didn't pass Alpaca fields → fixed
3. `renderWatchlistContent` remapped tier to MONITOR → fixed
4. `tierColors` dict missing STRONG_NOW → fixed with cyan 🚀 badge
5. Tier explainer tooltip, readiness tooltip, count indicator all updated

### Full website audit: 77/77 ✅ (0 real errors)

## Phase 4: Universe Expansion (75 → 130)

Added 55 new symbols across 6 new sectors:
- **Healthcare** (15): UNH, LLY, JNJ, PFE, ABBV, MRK, TMO, VRTX, BMY, REGN, GILD, ISRG, ZBH, ILMN, SGEN
- **Energy** (8): XOM, CVX, COP, SLB, EOG, PSX, MPC, OXY
- **Industrials** (8): GE, CAT, UNP, HON, UPS, RTX, LMT, DE
- **Financials** (8): JPM, BAC, WFC, GS, MS, BLK, SCHW, V
- **Communications** (6): DIS, CMCSA, TMUS, CHTR, WBD, PARA
- **Tech Expansion** (10): TXN, IBM, INTC, CRM, ORCL, ADBE, INTU, PYPL, FIS + AVGO already in semi

Result: 124 signals from 130 symbols, 15 sectors.

## Phase 5: Watchlist Expansion (15 → 20)
- Current: 7 STRONG_NOW, 12 NOW, 1 WATCH

## Backups
- `/opt/stonk-ai/backups/comprehensive-20260627-0905.tar.gz` (49MB)
- `/opt/stonk-ai/backups/comprehensive-20260627-0550.tar.gz` (49MB)

## Git
- Latest: `5fff8d9` on master
- ~15 commits this session

## Monday Scheduled (June 29)
- **13:25 UTC (9:25 AM ET)**: Pre-market generation — all generators run, results to Telegram
- **13:35 UTC (9:35 AM ET)**: Intraday pipeline test — verifies 15Min bars, VWAP stops, options live

---

## What Jeeves Should Do Next

### Immediate (Monday)
1. **Wait for Monday test results** — Einstein will run both crons and report via Telegram
2. **If intraday pipeline works:** Howie should switch to live Alpaca keys (change api_key/secret in alpaca_config.json from PK... to live keys, restart stonk-ai.service)

### Short-term (this week)
3. **Beta reduction** — still at 1.34, target <1.2. Options:
   - Add defensive ETFs (SHY, TLT) to portfolio as hedges
   - Sector cap tightening from 20% to 15%
   - Volatility filter (skip entries when VIXY > X%)
4. **Backtest parameter tuning** — experiment with:
   - Hold period: try 15-20 days (current 10)
   - Max positions: try 10 vs 15 vs 20
   - Sell threshold: try readiness <35 vs <40
   - Max universe: test performance with 100 vs 130 vs 150
5. **Monitor the monitor** — check `/opt/stonk-ai/logs/monitor.log` during market hours

### Medium-term (2-4 weeks)
6. **Live trade accumulation** — need 200+ trades for statistical significance in performance attribution
7. **Re-run performance_attribution.py weekly** — track factor correlations as they stabilize
8. **Re-run backtest monthly** — compare backtest vs live performance
9. **Options data gap** — 27/130 symbols have IV. Some symbols (MU during earnings) return no greeks. Consider alternative IV source or flagging

### Key technical notes
- **Alpaca v2 snapshots**: symbols at TOP LEVEL, not nested under "snapshots"
- **Alpaca bars pagination**: 1000 bars/page max → batch 15 symbols
- **chown stonkai:stonkai** after any root writes
- **Volume confirmation** is a contrarian indicator in current dataset — watch this
- **STRONG_NOW tier**: ≥80 readiness, 2x position sizing, 🚀 cyan badge in website
- **Cache-busting**: update both the meta tag AND the inline `var v=` version string
- **renderWatchlistContent** overwrites stock.tier — any new tiers must be added to the mapping there AND in tierColors dict

— Einstein 🎩