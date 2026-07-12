# StonkBOT.AI Trading & Watchlist Strategy Audit

**Date:** 2026-07-12 UTC  
**Scope:** `trading_bot.py`, `readiness_score.py`, `signal_engine.py`, `dynamic_watchlist_manager.py`, `risk_engine.py`, `website/index.html`

---

## 1. Strategy Overview

### Signal generation
- `signal_engine.py` fetches Alpaca SIP snapshots, daily bars, 15-min intraday bars, options IV/snapshots, corporate actions, and news.
- It scores 130 symbols with a momentum/quality/risk/regime model, then computes `readiness_score` via `readiness_score.py`.
- Output is `signals.json`.

### Readiness & tiering
- `readiness_score.py` combines 11 original factors + 6 new confirmation chips (5M, OF, SPR, CA, plus QBI) into a 0-100 readiness score.
- Tiers:
  - `STRONG_NOW/PRIME` ≥78 and entry-eligible
  - `NOW/BUILDING` ≥72
  - `WATCH/WATCHING` ≥40-55
  - `MONITOR/TRACKING` <40
- Entry gate requires: readiness ≥77, confirmation_count ≥5, above_ema, and ≥2 hard confirmations.

### Trading loop
- `trading_bot.py` refreshes signals every 15 min during/around market hours.
- Buys STRONG_NOW/PRIME names that pass risk checks.
- Sells on thesis breaks, ATR stops, trailing stops, profit targets, or risk-based trims.
- Position sizing scales with readiness (2.0× for ≥80, 1.0× for ≥75, 0.5× for ≥72).

### Watchlist
- `dynamic_watchlist_manager.py` builds `ai_watchlist_live.json` every 5 min.
- It ranks buy candidates as `queued`, `add`, `hold`, etc.
- Frontend reads `ai_watchlist_live.json` and renders chips.

---

## 2. Critical Issues

### 2.1 Tiering scale has been silently shifted
- Adding 6 new confirmation chips (total new weight ≈11%) changed the relative weight of every original factor.
- Old PRIME threshold of 78 was calibrated on the original 11-factor model.
- **Risk:** A symbol that was previously PRIME may no longer reach PRIME, or vice versa, not because of signal quality but because of weight renormalization.
- **Recommendation:** Backtest the new weights against the prior 30-60 days and verify PRIME/NOW thresholds still make sense.

### 2.2 Backend/frontend confirmation count mismatch
- `readiness_score.py` returns 17 confirmation booleans.
- The website’s `allFactors` array has 15 chips (MOM, RSI, VOL, MACD, EMA, SEC, INT, OPT, VWAP, RVOL, 5M, OF, SPR, QBI, CA).
- `readiness_score.py` returns `volume_5m_surge`, `price_above_5m_vwap`, `options_unusual_volume`, etc., but the UI only shows aggregate chips.
- **Risk:** Backend counts differ from what the user sees.
- **Recommendation:** Create a single source-of-truth mapping between backend booleans and frontend chips; unit test it.

### 2.3 `spread_ok` and `QBI` can be contradictory
- `spread_ok` is a positive weight in readiness score.
- `bid_ask_bullish` (QBI) is a separate positive weight.
- A wide-spread symbol is penalized by `wide_spread` and rewarded by `no_corporate_action_risk`, etc.
- **Risk:** Two quote-level signals can fight each other.
- **Recommendation:** Merge spread/imbalance into a single quote-quality factor or ensure they use the same quote snapshot to avoid stale/inconsistent values.

### 2.4 Entry gate mismatch between trading bot and watchlist
- `trading_bot.py` uses `_is_entry_eligible_for_mode()`.
- `dynamic_watchlist_manager.py` builds its own `buy_candidates` list.
- They share the same `signals.json`, but the watchlist manager has extra logic (high-beta cap, opportunistic cap) not present in the bot.
- **Risk:** A symbol shown as "queued" in the UI may not actually be bought, or a symbol the bot buys may not show as queued.
- **Recommendation:** Move `buy_candidates` logic into a shared module used by both bot and watchlist.

### 2.5 Hardcoded thresholds remain
- `BID_ASK_SPREAD_PCT_THRESHOLD = 0.005` in `signal_engine.py`
- `OPTIONS_ENRICHMENT_UNIVERSE_SIZE = 30`
- `WEIGHT_5M_MOMENTUM = 0.03`, `WEIGHT_OPTIONS_FLOW = 0.02`, etc.
- PRIME/NOW/WATCH thresholds in `readiness_score.py`
- `DIVERSIFICATION_READINESS_MIN = 65.0`, `DIVERSIFICATION_TARGET_PCT = 0.045`
- **Recommendation:** Centralize these in a config file and load at startup.

### 2.6 High-beta cap complexity
- The high-beta cap was recently changed to 35% steady / 40% opportunistic.
- Both `trading_bot.py` and `dynamic_watchlist_manager.py` implement similar but not identical logic.
- **Risk:** Drift between buy decision and watchlist display.
- **Recommendation:** Centralize the high-beta rule in `risk_engine.py` and import it everywhere.

---

## 3. Medium Issues

### 3.1 Options enrichment limited to first 30 symbols
- `signal_engine.py` enriches options flow for only the first 30 symbols in the universe.
- **Risk:** Symbols beyond the first 30 will not have OF/QBI/SPR/etc. or will have stale values.
- **Recommendation:** Either paginate across the full universe or document why only 30 are enriched.

