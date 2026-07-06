# StonkBOT.AI Trading Strategy & Watchlist Alignment

**Version:** v2.5  
**Date:** 2026-07-06  
**Status:** Live (sqlite migration complete, circuit breaker armed)

---

## 1. Strategy Overview

### Philosophy
- **Signal-driven:** `signals.json` is the single source of truth for what to buy
- **Readiness-driven:** Entry decisions use `entry_eligible` (not raw score) to prevent chasing false breakouts
- **Thesis-based:** Each position has an entry thesis with defined exit triggers (MACD, EMA, sector)
- **Risk-first:** Position sizing, concentration limits, drawdown brakes, regime detection
- **Anti-fragile:** Cash buffers, daily budgets, hard stops, profit trims

### Entry Gate (What the Bot Actually Checks)
| Check | Threshold | Purpose |
|-------|-----------|---------|
| Tier | `STRONG_NOW` only | Only the highest-conviction tier |
| Readiness score | `≥ 77` | Composite quality-momentum score |
| Confirmations | `≥ 5` soft, `≥ 2` hard | Volume, MACD, intraday, options, relative vol |
| Above EMA20 | `True` | Trend confirmation — no falling knives |
| `entry_eligible` flag | `True` | Set by `readiness_score.py` after all checks pass |

**Why entry_eligible != just STRONG_NOW:**  
A signal can be `STRONG_NOW` (top tier) but fail the stricter entry gate if, for example, volume confirmation is missing or RSI is stretched. This prevents false breakouts.

---

## 2. Tier System

### Backend Tiers (signal_engine.py)
| Tier | Readiness | Meaning |
|------|-----------|---------|
| `STRONG_NOW` | ≥ 77 | Entry-ready, all confirmations passed |
| `NOW` | 55–76 | Building strength, not yet entry-ready |
| `WATCH` | 40–54 | Watching — weak momentum or poor risk profile |
| `MONITOR` | < 40 | Tracking only, thesis not valid |

### Frontend Display Tiers (website/watchlist)
| Backend → Frontend | Display | Color |
|-------------------|---------|-------|
| `STRONG_NOW` + `entry_eligible=True` | **PRIME** | Cyan glow |
| `STRONG_NOW` + `entry_eligible=False` | **BUILDING** | Green |
| `NOW` | **BUILDING** | Green |
| `WATCH` | **WATCHING** | Amber |
| `MONITOR` | **TRACKING** | Gray |

### Current Distribution
| Tier | Count |
|------|-------|
| PRIME (entry-eligible) | 2 (SNOW, UBER) |
| BUILDING | 17 |
| WATCHING | 1 |
| TRACKING | 0 |
| **Total** | **20** |

---

## 3. Buy Queue Logic

### How a Symbol Gets to "Queued"
```
1. Signal generates → STRONG_NOW tier
   ↓
2. Readiness module checks → entry_eligible=True
   ↓
3. Signal saved to signals.json + stonkbot.db
   ↓
4. Watchlist manager reads signals.json
   ↓
5. Assigns frontend tier (PRIME if entry_eligible)
   ↓
6. Buy candidate logic checks:
      - entry_eligible? ✓
      - tier == PRIME? ✓
      - price > 0? ✓
      - not high-beta blocked? ✓
      - not already held? ✓
   ↓
7. Status = "queued"
   ↓
8. Trading bot reads watchlist → filters to queued
   ↓
9. Risk engine sizes position → submits order
```

### Current Buy Candidates (from ai_watchlist_live.json)
| Symbol | Status | Tier | Readiness | Notes |
|--------|--------|------|-----------|-------|
| SNOW | **add** | PRIME | 79.3 | Already held 4.7%, underweight |
| UBER | **add** | PRIME | 78.3 | Already held 5.1%, underweight |
| ETSY | not_ready | BUILDING | 79.9 | STRONG_NOW but NOT entry_eligible |
| DUOL | not_ready | BUILDING | 79.7 | STRONG_NOW but NOT entry_eligible |
| (16 others) | not_ready/tier_too_low | — | < 77 | Below entry gate |

### Why ETSY & DUOL Are STRONG_NOW but Not Entry-Eligible
Both have `readiness_score ≥ 77` (high enough for STRONG_NOW) but fail at least one hard confirmation:
- Missing volume confirmation, or
- MACD not turning, or
- RSI stretched (overbought), or
- Options signal not confirming

The `readiness_score.py` module sets `entry_eligible=False` when any hard check fails. This is by design — prevents buying into false breakouts.

---

## 4. Regime-Adaptive Strategy

