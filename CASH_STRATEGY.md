# Cash Management & Crash Deploy Strategy

## Overview

This document explains the complete cash management system designed to:
1. **Preserve capital** - Always maintain 10% dry powder
2. **Recycle capital** - Trim overbought positions to fund new opportunities
3. **Deploy aggressively** - Buy dips when the market crashes

---

## 1. Cash Floor Protection (Always Active)

### Purpose
Ensure we never deploy 100% of capital, keeping dry powder for opportunities.

### Threshold
```python
MIN_CASH_PCT = 0.10  # 10% of portfolio value
```

### Behavior
| Cash Level | Status | Action |
|------------|--------|--------|
| ≥ 10% | ✅ Healthy | Normal operation (RSI entries allowed) |
| 5-10% | ⚠️ Warning | New buys blocked, cash raise triggered |
| < 5% | 🔴 Critical | Emergency cash raise mode |

### Current Example
- Portfolio: $100,000
- Minimum cash: $10,000
- Current cash: $433 (0.4%) → **Below threshold, cash raise active**

---

## 2. Auto Cash Raise (Below 10%)

### Purpose
Restore cash to 10% by trimming overbought positions (taking profits without selling everything).

### Trigger
```python
if cash_pct < 0.10:
    execute_cash_raise()
```

### Strategy
```python
CASH_RAISE_RSI_THRESHOLD = 70.0   # RSI > 70 = overbought
CASH_RAISE_TRIM_PCT = 0.25        # Sell 25% of position
CASH_RAISE_MIN_POSITION = 3000    # Don't trim below $3K
```

### Execution Logic
1. **Scan** all positions for RSI > 70
2. **Sort** by RSI (highest first - most overbought)
3. **Trim** 25% of each overbought position
4. **Skip** positions that would drop below $3K
5. **Stop** when cash back above 10%

### Example
```
Position: AMD
- Current value: $17,137
- RSI: 75 (overbought)
- Trim: 25% = $4,284
- New cash: $433 + $4,284 = $4,717
- Still need: $5,283 more to reach $10K

Next position: NVDA
- Current value: $8,000
- RSI: 72 (overbought)
- Trim: 25% = $2,000
- New cash: $4,717 + $2,000 = $6,717
- Continue until cash ≥ $10,000
```

---

## 3. Graduated Crash Deploy

### Purpose
Deploy cash aggressively when the market crashes, buying quality stocks at discounts.

### Trigger
S&P 500 drops from 52-week high:

| Drop Level | Deploy % | Cumulative | Action |
|------------|----------|------------|--------|
| -5% | 30% | 30% | First deployment |
| -10% | 40% | 70% | Second deployment |
| -15% | 30% | 100% | Final deployment |

### Deployment Targets
```python
CRASH_DEPLOY_AI_MIN_SCORE = 70   # Only WATCH tier or better
CRASH_DEPLOY_TOP_N = 5           # Top 5 AI conviction plays
```

### Sizing Logic
Weighted by AI conviction score:
```python
allocation = deploy_cash × (symbol_ai_score / total_top_5_scores)
```

### Example
```
S&P 500 drops to -10% from ATH
Cash available: $10,000
Deploy at this level: 40% = $4,000

Top 5 AI picks:
1. NVDA - AI score: 95
2. AMD - AI score: 88
3. TSLA - AI score: 82
4. META - AI score: 78
5. NFLX - AI score: 75
Total score: 418

Allocations:
- NVDA: $4,000 × (95/418) = $909
- AMD: $4,000 × (88/418) = $842
- TSLA: $4,000 × (82/418) = $784
- META: $4,000 × (78/418) = $746
- NFLX: $4,000 × (75/418) = $717
```

---

## 4. Monitoring & Alerts

### Cash Status Alerts
Run `/opt/stonk-ai/cash_strategy_monitor.py` to check:
- Current cash %
- Distance to 10% floor
- Crash deploy readiness

### Daily Report
```bash
python3 /opt/stonk-ai/cash_strategy_monitor.py
```

### Log File
All cash strategy events logged to:
```
/opt/stonk-ai/cash_strategy_log.json
```

---

## 5. Configuration

All thresholds configurable in `trading_bot.py`:

```python
class StrategyConfig:
    # Cash floor
    MIN_CASH_PCT = 0.10
    
    # Cash raise
    CASH_RAISE_ENABLED = True
    CASH_RAISE_RSI_THRESHOLD = 70.0
    CASH_RAISE_TRIM_PCT = 0.25
    CASH_RAISE_MIN_POSITION = 3000
    
    # Crash deploy
    MARKET_CRASH_DEPLOY_ENABLED = True
    SP500_DROP_LEVELS = [-5.0, -10.0, -15.0]
    CRASH_DEPLOY_PCT_AT_LEVEL = [0.30, 0.40, 0.30]
    CRASH_DEPLOY_AI_MIN_SCORE = 70
    CRASH_DEPLOY_TOP_N = 5
```

---

## 6. Current Status

```
Portfolio Value: $100,000
Cash: $433 (0.4%)
Status: 🔴 CRITICAL - Below 10% minimum

Actions:
✅ New RSI entries blocked
🔄 Cash raise active - trimming overbought positions
⏳ Crash deploy standby - S&P 500 at ~-4% (need -5%)

Next Steps:
1. Bot will auto-trim RSI > 70 positions to restore cash
2. Once cash > $10K, RSI entries resume
3. If S&P 500 drops to -5%, deploy 30% cash into dips
```

---

## 7. Manual Override

To manually trigger cash raise:
```python
# In trading_bot.py, temporarily lower threshold:
MIN_CASH_PCT = 0.05  # Will trigger immediate cash raise

# Or manually execute:
bot.check_cash_raise(portfolio_data)
```

To disable crash deploy:
```python
MARKET_CRASH_DEPLOY_ENABLED = False
```

---

## Summary

This strategy ensures:
- ✅ **Never fully deployed** - Always 10% dry powder
- ✅ **Profit recycling** - Trim overbought, buy oversold
- ✅ **Fearless buying** - Deploy cash when market panics
- ✅ **Quality focus** - Only buy high-conviction AI plays
