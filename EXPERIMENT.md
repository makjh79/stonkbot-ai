# StonkBOT.AI — Pre-registered Experiment (Phase 2)

Registered: 2026-07-23, **before** outcome-tracker data lands.
Owner: Howie · Operator: Einstein

## Window
Jul 22 2026 (Phase 2 deploy: ATR-honest stops + min-hold rule) → Aug 15 2026 (~17 trading days).

**Frozen during window:** entry logic, stop widths, position caps, tier thresholds.
**Exceptions:** bot down, data-integrity failure, broker/API breakage.

## Primary metric
Profit factor (PF) of multi-day round trips (holds > 1 trading day), judged vs **QQQ** over the same window. Never SPY — a momentum book graded against SPY in a rotation gets killed for doing its job.

## Keep/kill rules (pre-committed)

1. **Momentum entries**
   - PF ≥ 1.3 (n ≥ 60 closed): validated → keep, window extends.
   - 1.0 ≤ PF < 1.3: marginal → raise readiness floor, add nothing new.
   - PF < 1.0 (n ≥ 60): **entries stop.** Bot to cash/index. No exceptions.

2. **Flips** (same-week exit → re-entry on same symbol): target 0.
   - More than 3 in window → anti-churn has regressed; fix machinery before ANY other work.

3. **Readiness score** (vs 5/10/20d forward returns, n ≥ 60)
   - r < 0.10 → delete the score and its UI.
   - 0.10–0.25 → simplify: cut the weakest factors.
   - r > 0.25 → keep.

4. **Confirmation count** — same thresholds as readiness.

5. **Below-VWAP trailing tightening** — if it produces another stop tighter than −3% twice more this week → ATR-gate it (tighten only when VWAP deviation > 0.5×ATR) or retire it. Base ATR stops are honest now; this component's original purpose is half-redundant.

## Regime gate — deliberately NOT built
Stops + re-entry lockout already express regime at position level: the 77% cash book *is* the detector working. A market-level gate is another unmeasured knob. Revisit only if the next rotation bleeds > 2% via stop-outs.

## Kill criterion (restated)
PF < 1.0 on multi-day holds (n ≥ 60) **and** trailing QQQ over the window → experiment ends, capital to index.

## Process rule
No midnight patches that reset the measurement clock. Every code change during the window gets logged here with a one-line justification.

## Change log
- 2026-07-23 21:20 HKT — comprehensive_monitor.py: removed portfolio_history.json from generic stale-file check (false DEGRADED 09:00-09:30 ET daily; dedicated check_portfolio_history_freshness covers it) and bumped ai_watchlist_live.json threshold 120s→700s to match DWM 5-min cron cadence. Monitoring-only; no trading logic touched.

---

# Amendment 1 — Stop architecture rework (pre-committed before code changes)

Registered: 2026-07-25 07:35 HKT (Saturday, market closed) · Owner approval: Howie, Telegram 07:22 HKT ("Do it")
Operator: Einstein

## Why amend early rather than wait for Aug 15
1. **The primary kill criterion is structurally unreachable.** It needs n≥60 *multi-day* holds, but the below-VWAP trailing-tightening floor (1× ATR) stops positions inside normal daily noise, so almost nothing survives to multi-day. The machine cannot generate the samples the criterion demands.
2. **The trade-level verdict is already statistically decisive:** 158 closed trades Jul 7→24 — win rate 27.2%, PF 0.46, expectancy ≈ −0.27%/trade (t ≈ −5). Portfolio −7.67% vs SPY −1.2% / QQQ −3.5% over the window.
3. **Item 5's trigger effectively fired.** VWAP-tightened stops kept landing sub−3% (AAPL −2.5% Jul 23 vs 2.4% ATR) and produced measured whipsaw: AAPL stopped 321.19 Jul 23 → re-entered 332.64 Jul 24 (+3.5% tax); ELF stopped 76.56 Jul 23 → re-bought ~77.1 Jul 24.
4. **Regime-gate revisit condition already met:** the doc said revisit if a rotation bleeds >2% via stop-outs; window bleed is −7.67%, predominantly stops.

