# Handover #2: Phase 2 strategy overhaul (Einstein, 2026-07-22 ~10:10 HKT)

**Commit:** 610d219 (risk_engine.py, trading_bot.py). Deployed, stonk-ai.service restarted 10:05 HKT. Follows anti-churn v2 (7c288c2) from this morning.

## Why
Full audit (529 trades Jul 7-21): same-day round-trips = 60% of activity, net -$4,887; multi-day holds net +$785. Stops sat inside the noise band of 4-7% ATR names. SPY was flat (+0.06%) — losses were self-inflicted.

## What changed
1. **Vol filter:** `max_entry_atr_pct = 0.07` — entries AND avg-ins blocked when daily ATR > 7% ("volatility filter" block reason in sizing result). LCID-class names no longer tradeable.
2. **Stops ATR-honest:** hard stop cap -8%→-11%; absolute hard cut -5%→min(-5%, -1xATR); bot -3% cut widens to 1x ATR; VWAP stop buffer max(2%, 0.5xATR); trailing cap -10%→-14%; below-VWAP tightening floor 1x ATR.
3. **Min-hold rule:** non-stop sells on positions bought TODAY are deferred in `_execute_sell`. `risk_engine.bought_today()` = entries_today OR position_last_add_time today (UTC date == ET trading date since bot trades 13:30-20:00 UTC only). Stop reasons (is_stop_reason) exempt — stops still fire same-day.
4. **Outcome tracker:** cron switched signal_tracker.py → outcome_tracker.py (every 15 min, logs/outcome_tracker.log). signal_accuracy.json now has by_cohort/by_tier. NOTE: signal_tracker.py is dead code — do NOT run it manually (it rewrites engine-owned signals.json). Candidate for repo deletion later.

## Watch tomorrow
- "MIN-HOLD: deferring non-stop sell" log lines on positions bought same-day
- "volatility filter" block reasons on high-ATR signals
- Stop widths in sell rationales should now scale with ATR (e.g. -6% on 4% ATR names, not flat -3%/-5%)
- signal_accuracy.json by_cohort should populate as 5d windows close
- Expected trade frequency: materially lower than the 30-48/day era
