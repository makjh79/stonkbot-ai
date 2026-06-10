# STONK.AI Website Changelog

## June 10, 2026 - Holdings Sync Fix

### Problem
Website holdings were completely out of sync with Alpaca paper trading account.

### Changes Made

#### 1. Updated FALLBACK_DATA (Corrected Holdings)
- **Portfolio Value**: $96,446.86 (was $98,045.18)
- **Cash**: -$14,787.64 (was +$34,893.46)
- **Total Positions**: 11 (was 14)

#### 2. Fixed Position Quantities
| Symbol | Old | New | Change |
|--------|-----|-----|--------|
| DKNG | ❌ Missing | 800 shares | **ADDED #1 position ($22,312)** |
| UPST | ❌ Missing | 350 shares | **ADDED ($10,815)** |
| HOOD | 25 shares | 225 shares | **9x increase** |
| PLTR | 45 shares | 145 shares | **3x increase** |
| META | 5 shares | ❌ Removed | **SOLD** |
| MSFT | 10 shares | ❌ Removed | **Not held** |
| SCHD | 30 shares | ❌ Removed | **Not held** |
| SGOV | 15 shares | ❌ Removed | **Not held** |
| SOFI | 200 shares | ❌ Removed | **Not held** |

#### 3. Updated Sector Mappings
- **Tech Giants**: AAPL, GOOGL, NVDA (removed MSFT, META)
- **AI/Growth**: AMD, PLTR, APP, CRWD (unchanged)
- **Fintech**: HOOD, UPST, DKNG (added UPST, DKNG; removed SOFI)
- **Defense/Income**: AVGO (removed SCHD, SGOV)

#### 4. Added Trade Rationale for New Holdings
- **DKNG**: Sports betting leader thesis
- **UPST**: AI-powered lending thesis

#### 5. Fixed Holdings Popups
- Changed `showTradeDetails()` to work for **any** symbol
- Added fallback popup showing position details when no rationale exists
- Stores live portfolio data in `window.lastPortfolioData`

### Backups Created
- Git commit: `aedabad` - "Fix holdings sync with Alpaca - June 10, 2026"
- File backup: `index.html.BACKUP-20260610-054034`

### Current Top Holdings (Real)
1. DKNG - $22,312 (23.1%)
2. PLTR - $19,046 (19.7%)
3. HOOD - $18,576 (19.2%)
4. AMD - $16,270 (16.9%)
5. UPST - $10,815 (11.2%)

---

## June 10, 2026 - Activity Log Fix

### Problem
Activity log was missing trades and didn't show complete history since inception.

### Solution
- Copied real trades log from `/opt/stonk-ai/trades_log.json`
- Activity log now loads **28 real trades** from Alpaca API
- All trades include accurate timestamps from June 4-9, 2026

### Complete Trade History (Since Inception)

**June 9, 2026:**
- BUY PLTR +100 shares @ $132.77
- BUY HOOD +200 shares @ $84.20
- BUY DKNG 800 shares @ $26.99 (**NEW #1 position**)
- BUY UPST 350 shares @ $30.97 (**NEW**)
- SELL SOFI 200 shares @ $16.68 (closed)
- SELL SGOV 15 shares @ $100.46 (closed)
- SELL SCHD 30 shares @ $32.34 (closed)

**June 8, 2026:**
- SELL MSFT 10 shares @ $411.24 (closed)
- SELL META 5 shares @ $588.26 (stop loss)

**June 5, 2026:**
- BUY PLTR +20 shares @ $136.93
- BUY AMD +10 shares @ $478.96
- BUY AAPL 25 shares @ $313.97
- BUY GOOGL 15 shares @ $367.54
- BUY MSFT 10 shares @ $428.80

**June 4, 2026 (Inception):**
- BUY AMD 25, NVDA 5, META 2, SOFI 100, HOOD 25
- BUY SOFI +100, SCHD 30, SGOV 15, AVGO 5, APP 8
- BUY CRWD 3, PLTR 25, NVDA +12, META +3

**Net Positions:** 11 active

### Files Updated
- `trades_log.json` - 28 trades from Alpaca

---

## Previous Changes

See git history:
```bash
cd /root/.openclaw/workspace/hedge-fund-website && git log --oneline
```