## Changes (effective Monday Jul 27 2026 open)
A. **Retire below-VWAP trailing tightening** (risk_engine.py tighten + 1× ATR floor). Base ATR trailing (2.0× ATR, clamp 3–14%) becomes the only trailing stop. Executes item 5's "retire" option.
B. **VWAP stop ATR-gate:** buffer max(2%, 0.5×ATR) → max(2%, 1.0×ATR).
C. **Position size halved** (dollar risk ≈ constant under ~2× wider effective stops): STRONG_NOW cap 12% → 6%, other tiers 8% → 4%; target_position_risk 0.015 → 0.0075.
D. **Re-entry price discipline:** after a stop-out, re-entry in that symbol requires price ≤ stop-out price for 5 trading days (existing 20h cooldown subsumed). Blocked re-entries logged with prices for opportunity-cost measurement.
E. **High-beta basket trim hysteresis:** apply concentration-trim guardrails (0.5pp band, trim-to-1pp-below-cap, $250 min notional, 4h cooldown) to basket trims. Machinery hygiene — ROKU fired six ~$142 trims in 2 days on a 0.1pp breach.
F. **Diagnostics** (new trade_quality.json, refreshed daily): whipsaw tax (stop→re-entry pairs + $ spread), median holding period, rolling 20-trade expectancy, blocked-reentry opportunity cost.

## NOT changed (still frozen)
Entry logic (readiness floor, confirmation count, avg-in rules), tier thresholds, hard-stop stack (abs cut / 1.5× ATR hard stop), profit-take levels, high-beta basket 35% cap level, max 10 positions, 20-name watchlist.
QQQ-below-50DMA gate: weekend backtest vs Jul 7–24 decides; if added, ships as a separately-flagged toggle with independent before/after measurement.

## Amended keep/kill criteria (window: Jul 27 → Aug 29, or 40 closed round trips, whichever first)
1. **All-trades PF < 1.0 AND trailing QQQ → shelve momentum entries; capital to index.** (Primary. Multi-day PF reported as secondary.)
2. **Median holding period < 2 trading days by Aug 8** → stop rework failed mechanically; revisit before any new work.
3. **Whipsaw accounting weekly:** re-entry rule opportunity cost vs tax saved; net-negative two weeks running → rule adjusted openly, not silently dropped.
4. Readiness r < 0.10 → delete score (unchanged; judged on data through Aug 29).
5. Flips > 3 in amended window → fix machinery before any other work (unchanged).

## Process
This amendment was written and committed BEFORE any code change. Analysis reports (whipsaw tax, QQQ-gate backtest) land in /opt/stonk-ai/analysis/ as supporting evidence; each code patch is logged below.

### Amendment 1 change log
- 2026-07-25 10:20 HKT — risk_engine.py: retired below-VWAP trailing tightening (`vwap_trailing_tighten_enabled=False`, item 5 "retire" executed); VWAP stop buffer 0.5x→1.0x ATR; tier caps halved (12/8/5/3% → 6/4/2.5/1.5%); target_position_risk 0.015→0.0075; re-entry price discipline (7 calendar days, stop-out price stored, blocked attempts logged); legacy-cap grandfathering for pre-amendment holdings (seeded AAPL 12%, ELF 12%, ROKU 5%, PAYO 3%); high-beta basket trim hysteresis (+0.5pp band, trim-to-1pp-below, $250 min notional, 4h per-symbol cooldown).
- 2026-07-25 10:20 HKT — trading_bot.py: entry guardrails accept price and call `reentry_price_blocked`; `record_stop_out` now passes fill price.
- 2026-07-25 10:25 HKT — trade_quality_report.py deployed (cron `20 7,13,21 * * *` HKT) → trade_quality.json with PF, median hold, whipsaw tax, re-entry opp-cost, post-amendment scoreboard; comprehensive_monitor.py freshness check (26h).
- 2026-07-25 — Evidence: analysis/amendment1-evidence.md — 447 FIFO round trips Jul 7–24: PF 0.323, median hold 3.6h, same-day PF 0.178, whipsaw tax $7,872 ≈ entire window realized loss; 3 sub−3% trailing stops (item 5). **QQQ-below-50DMA gate REJECTED by backtest**: would have blocked the better half of entries (gated PF 0.459 vs allowed 0.218) — regime detection stays position-level per original design.
- Smoke test 29/29 passed (/tmp/amendment1_smoke.py): tier caps, retired tighten (noise dip survives / real break stops), 1.0x ATR VWAP gate, re-entry block/allow/expiry/persistence, legacy seed/prune/override, basket hysteresis.

