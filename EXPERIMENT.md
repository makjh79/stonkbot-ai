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
