# STONK.AI Trading Strategy v1.0
## Complete Autonomous Trading Rules

**Effective:** June 6, 2026  
**Initial Capital:** $100,000  
**Account:** Alpaca Paper Trading  
**Management:** Autonomous (AI-designed, code-executed)

---

## 1. PORTFOLIO ALLOCATION TARGETS

Based on current holdings and risk assessment:

| Sector | Target % | Holdings | Strategy |
|--------|----------|----------|----------|
| **Tech Giants** | 25% | AAPL, MSFT, GOOGL, META, NVDA | Core stability, AI exposure |
| **AI/Growth** | 30% | AMD, PLTR, APP, CRWD | High conviction, high volatility |
| **Fintech** | 5% | HOOD, SOFI | Speculative growth |
| **Defense/Income** | 5% | AVGO, SCHD, SGOV | Dividend stability |
| **Cash Buffer** | 35% | - | Dry powder for opportunities |

**Current Status:** Portfolio at $97,003 (-3.0% from start)

---

## 2. RISK MANAGEMENT RULES

### Position Limits
- **Max single position:** 15% of portfolio
- **Max sector deviation:** ±10% from target
- **Min cash buffer:** 30% (never below)

### Stop Losses
- **Individual stocks:** -15% stop loss (auto-execute)
- **Portfolio level:** If total portfolio drops >20%, halt trading, notify human
- **Never move stop losses down** (no widening stops)

### Take Profits
- **Trim at +25%:** Sell 25% of position, let rest run
- **Full exit at +50%:** Take profits, reallocate

### Rebalancing
- **Threshold:** Rebalance when sector drifts >5% from target
- **Frequency:** Check daily during market hours
- **Method:** Sell overweight, buy underweight

---

## 3. TRADING RULES

### When to Buy
1. **Dip Buying:** Stock down >5% from entry, thesis intact
2. **New Positions:** Only if cash >35% and strong conviction
3. **Adding to Winners:** Only if position <15% of portfolio
4. **Rebalancing:** Sector underweight by >5%

### When to Sell
1. **Stop Loss Hit:** -15% (automatic)
2. **Take Profit:** +25% (trim) or +50% (full exit)
3. **Thesis Broken:** Fundamental change (earnings miss, guidance cut)
4. **Rebalancing:** Sector overweight by >5%
5. **Better Opportunity:** Sell laggard to buy stronger name

### Trade Limits
- **Max 3 trades per day** (avoid overtrading)
- **Max 10 trades per week**
- **Market hours only** (9:30 AM - 4:00 PM ET)

---

## 4. STOCK-SPECIFIC STRATEGIES

### Tech Giants (Core Holdings)
| Stock | Action | Rationale |
|-------|--------|-----------|
| AAPL | HOLD | AI iPhone cycle, stable compounder |
| MSFT | HOLD | Cloud + AI leadership, dividend |
| GOOGL | HOLD | Search monopoly, AI integration |
| META | HOLD | Cost discipline, AI investments |
| NVDA | HOLD | AI chip leader, high volatility accepted |

**Rule:** These are long-term holds. Only sell on +50% gains or -15% stop loss.

### AI/Growth (Active Management)
| Stock | Action | Rationale |
|-------|--------|-----------|
| AMD | BUY on dips | MI300 ramp, AI chip demand |
| PLTR | HOLD | Gov contracts sticky, AIP growing |
| APP | WATCH | Mobile ad recovery speculative |
| CRWD | HOLD | Cybersecurity leader, expensive but quality |

**Rule:** Trim on big runs (+25%), buy on dips (-5% to -10%).

### Fintech (High Risk/High Reward)
| Stock | Action | Rationale |
|-------|--------|-----------|
| HOOD | HOLD | Crypto momentum, retail trading |
| SOFI | HOLD | Bank charter, student loans |

**Rule:** Small positions only. Full exit on -15% or +50%.

### Defense/Income (Stability)
| Stock | Action | Rationale |
|-------|--------|-----------|
| AVGO | HOLD | VMware integration, dividend growth |
| SCHD | HOLD | Dividend ETF, stability anchor |
| SGOV | HOLD | Treasury bills, cash equivalent |

**Rule:** Never sell. These are permanent stabilizers.

---

## 5. MARKET CONDITIONS

