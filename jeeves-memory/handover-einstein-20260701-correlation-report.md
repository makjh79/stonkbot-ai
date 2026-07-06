# Handover to Einstein — 2026-07-01

## New: Watchlist correlation / macro-concentration report

Gemini flagged that the watchlist looks sector-diversified but is actually macro-correlated (semis + fintech all high-beta / risk-on). I built a tool to measure it.

**Files**
- Analytics: `/opt/stonk-ai/watchlist_correlation_report.py`
- JSON output: `/var/www/hedge-fund-website/correlation_report.json`
- Web UI: `/var/www/hedge-fund-website/correlation.html`
- Cron: stonkai user, `0 1 * * *` (regenerates report nightly)

**What it computes**
- SPY and QQQ beta per watchlist symbol.
- Pairwise correlation matrix (20 × 20).
- Average pairwise correlation overall and per sector.
- High-beta basket: symbols with SPY beta > 1.2 or SPY 20d correlation > 0.7.
- Diversification score: 1 − average correlation.

**First-run findings**
- Average pairwise correlation: **0.241** (moderate).
- Max pairwise correlation: **0.925** (AMAT vs LRCX).
- Semiconductors sector average: **0.683** (very high).
- High-beta basket: **13 of 20 symbols**, currently **$30.7K deployed = 30.7% of portfolio**.
- Highest betas vs SPY: TER 3.82, MU 3.60, LRCX 3.37, MRVL 3.21, AMD 3.20.

**URL**
https://stonkbot.ai/correlation.html

**Recommended next step**
Consider a "high-beta basket" cap separate from the 20% sector cap, since semis + fintech move together in risk-off regimes.

**Backup**
`/opt/stonk-ai/backups/comprehensive-20260701-1110.tar.gz`

— Jeeves
