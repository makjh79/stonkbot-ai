# STONK.AI Trading Bot - Complete Setup

## Owner: H Mak (Howie)

---

## 🔑 Alpaca API Credentials
**Location**: `/root/.openclaw/workspace/alpaca_config.json`
- API Key: PKITYG…TWJX
- Secret: H5ExSkJqu4gsEZd2YDjwhCMzFBHj5UG8SPMJYrsT1WKi
- Base URL: https://paper-api.alpaca.markets
- Account: PA3OMDCJW8VU

---

## 🤖 Bot Status
**Status**: LIVE and Running (Paper Trading)
- Trading Bot PID: 87595
- Data Fetcher PID: 87597
- Location: `/opt/stonk-ai/`
- Systemd services: `stonk-ai.service`, `data-fetcher.service`

---

## 📊 Current Portfolio (Last Updated)
- Portfolio Value: $97,003.40
- Cash: $34,893.47 (36% dry powder)
- Total P&L: -$2,996.59 (-2.996%)
- Starting Capital: $100,000
- Positions: 14
- Status: live

### Top 5 Positions:
1. AMD: $16,266.60 (-8.24%) - Largest position at 16.8%
2. AAPL: $7,682.50 (-2.12%)
3. PLTR: $6,041.25 (-4.74%)
4. GOOGL: $5,499.75 (-0.24%)
5. APP: $4,404.80 (-3.13%)

### All Holdings (11 positions):
AAPL(25), AMD(35), APP(8), AVGO(5), CRWD(3), DKNG(800), GOOGL(15), HOOD(225), NVDA(17), PLTR(145), UPST(350)

---

## ⚙️ Trading Strategy

### Automated Exits:
- Stop Loss: -15% (hard stop)
- Profit Trim: +25% (sell 25% of position)
- Profit Exit: +50% (full exit)

### Automated Entries (NEW):
- RSI < 30 (oversold)
- Volume 2x average
- AI conviction > 70%
- Max 2 new positions/day
- Min cash reserve: $15,000
- Position size: 5-8% per entry
- Max position: 20% per stock

### Constraints:
- Max daily entries: 2
- Min cash: $15,000 (15%)
- Max position: 20% per stock
- Max sector: 35%

---

## 💰 Costs
- **Total Monthly Cost: $0**
- Alpaca API: Free (commission-free)
- Market data: Free (SIP feed)
- Running on existing infrastructure
- No AI tokens currently used

---

## 🎯 Graduation Plan
**Current Phase**: Paper Trading (Testing)
**Next Phase**: Real money trading IF bot beats S&P 500 in paper mode
**Switch Command**: Set `ALPACA_PAPER='false'` and restart

---

## 🚀 Bot Management Commands
```bash
# Check status
sudo systemctl status stonk-ai

# View logs
sudo journalctl -u stonk-ai -f

# Restart
sudo systemctl restart stonk-ai

# Stop
sudo systemctl stop stonk-ai
```

---

## 📁 Key Files
- Main bot: `/opt/stonk-ai/trading_bot.py`
- Data fetcher: `/opt/stonk-ai/fetch_data.py`
- Portfolio data: `/opt/stonk-ai/portfolio_data.json`
- Logs: `/opt/stonk-ai/trading_bot.log`
- Website: `/root/.openclaw/workspace/hedge-fund-website/index.html`
- Config: `/root/.openclaw/workspace/alpaca_config.json`

---

## 📈 Website Features
- Real-time portfolio display
- Live position tracking
- Auto-entry system section
- Risk analysis modal
- Performance vs S&P 500 comparison
- Market open: 9:30 AM ET
- Market close: 4:00 PM ET

---

## 📝 Notes
- Bot updates every 30 seconds during market hours
- Website updates from portfolio_data.json
- Friday June 5, 2026 was a bloodbath (-4.2% NASDAQ)
- Bot is currently down -2.996% from $100K start
- Ready for Monday market open

---

## 💬 Conversation History

### June 7, 2026 Chat Session (H Mak)
**Key Points**:
- User verified bot is running and ready for Monday market open
- Discussed token/cost analysis: confirmed $0/month to run
- User decided to keep setup as-is (no changes)
- Graduation plan: Switch to real money only if bot beats S&P 500 in paper mode
- All website bugs fixed and data corrected during this session
- User emphasized storing everything to memory to avoid repetition

**Decisions Made**:
1. Keep current infrastructure (no AWS/VPS migration)
2. No AI token costs (stay with current Python bot)
3. Paper trading until proven performance
4. Max position updated to 20% (reflects AMD at 16.8%)

---

## 💬 Conversation History

### June 7, 2026 Chat Session (H Mak)
**Duration**: Multiple hours  
**Topics Covered**:

#### 1. Website Bug Fixes
- Fixed sector data weights (was inflated: Tech 38.3%→24.5%, AI 46.2%→29.6%, etc.)
- Fixed Risk modal layout (added scrolling, max-height constraints)
- Updated Performance Analytics popup with real market data (Dow -1.35%, NASDAQ -4.18%, S&P 500 -2.60%)
- Fixed color bugs (negative returns showing green instead of red)
- Fixed table layout issues (removed inconsistent inline styles)
- Updated all holding prices to match live Alpaca data
- Changed max position limit from 15% to 20% (reflects AMD at 16.8%)

#### 2. Auto-Entry System
- Designed and implemented auto-entry configuration
- RSI < 30 + volume 2x as entry trigger
- $15,000 minimum cash reserve
- 5-8% position size per entry
- Max 2 new positions per day
- Scans 5,000+ stocks (not just current holdings)

#### 3. Integration Discussion
- User requested auto-entry be integrated into AI Strategy section
- Integrated as 4th pillar alongside Protection, Harvest, Execution
- Changed from separate blue box to cohesive 4-card layout
- Updated descriptions to flow naturally

#### 4. Publication Decision
- User agreed to test for 2-3 days before publishing
- Testing schedule: Monday-Wednesday
- Target publish date: Thursday (if no issues)
- Monitoring every 4 hours during market hours

#### 5. Monitoring Setup
- Cron job created for automated health checks
- Will auto-fix common issues (restart services, etc.)
- Will alert user for issues requiring manual intervention
- Job ID: 8981e81f-6278-4547-8736-7e202f4a0978

#### 6. Key Decisions Made
1. Keep costs at $0/month (no AI tokens, no AWS)
2. Paper trading until proven performance vs S&P 500
3. Graduate to real money only after successful paper period
4. All future conversations stored to long-term memory

---

**Last Updated**: June 7, 2026  
**Status**: Active paper trading, ready for real money graduation upon successful performance  
**Next Action**: Monitor bot performance vs S&P 500  
**Next Check**: Monday 9:30 AM ET market open