---

# Amendment 2 — Event-risk data gates (veto-only; freeze override)

Registered: 2026-07-25 10:50 HKT (Saturday, market closed) · Owner directive: Howie, Telegram 10:42 HKT ("Let's override the freeze")
Operator: Einstein

## Scope decision
Earnings + implied-move gates go LIVE (both are veto-only: they prevent trades, never create them). Breadth + macro calendar ship as MEASUREMENT-ONLY — neither has supporting evidence in this book yet, and promotion must clear the same evidentiary bar that rejected the QQQ-50DMA gate.

## Attribution safeguard
Veto-only design + separate block logging (logs/gate_blocks.jsonl → trade_quality.json). Kill-criteria PF is computed on trades that occur; each gate's value is assessed from its block log + measured avoidance, not folded silently into PF.

## Changes (effective Monday Jul 27 2026 open)
A. **Earnings proximity gate (live):** block NEW entries and avg-ins when a confirmed earnings report is ≤2 calendar days away. Source: Finnhub /calendar/earnings, daily cache (earnings_cache.json), fail-open on missing/stale data (logged).
B. **Implied-move event gate (live):** when earnings is 3–7 days away, block entry if the ATM straddle implied move > 1.5× daily ATR% (Alpaca options snapshot, per-symbol daily cache, fail-open). Rationale: Amendment 1's wider stops do not control gap risk; event vol dominates the historical-vol sizing model.
C. **Market breadth (measure-only):** % of signal universe above own 50DMA, computed from existing Alpaca SIP bars (zero new deps), into trade_quality.json. NOT gating — the QQQ-gate backtest showed price-based gates can select against the better trades in this book.
D. **Macro calendar (measure-only):** CPI/FOMC dates; trades opened on those mornings flagged in trade_quality.json. NOT blocking — zero supporting evidence; cheapest to measure.

## NOT changed
Everything frozen under Amendment 1 (entry logic, stops, caps, tiers, regime approach).

## Rollback
Config flags (`earnings_gate_enabled`, `implied_move_gate_enabled`) → False. No code revert needed.

## Keep/kill
Gates evaluated at Aug 29 with Amendment 1 criteria. A gate showing zero measured avoidance value AND material blocked-winner cost gets retired, openly, in the change log.

### Amendment 2 change log
- 2026-07-25 11:15 HKT — earnings_calendar.py: Finnhub daily cache (cron 30 6,13 HKT) -> earnings_cache.json (1,498 symbols); trading_bot.py: earnings proximity gate (<=2d block) + implied-move event gate (3-7d, IV daily move > 1.5x ATR, uses signals' options_implied_vol.iv_30d), both veto-only, fail-open, logged to logs/gate_blocks.jsonl; risk_engine.py: gate config flags (rollback path).
- 2026-07-25 11:20 HKT — trade_quality_report.py: + gate-block accounting, market breadth (% universe above own 50DMA from existing SIP bars — first reading 64.6%), macro-calendar trade flagging (CPI/FOMC, measure-only), holdings earnings radar (<=7d).
- Gate smoke test 8/8 passed (run as stonkai): <=2d block, 3-7d high-IV block, low-IV allow, >7d allow, fail-open x2, config-flag rollback, jsonl logging.
- 2026-07-25 12:50 HKT — display-only frontend: popup stop levels now computed from amended rules (1.5x/2x ATR clamps; was stale fixed -10%%); trade_quality_report exports config_truth.json (caps/stops/gates/experiment meta from live risk_engine) + earnings.json; About tab: live experiment panel + earnings chip on popups. No trading-logic change.