### 3.2 Corporate actions only look 30 days forward
- `alpaca_data.py` default `days_forward = 30`.
- **Risk:** A split/dividend beyond 30 days is invisible; within 30 days the bot may still enter too close to the event.
- **Recommendation:** Make look-forward window configurable and consider adding a minimum-days-to-event guard (e.g., don’t enter within 2 trading days of a split).

### 3.3 `readiness_score.py` weight naming drift
- Some weights use `_WEIGHT` suffix, others use `WEIGHT_` prefix.
- The new chips are `WEIGHT_5M_MOMENTUM`, but existing ones are `WEIGHT_SIGNAL`.
- **Recommendation:** Standardize naming for maintainability.

### 3.4 QBI chip not present in `compute_readiness` hard confirmations
- `bid_ask_bullish` is not counted toward `hard_confirmations`.
- **Risk:** A symbol can show QBI active but it does not affect the entry gate.
- **Recommendation:** Decide whether QBI should be a hard confirmation. If yes, add it.

### 3.5 `run_cycle()` is very long
- `run_cycle()` in `trading_bot.py` is ~760 lines.
- **Risk:** Hard to test, hard to reason about, hard to change safely.
- **Recommendation:** Refactor into smaller functions with clear responsibilities.

### 3.6 Frontend chip layout can truncate
- The 15 chips are wrapped to 2 rows with `max-height: 2.2em`.
- **Risk:** On narrow mobile screens some chips may be hidden.
- **Recommendation:** Make the chip area expandable or use a popover on mobile.

---

## 4. Low / Operational Issues

### 4.1 LLM narratives only during market hours
- `llm_narrative_scheduler.py` exits when `is_open=False`.
- **Impact:** Weekend/evening popups show stale narratives.
- **Status:** By design; acceptable for now.

### 4.2 `alert_logger.py` is not in git
- I just restored it from `/tmp` and added it.
- **Status:** Fixed in `68fb3c0`.

### 4.3 Log and generated data were tracked in git
- I added `.gitignore` and removed logs/cache from history.
- **Status:** Fixed in `75f5a00`.

### 4.4 `signals.json` and `ai_watchlist_live.json` are still tracked
- These are generated data but still in git.
- **Recommendation:** Remove from git tracking and let the bot regenerate them on deploy.

---

## 5. Recommendations (Prioritized)

| Priority | Action | File(s) |
|---|---|---|
| **High** | Backtest new readiness weights and recalibrate PRIME/NOW thresholds | `readiness_score.py` |
| **High** | Unify `buy_candidates` logic between bot and watchlist | `trading_bot.py`, `dynamic_watchlist_manager.py` |
| **High** | Centralize all thresholds in a config file | all |
| **Medium** | Create a single chip-mapping between backend and frontend | `readiness_score.py`, `website/index.html` |
| **Medium** | Centralize high-beta cap in `risk_engine.py` | `risk_engine.py` |
| **Medium** | Expand options enrichment beyond 30 symbols or document why | `signal_engine.py`, `options_iv_analytics.py` |
| **Medium** | Decide if QBI should be a hard confirmation | `readiness_score.py` |
| **Low** | Refactor `run_cycle()` into smaller functions | `trading_bot.py` |
| **Low** | Improve mobile chip layout | `website/index.html` |
| **Low** | Untrack `signals.json` and `ai_watchlist_live.json` from git | `.gitignore` |

---

## 6. Immediate Risks to Monitor

1. **Readiness score recalibration** — PRIME count may drop/increase unexpectedly.
2. **Backend/frontend chip mismatch** — users may see green chips that the backend did not actually confirm.
3. **Entry gate drift** — watchlist shows one thing, bot does another.
4. **QBI signal quality** — quote imbalance can flip quickly during volatile sessions.

---

*Report generated by Einstein / Jeeves audit on 2026-07-12.*

---

## 7. Post-Audit Recalibration (2026-07-12)

### Actions taken
1. **Halved new chip weights** in  to reduce scale shift:
   - : 0.03 → 0.015
   - : 0.01 → 0.005
   - : 0.01 → 0.005
   - : 0.02 → 0.01
   - : 0.02 → 0.01
   - : 0.02 → 0.01
   - : 0.02 → 0.01
2. **Kept original thresholds**: STRONG_NOW 78 / NOW 72 / WATCH 55 / ENTRY 77.
3. **Reverted  to 2** after briefly testing 1.
4. **Centralized ** constant in  and .
5. **Untracked  and ** from git.

### Current state
- **0 PRIME / STRONG_NOW**
- **13 NOW / BUILDING**
- **189 WATCH / WATCHING**
- **291 MONITOR / TRACKING**
- **0 entry-eligible symbols**

### Interpretation
The current market is not producing symbols that satisfy the full entry gate:
- Readiness ≥ 78
- ≥2 hard confirmations among [volume, MACD, intraday, options, relative volume]
- Above 20d EMA
- ≥5 total confirmations

This is arguably the correct behavior for a weak or transition market. The bot should not force trades.

### Remaining concern
Even with halved weights, the new confirmation chips still dilute the readiness scale and add complexity. A future review should consider whether they belong in the readiness score at all, or only as display/confirmation chips.

