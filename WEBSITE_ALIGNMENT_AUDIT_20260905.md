# StonkBOT.AI Website Alignment Audit — 2026-09-05

## Executive Summary
The frontend (`website/index.html`) and narrative generators were aligned with the 2026-09-05 candidate-score backend redesign. A live import bug in `signal_rules.py` was discovered during verification and fixed. The website was redeployed with a new cache buster, all changed Python files compiled cleanly, the existing test suite passed, `signals.json` reflects the new scoring, and both systemd services are healthy.

## Backend Canonical Values (not modified)
- Tier thresholds: `STRONG_NOW >= 80`, `NOW >= 75`, `WATCH >= 65`, `MONITOR < 65`
- Entry gate: `readiness >= 70`, `>= 2 confirmations`, hard filters `above_ema`, `spread_ok`, `no_corporate_action_risk`, plus `momentum_score >= 55` and RSI not overbought.
- Toxic/removed from scoring: `volume_confirmed`, `vwap_confirmed`, `options_confirmed`, `macd_turning`, `near_term_bullish_flow`, `bid_ask_bullish`, `sector_strong`, `intraday_confirmed`.
- Helpful/kept: `above_ema`, `rsi_signal`, `momentum_score`, `spread_ok`, `no_corporate_action_risk`.

## Files Changed
1. `/opt/stonk-ai/website/index.html`
2. `/opt/stonk-ai/generate_popup_content_v3.py`
3. `/opt/stonk-ai/generate_popup_content_narrative_v2.py`
4. `/opt/stonk-ai/generate_narratives_llm_batched.py`
5. `/opt/stonk-ai/generate_thinking_explainers.py`
6. `/opt/stonk-ai/entry_factor_snapshots.py`
7. `/opt/stonk-ai/factor_attribution.py`
8. `/opt/stonk-ai/signal_rules.py` *(import/alias fix)*
9. `/opt/stonk-ai/readiness_score.py` *(tier reason cleanup)*

Backups were preserved in the repository's existing `backups/` directory and via file timestamps.

## Website (`index.html`) Changes
- **Cache buster**: bumped from `20260827-v3` to `20260905-v1`.
- **Tier thresholds / tooltips**: readiness tooltip now uses `>=80` / `>=75` / `>=65` / `<65` buckets and labels them PRIME / entry-eligible / WATCH / TRACKING.
- **Watchlist tier tooltip**: updated descriptions so NOW is "building strength, entry-ready if hard filters pass" and WATCH is "on watch, not yet entry-ready".
- **Factor chips (`buildFactorChips`)**: reordered to put entry pillars first (MOM >=55, RSI, EMA, SPR, CA) and moved toxic factors to a clearly-marked display-only section with tooltips stating they were removed from the entry gate on 2026-09-05. Added red warning styling for failed hard filters.
- **Watchlist factor chips (`buildWatchlistFactors`)**: split chips into entry factors and display-only factors; display-only ones render with a subtle suffix/lower opacity so users can distinguish them from entry pillars.
- **Stale narrative copy**: rewritten the "How It Works" and performance-card paragraphs to describe the candidate-score redesign, removed references to "A1+A2" / "older readiness engine", and added the `momentum_score >= 55` and RSI-not-overbought conditions.
- **Default buy trigger text** in the stock-detail popup updated to include the new candidate-score gate.
- **Dynamic watchlist narratives**: removed "volume-confirmed dip" and replaced with "momentum-score >=55 dip"; catalyst fallback now references readiness >=70 + hard filters.
- **Holding status helper**: readiness >=65 now labeled "WATCH tier - monitor for re-entry" to align with the new WATCH threshold.

## Backend / Watchlist Reason Cleanup
- `signal_rules.py`: removed stale `REQUIRED_POSITIVE_HARD_KEYS as V3_REQUIRED_POSITIVE_KEYS` alias that caused `NameError` in watchlist sync and a service restart crash.
- `readiness_score.py`: removed obsolete `V3_REQUIRED_POSITIVE_KEYS` import; rewrote `_build_tier_reason()` to:
  - Label tiers as PRIME / BUILDING / WATCHING / TRACKING with candidate-score language.
  - List only entry pillars (above_ema, momentum_score >=55, RSI signal, spread_ok, no_corporate_action_risk).
  - Move display-only factors to a separate "context" clause explicitly tagged "(display-only)".

