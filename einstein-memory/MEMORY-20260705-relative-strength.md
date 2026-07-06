## 2026-07-05: Einstein — Relative Strength Factor Added

Added a relative-strength factor to `readiness_score.py` to reduce momentum multicollinearity.

Weight change:
- EMA: 12% -> 4%
- Relative Strength (new): 8%

Implementation:
- `signal_engine.py`: computed `relative_strength_20d` = stock 20d return - SPY 20d return
- `readiness_score.py`: scored 0-100 based on alpha magnitude; added to `factor_breakdown`
- No new chips; monitor/frontend/LLM unchanged

Backtest (PRIME-only, hard-confirmation gate, -5% cut, ATR stops, 5-day flat exit, 10% DD halt, 2025-01-01 -> 2026-07-05):

| Metric | Old | New |
|---|---|---|
| Final value | $98,452 (-1.55%) | $102,167 (+2.17%) |
| Sharpe | -0.23 | +0.26 |
| Max DD | -6.55% | -5.62% |
| Win rate | 8.56% | 14.17% |
| Alpha | -0.00005 | +0.00003 |
| Trades | 140 | 214 |

Backup: `/opt/stonk-ai/backups/relative-strength-before-20260705.tar.gz`
