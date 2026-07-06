# MEMORY.md — Long-Term Memory

## User: Howie Mak
- Timezone: Asia/Hong_Kong (GMT+8)
- Met via Telegram. Runs StonkBOT.AI — a $100K real-money autonomous AI trading experiment.
- Highly clutter-sensitive. Prefers terse copy, minimal indicators, and easy reverts.
- Likes subtle motion/polish, dislikes flashy or try-hard copy.
- Avatar emoji: 🎩 (Jeeves identity)

## Setup
- **Working model:** `deepinfra/deepseek-ai/DeepSeek-V4-Flash` (DeepInfra) — switched 2026-06-28. Was deepinfra/zai-org/GLM-5.2.
  - Had to add model to `models.providers.deepinfra.models` in openclaw.json (was only in `agents.defaults.models` allowlist, missing provider registration). Also had to clear stale GLM-4.5V session override.
  - **Known issue:** DeepSeek V4 Flash keeps getting rate-limited on DeepInfra. System auto-falls back to GLM-5.2. Session override keeps reverting to GLM-5.2 after gateway restarts. Config default is now DeepSeek V4 Flash but stale session overrides persist. May need to switch back to GLM-5.2 as default if rate-limiting continues.
  - **New API key** (2026-06-28): Updated DeepInfra API key. Stored in `/root/.openclaw/agents/main/agent/plugins/deepinfra/catalog.json`.
  - **Image model:** Changed from `deepinfra/zai-org/GLM-4.5V` (404 — doesn't exist on DeepInfra) to `deepinfra/Qwen/Qwen3-VL-30B-A3B-Instruct`. Had to add to `models.providers.deepinfra.models` in openclaw.json.
- **Channel:** Telegram direct chat
- **Known issue (2026-06-26):** Previous model repeatedly errored out. Switching to GLM-5.2 fixed it. If it breaks again, check model config first.
- **Agent name:** Jeeves (from prior memory). Identity: calm, capable AI valet. 🎩

## StonkBOT.AI Project
- Site: https://stonkbot.ai
- Repo: makjh79/stonkbot-ai
- Deploy target: `/var/www/hedge-fund-website/index.html` on VPS `23.80.82.47`
- Current live version: v103 (Alpaca full integration + Phase 2 + universe expansion + STRONG_NOW)
- Bot version: v2.4 (ATR stops, 8% hard cap all tiers, 8-factor readiness, zero external data deps [except Alpaca news for PEAD inference], sector 30%)
- Previous: v2.3 (readiness-driven quality-momentum, VWAP stops, IV sizing, intraday timing, limit orders, TWAP, recalibrated weights, STRONG_NOW tier)

### Key infrastructure
- **alpaca_data.py** — Unified Alpaca data hub (snapshots, daily bars, 15Min intraday, options IV, news). ALL data flows through this. ALL endpoints use `feed=sip`.
- **Zero external data dependencies** — Finnhub, Yahoo Finance, Polygon all removed (2026-06-28). Earnings (PEAD) factor dropped.
- SSH key: `~/.ssh/id_rsa` (VPS access)
- Finnhub key: `~/.openclaw/workspace/.secrets/finnhub.key` (chmod 600) — NO LONGER USED, kept for reference only
- Cloudflare Zone ID: `b2ef773ddf3d8f3711aef1584cd598be`
- `deploy.yml` syncs `website/sentiment/` and `website/history/` to web root.

### Automation on server (updated 2026-07-01)
- **Sentiment cron:** every 15 min `*/15 * * * *` (re-enabled 2026-06-23)
- **History cron:** daily `30 6 * * *` (HK time, after US market close)
- **Freshness check:** `/opt/stonk-ai/check_sentiment_freshness.py` every 15 min
- **Signal enrichment:** `30 5 * * 1-5` and `0 21 * * 1-5` via `signal_enricher.py`
- **Alpaca trade sync:** `*/5 * * * *` via `sync_alpaca_trades.py`
- **Signal refresh:** every 15 min. Bot scan: every 5 min during US market hours.
- **Nightly history reconstruct:** `22:30 UTC` via `reconstruct_portfolio_history.py`
- **LLM narrative generation:** every 15 min via `stonk-ai-llm-narrative.timer` (VPS)
- **v6 merge + deploy:** every 2 min via `stonk-ai-popup-v6.timer` (VPS, overlays LLM narratives on popup/watchlist data)
- **Health monitoring:** `comprehensive_monitor.py` every 15 min (was 5 min during market hours, reduced 2026-07-01 for efficiency)
- **Heartbeat tracker:** `heartbeat_tracker.py` records successful runs from all critical cron jobs into `/opt/stonk-ai/heartbeats/`. 18 jobs tracked. Monitor checks for stale/missing heartbeats.
- Options skew analysis: daily 7 AM HKT via `analyze_options_skew_signal.py`
- Watchlist: 20 symbols. MAX_WATCHLIST_SIZE = 20.
- **Pipeline integrity monitor:** `/opt/stonk-ai/comprehensive_monitor.py` (every 15 min; detects stale heartbeats, LLM pipeline health, stale data, failed services).

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
- Muted text contrast fixed to #7a8098 (WCAG AA).
- Unified header bar with hamburger menu + iOS-style tabs (v85 baseline).

## Skills configured
- `macos-local-voice`: `yap` + `ffmpeg` in `~/.local/bin/`, default voice `Daniel`.
- `spotify-claw`: script at `~/.openclaw/scripts/spotify.py`, credentials in macOS Keychain.
- **Zapier MCP**: Google Sheets, Spotify, GitHub, Google Calendar, Telegram, Microsoft 365, Gmail. All authenticated.

## Agent communication
- **Jarvis:** sibling OpenClaw agent but not reachable via `sessions_send`. Needs config change to register as named agent.
- **Jeeves** is the primary bot working on StonkBOT.AI on the VPS. Runs **local Ollama** (`ollama/kimi-k2.7-code:cloud` primary, `ollama/qwen3:latest` fallback). **Not DeepInfra.** DeepInfra config is Einstein's.
- Jeeves saves memory to `/opt/stonk-ai/jeeves-memory/` on the VPS.
- Jeeves auto-syncs memory to VPS daily at 3 AM HKT.
- Jeeves created a **VPS memory maintenance script** (`vps_memory_maintenance.py`, report-only, no auto-edits) that runs at 3 AM HKT and writes analysis to `DREAMS.md`.
- I (Einstein) read Jeeves' memory daily at 9 AM HKT via cron to stay synced.
- Memory pipeline: Jeeves works → saves memory → 3 AM sync to VPS → 9 AM I read & sync into my own memory.
- Reverse pipeline: I work → save memory → 8 AM HKT push to VPS `/opt/stonk-ai/einstein-memory/` → Jeeves reads & syncs.
- My memory push cron: 8 AM HKT daily. My Jeeves read cron: 9 AM HKT daily.
- **Message relay:** `/opt/stonk-ai/agent-messages/` on VPS — `einstein/` inbox for messages TO me, `jeeves/` inbox for messages TO Jeeves. Jeeves writes handovers there (not in inbox). Checked during daily memory sync cron. Format in README.md.
- **Daily maintenance checklist** (from Jeeves, 2026-06-26): Check systemd services, rogue processes, file permissions, data freshness, signal enricher, disk space, portfolio sanity, website health. Report issues via message relay.

## Trading bot architecture (v2.4 — 2026-06-28)
- `signal_engine.py` — multi-factor scoring (momentum 40%, quality 25%, risk 20%, regime 15%) + readiness score (0-100) + confirmations. PEAD removed.
- `readiness_score.py` — 8-factor composite: signal 25%, sector 30%, EMA 12%, RSI 10%, intraday 10%, MACD 8%, volume 5%, options IV 5%
  - PEAD (Post-Earnings Announcement Drift) revived as 9th **confirmation** via Alpaca news headline inference (June 29 2026) — keeps zero-external-deps promise, uses existing Alpaca news feed.
- `trading_bot.py` v2.4 — entry queue ranked by readiness, thesis-based exits, position sizing by conviction. STRONG_NOW 12% cap override REMOVED — 8% for all tiers.
- Signal refresh now happens before `run_cycle()` in main loop, so it fires every 15 min even when US market is closed (previously frozen outside hours).
- Bottom guard patches (403 duplicate-sell guard, market-order sell wrapper) moved above `if __name__ == "__main__"` so they actually load.
- `risk_engine.py` — ATR stops (1.5× ATR hard, 2.0× ATR trailing, clamped 3-8%/3-10%), trim +25%, exit +50%, 8% max position (all tiers), 20% sector cap, concentration trim at 1.0× (was 1.25×)
- `dynamic_watchlist_manager.py` — tiers driven by readiness, auto promote/demote with reasons
- `generate_popup_content.py` — generates trader-style narratives per holding + watchlist. Per-company profiles for ~45 symbols, dynamic fallback for unknowns. Refreshes every 2 min via cron.
- Holdings popups now carry pre-market/after-hours fields copied from `ai_watchlist_live.json` (fixed 2026-06-30).
- `fetch_ai_watchlist.py` — enriches brain watchlist with live prices. All 4 API calls use `feed=sip`. Yahoo/Polygon RSI stubbed out.
- `pead_factor.py` — STUBBED (returns zero). Alpaca has no earnings API.
- `signal_enricher.py` — `fetch_earnings()`, `fetch_recommendation()`, `fetch_news()` all stubbed. Only Alpaca news API used.
- Entry gate: readiness ≥72 AND ≥2 confirmations. Position size: 1.0x/1.5x by tier.
- Currently paper trading (Alpaca PK... keys). Live keys needed for real trading.
- **ATR stops** (2026-06-28): hard stop 1.5× ATR (clamped 3-8%), trailing 2.0× ATR (clamped 3-10%). Replaces fixed 10%.
- **8 confirmations**: momentum, RSI, volume, MACD, EMA, sector, intraday, options (PEAD removed)
- **Tiers**: STRONG_NOW ≥78 (1.5x sizing, 8% cap), NOW ≥72 (1x, 8% cap), WATCH ≥55, MONITOR <55
- **Risk**: max position 8% (all tiers), entry halt at -10% DD, trailing ATR 2.0, VWAP stops, IV sizing
- **Execution**: limit orders at midpoint, TWAP for >100 shares
- **Zero external deps**: All data from Alpaca SIP. No Yahoo, Finnhub, Polygon, yfinance.
- **MR merge fix** (2026-06-28): mean reversion signals no longer replace momentum signals — they merge, preserving avg_volume, sector, earnings, news, etc.
- **Signal engine min bars** lowered from 50 to 20 (2026-06-28) — newer symbols now get scored.
- Universe expanded: 75 → 130 symbols (2026-06-27). Added Healthcare (15), Energy (8), Industrials (8), Financials (8), Communications (6), Tech Expansion (10). 15 sectors total.
- PSTG not tradable on Alpaca — bot auto-skips it.
- Signal refresh fixed (2026-06-30): `maybe_refresh_signals()` moved above `run_cycle()` in main loop so signals update every 15 min even when market is closed. Previously frozen outside hours because `run_cycle()` early-exited before calling refresh.
- After-hours data fixed (2026-06-30): `get_extended_hours_bars()` in `alpaca_data.py` now pulls *yesterday's* after-hours bars when current time is before 8pm UTC. Previously always queried today's not-yet-opened window → blank every morning.
- Holdings popups fixed (2026-06-30): `generate_popup_content.py` now copies pre-market/after-hours fields from `ai_watchlist_live.json` into popup narratives. Previously never fetched extended-hours data at all.
- Design decision (2026-06-30): Keep honest blanks for missing after-hours data. No synthetic "0.00%" lines. Alpaca SIP only returns bars for actual trades — zero volume = no bar. Fintech apps use premium aggregators (Polygon paid, Refinitiv, IEX) that interpolate gaps. Consensus: stick with zero external deps, don't add another data provider just for cosmetic after-hours lines.
- Playwright installed on VPS for automated visual testing.
- 14 redundant files cleaned up to `/opt/stonk-ai/backups/redundant-20260626/`. ~24 active Python files in `/opt/stonk-ai/`.

## Lessons learned
- Always verify deploy reached the server before assuming browser cache is the issue. Untracked server files can silently break `git pull` in GitHub Actions.
- Yahoo Finance and Finnhub free historical candles are unreliable/blocked on the VPS; keep fallback synthetic generation and plan for a paid/reliable source.
- Always chown JSON files to stonkai after manual root writes — bot can't write to root-owned files.
- `fetch_ai_watchlist.py` runs independently and can clobber brain-managed watchlist if not patched to enrich instead of replace.
- Yahoo Finance 429 rate-limits kick in fast when fetching 75 symbols sequentially — synthetic bar fallback from Alpaca real-time quotes is the fix.
- Alpaca data API returns 401 on IEX feed for some symbols on free/paper tier — paper keys have limited data access.
- Sub-agent output limits: large builds can exceed sub-agent output budget — handle directly when they fail.
- JS patching via Python string replacement is fragile — always verify exact string exists before replacing.
- SSH heredoc quoting is unreliable for Python scripts with nested quotes — write locally, scp, then run.
- Large HTML structural changes via string replacement are risky — can silently swallow adjacent elements. Make changes in smaller chunks with backups, test on real devices early.

## Backups on server
- `/opt/stonk-ai/backups/pre-brain-rewrite-20260626/` — before brain upgrade
- `/opt/stonk-ai/backups/pre-visual-upgrade-20260626/` — before visual upgrade
- `/opt/stonk-ai/backups/comprehensive-20260626-0225/` — full backup
- `/opt/stonk-ai/backups/comprehensive-20260627-0550.tar.gz` — pre-risk-fix
- `/opt/stonk-ai/backups/comprehensive-20260627-0905.tar.gz` — pre-risk-fix
- `/opt/stonk-ai/backups/risk-fix-20260628/` — individual file backups before each patch
- `/opt/stonk-ai/backups/comprehensive-20260628-0650.tar.gz` — after ATR stops + cap fix (499KB)
- `/opt/stonk-ai/backups/comprehensive-20260628-0830.tar.gz` — after all June 28 changes (498KB, 203 files)

## Phase 2 status: DEPLOYED (updated 2026-06-28)
- backtest.py — working, Sharpe 0.89 (post-ATR stops), return +56.85% over 18 months
- performance_attribution.py — 7 factor correlations computed
- stress_test.py — VaR, 4 scenarios, concentration risk
- monitor.py — cron every 5 min, kill switch at -15% DD
- regime_patch — yield curve (SHY/TLT), credit spreads (LQD/HYG), breadth
- execution_patch — limit orders at midpoint, TWAP splitting
- All 53/53 audit checks passed

## Phase 2 priorities (handover to Jeeves)
- Handover note: `/root/.openclaw/workspace/handover-jeeves-phase2.md` and on VPS at `/opt/stonk-ai/einstein-memory/`
- 1. Backtesting framework (HIGHEST — prove the edge exists)
- 2. Performance attribution (Sharpe, alpha, factor decomposition)
- 3. Stress testing (VaR, correlation, scenarios)
- 4. Execution optimization (limit orders, TWAP)
- 5. Regime detection enhancement (yield curve, credit spreads, breadth)
- 6. Real-time monitoring & alerting (Discord alerts, kill switch)
- Howie knows these gaps. He asked about "professional trader standards" — was told ~60% there.

## Backtest-driven optimization
- Factor analysis on 38 live trades revealed:
  - above_ema: +0.593 (STRONGEST predictor) — weight raised
  - sector_strong: +0.459 — weight raised to 30% (best non-price predictor)
  - volume_confirmed: -0.231 (NEGATIVE!) — weight cut to 5%, logic inverted
  - readiness_score: +0.481, confirmation_count: +0.437
- Backtest (pre-ATR stops): Sharpe 1.30, return +101.97%, max DD -31.7%, 1935 trades
- Backtest (post-ATR stops, 2026-06-28): Sharpe 0.89, return +56.85%, max DD -29.5%, 1819 trades
  - Sharpe drop is expected/healthy — old 1.30 was inflated by wide fixed stops in bull market
- Live performance (25 days, 38 trades): Sharpe -1.16, return -3.55%, win rate 34.2%, avg winner +3.87%, avg loser -4.47%
  - Negative expectancy (-1.62%/trade) — ATR stops should fix by tightening losers
- **Freeze rule**: no parameter changes for 200 trades
- Gemini audit (2026-06-28): confirmed overfitting risk, collinearity, stop width as key issues

## Website news display bug (FIXED 2026-06-29)
- `loadStockSentiment()` in watchlist popup fetches `./sentiment/{symbol}.json` (often missing) then falls back to generic message
- Should use `alpacaNewsHeadline` from popup_content.json / ai_watchlist_live.json instead
- Holdings popup also doesn't display Alpaca news headline (data is there, not rendered in HTML)
- **Fix applied:**
  - `generate_popup_content.py` now exposes `alpacaNewsHeadline`, `alpacaNewsSentiment`, `alpacaNewsUrl`, `alpacaNewsSource`, and `catalyst` in `watchlist_narratives.json` output.
  - `index.html` holdings popup (`showTradeDetails`) now renders a "Latest news" section using `preGenerated.alpacaNewsHeadline` / `catalyst`.
  - `index.html` watchlist popup (`loadStockSentiment`) rewritten to load `watchlist_narratives.json`, prioritize `alpacaNewsHeadline`, fall back to `popup_content.json` (for overlapping holdings), then `./sentiment/{symbol}.json`, then generic.
  - `monitor/vps_check.py` now has checks `holdings_news` and `watchlist_news` that flag when Alpaca news is missing from popup JSONs.

## StonkBOT Comprehensive Integrity Monitor (2026-06-29)
- **Location:** `/opt/stonk-ai/comprehensive_monitor.py`
- **Behavior:** Silent when HEALTHY (exit 0). Prints JSON issue report to stderr when degraded (exit 1).
- **Checks:**
  - Service health: `stonk-ai.service`, `stonk-ai-watchlist.service`
  - File freshness: `signals.json` (10 min), `ai_watchlist_live.json` (2 min), `popup_content.json` (5 min), `watchlist_narratives.json` (5 min) — aware of US market hours.
  - Extended hours prices: all 130 universe symbols have non-zero `price` + `prev_close` in `signals.json`; all 20 watchlist stocks have non-zero `price`.
  - Universe name coverage: asserts `DEFAULT_UNIVERSE` == `COMPANY_NAMES.keys()` in `signal_engine.py`.
  - Shadow COMPANY_NAMES: scans `/opt/stonk-ai/*.py` (excluding backups) for dict definitions that shadow the canonical dict.
  - Signal-Watchlist alignment: `ai_score` vs `total_score` (±2 tolerance), `readiness_score`, `tier`, `momentum_score` field existence.
  - Factor confirmation integrity: strategy-aware (momentum vs mean_reversion). Checks expected keys present, `confirmation_count` in valid range (0–9 for momentum, 0–6 for MR).
  - Popup/narrative alignment: cross-references `confirmations` dict between `signals.json`, `popup_content.json["holdings"]`, and `watchlist_narratives.json["narratives"]`. Tolerates `earnings_confirmed` injected by `_infer_pead`.
  - Popup integrity: `earnings_confirmed` present, `sources` provenance dict, `/9` denominator.
  - Dead code audit: forbidden imports (`yfinance`, `finnhub`, `polygon`, `yahoo_finance`).
  - Portfolio sanity: checks 8% single-position cap and 20% sector cap against `portfolio_state.json`.
  - HTML currency: deployed `index.html` cache-buster freshness, `/9` denominator check.
- **Telegram alerting:** wired. Reads token + chat_id from `/opt/stonk-ai/.secrets/telegram.env`. Sends Markdown alert only when issues are found.
- **Fixes applied during build:**
  - Patched `generate_popup_content.py` to inject `confirmations` + `confirmation_count` into watchlist narrative output.
  - Made monitor strategy-aware to avoid false positives on mean reversion signals (AAPL, DOCN).
  - Tolerated PEAD `earnings_confirmed` injection in popup vs signal comparisons.
- **Wiring suggestion:** run via cron every 5 minutes during market hours, 15 minutes after hours. Wire non-zero exit code to Telegram if desired.
- **Test result:** deployed and validated HEALTHY at 2026-06-29T16:47 UTC.
- 13:25 UTC (9:25 AM ET): Pre-market generation (all data generators, results to Telegram)
- 13:35 UTC (9:35 AM ET): Intraday pipeline test (verify live 15Min bars, VWAP stops, options)
- Both are one-shot, delete after run

## Safety rules
- **skill-creator**: Never write, update, apply, revise, reject, or quarantine any Skill Workshop proposal without Howie's explicit prior approval in the current session.
- **Zapier MCP (Gmail, Sheets, Calendar, GitHub, Telegram):** Must ask before any *write, send, delete, or modify* action. Read-only operations fine when explicitly requested. Never write unprompted.

- **June 28 2026 session summary**
  - Risk engine overhaul: 10% → ATR stops, STRONG_NOW 12% cap removed, concentration trim tightened.
  - Data pipeline: `feed=sip` everywhere, Yahoo/Polygon/Finnhub fully removed.
  - PEAD temporarily dropped from signal engine — earnings API unavailable from Alpaca.
  - Signal engine min bars 50→20, popup narratives rewritten (~45 company profiles).
- **June 29 2026 session summary**
  - **PEAD revived**: Inferred from Alpaca news headlines via keyword scan (`earnings`, `EPS`, `beat`, `missed`, `guidance`, `revenue`, `profit`). Sets `confirmations["earnings_confirmed"]=true` + increments `confirmation_count` (8→9 when detected).
  - **Backend** (`generate_popup_content.py`): `_infer_pead()` helper injected at top of both `generate_dynamic_narrative` and `generate_watchlist_narrative`. Pre-existing `_why_bot_bought` narrative automatically picks up "post-earnings drift" again.
  - **Frontend**: `buildFactorChips` & `buildWatchlistFactors` updated to 9 factors (`/8→/9`), PEAD chip added. Fallback PEAD augmentation in `showStockDetail` and `showTradeDetails` via headline scan.
  - **Tier chip emoji removed** from popups (`🟢`, `🟡` stripped from `getSignalDisplay` and `buildWatchlistSignal` tier texts). Colored-dot + text styling already present, emojis were redundant.
  - **Alpaca 403 sell bug investigated** (2026-06-29 ~17:15 UTC): Investigated recurring 403 errors on sell orders. Root cause: missing open-order deduplication guard in `_execute_sell` causing repeated duplicate sell attempts when a prior limit sell is already open.
    - One stale AAPL limit sell order at $285.92 (submitted 13:39 UTC, qty=10) sat unfilled for 4+ hours and was the primary trigger of the 403 flood.
    - API credentials and paper account verified as perfectly valid. Account active, positions readable, market orders succeed.
    - Safe infra fixes applied: `BOT_DIR` attribute added to `TradingConfig`; `regime_status.json` ownership fixed for `stonkai` user.
    - Pending explicit approval: cancel stuck AAPL order; patch open-order dedup guard; consider market-order exits for stops.

## Known active issue: Alpaca 403 sell loop (2026-06-29)
- **Symptom:** Every ~5 minutes the bot logs `403 Client Error: Forbidden` on sell orders (specifically AAPL, and transiently others).
- **Root cause:** `_execute_sell` does not check existing open sell orders before calling `alpaca_api.submit_order`. If a prior limit sell is unfilled (e.g., AAPL @ $285.92, which is above current market after the stock dropped), the bot retries on every cycle. Alpaca rejects duplicates with `insufficient qty available` (code 40310000).
- **Why the limit order is stuck:** Stop exits compute a limit price from the midpoint at trigger time. If the stock continues falling, the limit sits above the market and can never fill.
- **Mitigation applied:** `BOT_DIR` attribute added to `TradingConfig` (fixes `AttributeError` on trade logging); `/var/www/hedge-fund-website/regime_status.json` ownership changed to `stonkai:stonkai` (fixes permission denied).
- **Fixes pending explicit approval:**
  1. Cancel stale AAPL order `aabe07b0-486f-4c85-86e5-f58d9d46ab1d` so the bot can place a fresh exit.
  2. Patch `_execute_sell` or `alpaca_data.py` to check `list_orders(status='open', symbols=[symbol])` before submitting a duplicate sell.
  3. Evaluate using market orders instead of limit orders for trailing/hard stop exits (to guarantee fill rather than relying on a possibly stale midpoint).
- **Files involved:** `trading_bot.py`, `alpaca_data.py`, `alpaca_config.json`, `comprehensive_monitor.py`.

## Notes
- Don't break down. Howie doesn't like it. 😤
- Daily memory task: Distill each day's chats into `memory/YYYY-MM-DD.md`. Periodically update MEMORY.md with durable decisions, preferences, and lessons.