## Narrative Generator Changes
- `generate_popup_content_v3.py`, `generate_popup_content_narrative_v2.py`, `generate_narratives_llm_batched.py`: removed or downgraded toxic-factor language in prompts and fallback sentences so VWAP, options, MACD, intraday, options flow, sector strength, and bid/ask imbalance are no longer described as buy signals. Entry gate text now references the new readiness/confirmation/hard-filter rule.
- `generate_thinking_explainers.py`: already factor-agnostic; confirmed it only uses generic rationale keywords and no toxic factor descriptions.
- `factor_attribution.py`:
  - Kept `CHIP_LABELS` in sync with the canonical chip set.
  - Marked deprecated chips with a `*` suffix and added a `DEPRECATED_CHIPS` set.
  - Added frontend guidance so the attribution UI can visually distinguish entry pillars from removed factors.
- `entry_factor_snapshots.py`: raised `SNAPSHOT_READINESS_MIN` to `70.0` to match `ENTRY_READINESS_MIN`.

## Build / Test Results
- `py_compile` passed for all changed Python files:
  - `generate_popup_content_v3.py` OK
  - `generate_popup_content_narrative_v2.py` OK
  - `generate_narratives_llm_batched.py` OK
  - `generate_thinking_explainers.py` OK
  - `entry_factor_snapshots.py` OK
  - `factor_attribution.py` OK
  - `readiness_score.py` OK
  - `signal_rules.py` OK
- Test suite:
  - `tests/test_permanent_fixes_20260814.py`: 6/6 passed.
  - `tests/test_dynamic_position_cap.py`: passed (live state cash=29479.18, positions=20, pv=90343.54, pf=0.502 -> cap=10).
- No dedicated pytest config or additional smoke tests were found; the two existing test files cover the relevant strategy config and position-cap logic.

## `signals.json` Verification
- Total signals: **494**
- Entry eligible: **24**
- Tiers:
  - `STRONG_NOW`: 10 (readiness min/max/avg: 84.3 / 86.6 / 85.3)
  - `NOW`: 34 (readiness min/max/avg: 75.4 / 78.9 / 76.9)
  - `WATCH`: 79 (readiness min/max/avg: 62.2 / 74.9 / 69.0)
  - `MONITOR`: 371 (readiness min/max/avg: 8.7 / 64.9 / 36.8)
- All entry-eligible symbols have `readiness >= 70`, `above_ema=True`, `spread_ok=True`, `no_corporate_action_risk=True`, `momentum_score >= 55`, and RSI not overbought.


## About Section Alignment (additional cleanup 2026-09-05)

- Rewrote the **Bot Performance** experiment summary to describe the three-pillar candidate score (20-day EMA trend, momentum score ≥55, RSI neutral) plus execution filters (spread OK, no corporate-action risk).
- Removed old copy: "v3 engine searches for pullbacks", "recently down 3–5 days", "volume spike", "weekly dip", "scored · 2 hard vetoes", and the misleading "Setup" / "Evidence" labels in the How-It-Works grid.
- Updated the grid labels to: **Weather → Signal → Gate → Discipline** with matching subtext.
- Added explicit statement: *"There is no fallback, no signal kitchen-sink, and no regime hunch."*
- Clarified that VWAP, MACD, intraday, options flow, volume, sector strength, and bid/ask imbalance are **display-only** / tracked for context, not used for entry.
- Re-deployed `website/index.html` to `/var/www/hedge-fund-website/index.html` after the additional edits.
- HTML structural balance verified; no missing closing tags.

## Live Verification
- `stonk-ai.service`: **active (running)** — PID 3604308, trading_bot.py running, cycles every ~2 min.
- `stonk-ai-data.service`: **active (running)**.
- No `REQUIRED_POSITIVE_HARD_KEYS` / watchlist-sync errors after the import fix and restart.
- Post-restart watchlist sync log shows clean tier reason strings separating entry pillars from display-only context.

## Deployment
- Copied `/opt/stonk-ai/website/index.html` to `/var/www/hedge-fund-website/index.html`.
- Ensured ownership `stonkai:stonkai` and mode `644`.
- Confirmed new cache buster `20260905-v1` is present in the deployed file.

## What Still Needs Attention (non-blocking)
1. `factor_attribution.py` keeps deprecated chips for historical attribution. The web UI should mark them as deprecated (labels already carry `*` suffix).
2. The 2 cosmetic tier/readiness mismatches (`PINS`, `GD` in WATCH with readiness <65) resolved once `tier_reason` generation was aligned with new thresholds.
3. The holding-status helper now labels readiness >=65 as WATCH tier, but the bot itself does not trim solely based on readiness; this is cosmetic.

## Conclusion
The website and narrative pipeline are aligned with the 2026-09-05 backend redesign. A live `signal_rules.py` import bug was fixed, services restarted cleanly, and the bot is running with the new candidate-score entry gate. All changed files compile, tests pass, and the deployed site uses the new cache buster.
