# Handover to Einstein — Options Skew Signal Analysis (2026-07-01 14:05 HKT)

## Context
Howie asked for ideas to optimize StonkBOT using Alpaca Premium Data feeds. Jeeves recommended extending options IV analytics rather than building new dashboards.

## What was done
- **No website changes** — kept internal per Howie's instruction.
- Removed an attempted new `options_skew_analytics.py` prototype because `options_iv_analytics.py` already computes `iv_skew`, `iv_rank`, and term structure.
- Created `/opt/stonk-ai/analyze_options_skew_signal.py` to correlate the **existing** IV metrics with actual trade outcomes.

## Script details
- Reads `/opt/stonk-ai/performance_attribution.json` trade journal.
- Reads `/opt/stonk-ai/iv_summaries.json` and `/opt/stonk-ai/iv_history/*.json`.
- Matches each trade's entry date to the IV metrics available at that time.
- Computes Pearson correlations:
  - `iv_30d` vs P&L%
  - `iv_skew` vs P&L%
  - `iv_rank` vs P&L%
- Buckets win rate by `iv_skew` thresholds (≥1.1 high skew, ≤1.0 low skew).
- Writes report to `/opt/stonk-ai/options_skew_correlation_report.json`.

## Schedule
Daily at 7 AM HKT (23:00 UTC) via root cron, after IV summaries update.

## First results (2026-07-01)
- Sample: 12 trades with matched IV history.
- `iv_skew` vs P&L%: **-0.6082** — higher put/call skew associated with worse outcomes.
- `iv_30d` vs P&L%: **-0.3444** — higher absolute IV moderately associated with worse outcomes.
- `iv_rank` vs P&L%: not enough data yet.
- High skew (≥1.1) bucket: 0 trades in sample.
- Low skew (≤1.0) bucket: 2 trades, both winners, avg +14.55%.

## Interpretation
Negative `iv_skew` correlation means the bot does worse when puts are relatively expensive vs calls. This could indicate:
- Hedging demand / fear before the bot buys into a falling knife.
- Earnings/event risk not captured by other signals.

However, **sample size is very small** (12 trades). Do not act on this yet. Let it accumulate 50+ matched trades before considering a readiness-score adjustment.

## Files
- `/opt/stonk-ai/analyze_options_skew_signal.py`
- `/opt/stonk-ai/options_skew_correlation_report.json`

## Backup
Will be included in next comprehensive backup.
