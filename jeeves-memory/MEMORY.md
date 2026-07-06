# Long-Term Memory

## User: Howie Mak
- Timezone: Asia/Hong_Kong (GMT+8)
- Met via Telegram.
- Runs StonkBOT.AI — a $100K real-money autonomous AI trading experiment.
- Highly clutter-sensitive. Prefers terse copy, minimal indicators, and easy reverts.
- Likes subtle motion/polish, dislikes flashy or try-hard copy (avoids war/battle clichés unless understated).

## Setup
- **Working model:** `deepinfra/deepseek-ai/DeepSeek-V4-Flash` (DeepInfra) — switched 2026-06-28. Was `deepinfra/zai-org/GLM-5.2`.
  - Added to `models.providers.deepinfra.models` in openclaw.json; set as config default.
  - New DeepInfra API key configured.
  - **Known issue:** DeepSeek V4 Flash gets rate-limited on DeepInfra; system auto-falls back to GLM-5.2. Session overrides may revert after gateway restarts.
- **Image model:** `deepinfra/Qwen/Qwen3-VL-30B-A3B-Instruct` — switched 2026-06-28 after GLM-4.5V returned 404 on DeepInfra.

## StonkBOT.AI Project
- Site: https://stonkbot.ai
- Repo: makjh79/stonkbot-ai
- Deploy target: `/var/www/hedge-fund-website/index.html` on VPS `23.80.82.47`
- Current live version: v145+ (10-factor confirmation chips end-to-end, PEAD fully removed, monitor clean)
- Bot version: v2.5 (readiness-driven quality-momentum, ATR stops, IV sizing, intraday timing, limit orders, TWAP, 10-factor readiness, zero external data deps, STRONG_NOW tier, regime detection)
- Git latest: `68d7eb4` on master

### Key infrastructure
- SSH key: `~/.openclaw/workspace/.ssh/id_stonkbot_root` (chmod 600)
- Finnhub key: `~/.openclaw/workspace/.secrets/finnhub.key` (chmod 600) — **no longer used**, kept for reference only. All data now from Alpaca SIP.
- Cloudflare Zone ID: `b2ef773ddf3d8f3711aef1584cd598be`
- `deploy.yml` syncs `website/sentiment/` and `website/history/` to web root.

### Automation on server
- Sentiment cron: every 15 min `*/15 * * * *` (re-enabled 2026-06-23, was hourly then commented out)
- History cron: daily `30 6 * * *` (HK time, after US market close)
- Freshness check: `/opt/stonk-ai/check_sentiment_freshness.py` every 15 min
- Watchlist: 20 symbols (was 15, expanded 2026-06-27). MAX_WATCHLIST_SIZE = 20.
- Watchlist feedback: `30 22 * * 1-5` via `watchlist_feedback.py`
- Signal enrichment: `30 5 * * 1-5` and `0 21 * * 1-5` via `signal_enricher.py` (full), 22:00/1:00/4:00 UTC weekdays (news-only), 12:30/20:30 UTC weekends
- Alpaca trade sync: `*/5 * * * *` via `sync_alpaca_trades.py`
- Signal refresh: every 15 min (24/7; refresh moved above market-open check so signals stay fresh overnight). Bot scan: every 5 min during US market hours.
- Nightly history reconstruct: `22:30 UTC` via `reconstruct_portfolio_history.py`
- Popup content generation: every 2 min (24/7). Narrative v2 deployed 2026-07-01 ~01:15 HKT via wrapper `generate_popup_content_narrative_v2.py`. Backup: `/opt/stonk-ai/backups/generate_popup_content-pre-narrative-v2-20260701-0114.tar.gz`. Revert: restore `generate_popup_content.py` from backup.
- **LLM narrative generator moved to VPS (2026-07-01):** `stonk-ai-llm-narrative.timer` runs every 15 min, generating 11 holdings + 20 watchlist narratives via `openrouter/moonshotai/kimi-k2.6` in 6-symbol batches. Writes `popup_narratives.json` and `watchlist_narratives_llm.json` to web root. No Mac dependency.
- Monitor: every 5 min during market hours via `monitor.py`
- **Comprehensive integrity monitor:** `/opt/stonk-ai/comprehensive_monitor.py` every 5 min market hours / 15 min after hours. Silent when healthy; Telegram alerts when degraded. **Added `check_llm_narrative_pipeline()` on 2026-07-01 to verify timer active, service not failed, LLM output files valid+fresh, and merged popups contain narrative fields.**
- Jeeves health alert cron: DISABLED (Einstein handles health checks now)

