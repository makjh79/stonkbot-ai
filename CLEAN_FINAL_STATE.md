# STONK.AI - Clean Final State
**Date:** June 13, 2026 11:40 UTC

## ✅ Live System Status

### Website (Port 8080)
**URL:** http://localhost:8080/

**Files in `/var/www/hedge-fund-website/`:**
- `index.html` - Main website (current v=20260613-1130)
- `ai_watchlist_live.json` - Live watchlist with AMZN, NFLX (updated)
- `portfolio_data.json` - Live portfolio from Alpaca
- `portfolio_history.json` - Historical performance
- `crowd_sentiment.json` - Social sentiment data
- `market_indices.json` - S&P 500, DOW, NASDAQ
- `trades_log.json` - Trade history
- `earnings_data.json` - Earnings dates
- `watchlist_changes.json` - Auto-replacement log
- `mascot.jpg` - Website mascot

**Current Watchlist:** AMZN, COIN, DKNG, NET, NFLX, PATH, SHOP, SQ, SQQQ, TQQQ, UPST, XLE

### Trading Bot (`/opt/stonk-ai/`)
**Active Scripts:**
- `trading_bot.py` - Main trading bot (always running)
- `fetch_data_simple.py` - Portfolio data fetcher
- `fetch_ai_watchlist.py` - Watchlist price fetcher
- `fetch_market_indices.py` - Market benchmark fetcher
- `fetch_earnings.py` - Earnings date scraper
- `dynamic_watchlist_manager.py` - Auto-replacement logic

**Config:**
- `alpaca_config.json` - API credentials
- `portfolio_baseline.json` - $100K reference

**Systemd Services:**
- `stonk-ai.service` - Trading bot
- `stonk-ai-data.service` - Data fetcher
- `stonk-ai-watchlist.service` - Watchlist fetcher
- `stonk-ai-markets.service` - Market indices
- `stonk-ai-earnings.timer` - Daily at 6 AM
- `stonk-ai-watchlist-manager.timer` - Every 5 minutes

### Workspace (`/root/.openclaw/workspace/`)
**Core Files:**
- `AGENTS.md` - Agent configuration
- `SOUL.md` - Personality/tone
- `USER.md` - User preferences
- `IDENTITY.md` - Agent identity
- `TOOLS.md` - Tool notes
- `MEMORY.md` - Long-term memory
- `HEARTBEAT.md` - Periodic tasks
- `portfolio_baseline.json` - Portfolio reference
- `upload_alpaca_watchlist.py` - Manual upload utility
- `CLEAN_FINAL_STATE.md` - This file

**Memory Folder:**
- `2026-06-04.md` through `2026-06-13.md` - Daily logs
- `STONK_AI_SETUP.md` - Complete technical documentation
- `CONVERSATION_POLICY.md` - Memory policy
- `conversation_log.md` - Conversation history
- `heartbeat-state.json` - Heartbeat tracking

**Backups:**
- `/backups/20260613/` - Recent backups
- `/backups/20260613-final/` - Pre-cleanup backup

---

## ❌ Deleted Files

### Old Scripts (No longer used)
- `stock_monitor.py` - Replaced by Alpaca integration
- `rebalance.py` - Manual rebalancing (now automatic)
- `set_stop_losses.py` - Now handled by trading_bot.py
- `set_amd_stop.py` - AMD-specific (manual)
- `premarket_fetch.py` - Merged into main fetcher
- `update_website.py` - Now automated
- `trading_strategy.md` - Outdated
- `x_stock_monitor.py` - Old monitor

### Old Data Files
- `ma_data.json` - Moving averages (now fetched live)
- `options_data.json` - Options (not used)
- `prediction_data.json` - Empty/placeholder
- `premarket_data.json` - Stale
- `stock_data.json` - Old cache

### Old Reports
- All `STONKAI_HEALTH_CHECK_*.md` files
- All `HEALTH_*` reports
- `CLEANUP_SUMMARY_2026-06-12.md`

### Python Cache
- All `__pycache__/` directories
- All `*.pyc` files
- All `*.pyo` files

### Temp Files
- `/tmp/add_earnings.py`
- `/tmp/add_earnings_ui.js`
- `/tmp/extracted_js.js`

---

## 🔄 Active Data Flow

```
Alpaca Markets → fetch_data_simple.py → portfolio_data.json → Website
Alpaca Markets → fetch_ai_watchlist.py → ai_watchlist_live.json → Website
Yahoo Finance → fetch_earnings.py → earnings_data.json → Website
Manager (5min) → watchlist_changes.json → (triggers rotation)
```

---

## 🎯 Current Watchlist Configuration

**Auto-Replacement Thresholds:**
- RSI > 65: Remove (overbought)
- RSI < 25: Remove (oversold)
- Daily move > 8%: Remove (take profits)
- vs S&P < -5%: Remove (underperforming)

**Check Frequency:** Every 5 minutes

**Candidate Pool:** 145 stocks (scanned for opportunities)

---

**System Status:** ✅ CLEAN & OPERATIONAL
**Last Updated:** June 13, 2026 11:40 UTC
