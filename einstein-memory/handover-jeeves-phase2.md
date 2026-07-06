# HANDOVER NOTE — Einstein → Jeeves
## Phase 2 Development Brief
**Date:** 2026-06-27
**From:** Einstein (hat agent, Telegram)
**To:** Jeeves (VPS agent, StonkBOT primary)
**Re:** Alpaca Paid Data Integration Complete — Phase 2 Priorities

---

## What Happened (Phase 1 Summary)

Howie upgraded his Alpaca account to the paid plan. I spent ~4 hours doing a full integration:

### Built
- `alpaca_data.py` — Unified data hub (snapshots, daily bars, 15Min intraday, options IV, news, market clock)
- All components now source exclusively from Alpaca. Yahoo Finance, synthetic bars, yfinance, alpaca_trade_api — all removed.

### Fixed (7 gaps found in audit)
1. **VWAP stops were silently inactive** — trading_bot.py never passed VWAP data to risk engine. Now injected via Alpaca snapshots into every position.
2. **Entry pricing** — hub snapshot fallback added
3. **Intraday entry timing** — bot now skips buys if >3% pump in 15Min candle
4. **Options IV sizing** — high IV reduces position size (0.5× at IV>0.8)
5. **RSI** — from signals.json + hub (Yahoo/Polygon removed)
6. **VWAP stop in popup** — now displayed on website when losing
7. **fetch_data_simple.py** — hub replaces alpaca_trade_api, VWAP added to portfolio_data

### Current State
- 71 signals, 7 confirmations each (momentum, RSI, volume, MACD, EMA, sector, intraday, options)
- 22 positions, ~$97K portfolio, 15 winners / 7 losers
- All website data points source from Alpaca ✅
- News auto-populates 24/7 including weekends
- Git: `dc40ad7` on master
- Backup: `/opt/stonk-ai/backups/comprehensive-20260627-0550.tar.gz` (49MB)
- Still on **paper trading** (PK keys). Live keys needed for real trading.

### Monday Scheduled
- 9:25 AM ET — Pre-market generation (all data generators run, results to Howie via Telegram)
- 9:35 AM ET — Intraday pipeline test (verifies 15Min bars, VWAP stops, options live)

---

## Phase 2 Priorities (for Jeeves)

Howie knows these gaps exist. He asked about "professional trader standards" and I was honest. Here's what Phase 2 should tackle, in priority order:

### 1. Backtesting Framework (HIGHEST PRIORITY)
We deploy strategy changes on faith. Need:
- Historical signal replay: run signal_engine.py over 1-2 years of Alpaca daily bars
- Simulate trades with entry/exit rules from risk_engine.py
- Compare portfolio value vs SPY buy-and-hold
- Output: Sharpe ratio, max drawdown, win rate, alpha
- File to create: `/opt/stonk-ai/backtest.py`
- Data source: `alpaca_data.py` hub `get_daily_bars()` (can fetch 2+ years)

### 2. Performance Attribution
We track P&L but not *why*. Need:
- Sharpe ratio, alpha vs beta, benchmark comparison (are we beating SPY?)
- Factor decomposition: which of the 7 confirmations correlate with winners?
- Per-trade journal: entry signal, thesis at exit, what worked/didn't
- File to create: `/opt/stonk-ai/performance_attribution.py`
- Data: `trades_log.json` + `signals.json` + `portfolio_history.json`

### 3. Stress Testing
No "what if market drops 5% tomorrow" simulation. Need:
- Portfolio correlation matrix (are positions too correlated?)
- VaR (Value at Risk) — 95th percentile daily loss
- Scenario simulation: market -5%, sector rotation, specific stock crashes
- File to create: `/opt/stonk-ai/stress_test.py`

### 4. Execution Optimization
We fire market orders. At ~$90K this is fine but for scaling up:
- Limit orders at bid/ask midpoint
- TWAP for large orders
- Slippage tracking
- Modify: `trading_bot.py` `submit_order()`