### UI decisions
- Filter bar: 6 one-row pill buttons (P&L% | Value | A-Z | All | Gainers | Losers).
- Desktop header/nav logo hidden; mobile keeps it.
- Live/stale indicator removed entirely.
- Tagline: "$100K AI trading experiment".
- Section header: "Bot vs. Market".
- Watchlist rich signals (sentiment/news) live in popups, not main table.
- Holdings rows: centered 112px sparklines, 30-day synthetic history, no 💡 icon.
- Hero portfolio value with animated count-up + cyan glow.
- Colored tier badges: NOW (cyan glow), WATCH (amber), MONITOR (gray).
- Left-border accent on holding cards (green/red by P&L) replacing full gradient.
- Staggered card fade-in (30ms per card).
- Market closed banner (auto-detects US ET hours).
- Minimal footer: Alpaca · Not investment advice · GitHub.
- Holdings popups redesigned (v94): clean trading brief — P&L hero, context-aware status line, simplified thesis, exit levels, signal chips. 10-factor chips: MOM · RSI · VOL · MACD · EMA · SEC · INT · OPT · RVOL · VWAP.
- Watchlist popups redesigned (v95): price + change, status line, simplified strategy, key levels, signal chips, 1 clickable news headline.
- Readiness chips show /100 and are tappable for tooltip explaining the score (v98).
- Watchlist tier tooltip redesigned (v99): compact 3-line tooltip instead of full-screen modal.
- Meet the Team section added to About tab as FAQ dropdown (v104): Jeeves, Einstein, how they work together, founder (anonymised).
- Trade log sync enhanced: bot writes structured rationale to `trade_rationale.json`, sync script merges + infers rationale for all trades (strategy tags: entry, cash_raise, rotation, profit_trim, stop_loss, profit_exit).
- Muted text contrast fixed to #7a8098 (WCAG AA).
- Unified header bar with hamburger menu + iOS-style tabs (v85 baseline).
- Popup content rewrite (v138–v144): dynamic data-driven narratives with "Smart Sniper" trader voice. Holdings: What It Is, Why We Own It, How It's Doing, Confidence, Catalyst, Risk. Watchlist: What It Is, Why On Watchlist, What Triggers Buy, Catalyst, Risk. New `watchlist_narratives.json`. All 130 symbols have custom `_COMPANY_NOTES` descriptions + 130 `_COMPANY_RISKS` entries.
- Popup redesign: colored left-border cards (cyan info, green/red P&L, amber catalyst, red risk), status pills, subtle tints.
- Watchlist mobile: 4 columns (hide AI score + RSI), company name 120px, cell padding 12px 6px.
- Tooltip: bottom sheet modal on mobile, centered on desktop. Hover tooltips removed from factor chips.
- Regime status indicator removed from header (clutter).
- FAQ rewritten: "What's the story behind this?" origin story, "How does the AI work?" cryptic (no thresholds). "Is this real money?" removed.
- Market indices fix: Dow ^DJI→DIA (Alpaca), NASDAQ ^IXIC→QQQ (Alpaca). Progress bars update dynamically.
- News display fix: loadStockSentiment rewritten to use `watchlist_narratives.json`/`popup_content.json` Alpaca news headline, with fallback to `signal_enrichment.json`. Sentiment badges removed (keyword-based unreliable). Headlines clickable with ↗.
- STRONG_NOW tier end-to-end: 🚀 cyan badge, popup chip, tooltip, count indicator. (🚀 emoji removed from tier labels per Howie preference.)
- **Confirmation count canonicalization (2026-07-01):** fixed mismatch where SOFI showed 4 confirmations in frontend chips but backend/LLM reported 3. Added `compute_confirmation_count()` in `readiness_score.py` as single source of truth; patched `generate_narratives_llm_batched.py` and `index.html` to derive count from `confirmations` dict; monitor (`comprehensive_monitor.py`) now flags drift. Backup: `/opt/stonk-ai/backups/confirmation-count-canonical-20260701-1517.tar.gz`.
- **10 confirmation chips end-to-end (2026-07-04):** backend `readiness_score.py` now excludes all 5 numeric scores (`momentum_score`, `intraday_score`, `options_score`, `relvol_score`, `vwap_score`) from `compute_confirmation_count()`; frontend `buildFactorChips()` renders MOM/RSI/VOL/MACD/EMA/SEC/INT/OPT/RVOL/VWAP (10 chips) in popups only; dynamic and LLM narrative generators updated from `/9` to `/10`. Source: `/opt/stonk-ai/agent-messages/jeeves/handover-from-einstein-20260704.md`.
- **PEAD fully removed (2026-07-04):** Alpaca news headline keyword matching for PEAD was noise, not signal. Removed from backend, frontend, dynamic narratives, and LLM narratives. Zero-external-deps policy maintained.
- **Risk cap loosening (2026-07-01):** raised `max_sector_pct` from 20% to 25% in `risk_engine.py`. Also fixed `paper_rebalancer.py` to be cash-aware, disabled over-diversification into 25+ tiny positions, and corrected post-rebalance cash reporting. Added a paper-only entry gate (`readiness>=70`, `confirmations>=3`, `above_ema`) so the paper simulation can deploy capital while the live bot keeps the stricter gate. Paper plan now shows 20 buys and cash down to ~5%. Position cap later refined (Einstein July 4): **12% for STRONG_NOW / 8% for other tiers**. Backup: `/opt/stonk-ai/backups/paper-rebalancer-paper-gate-20260701-2342.tar.gz`.

## Skills configured
- `macos-local-voice`: `yap` + `ffmpeg` in `~/.local/bin/`, default voice `Daniel`.
- `spotify-claw`: script at `~/.openclaw/scripts/spotify.py`, credentials in macOS Keychain, authenticated and working.
- **Zapier MCP**: installed via `mcporter`, connected to `mcp.zapier.com`. Apps enabled: Google Sheets (29), Spotify (17), GitHub (20), Google Calendar (14), Telegram (4), Microsoft 365 (29), Gmail (12). All authenticated and working.

## Agent communication
- **Einstein** is another OpenClaw agent working with Howie on StonkBOT.AI. Runs on `deepinfra/zai-org/GLM-5.2` (DeepInfra). Einstein's workspace is at `/root/.openclaw/workspace/` on the VPS.
- **Jeeves** is the primary bot working on StonkBOT.AI on the VPS (local Ollama: `ollama/kimi-k2.7-code:cloud` primary). Saves memory to `/opt/stonk-ai/jeeves-memory/`; auto-syncs daily at 3 AM HKT.
- **Jarvis** is a sibling OpenClaw agent but not reachable via `sessions_send` (not registered as named agent, session not in scope). User wants Jeeves ↔ Jarvis communication set up. Needs OpenClaw config change to register Jarvis as a named agent or adjust session visibility.
- **Two-way memory pipeline:**
  - Jeeves works → saves memory → 3 AM HKT syncs to VPS at `/opt/stonk-ai/jeeves-memory/` → 9 AM HKT Einstein reads
  - Einstein works → saves memory → 8 AM HKT pushes to VPS at `/opt/stonk-ai/einstein-memory/` → 8:30 AM HKT Jeeves reads
- Daily cron at 8:30 AM HKT reads Einstein's memory and syncs new info into my own MEMORY.md.
- **Message relay:** `/opt/stonk-ai/agent-messages/` on VPS — `einstein/` inbox for messages TO Einstein, `jeeves/` inbox for messages TO Jeeves. Jeeves writes handovers there (not in inbox). Format in README.md.
- **Einstein responsibilities:** 24/7 nightshift operator, daily maintenance checks (services, processes, permissions, disk, data freshness, portfolio sanity, website, memory sync).
- **Jeeves Auto-Dream:** Daily memory consolidation cron at 03:00 UTC (11:00 HKT), isolated agentTurn. First run: 2026-07-02. Created VPS memory maintenance script (`vps_memory_maintenance.py`, report-only) that runs at 3 AM HKT and writes analysis to `DREAMS.md`.

