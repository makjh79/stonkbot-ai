# STONK.AI System State - Final Clean

**Date:** June 13, 2026  
**Status:** ✅ Production Ready

---

## System Overview

| Component | Status | Details |
|-----------|--------|---------|
| **Trading Bot** | ✅ Active | Paper trading mode, $100K capital |
| **Price Fetcher** | ✅ Running | 30-second updates |
| **Watchlist Manager** | ✅ Running | 5-minute checks (market hours only) |
| **Website** | ✅ Live | hedge-fund-website/index.html |
| **Portfolio** | ✅ $96,650 | -3.35% from $100K start |

---

## Current Watchlist (20 Stocks)

| Symbol | Company | Price | Status |
|--------|---------|-------|--------|
| ABNB | Airbnb | $132.28 | Active |
| AMZN | Amazon | $238.56 | Active |
| CDNS | Cadence | $384.83 | Active |
| COIN | Coinbase | $159.72 | Active |
| DKNG | DraftKings | $28.99 | Active |
| GM | General Motors | $81.48 | Active |
| LCID | Lucid | $5.22 | Active |
| NET | Cloudflare | $228.39 | Active |
| NFLX | Netflix | $80.33 | Active |
| NIO | NIO Inc. | $5.21 | Active |
| PATH | UiPath | $10.55 | Active |
| SHOP | Shopify | $108.29 | Active |
| SNOW | Snowflake | $232.69 | Active |
| SOFI | SoFi | $16.59 | Active |
| SQ | Block | $86.95 | Active |
| SQQQ | Short QQQ | $39.92 | Hedge |
| TQQQ | Ultra QQQ | $77.88 | Hedge |
| UPST | Upstart | $30.50 | Active |
| XLE | Energy ETF | $57.56 | Active |
| XPEV | XPeng | $14.50 | Active |

---

## Trading Strategy

| Rule | Setting |
|------|---------|
| **RSI Entry** | < 35 (oversold) |
| **Volume Confirmation** | 1.5x average |
| **Stop Loss** | -15% (hard stop) |
| **Take Profit Trim** | +25% (partial) |
| **Take Profit Full** | +50% (exit) |
| **Max Position** | 20% per stock |
| **Min Cash** | $15,000 (15%) |

---

## Automation Schedule

| Task | Frequency | Next Run |
|------|-----------|----------|
| Price Updates | Every 30 sec | Continuous |
| Watchlist Check | Every 5 min | Market hours only |
| Earnings Fetch | Daily 6 AM | Next business day |
| Price Verification | Daily 7 PM | Tonight |
| Sync Verification | Daily 7 PM | Tonight |

---

## System Safeguards

✅ **Weekend/Holiday Detection** - No trading when markets closed  
✅ **Dynamic Company Info** - Auto-syncs with watchlist rotations  
✅ **Daily Verification** - Automated sync and price checks  
✅ **Backup System** - Comprehensive backups before changes  
✅ **Cache Busting** - Versioned updates prevent stale data  

---

## File Locations

| Component | Path |
|-----------|------|
| Trading Bot | `/opt/stonk-ai/trading_bot.py` |
| Watchlist Manager | `/opt/stonk-ai/dynamic_watchlist_manager.py` |
| Price Fetcher | `/opt/stonk-ai/fetch_ai_watchlist.py` |
| Website | `/var/www/hedge-fund-website/index.html` |
| Live Data | `/var/www/hedge-fund-website/ai_watchlist_live.json` |
| Company Info | `/var/www/hedge-fund-website/company_info.json` |
| Portfolio | `/var/www/hedge-fund-website/portfolio_data.json` |
| Backups | `/root/.openclaw/workspace/backups/` |
| Memory | `/root/.openclaw/workspace/memory/` |

---

## 2026 Market Holidays (No Trading)

- **Jan 1** - New Year's Day
- **Jan 19** - Martin Luther King Jr. Day
- **Feb 16** - Presidents' Day
- **Apr 3** - Good Friday
- **May 25** - Memorial Day
- **Jun 19** - Juneteenth
- **Jul 4** - Independence Day
- **Sep 7** - Labor Day
- **Oct 12** - Columbus Day
- **Nov 11** - Veterans Day
- **Nov 26** - Thanksgiving
- **Dec 25** - Christmas

---

## Quick Commands

```bash
# Check system status
systemctl status stonk-ai stonk-ai-watchlist stonk-ai-watchlist-manager

# Verify sync
cd /opt/stonk-ai && python3 verify_sync.py

# Check thresholds
cd /opt/stonk-ai && python3 verify_thresholds.py

# View logs
journalctl -u stonk-ai -f
journalctl -u stonk-ai-watchlist -f

# Manual manager refresh
cd /opt/stonk-ai && python3 dynamic_watchlist_manager.py
```

---

## Recent Changes

### June 13, 2026
- ✅ Fixed weekend rotation bug (now skips on weekends/holidays)
- ✅ Added public holiday detection
- ✅ Implemented dynamic company info loading
- ✅ Added daily automated verification
- ✅ Updated RSI threshold to < 35
- ✅ Fixed volume multiplier to 1.5x
- ✅ Cleaned up old backup files

---

## Backup Location

**Latest Full Backup:**
`/root/.openclaw/workspace/backups/FINAL-CLEAN-20260613-152030/`

Contains:
- stonk-ai-complete.tar.gz
- website-complete.tar.gz
- systemd-services.tar.gz
- All memory files and documentation

---

*System operational. No manual intervention required.*