### 5. Regime Detection Enhancement
Currently uses SPY/QQQ/VIXY only. Should add:
- Yield curve (2y/10y spread) — recession indicator
- Credit spreads (ICE BofA)
- Market breadth (advance/decline ratio)
- Sector rotation model
- Modify: `signal_engine.py` `_regime_score()`

### 6. Real-time Monitoring & Alerting
If something breaks at 3 AM, nobody knows. Need:
- Discord/Telegram alert on: service failure, large drawdown, stuck position
- Kill switch: halt all trading if portfolio drops >15% in a day
- File to create: `/opt/stonk-ai/monitor.py`

---

## Technical Notes for Jeeves

### Key Files
- `alpaca_data.py` — the hub. All data access goes through here.
- `signal_engine.py` — generates signals using hub composite fetch
- `readiness_score.py` — 7 confirmations: momentum, RSI, volume, MACD, EMA, sector, intraday, options
- `risk_engine.py` — hard stop (-10%), trailing (ATR-aware), VWAP stop (-2% below), VWAP-enhanced trailing
- `trading_bot.py` — main loop. Now injects VWAP into positions, IV sizing, intraday entry timing
- `generate_popup_content.py` — always generates (24/7), VWAP stop + Alpaca news in popups
- `signal_enricher.py` — Finnhub + Alpaca news, keyword sentiment
- `fetch_data_simple.py` — uses hub, VWAP in portfolio_data.json

### Gotchas
- Alpaca v2 snapshots return symbols at TOP LEVEL (not nested under "snapshots")
- Alpaca bars API paginates at 1000 bars/page — batch size 15 symbols max
- `@staticmethod` decorators can get eaten by regex patches — always verify after patching
- `chown stonkai:stonkai` after any root writes — bot can't write to root-owned files
- Popup generator no longer skips when market closed — generates 24/7

### Backups
- `/opt/stonk-ai/backups/comprehensive-20260627-0550.tar.gz` (49MB, everything)
- `/opt/stonk-ai/backups/signal_engine_pre_alpaca_upgrade.py`
- `/opt/stonk-ai/backups/risk_engine_pre_alpaca_upgrade.py`
- `/opt/stonk-ai/backups/dwm_pre_alpaca_upgrade.py`
- `/opt/stonk-ai/backups/trading_bot_pre_alpaca.py`
- `/opt/stonk-ai/backups/fetch_data_simple_pre_hub.py`
- `/opt/stonk-ai/backups/fetch_ai_watchlist_pre_alpaca.py`
- `/opt/stonk-ai/backups/generate_popup_pre_vwap.py`
- `/opt/stonk-ai/backups/signal_enricher_pre_alpaca.py`

### Git
- Repo: `makjh79/stonkbot-ai` (master branch)
- Latest commit: `dc40ad7 v94-alpaca-fix: VWAP stop in popup, all data sourced from Alpaca paid API`
- Deploy: GitHub Actions triggers on push to master, syncs to VPS

### Crontab
- Popup content: every 2 min (24/7)
- Signal refresh: every 15 min
- Bot scan: every 5 min during market hours
- Enrichment: 5:30 + 21:00 UTC weekdays (full), 22:00/1:00/4:00 UTC weekdays (news-only), 12:30/20:30 UTC weekends
- Alpaca trade sync: every 5 min
- History reconstruct: 22:30 UTC daily

### Monday Crons (one-shot, will delete after run)
- 13:25 UTC — Pre-market generation (Einstein will run, results to Telegram)
- 13:35 UTC — Intraday pipeline test (Einstein will run, results to Telegram)

---

## When Howie Asks "What's Next?"

The honest answer: backtesting + performance attribution should come first. They tell us if the bot is actually making money or just getting lucky. Everything else is secondary until we can prove the edge exists.

— Einstein 🎩