## Lessons learned
- Always verify deploy reached the server before assuming browser cache is the issue. Untracked server files can silently break `git pull` in GitHub Actions.
- **Risk cap evolution:** June 2026: 8% all tiers. June 28: LCID breach audit removed a temporary STRONG_NOW 12% override, enforcing 8% for all tiers. July 1: raised `max_sector_pct` 20% → 25%. Latest state (per Einstein, July 4): **12% max position for STRONG_NOW, 8% for NOW/WATCH/MONITOR**, 25% sector cap. `risk_engine.py` is source of truth.
- LCID position breached the cap — caught by Gemini audit. Concentration trim trigger lowered to 1.0× and temporary STRONG_NOW 12% override was removed (returned to 8% for all tiers at that time).
- `/tmp/bt_stress.py` couldn't import `alpaca_data` from `/opt/stonk-ai/` — Python path issue. Run from correct dir or add to `sys.path`.
- Yahoo Finance and Finnhub free historical candles are unreliable/blocked on the VPS; keep fallback synthetic generation and plan for a paid/reliable source.
- Always chown JSON files to stonkai after manual root writes — bot can't write to root-owned files.
- `fetch_ai_watchlist.py` runs independently and can clobber brain-managed watchlist if not patched to enrich instead of replace.
- Yahoo Finance 429 rate-limits kick in fast when fetching 75 symbols sequentially — synthetic bar fallback from Alpaca real-time quotes is the fix.
- Alpaca data API returns 401 on IEX feed for some symbols on free/paper tier — paper keys have limited data access.
- Sub-agent output limits: large builds can exceed sub-agent output budget — handle directly when they fail.
- JS patching via Python string replacement is fragile — always verify exact string exists before replacing.
- Counts derived from the same dict can still drift if one consumer uses a stored integer and another recomputes from flags. Keep a single `compute_*` helper and use it everywhere (backend, LLM prompt, frontend chips, monitor).
- SSH heredoc quoting is unreliable for Python scripts with nested quotes — write locally, scp, then run.
- Large HTML structural changes via string replacement are risky — can silently swallow adjacent elements. Make changes in smaller chunks with backups, test on real devices early.
- Backtest lookahead bias: same-day close for signal + execution = no T+1 delay. Must use T+1 (signal from day T close, execute at T+1 open).
- Volume confirmation was NEGATIVELY correlated with wins (-0.231) — volume spikes on drops = selling pressure, not bullish.
- `@staticmethod` decorators can get eaten by regex patches — always verify after patching.
- Alpaca v2 snapshots: symbols at TOP LEVEL, not nested under "snapshots" key.
- Alpaca bars API paginates: 1000 bars/page max → batch 15 symbols.
- Backtest slippage: `/tmp/bt_stress.py` couldn't import `alpaca_data` from `/opt/stonk-ai/` — Python path issue. Run from correct dir or add to sys.path.
- Gemini assessment: backtest→live gap can be caused by lookahead bias or regime shift, not just overfitting. Walk-forward validation is the answer.
- Numeric scores must be explicitly excluded from confirmation counts; leaving them in inflates counts and causes backend/frontend/monitor drift.
- Canonical data paths matter: monitor was checking a backend copy of `ai_watchlist_live.json` while the frontend read from webroot. Use the same path the consumer uses.
- Scheduler status files should be written every run, not only when active, or monitors will false-alert on weekends/idle periods.
- Case-insensitive mode matching prevents stale-status alerts when "weekend" vs "Weekend" strings drift.
- Broken stub code (e.g. `generate_risk(`) will eventually surface as a syntax error; remove or finish stubs immediately, don't leave them in place.
- Broken function stubs (`def generate_risk(`) can survive in production if the error only manifests when the code path is exercised — positive test coverage matters.
- Numeric scores in confirmation counts inflate counts if not explicitly excluded — always audit the exclude set when adding new score fields.
- Monitor should check canonical file paths, not whatever is convenient in the backend dir.
- Scheduler must write status files even when skipping work, or monitors will false-positive on missing state.
- Case-sensitive string matching in monitors is a bug waiting to happen — always normalize.
- Cash-only guards must be enforced at order submission time, not just in sizing logic, because `buying_power` can exceed `cash`.
- IV summary migration must update every scalar consumer (e.g. `trading_bot.py` sizing); otherwise a dict-vs-int comparison crashes the bot.
- Thesis-exit rules need a minimum hold period; otherwise positions can be bought and sold within the same cycle on noisy signals.

## Daily memory task
- Distill each day's chats into `memory/YYYY-MM-DD.md`.
- Periodically update this file with durable decisions, preferences, and lessons.

## Monday June 29 scheduled crons (completed)
- 13:25 UTC (9:25 AM ET): Pre-market generation (all data generators, results to Telegram)
- 13:35 UTC (9:35 AM ET): Intraday pipeline test (verify live 15Min bars, VWAP stops, options)
- Both were one-shot; deleted after run.

## Backups on server
- `/opt/stonk-ai/backups/comprehensive-20260701-0340.tar.gz` — 51 MB, post-LLM-VPS-migration + health-monitor update
- `/opt/stonk-ai/backups/2026-07-04-einstein/` — 14 files, full backend/frontend/narrative backup with manifest
- `/opt/stonk-ai/backups/pre-brain-rewrite-20260626/` — before brain upgrade
- `/opt/stonk-ai/backups/pre-visual-upgrade-20260626/` — before visual upgrade
- `/opt/stonk-ai/backups/comprehensive-20260626-0225/` — full backup (2.7MB)
- `/opt/stonk-ai/backups/comprehensive-20260627-0550.tar.gz` — 49MB, pre-Phase 2
- `/opt/stonk-ai/backups/comprehensive-20260627-0905.tar.gz` — 49MB, post-Phase 2 + website overhaul + universe expansion
- `/opt/stonk-ai/backups/comprehensive-20260628-0650.tar.gz` — after ATR stops + 8% cap fix
- `/opt/stonk-ai/backups/comprehensive-20260628-0830.tar.gz` — 498KB, 203 files, after all June 28 changes (zero external deps, narrative rewrite, factor fixes)
- `/opt/stonk-ai/backups/risk-fix-20260628/` — individual file backups before each June 28 patch
- `/opt/stonk-ai/backups/pre-factor-fix-20260628/` — 7 files backed up before factor-system fixes
- `/opt/stonk-ai/backups/pre-sip-migration-20260627/` — before Alpaca SIP migration
- `/opt/stonk-ai/backups/pre-skeleton-frosted-20260626/index.html` — v108 state
- Pre-upgrade backups: signal_engine, risk_engine, trading_bot, fetch_data_simple, fetch_ai_watchlist, generate_popup, signal_enricher, dwm
- Multiple per-component backups (signal_engine, risk_engine, trading_bot, fetch_data_simple, etc.)