The bot detects market regime every cycle and adjusts behavior:

| Regime | Max Position | Cash Floor | Entry Tier | Strategy |
|--------|-------------|------------|------------|----------|
| **RISK_ON** | 8% | 5% | NOW | Momentum — normal entries |
| **RISK_OFF** | 4% | 15% | STRONG_NOW only | Defensive — higher bar |
| **CRISIS** | 4% | 30% | None | No new entries, exit readiness < 70 |

### Regime Inputs
- SPY/QQQ 20-day return (equity trend)
- VIXY 5-day change (volatility)
- SHY/TLT ratio (yield curve)
- LQD/HYG ratio (credit spreads)
- SPY volume breadth

---

## 5. Risk Engine Constraints

### Position Sizing
| Readiness | Multiplier | Meaning |
|-----------|-----------|---------|
| ≥ 80 | 2.0× | Full conviction |
| 75–79 | 1.0× | Normal size |
| 72–74 | 0.5× | Reduced size |
| < 72 | 0× | Blocked |

### Hard Limits
- **Max single position:** 12% (STRONG_NOW) / 8% (other tiers)
- **Max sector exposure:** 30%
- **High-beta basket cap:** 35% of deployed capital
- **Cash floor:** 5% (RISK_ON) / 15% (RISK_OFF) / 30% (CRISIS)
- **Min cash absolute:** $2,000

### Exit Triggers
1. **Thesis broken:** Price below 20d EMA
2. **MACD loss:** Histogram negative for 2+ days
3. **Sector reversal:** Sector momentum + RSI overbought
4. **Readiness drop:** Below 55 (standard) or 70 (CRISIS)
5. **Flat exit:** Held ≥ **5 days** (RISK_OFF/CRISIS) / ≥ **7 days** (RISK_ON), price within ±3%, readiness < 70  
   *Widened in RISK_ON to reduce churn in trending markets*
6. **Drawdown brake:** Portfolio down **10%** from high — halt new entries
7. **Concentration brake:** Single position at or above cap (12% STRONG_NOW / 8% other / 4% risk-off) — trim to cap
8. **Hard stop loss:** Position down **-5%** from entry — immediate exit, overrides thesis-based exits

---

### Execution Method

The bot uses **two execution paths** depending on context:

| Path | Used By | Behavior |
|------|---------|----------|
| **Standard** (`submit_order`) | Diversification entries, simple adds | Midpoint limit → **market order fallback** if quote unavailable |
| **Tiered** (`submit_tiered_order`) | PRIME momentum entries | Midpoint limit + 5s timeout → **marketable limit** at ask+0.5% → **abort** if flash crash |

#### Tiered Execution (Primary Path for PRIME Entries)

1. **Midpoint limit** — `(bid + ask)/2`, 5-second timeout
2. **Marketable limit with cap** — if unfilled, resubmit at `min(ask + $0.01, ask × 1.005)`
3. **Flash crash guard** — abort if marketable limit > `midpoint × 1.02`
4. **No market order fallback** — only aborts (safe mode)

**STRONG_NOW openings (9:30-10:00 ET):** Execution is forced to aggressive mode to avoid spread timeout cascades.

#### Standard Execution (Diversification / Adds)

- Midpoint limit first
- If no quote available → **market order fallback** (necessary for illiquid names)
- No timeout escalation; simpler but less optimal for momentum entries

#### TWAP

Code includes TWAP splitting for orders >100 shares, but typical position sizes (50-200 shares = $3-5K) rarely trigger it. TWAP is a safety valve, not the default.

#### Flash Crash Guard

If the marketable limit would exceed the original midpoint by >2%, the order is **aborted entirely**. This prevents buying into dislocations or erroneous quote spikes.

---

### Portfolio Management

The bot manages the portfolio beyond individual trades:

#### Position Count Ceiling
- **MAX_POSITIONS = 12** — hard ceiling. No new entries at limit.
- If >12 positions → trim weakest 25% to make room

#### Diversification Engine
When cash > 40% of portfolio **and regime = RISK_ON**, the bot proactively adds **non-entry-eligible** (BUILDING tier) high-readiness names from underweight sectors to balance exposure:
- Readiness ≥ 65, confirmations ≥ 2
- Non-high-beta, above EMA
- Target: ~4.5% per name
- Only in RISK_ON — avoids buying lower-quality names in choppy/defensive markets

#### Rotation Logic
- Sells low-readiness positions (< 55) to free capital
- Buys high-readiness PRIME entries with proceeds
- Respects regime-aware minimum hold periods (1 day RISK_OFF, 0 day CRISIS)

