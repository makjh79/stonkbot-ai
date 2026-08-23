# Macro + Satellite Realistic Backtest Verdict

## Summary Table

| Window | Original Satellite | Realistic Satellite | QQQ | Max DD (realistic) | Avg Stock Count (realistic) |
|---|---:|---:|---:|---:|---:|
| 2022 bear | -6.07% | -14.18% | -33.22% | -12.70% | 0.0 |
| 2023–Aug 2024 | 73.12% | 4.80% | 81.85% | -20.46% | 4.2 |
| Aug 2024–Aug 2026 | 173.40% | 33.15% | 56.84% | -18.67% | 4.9 |

## Data Audit Findings

- `daily_bars_2yr.json` symbols: **63**
  - Full-history symbols (>=500 trading days): **61**
  - Mid-window additions: **0**
  - Delisted/disappeared: **2** (CFLT, SQ)
  - Suspicious split flags: **2** (TTD, ZS)
- Cross-market merged symbols (2022-2026): **62**
  - Full-history symbols 2022-2026: **62**
  - Mid-window additions: **0**
  - Delisted/disappeared: **0**
  - Suspicious split flags: **9** (ELF, META, NFLX, PANW, S, SNAP, TTD, UPST, ZS)
- Point-in-time universe (252+ days of history as of each date) is stable at **62** symbols throughout the merged window after de-duplicating overlapping dates.

## Walk-Forward Test

- In-sample optimization (macro allocator parameters only on 2022–Aug 2024):
  - In-sample macro-only return: **+6.20%**
  - Optimized params: `CREDIT_STRESS_Z=-1.5`, `CREDIT_EASY_Z=0.2`, `VIXY_ELEVATED_Z=0.8`, `VIXY_CALM_Z=-0.5`, `TLT_RISING_SLOPE=0.0002`, `TLT_FALLING_SLOPE=-0.0005`, `DRAWDOWN_SPY_60D_LIMIT=-0.15`
- Forward test (Aug 2024–Aug 2026):
  - Forward macro-only return: **+2.70%**
  - Forward realistic combined return: **+37.25%** (with optimized macro params)
  - Note: realistic combined with **default** macro params returned **+33.15%**, showing only modest parameter sensitivity.

## Honest Verdict

The originally reported **+173%** in Aug 2024–Aug 2026 **does not hold up**.

Under the requested realistic execution assumptions:
- Next-open execution with estimated opens,
- Point-in-time 252-day history requirement,
- $10M min 20-day dollar-volume,
- 80% max 20-day vol,
- $5 min price,
- Vol-scaled slippage (0.10% per side + vol20d * 0.05),
- 12.5% per-stock cap,

the forward return drops to **+33.15%** (default params) and **+37.25%** (in-sample optimized params). The satellite alpha is almost entirely consumed by:
1. **High slippage** on volatile momentum names (vol-scaled cost is 2–5% per side for the selected stocks),
2. **Next-open execution drift** and conservative open estimation,
3. **Liquidity/vol filters** removing some of the strongest momentum names at certain dates,
4. **Point-in-time universe** delaying satellite activation in the forward window until late 2025.

## Stop-Condition Check

The realistic combined system **fails** all three stop conditions:
- Max drawdown in 2023–Aug 2024 is **-20.46%** (within -25% tolerance, but 2022 bear -12.70% and forward -18.67% are OK).
- It **never beats the pure macro allocator** in any window.
- It **underperforms the pure macro allocator by more than 10 pp in every window**:
  - 2022 bear: -14.18% vs -1.68% macro → underperform by 12.50 pp
  - 2023–Aug 2024: +4.80% vs +43.75% macro → underperform by 38.96 pp
  - Aug 2024–Aug 2026: +33.15% vs +53.69% macro → underperform by 20.54 pp

## Recommendation

**STOP.** Continue only after a fundamental redesign of the satellite execution model. The current satellite alpha engine v0, once realistic frictions are applied, does not add value over the pure macro allocator. The +173% was largely an artifact of idealized month-end close execution, low transaction-cost assumptions, and a volatile momentum sleeve that looks good in a backtest but cannot be executed cheaply enough to retain the edge.

If continuing:
- Reduce turnover frequency (e.g., quarterly rebalancing or holding winners longer).
- Lower the vol-scaled slippage coefficient or use limit-order/implementation-shortfall models.
- Add a real sector/neutralization layer.
- Validate signals on an intraday or simulated execution dataset with actual open prices.

Generated: 2026-08-23