### Bull Market (S&P > 200-day MA)
- **Increase AI/Growth to 35%** (overweight)
- **Reduce cash to 25%** (deploy capital)
- **Aggressive dip buying** (-3% to -5%)

### Bear Market (S&P < 200-day MA)
- **Increase cash to 45%** (defensive)
- **Reduce AI/Growth to 20%** (protect downside)
- **Only buy extreme dips** (-10% to -15%)
- **Tighten stop losses to -10%**

### Sideways/Uncertain
- **Maintain current allocation**
- **Focus on rebalancing**
- **Preserve cash for opportunities**

---

## 6. AUTONOMOUS EXECUTION

### The Bot Will:
1. ✅ Monitor all positions 24/7 during market hours
2. ✅ Execute stop losses automatically at -15%
3. ✅ Check for rebalancing needs daily
4. ✅ Log all decisions with rationale
5. ✅ Never exceed trade limits (3/day, 10/week)

### The Bot Will NOT:
1. ❌ Trade outside market hours
2. ❌ Exceed position limits (15% max)
3. ❌ Let cash drop below 30%
4. ❌ Move stop losses down (no averaging down on losers)
5. ❌ Panic sell (follow the strategy)

---

## 7. HUMAN OVERRIDE TRIGGERS

**Contact Jarvis (AI) immediately if:**

1. **Portfolio drops >20%** from start ($80,000)
2. **Any single stock drops >30%** (stop loss didn't trigger)
3. **Major market event** (war, crash, black swan)
4. **Alpaca account issue** (API failure, suspension)
5. **Strategy not working** (3 months of consistent losses)

**Regular Check-ins:**
- **Weekly:** Review performance, minor tweaks
- **Monthly:** Deep dive, strategy adjustments
- **Quarterly:** Major strategy review, allocation changes

---

## 8. PERFORMANCE BENCHMARKS

### Success Metrics
| Metric | Target | Timeframe |
|--------|--------|-----------|
| **Beat S&P 500** | +5% outperformance | Annual |
| **Max Drawdown** | <20% | Any period |
| **Win Rate** | >50% | Per trade |
| **Sharpe Ratio** | >1.0 | Annual |
| **Cash Yield** | 4-5% | Annual (SGOV + SCHD) |

### Failure Triggers
- **Underperform S&P by >10%** for 6 months
- **Max drawdown >30%** at any point
- **Lose >30% of capital** ($70,000 remaining)

**If any trigger hit:** Halt bot, contact Jarvis for strategy review.

---

## 9. EMERGENCY PROTOCOLS

### If Market Crashes (>10% in single day):
1. **Halt all buying** for 24 hours
2. **Review all positions** for stop losses
3. **Consider raising cash** to 45%+
4. **Contact Jarvis** for guidance

### If Major Holdings Implode (>20% single day):
1. **Check if stop loss triggered**
2. **Assess news/earnings**
3. **If thesis broken:** Exit position
4. **If temporary:** Hold, monitor closely

### If Bot Malfunctions:
1. **Stop the service:** `sudo systemctl stop stonk-ai`
2. **Check logs:** `sudo journalctl -u stonk-ai -f`
3. **Contact Jarvis** with error details

---

## 10. STRATEGY REVIEW SCHEDULE

| Frequency | Action | Who |
|-----------|--------|-----|
| **Daily** | Bot runs autonomously | Bot |
| **Weekly** | Review performance, minor tweaks | You + Jarvis |
| **Monthly** | Deep analysis, allocation review | You + Jarvis |
| **Quarterly** | Major strategy overhaul | You + Jarvis |
| **As Needed** | Emergency interventions | Contact Jarvis |

---

## SUMMARY

**This is a long-term, buy-and-hold strategy with:**
- Core tech positions (stable compounders)
- AI growth exposure (high conviction)
- Strict risk management (stop losses, position limits)
- High cash buffer (35% for opportunities)
- Autonomous execution (bot follows rules)

**Expected Outcomes:**
- **Good:** +10-20% annually, beat S&P
- **Normal:** +5-10% annually, match S&P
- **Bad:** -5-10% (bear market), preserve capital
- **Disaster:** -20%+ (contact Jarvis immediately)

**Remember:** This is a $100K experiment. The goal is learning + beating the market over 1-3 years, not getting rich quick.

---

**Last Updated:** June 6, 2026  
**Next Review:** Weekly (Sundays)  
**Emergency Contact:** Message Jarvis (AI Assistant)