#### Cash Raise
If cash falls below the dynamic floor:
- Trims weakest positions (lowest readiness first)
- Maintains minimum cash for new entries
- CRISIS regime: more aggressive trimming

---

## 6. Signal-Watchlist-Portfolio Alignment

### Data Flow
```
SignalEngine (Alpaca data)
   ↓ generate_signals()
   ↓ save_signals()
signals.json  →  stonkbot.db  ←  (new)
   ↓                    ↓
   ↓              DB queries
   ↓                    ↓
Watchlist Manager    Healthcheck
   ↓ build_watchlist()    ↓ reads freshness
ai_watchlist_live.json   ↓ tripped?
   ↓                    Circuit Breaker
Trading Bot              ↓
   ↓ _load_watchlist()  ← open = NO TRADES
   ↓ filters to queued
Order submission
```

### Key Alignment Rules
1. **Signal dictates watchlist:** Watchlist is built from top 20 signals by readiness_score
2. **Watchlist gates trading:** Bot only buys symbols present in `ai_watchlist_live.json`
3. **Tier alignment enforced:** `assign_tier()` uses deterministic mapping (see §2)
4. **Stale watchlist fallback:** If watchlist > 15 min old, bot falls back to full universe (safety)

### Current Alignment Check
| Check | Result |
|-------|--------|
| Entry-eligible in JSON | 2 (SNOW, UBER) |
| Entry-eligible in DB | 2 (✓ synced) |
| In watchlist | ✓ Both PRIME |
| Held positions | ✓ Both in portfolio |
| Tier mapping | ✓ All 20 match |
| JSON ↔ DB sync | ✓ After fix |

---

## 7. Circuit Breaker Integration

### What Trips the Breaker
- Healthcheck detects critical issues (stale data, failed services, root processes)
- Manual operator trip: `python3 circuit_breaker.py --trip reason`

### What Happens When Tripped
- All BUY orders rejected at `submit_order()`
- `run_cycle()` exits immediately (no new entries)
- Positions still monitored, exits still processed
- Telegram alert sent automatically

### Reset
- Manual only: `python3 -c "from circuit_breaker import CircuitBreaker; CircuitBreaker().reset()"`
- Prevents buggy automation from silently re-enabling trading

**Current Status:** `Halted: False` (trading enabled)

---

## 8. Known Behavior (Not Bugs)

| Observation | Explanation |
|-------------|-------------|
| 4 STRONG_NOW, only 2 entry-eligible | ETSY/DUOL fail `≥ 2 hard confirmations` |
| SNOW/UBER show "add" not "queued" | Already held but underweight (< 6%) |
| No buy orders submitted yet | Market closed (US pre-market); bot checks `is_market_open()` |
| Watchlist has 20, portfolio has 12 | Cash deployment is gradual; positions added over days |
| ETSY/DUOL in BUILDING not PRIME | `entry_eligible=False` forces BUILDING even with high readiness |
| Bot buys BUILDING-tier names | Diversification engine — sector balance when cash > 40% |
| Position trimmed after entry | Rotation logic — sold low-readiness to fund PRIME entry |

---

## 9. When Trading Resumes (Next Cycle)

Assuming market opens with no regime change:

1. Signal engine refreshes (every 15 min) → generates new signals
2. If SNOW/UBER still entry_eligible → stay PRIME
3. If ETSY/DUOL gain missing confirmations → promote to PRIME
4. Trading bot checks watchlist → finds PRIME symbols
5. Risk engine sizes positions → adds to SNOW/UBER if underweight
6. New positions added if cash > floor + entry cost

---

## 10. Files & Their Roles

| File | Role |
|------|------|
| `signal_engine.py` | Generates scores, sets tiers, computes entry_eligible |
| `readiness_score.py` | 10-factor readiness + confirmation logic |
| `trading_bot.py` | Executes trades, risk management, exits |
| `dynamic_watchlist_manager.py` | Builds watchlist from signals, assigns frontend tiers |
| `risk_engine.py` | Position sizing, concentration, drawdown brakes |
| `circuit_breaker.py` | Safety halt for critical failures |
| `stonkbot_healthcheck.py` | Monitors health, trips breaker |
| `stonkbot_db.py` | SQLite data layer (new) |
| `signals.json` | Signal source of truth |
| `ai_watchlist_live.json` | Watchlist + buy candidates for website/bot |
| `portfolio_data.json` | Holdings + cash + P&L |

---

*This document is auto-generated from live system state on 2026-07-06.*
