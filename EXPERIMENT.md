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
- (pending — code patches land 2026-07-25/26)
