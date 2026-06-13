# STONK.AI System Architecture

## Core Principle: Single Source of Truth

**NEVER hardcode data that changes dynamically.**

All dynamic data flows from JSON files → Website/Bot. Never the reverse.

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                              │
├─────────────────────────────────────────────────────────────┤
│  Alpaca API    →  Prices, RSI, Holdings                     │
│  Yahoo Finance →  Earnings, Volume                          │
│  Manager Logic →  Watchlist rotation decisions              │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│              JSON FILES (Single Source of Truth)            │
├─────────────────────────────────────────────────────────────┤
│  ai_watchlist_live.json      → Current prices + 20 stocks   │
│  company_info.json           → Company profiles (auto-sync) │
│  watchlist_changes.json      → Rotation history             │
│  portfolio_data.json         → Portfolio state              │
│  earnings_data.json          → Earnings dates               │
│  crowd_sentiment.json        → Social sentiment             │
└────────────────┬────────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
┌──────────────┐  ┌──────────────┐
│   WEBSITE    │  │  TRADING BOT │
│  (index.html)│  │ (trading_bot)│
│              │  │              │
│ Loads JSON   │  │ Loads JSON   │
│ Dynamically  │  │ + Executes   │
└──────────────┘  └──────────────┘
```

## File Responsibilities

| File | Managed By | Consumed By | Update Frequency |
|------|-----------|-------------|------------------|
| `ai_watchlist_live.json` | Watchlist Fetcher | Website, Bot | 30 seconds |
| `company_info.json` | Watchlist Manager | Website | On rotation |
| `watchlist_changes.json` | Watchlist Manager | Website | On rotation |
| `portfolio_data.json` | Data Fetcher | Website | 30 seconds |
| `earnings_data.json` | Earnings Fetcher | Website | Daily 6 AM |
| `crowd_sentiment.json` | Sentiment Fetcher | Website | 5 minutes |

## Critical Rules

### 1. NO HARDCODED SYMBOL LISTS

**❌ WRONG:**
```javascript
// In HTML
const companyInfo = {
  'AMZN': { ... },  // Hardcoded
  'NFLX': { ... },  // Gets stale!
};
```

**✅ CORRECT:**
```javascript
// Fetch dynamically
let companyInfo = {};
async function fetchCompanyInfo() {
  const response = await fetch('./company_info.json');
  companyInfo = (await response.json()).stocks;
}
```

### 2. UPDATE BOTH FILES ATOMICALLY

When watchlist rotates, update BOTH files in same transaction:

```python
# In dynamic_watchlist_manager.py
# 1. Update prices
with open('ai_watchlist_live.json', 'w') as f:
    json.dump(price_data, f)

# 2. Update company info (SAME FUNCTION!)
with open('company_info.json', 'w') as f:
    json.dump(company_data, f)
```

### 3. CACHE BUSTER ON EVERY CHANGE

Always increment cache buster when modifying:
- HTML structure
- JavaScript logic
- JSON schema

Format: `v=YYYYMMDD-HHMM-DESCRIPTION`

### 4. VERIFY BEFORE DEPLOYING

Run this check after any change:
```bash
python3 verify_sync.py
```

## Change Management Process

### For Watchlist Changes

1. **Update Manager Config** (`dynamic_watchlist_manager.py`)
   - Change thresholds, max_stocks, etc.

2. **Manager Auto-Updates JSON Files**
   - `ai_watchlist_live.json` (prices)
   - `company_info.json` (profiles)
   - `watchlist_changes.json` (history)

3. **Verify Sync**
   ```bash
   python3 << 'PYEOF'
   import json
   watchlist = json.load(open('watchlist_changes.json'))['new_watchlist']
   companies = json.load(open('company_info.json'))['stocks'].keys()
   assert set(watchlist) == set(companies), "MISMATCH!"
   print("✅ Sync verified")
   PYEOF
   ```

4. **Update Cache Buster**
   ```bash
   # In index.html
   # Change: v=...-DESCRIPTION
   ```

5. **Hard Refresh to Test**

### For Entry/Exit Rule Changes

Must update ALL three components:

1. **Website** (`index.html`)
   - Display thresholds
   - Disclaimer text
   - Cache buster

2. **Trading Bot** (`trading_bot.py`)
   - `StrategyConfig` class
   - Entry/exit logic
   - Unit tests

3. **Watchlist Manager** (`dynamic_watchlist_manager.py`)
   - RSI thresholds
   - Removal criteria
   - Config validation

4. **Run Consistency Check**
   ```bash
   python3 verify_thresholds.py
   ```

## Prevention Checklist

Before marking any task complete:

- [ ] All JSON files reference same symbols?
- [ ] No hardcoded lists in HTML?
- [ ] Cache buster incremented?
- [ ] Trading bot has same thresholds?
- [ ] Watchlist manager aligned?
- [ ] Verified with `verify_sync.py`?
- [ ] Hard refresh tested?

## Emergency Fix Procedure

If sync breaks:

1. **Identify mismatch**
   ```bash
   python3 diagnose_sync.py
   ```

2. **Force manager refresh**
   ```bash
   cd /opt/stonk-ai && python3 dynamic_watchlist_manager.py
   ```

3. **Verify JSON files**
   ```bash
   python3 verify_sync.py
   ```

4. **Increment cache buster**
   ```bash
   # Edit index.html
   ```

5. **Test with hard refresh**
