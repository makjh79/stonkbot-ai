# Long-Term Memory

## Quick Reference

### STONK.AI Trading Bot
**Owner**: Howie (H Mak)  
**Chat ID**: telegram:8795294800  
**Status**: Live paper trading, ready for real money  
**Portfolio**: $98,417 (down -2.20% from $100K)  
**Cash**: $37,835 (38% dry powder)  
**Positions**: 13 stocks (META sold via stop-loss June 8)  
**Largest**: AMD at 17.4% ($17,137)

**Key Details**:
- Alpaca paper account: PA3OMDCJW8VU
- API keys stored in: `/root/.openclaw/workspace/alpaca_config.json`
- Bot running at: `/opt/stonk-ai/`
- PIDs: Trading bot 87595, Data fetcher 87597
- Systemd services: stonk-ai.service, data-fetcher.service
- Cost: $0/month (Alpaca free tier)
- Strategy: -15% stop loss, +25% trim, +50% exit, RSI<30 auto-entry
- Website: hedge-fund-website/index.html displays live data

**Website Fixes Applied (June 7, 2026)**:
- Fixed sector data weights (was inflated, now accurate: Tech 24.5%, AI 29.6%, Fintech 5.4%, Defense 4.5%)
- Fixed Risk modal layout (added scrolling, max-height)
- Updated Performance Analytics popup (added Dow Jones -1.35%, NASDAQ -4.18%, S&P 500 -2.60%)
- Fixed color bugs (negative returns now show red correctly)
- Fixed table layout issues (removed inconsistent inline styles)
- Updated all holding prices to match live Alpaca data
- Added Auto-Entry system section to website
- Max position limit: 20% (was 15%, updated to reflect AMD at 16.8%)

**Graduation Plan**: Beat S&P 500 in paper mode → Switch to real money (set ALPACA_PAPER='false')

**Full details**: See `memory/STONK_AI_SETUP.md`

---

### User Preferences
- **Name**: Howie (H Mak)
- **Telegram ID**: 8795294800
- **Cost-conscious**: Wants $0/month bot operation
- **Risk approach**: Testing in paper first, graduating to real money if successful
- **Trading style**: AI-automated, hands-off
- **Preference**: Keep current setup (no changes needed), add AI features only if bot performs well

---

### Active Projects
1. **STONK.AI Trading Bot** - Live paper trading, 13 positions, $98K portfolio
2. **Website Dashboard** - Real-time portfolio display connected to Alpaca

---

### Key Decisions & Context
**June 7, 2026 Chat Session**:
- User wants to keep costs at $0/month
- Will graduate to real money only if bot beats S&P 500 in paper mode
- Bot is ready for Monday market open (June 8, 2026)
- Website bugs fixed and consistent now
- All market data corrected (June 4-5 was a bloodbath, not gains)

---

## 📝 Memory Management Policy

**Going Forward**: All conversations with H Mak are automatically stored to long-term memory to prevent repetition and maintain continuity.

**Storage**: 
- `memory/STONK_AI_SETUP.md` - Complete technical details
- `memory/CONVERSATION_POLICY.md` - Storage policy
- `MEMORY.md` - Quick reference (this file)

---

*This file is updated with key facts to prevent repetition.*