## Trading bot architecture (v2.5 + Phase 2 + Optimization)
- `alpaca_data.py` — unified data hub (snapshots, daily/intraday bars, news, options IV, market clock, quotes). ALL data flows through this. **Zero external data dependencies** — Yahoo, Finnhub, Polygon, yfinance, synthetic bars all removed. `feed=sip` added to ALL endpoints; snapshot/quote endpoints were missing it, causing DOCN and others to return no price data.
- `signal_engine.py` — multi-factor scoring + readiness score + 10 confirmations + mean reversion signals + enhanced regime (yield curve SHY/TLT, credit spreads LQD/HYG, market breadth). REGIME_SYMBOLS: SPY, QQQ, VIXY, SHY, TLT, LQD, HYG (7 total). Min bars threshold lowered 50→20; MR merge preserves momentum fields.
- `readiness_score.py` — 10-factor composite: signal 20%, sector 30%, EMA 12%, RSI 10%, intraday 10%, MACD 8%, volume 5%, options IV 5%, relative volume 5%, VWAP 5%. Backtest-driven, then collinearity rebalanced. Volume NEGATIVELY correlated with wins (-0.231). EMA strongest predictor (+0.593).
- `generate_popup_content.py` / `generate_popup_content_v3_full.py` — generates 24/7, dynamic narratives (not templates), VWAP stop + Alpaca news + options IV + `sources` provenance dict in popups. `earnings_confirmed`/`PEAD` removed 2026-07-04.
- `trading_bot.py` — entry queue by readiness, thesis exits, rotation, cash raise, tradability pre-filter, failed buy tracking, structured rationale, intraday entry timing (5-min bars), IV sizing, limit orders at midpoint, TWAP splitting (dynamic 0.1% ADV threshold). **Critical fix:** `self._positions` + `_exit_position()` added (was missing, would've crashed on market open). Sizing multipliers: 2.0× readiness ≥ 80, 1.0× readiness 75–79, 0.5× readiness 72–74, blocked below 72. **Only STRONG_NOW tier is tradeable; NOW/WATCH/MONITOR are non-trading.** Rejects mean reversion entries. Marketable limit at ask for STRONG_NOW (aggressive fill). NOW: midpoint limit + 5s timeout → marketable limit (ask + 1¢), not market order.
- `risk_engine.py` — ATR hard stop 1.5× (clamped 3-8%), ATR trailing 2.0× (clamped 3-10%), VWAP stops (-2% below), VWAP-enhanced trailing, trim +25%, exit +50%, **12% max position for STRONG_NOW / 8% for other tiers**, 25% sector cap (raised from 20%), dynamic cash floor (10% base → 25% deep DD ladder), entry cash buffer 12%, check_cash_raise(), check_rotation() with 2h cooldown, halt at -10% DD + trim weakest 25% + 3-day pause. Added `allow_margin: bool = False` (2026-07-02); trading bot enforces cash-only ordering at submit time.
- `regime_detector.py` (NEW) — 3 states: RISK_ON / RISK_OFF / CRISIS. Triggers: credit spreads (LQD/HYG >1.45), SPY vs 50-day EMA, VIXY spikes, yield curve. RISK_OFF: max 4% position, 15% cash floor, STRONG_NOW only. CRISIS: max 4%, 30% cash floor, no new entries, halve positions. Current: RISK_OFF.
- `intraday_confirm.py` — 5-min bar entry timing (green=go, mixed=80% size, all red=skip)
- `mean_reversion_signal.py` — oversold bounce candidates (RSI<35, >5% below EMA, vol spike), capped at 0.75x size
- `sync_alpaca_trades.py` v2 — syncs trades every 5 min, merges rationale, infers historical rationale
- `dynamic_watchlist_manager.py` — tiers: STRONG_NOW ≥78 (2.0× sizing, 12% cap, **only tradeable tier**), NOW ≥72 (1.0×, 8% cap, **non-trading building strength**), WATCH ≥55, MONITOR <55. Max 20 in watchlist; hard-truncates to `MAX_WATCHLIST_SIZE` before writing (2026-07-02). Backend tiers map to frontend display tiers: PRIME / BUILDING / WATCHING / TRACKING (2026-07-04).
- `fetch_ai_watchlist.py` — enriches watchlist with live prices (patched, RSI from signals.json + hub)
- `fetch_data_simple.py` — uses data hub, VWAP + intraday in portfolio_data
- `fetch_market_indices.py` — hub + regime data (VIXY, yield curve, credit spreads). Dow → DIA, NASDAQ → QQQ (Alpaca ETFs, no Yahoo).
- `watchlist_feedback.py` — tracks non-bought watchlist outcomes
- `backtest.py` — historical replay. T+1 execution (no lookahead bias). Final: Sharpe 1.30, return +102%, max DD -31.7%, 1,935 trades, win rate 53.7%, alpha +0.03%, beta 1.07. Walk-forward validated: +18.5% out-of-sample, alpha +12% annualized.
- `performance_attribution.py` — factor decomposition, per-trade journal, CSV export. 7 factor correlations.
- `stress_test.py` — correlation matrix, VaR (parametric + historical), 4 scenario simulations, concentration risk
- `monitor.py` — service checks, data freshness, kill switch (-15% daily DD), disk, rogue processes, permissions, Telegram alerts
- Entry gate: `readiness >= 77` AND `confirmation_count >= 5` AND `above_ema = True`. STRONG_NOW ≥78 gets 2.0× sizing + 12% cap; NOW 72–77 gets 1.0× + 8% cap.
- Exit logic: readiness <40 = immediate exit (thesis broken). Readiness 40-55 = exit after min hold (1 day, was 5). Min hold 1 day (was 10). Flat exit 5 days (was 10). Hard -5% cut exits immediately regardless of hold period.
- Universe: 130 symbols across 15 sectors. PSTG not tradable on Alpaca — auto-skips.
- Currently paper trading (Alpaca PK... keys). Live keys needed for real trading.
- **Alpaca 403 sell bug FIXED (2026-06-29 ~17:42 UTC):** Root cause was duplicate limit sell orders when a prior stop exit sat unfilled above a falling market. Cancelled stuck AAPL order, added `list_orders(status='open')` dedup guard in `trading_bot.py`, and forced sell orders to market orders for guaranteed stop fills. Service restarted.
- Alpaca paid data (Unlimited plan $9/mo): SIP consolidated feed, options snapshots, news API.
- Phase 2 audit: 53/53 ✅. Website audit: 77/77 ✅.
- Volume confirmation is a CONTRARIAN indicator (-0.231 corr). Up-volume vs down-volume distinction added.
- Options IV data gap: 27/130 symbols have IV.
- Beta 1.07 (down from 1.34 after T+1 fix + tuning). Target <1.2 — achieved.
- All systemd services run as `stonkai` user. Check for rogue root processes.
- Playwright installed on VPS for automated visual testing.
- 14 redundant files cleaned up to `/opt/stonk-ai/backups/redundant-20260626/`.
- Health monitoring consolidated: 4 redundant check scripts merged into one source of truth. `vps_check.py` reads existing `health_status.json` + `monitor_status.json` instead of re-checking; OpenClaw cron every 10 min; Telegram alerts only when broken, silent when healthy; weekend-aware (skips freshness/content checks when market closed); data-integrity checks for factor denominator (/9 vs /8) and ghost `earnings_confirmed` field.
- **Comprehensive Integrity Monitor (2026-06-29 → 2026-07-04):** `/opt/stonk-ai/comprehensive_monitor.py` runs every 5 min market hours / 15 min after hours. Checks services, file freshness, extended-hours prices, universe name coverage, shadow `COMPANY_NAMES`, signal-watchlist alignment, factor confirmation integrity, popup/narrative alignment, dead-code imports, portfolio cap sanity, HTML currency. Silent + exit 0 when healthy; Telegram alert on degradation. **July 4 fixes:** canonical path for `ai_watchlist_live.json` in webroot, `/10` chip-count check, LLM scheduler writes `.llm_narrative_status` every run, case-insensitive market-mode matching, heartbeat tracking added for watchlist/IV/liquidity jobs. Current status: 0 issues, 0 warnings.
- Gemini strategy assessment: 3 rounds. Confirmed ready for live trading. Flagged: survivorship bias, slippage underestimation, curve-fitting risk. Most addressed.
- **Data provenance audit (2026-06-29):** Every popup field now carries a `sources` dict mapping to Alpaca origin (`Alpaca bars API`, `Alpaca news API`, `Alpaca options API`, `StonkBOT signal engine`). Dead code audit forbids `yfinance`, `finnhub`, `polygon`, `yahoo_finance` imports. Universe name coverage guardrail asserts `DEFAULT_UNIVERSE == COMPANY_NAMES.keys()`.

## Backtest results (final, T+1 fixed + tuned)
| Metric | Original (lookahead) | T+1 Fixed | T+1 Tuned (final) |
|---|---|---|---|
| Sharpe | 1.26 | 0.67 | **1.30** |
| Return | +65.2% | +33.5% | **+102.0%** |
| Max DD | -26.9% | -22.9% | **-31.7%** |
| Win rate | 54.1% | 52.6% | **53.7%** |
| Alpha | — | -0.01% | **+0.03%** |
| Beta | 1.34 | 0.87 | **1.07** |
| Trades | 38 | 2,441 | **1,935** |

Walk-forward: Train 2024 +33.8%, Test 2025-26 +18.5%, alpha +12% annualized. Edge confirmed real.

**Note (2026-06-30):** These results used `adjustment=raw` bars. The Premium Data audit on `adjustment=all` (split/dividend-adjusted) revised performance to +25.5% / Sharpe 0.52 / alpha -0.0155%. See "Backtest on adjusted bars" below.

## Einstein sync — 2026-06-30
Source: `/opt/stonk-ai/einstein-memory/2026-06-30.md`

### Signals stale overnight — FIXED
- `signals.json` was 500+ minutes stale.
- Root cause: `maybe_refresh_signals()` only ran inside `run_cycle()`, which early-exits when market is closed.
- Fix: moved refresh above market-open check in main loop. Signals now update every 15 min regardless of hours.
- Restarted `stonk-ai.service`; fresh signals at 08:19 UTC and 10:25 UTC.

### Trading bot bottom-guard patches — LOADED
- 403 duplicate-sell guard + market-order sell wrapper were placed *after* `if __name__ == "__main__"`, so they never executed.
- Fix: moved both patches above the `if __name__` block so they run at import time.
- Added `exc_info=True` to `_execute_sell` error logging for full tracebacks.

### Extended-hours UI data — FIXED
- Holdings popups had zero extended-hours data; watchlist popups blank after-hours in the morning.
- Holdings fix: `generate_popup_content.py` now copies pre-market/after-hours fields from `ai_watchlist_live.json` into popup narratives.
- Watchlist fix: `get_extended_hours_bars()` queried today's not-yet-opened 20:00-23:59 UTC window; now pulls yesterday's after-hours bars when current UTC < 20:00.
- Result: watchlist 7/20 with after-hours, 9/20 with pre-market; holdings 5/11 with both.

### Design decision: no synthetic after-hours data
- Alpaca SIP only returns bars for actual trades; zero volume = no bar.
- Fintech apps use paid aggregators that interpolate gaps.
- Consensus: keep honest blanks (`—` or hide field when missing). Stay zero-external-deps.

### Stuck orders
- Checked Alpaca paper account: 0 open orders. Prior stuck AAPL limit sell auto-cleared by Alpaca at market close.

## Next steps (from Einstein's handover)
- Monday June 29 9:25 AM ET: pre-market generation test + 9:35 AM ET intraday pipeline test (one-shot crons)
- If intraday pipeline works: switch to live Alpaca keys
- Paper-trade 1-2 weeks to verify real slippage vs 8bps model
- Dead man's switch (external monitor on separate machine)
- Phased capital: start $10-20K, not full $100K
- API rate limit stress test
- 200+ live trades for statistical significance
- Weekly performance_attribution.py runs
- Monthly backtest vs live performance comparison

## Entry gate tightening (2026-06-30)

### Performance attribution finding
- Ran `performance_attribution.py` on 50 live closed trades.
- Factor correlations with P&L:
  - `above_ema`: **+0.572** (strongest predictor)
  - `confirmation_count`: **+0.489**
  - `readiness_score`: **+0.371**
  - `macd_turning`: **+0.347**
  - `sector_strong`: **+0.238**
  - `volume_confirmed`: -0.084 (negative, confirms earlier finding)
  - `rsi_neutral_not_overbought`: -0.002 (noise)

### Filter simulation on live trades
| Filter | Trades | Win rate | Avg P&L | Expectancy |
|---|---|---|---|---|
| All trades | 50 | 40.0% | -0.88% | **-0.88%** |
| Readiness ≥ 75 | 12 | 75.0% | +3.57% | **+3.57%** |
| Confirmations ≥ 4 | 8 | 87.5% | +5.56% | **+5.56%** |
| Readiness ≥ 75 + conf ≥ 4 | 8 | 87.5% | +5.56% | **+5.56%** |

### Change applied
- Tightened entry gate in `readiness_score.py`:
  - `ENTRY_READINESS_MIN = 75.0` (was 72.0)
  - `ENTRY_MIN_CONFIRMATIONS = 4` (was 2)
  - Added `above_ema = True` requirement
- Patched `trading_bot.py` to rely on `entry_eligible` instead of re-checking readiness >= 72.
- Updated dead-money exit threshold from 72 to 75.
- Updated `generate_popup_content.py` narrative threshold references to 75.
- Bot restarted in paper mode; confirmed startup message: `Entry: readiness >= 75 AND >= 4 confirmations AND above_ema`.
- Current entry-eligible momentum signals: 6 (AMD, UPST, SOFI, AMAT, TER, LRCX), all above_ema=True.

### Backups
- `/opt/stonk-ai/backups/entry-gate-tighten-20260630-2327/`

### Monitoring plan
- Paper-trade with tightened gate for 50-100 trades.
- Do NOT switch to live keys until the new gate proves positive expectancy.
- Weekly review via `performance_attribution.py`.

## Premium Data audit and measurement tools (2026-06-30)

### Backtest on adjusted bars
- Switched all Alpaca bar fetches from `adjustment=raw` to `adjustment=all`.
- Re-ran `backtest.py` over 2024-01-01 → 2026-06-30.
- **Result:** the previous +102% / Sharpe 1.30 result was inflated by split/dividend artifacts.

| Metric | Raw bars (old) | Adjusted bars (new) |
|---|---|---|
| Total return | +102.0% | **+25.5%** |
| Sharpe | 1.30 | **0.52** |
| Max drawdown | -31.7% | **-31.3%** |
| Win rate | 53.7% | **52.1%** |
| Alpha | +0.03% | **-0.0155%** |
| Beta | 1.07 | **1.08** |
| Trades | 1,935 | **1,599** |

- **Decision:** do NOT switch to live Alpaca keys until strategy edge is rebuilt or verified with a longer live/paper track record.

### IV term structure + rank module
- Created `/opt/stonk-ai/options_iv_analytics.py`.
- Uses Alpaca `v1beta1/options/snapshots/{symbol}?feed=opra` with pagination (full chain spans 0–170 DTE).
- Outputs `iv_30d`, `iv_60d`, `iv_90d`, `iv_120d`, `iv_rank`, `iv_skew`.
- Added TTL caches: option snapshots 5 min, IV summary 1 min.
- Patched `readiness_score.py` to accept IV summary dict and use `iv_rank` for scoring; falls back to absolute 30d IV.
- Patched `signal_engine.py` to load pre-computed summaries from `/opt/stonk-ai/iv_summaries.json`.
- Created `/opt/stonk-ai/update_iv_summaries.py` cron script; ~2 min for 20 symbols; updates history for rank calculation.

### Slippage / liquidity model
- Created `/opt/stonk-ai/execution_analytics.py` using 1Min quote history from Alpaca Premium Data.
- Computes half-spread, ADV, square-root market impact, total expected slippage in bps.
- Created `/opt/stonk-ai/daily_liquidity_report.py` cron; writes `/opt/stonk-ai/liquidity_report.json`.
- **Current watchlist findings (2026-06-30):**
  - Most spreads 2–10 bps.
  - **LMND: 35 bps half-spread** → flagged as liquidity warning.
  - EXPE: 19.5 bps → near warning threshold.
  - This is well above the 8 bps slippage assumption used in the model.

### Files changed on VPS
- `/opt/stonk-ai/alpaca_data.py` — all `adjustment=raw` → `all`
- `/opt/stonk-ai/fetch_ai_watchlist.py` — all `adjustment=raw` → `all`
- `/opt/stonk-ai/intraday_confirm.py` — all `adjustment=raw` → `all`
- `/opt/stonk-ai/readiness_score.py` — IV summary dict support
- `/opt/stonk-ai/signal_engine.py` — load pre-computed IV summaries
- `/opt/stonk-ai/options_iv_analytics.py` — new module
- `/opt/stonk-ai/update_iv_summaries.py` — new cron script
- `/opt/stonk-ai/execution_analytics.py` — new module
- `/opt/stonk-ai/daily_liquidity_report.py` — new cron script

### Backups
- `/opt/stonk-ai/backups/premium-data-phase1-20260630-2214/`
- `/opt/stonk-ai/backups/premium-data-phase2-20260630-2228/`

### Honest next steps
1. Do not go live with current strategy; alpha is negative on adjusted data.
2. Consider redesigning the signal stack or adding a real edge before risking capital.
3. Keep running measurement tools (IV rank, liquidity report) to build data for later.
4. If strategy is rebuilt, re-run backtest on adjusted bars before any live switch.

## July 4 weekend cleanup (Einstein)

Source: `/opt/stonk-ai/agent-messages/jeeves/handover-from-einstein-20260704.md`

### 10 confirmation chips end-to-end
Connected all 10 confirmation chips from Alpaca data → backend → frontend popups:

**Backend source of truth (`readiness_score.py`):**
- `compute_confirmation_count()` now excludes all 5 numeric scores: `momentum_score, intraday_score, options_score, relvol_score, vwap_score`
- Was only excluding 3 → numeric scores were inflating confirmation counts
- 14-key confirmations dict: 5 booleans + 6 scores + `rsi_signal` + `momentum_score`
- Entry gate: `readiness >= 75 && confirmation_count >= 4 && above_ema`

**Readiness composition (10-factor, v2.5):**
- signal 20%, sector 30%, EMA 12%, RSI 10%, intraday 10%, MACD 8%, volume 5%, options IV 5%, relative volume 5%, VWAP 5%

**Sizing multipliers by readiness band:**
- ≥80 → 3.0×
- 75–79 → 1.5×
- 72–74 → 0.5×
- <72 → blocked

**Position caps (v2.5):**
- STRONG_NOW (readiness ≥78): 12% max position
- NOW / WATCH / MONITOR: 8% max position
- Sector cap: 25%

**Frontend (`index.html`):** `buildFactorChips()` renders 10 chips in popups only — MOM, RSI, VOL, MACD, EMA, SEC, INT, OPT, RVOL, VWAP. Watchlist table rows stay clean.
- Dynamic + LLM narratives updated from `/9` to `/10`.

### PEAD fully removed
- Alpaca news headline keyword matching for earnings/PEAD was noise, not signal.
- Removed from `readiness_score.py`, `index.html`, `generate_popup_content_v3_full.py`, `generate_narratives_llm_batched.py`, and regenerated `signals.json`/`ai_watchlist_live.json`.
- Orphaned `_EARNINGS_RE` regex in `generate_narratives_llm_batched.py` (~line 173) remains; safe to remove later.

### Tier alignment across pipeline
- Backend tiers: `STRONG_NOW / NOW / WATCH / MONITOR`.
- Frontend display: `PRIME / BUILDING / WATCHING / TRACKING`.
- Single source: `ai_watchlist_live.json` carries both `signal_tier` and `display_tier`.

### Monitor alert fixes (was flooding phone)
| Alert | Root Cause | Fix |
|---|---|---|
| `index.html missing /9` | PEAD removal changed chip count to `/10` | Updated monitor check to `/10` |
| `ai_watchlist_live.json stale` | Monitor checked backend path, canonical file is in webroot | Path patched to `WEB_DIR` |
| `.llm_narrative_status missing` | Scheduler skipped weekends and never wrote status | Scheduler writes status every run |
| `LLM narratives stale` | Missing status + case-sensitive mode matching | Status file + case-insensitive matching + threshold logic fixed |
| 126 `confirmation_count` mismatches | `compute_confirmation_count` excluded only 3 of 5 numeric scores | Added `relvol_score` + `vwap_score` to exclude set; regenerated 124 signals |
| `generate_risk(` syntax error | Broken stub left in popup generator | Removed stub; regenerated popup content |

**Current status:** 0 issues, 0 warnings.

### Stack trace detection improvement (2026-07-04)
- Enhanced `comprehensive_monitor.py` to detect all stack traces across services by removing restrictive grep pattern, reducing sampling interval from 60 min to 5 min, and adding `systemctl` fallback for failed services.
- Detects known failure modes: signal-engine crashes, malformed portfolio errors, Alpaca `Insufficient qty` rejections, dict-vs-int comparison errors in popup generator.

### Frontend performance fixes
- Removed rogue 30s timer that reset holdings filters.
- Deduped identical data updates that caused flickering.
- Note: pre-existing orphan `} else {` in DOM ready block (~line 5987 in `index.html`) still present; browsers tolerate it but it's fragile for future edits.

### Monday checklist (from handover)
- Live market verification at open.
- Factor correlation analysis after 20+ instrumented trades.
- Options skew validation after 50+ trades.

### Gemini assessment & July 4 live-performance patch
- **Source:** Gemini analysis shared by Howie (2026-07-04).
- **Finding:** Live expectancy was negative: E = (0.342 × 3.87%) − (0.658 × 4.47%) = **−1.6% per trade**. Win rate 34% vs backtest 54%; average loser larger than winner.
- **Rule conflict:** 5-day minimum hold was clashing with −5% hard cut and ATR stops.
- **Collinearity:** `volume` and `rel_volume` used the exact same `recent_vol / avg_vol` ratio.

**Patches applied 2026-07-04:**
- `trading_bot.py`:
  - Min hold reduced 5 days → 1 day for readiness-based exits (thesis broken still immediate)
  - Flat exit reduced 10 days → 5 days
  - Fixed hard −5% cut bug: it was only checking the last symbol in the flat-exit loop; now loops over all positions
  - Tightened paper fallback entry gate to `readiness >= 77` and `>= 5 confirmations`
  - Reduced STRONG_NOW sizing 3.0× → 2.0× (upper NOW 1.5× → 1.0×)
  - Rejects mean reversion `strategy_type` for entries
  - Updated startup logs and trade reasons to `/10` confirmations
  - **Tier Option B (2026-07-04 16:39 HKT):** only STRONG_NOW tier is tradeable; NOW/WATCH/MONITOR are non-trading. `_is_entry_eligible_for_mode` requires `tier == "STRONG_NOW"`.
- `readiness_score.py`:
  - Entry gate tightened: `ENTRY_READINESS_MIN` 75 → 77; `ENTRY_MIN_CONFIRMATIONS` 4 → 5
  - Removed `rel_volume` weight collinearity (`WEIGHT_REL_VOLUME = 0.00`); kept as boolean chip only
  - Fixed stale header comments to match actual 10-factor weights, tiers, and gate
  - Fixed tier reason text from `/8` to `/10` confirmations
  - **Tier Option B:** `entry_eligible` only set for `tier == "STRONG_NOW"`; NOW tier never gets `entry_eligible`. Tier reason updated to say "Non-trading — building strength".
- `signal_engine.py`:
  - Mean reversion merge preserves momentum `entry_eligible`; adds `entry_eligible_mr` and `has_mean_reversion_signal`
  - Debug log updated `/5` → `/10` confirmations
- `mean_reversion_signal.py`:
  - Mean reversion no longer sets `entry_eligible=True` — watch-only bounce candidate
  - Restored `readiness_score = reversion_score` which had been accidentally removed and caused `name 'readiness_score' is not defined`
- `generate_popup_content_v3_full.py`:
  - Watchlist narratives updated to 77/5 gate
  - Mean reversion labeled as bounce candidate, not entry-ready
  - IV/vol type checks fixed to handle dict-valued `options_implied_vol`
  - **Tier Option B:** NOW tier watchlist popups explicitly say "Non-trading — needs X points to reach STRONG_NOW / PRIME entry tier" and "To become tradeable: reach STRONG_NOW / PRIME tier at readiness 78..."

**End-to-end verification (2026-07-04 08:43 UTC):**
- Bot completed full signal refresh after Tier Option B patch
- Entry-eligible symbols (STRONG_NOW only): `UBER` (79.9, 6/10 conf), `SNOW` (78.5, 6/10 conf)
- NOW tier symbols correctly `entry_eligible=False`: UPST, PINS, MDB, SOFI, NET, HD, NKE, DDOG, SPOT, ABNB, SHOP, PATH, GTLB
- Watchlist popups now say "NOW / BUILDING tier... Non-trading — needs ... to reach STRONG_NOW / PRIME entry tier"

### Backups
- `/opt/stonk-ai/backups/2026-07-04-einstein/` — 14 files, full backend/frontend/narrative backup with manifest.
- `/opt/stonk-ai/backups/end-to-end-align-20260704-080417/` — files modified during Gemini alignment patch.
- `/opt/stonk-ai/backups/patch-gemini-fixes-20260704-074336/` — initial trading_bot/readiness/signal/risk backup.

## 2026-07-02 Alpha Config Patches (Einstein)

Source: `/root/.openclaw/workspace/MEMORY.md` (Einstein's canonical memory)

### Problem
Bot was tracking S&P 500 too closely (22 positions, ~$4K average, 63.5% capital in NOW tier, only 25.3% in STRONG_NOW). Portfolio looked like a momentum ETF, not an alpha strategy.

### Patches applied
1. **STRONG_NOW cap 12%** (was 8% for all tiers) — `_tier_max_position_pct()` returns 0.12 for STRONG_NOW, 0.08 for others.
2. **Readiness sizing multiplier:** ≥80 readiness = 3.0×, 75-79 = 1.5×, 72-74 = 0.5×, <72 = 0× (blocked).
3. **Position cap 12** — `entry_candidates` trimmed to top 12 before execution.
4. **Min hold 5 days** (was 10) — cut losers faster.
5. **Flat exit 5 days** — dead money exits faster (readiness threshold lowered from 75 to 70).
6. **Hard -5% cut** — any position down -5% exits immediately regardless of hold period.
7. **Cash gate** — if cash <= 0, all new entries blocked immediately.
8. **`max(1, 0)` fix** — added `if multiplier <= 0: continue` in RISK_OFF and RISK_ON entry paths so 0 multiplier actually blocks instead of becoming 1.
9. **RISK_OFF = STRONG_NOW only** — mean reversion mode disabled. RISK_OFF only allows STRONG_NOW momentum entries with readiness ≥82.
10. **Diversification entries** — `_add_diversification_entries()` exists but is not called in current `run_cycle()` (already disabled).
11. **`fetch_data_simple.py`** — refresh cycle 60s → 5s during market hours (near-live price updates). Also patched with split auto-detection.
12. **Frontend polling** — holdings + watchlist refresh 30s → 5s to match backend.

### Services restarted
- `stonk-ai.service` — active, new alpha logic loaded.
- `stonk-ai-data.service` — active, 5s refresh rate.

### Expected behavior
- Position count drifts from 22 down to ~8-12 as weak names are trimmed.
- Only STRONG_NOW and upper-NOW entries make it through.
- Losers cut in 5 days or at -5%.
- Cash gate prevents negative balance.

### Risk
- Aggressive concentration. If STRONG_NOW is wrong, drawdowns are larger.
- 5s data refresh increases Alpaca API load (~60 calls/min, still well under 200/min limit).
- Paper-trading experiment — appropriate venue for testing aggressive configs.

## 2026-07-02 Bot aligned to Watchlist (Einstein)

### Problem
Bot held 21 positions across the full 130-symbol universe, while the watchlist (`ai_watchlist_live.json`) only curated the top 20. Holdings popups and watchlist popups had different signal sources.

### Fix
1. `dynamic_watchlist_manager.py` — added `watchlist[]` array alongside existing `prices` dict so JSON has both keyed and indexed formats.
2. `trading_bot.py` — new `_load_watchlist_symbols()` reads `ai_watchlist_live.json`; filters `top_signals` to **watchlist-only** before entry decisions. Falls back to full universe if watchlist is >15 min stale.

### Result
- Bot now only enters positions from the 20 curated watchlist symbols.
- No more off-watchlist drift.
- **End-to-end data flow:** Signal engine → Watchlist manager (top 20) → Trading bot (filtered) → Portfolio/popup merge → Website (holdings + watchlist popups share same underlying signals).

## 2026-07-02 CRWD Stock Split Auto-Detection (Einstein)

### Issue
CRWD executed a 4-for-1 stock split (Jul 2 2026 ex-date). Alpaca positions API lagged, still showing `qty=1 avg=$775.50` instead of `qty=4 avg=$193.88`. Website reported fake **-75% P&L**.

### Immediate fix
Patched `portfolio_data.json`, `signals.json`, and `popup_content.json` to split-adjust CRWD values (qty→4, avg→193.87, stops, daily bars).

### Code patches
1. `trading_bot.py` — added `PortfolioDataStore._detect_and_fix_splits(positions_data, snaps)` which auto-detects splits by comparing `avg_entry / current_price` ratio. When a clean integer ratio (2-10) is found, it adjusts qty, avg_entry, unrealized P&L, and **also adjusts snapshot historical bars** (`prev_close`, `daily_vwap`, `hardStop`, etc.) so enrichment doesn't overwrite with pre-split values.
2. `split_guardian.py` — standalone daily checker at `/opt/stonk-ai/split_guardian.py`. Runs via cron at 00:30 UTC (08:30 HKT) to warn if any positions show unprocessed splits before the bot catches them.

### Prevention
Bot now auto-corrects on every cycle, and guardian alerts if any slip through. No manual intervention needed for future splits.

## 2026-07-02 Duplicate-Sell + Alert Cleanup (Einstein)

### Problem
Bot was stuck in a 403 Forbidden sell loop on AAPL because a prior limit sell order sat unfilled above the falling market. Alpaca rejected duplicate sells with `insufficient qty available` (code 40310000).

### Fixes applied
- Cancelled stale AAPL sell order via Alpaca API.
- `trading_bot.py` 403 guard now **blocks** sells if the `list_orders` API check fails (fail-closed instead of fall-through).
- Belt-and-suspenders `_execute_sell()` — added direct open-order query before `submit_order`, skipping if an open sell exists.
- Removed old `stonk_health_check.py` cron that was flooding alerts about watchlist size and cash < 5% — superseded by `comprehensive_monitor.py`.
- Services restarted.

### Remaining risk
`fetch_ai_watchlist.py` still writes its own `ai_watchlist_live.json` to `/opt/stonk-ai/` and could desync with webroot. If 21-symbol alerts recur via `comprehensive_monitor.py`, investigate race between `dynamic_watchlist_manager.py` and `fetch_ai_watchlist.py`.

- **Tier Option B applied (2026-07-04):** only STRONG_NOW / PRIME tier is tradeable. NOW / BUILDING, WATCH / WATCHING, MONITOR / TRACKING are non-trading. Entry gate: readiness ≥77, ≥5 confirmations, above_ema. Watchlist UI updated to show display tiers (`PRIME`/`BUILDING`/`WATCHING`/`TRACKING`) instead of backend tiers (`STRONG_NOW`/`NOW`/etc.), with council notes reflecting non-trading status. `index.html` cache buster bumped to force fresh JS load.
- **Watchlist display fix (2026-07-04):** `dynamic_watchlist_manager.py` now writes display tier into `targets.signal` and tier-aware `/10` council notes. Frontend flipped `signal` precedence to use `targets.signal` over `data.signal_tier`, added `display_tier` to stock objects, fixed popup tier chip and status text to handle both backend and display tier strings. Bumped `index.html` cache-buster version to `stonkbot_v150` and added one-time `location.reload(true)` fallback to defeat aggressive browser caches.
- **Watchlist Next Buys cleanup (2026-07-04 ~19:40 HKT):** removed legacy `diversification` candidate branch from `dynamic_watchlist_manager.py` and the corresponding 🌿 Diversification block from `index.html`. Next Buys now only shows PRIME `queued`/`add` candidates. Replaced watchlist table “AI Score” column with “Conf” (confirmations /10) to reduce confusion. Bumped cache buster to `stonkbot_v152`.
- **Confirmation count popup mismatch (2026-07-04 ~20:03 HKT):** `buildFactorChips()` popup header was using green-chip count instead of canonical `confirmation_count`, causing UBER to show 5/10 in popup vs 6/10 in table. Fixed header to use passed `count`; aligned RSI chip rule to count `neutral`/`oversold` like backend; patched `readiness_score.py` to count `momentum_score >= 50` as a confirmation; patched `dynamic_watchlist_manager.py` to recompute `confirmation_count` from `confirmations` instead of copying stale value; patched frontend `computeCanonicalConfirmationCount()` to also count `momentum_score >= 50` so it matches backend; updated stale ≥75/4+ references to ≥77/5+. Bumped cache buster to `stonkbot_v161`.

## Safety rules
- **skill-creator**: Never write, update, apply, revise, reject, or quarantine any Skill Workshop proposal without Howie's explicit prior approval in the current session. This applies to all `skill_workshop` tool actions. No exceptions.
- **Zapier MCP (Gmail, Sheets, Calendar, GitHub, Telegram):** Must ask before any *write, send, delete, or modify* action. Read-only operations (check inbox, list events, view sheet data) are fine when explicitly requested. Never write unprompted.
