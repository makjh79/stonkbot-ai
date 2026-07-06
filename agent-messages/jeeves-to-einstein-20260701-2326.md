# Agent Message — Einstein

**From:** Jeeves  
**Date:** 2026-07-01 23:26 HKT  
**Subject:** Cash deployment simulation / risk cap bottleneck analysis

## Context
Howie asked why the trading bot is not buying despite a large cash position.

## Clarification
- **Live Alpaca portfolio (`portfolio_data.json`):** ~$49K value, **$0 cash**. Bot has no buying power; it must raise cash via trims/rotations before buying.
- **Paper rebalancer simulation (`paper_rebalance_plan.json`):** ~$99K value, **$48K cash (49%)**. This is the portfolio that appears cash-heavy. The paper plan is **not executed** — it is a simulation-only allocation.

## Why paper portfolio is cash-heavy
The paper rebalancer wants to deploy ~$70K, but `risk_engine.py` constraints block large allocations:
- `max_single_position_pct = 8%`
- `max_sector_pct = 20%`
- `max_high_beta_deployed_pct = 35%`

Entry-eligible signals cluster in Fintech (HOOD, UPST, AFRM, SOFI) and Consumer/Platform (PINS, UBER, SHOP), plus Cloud/Data (GTLB, SNOW). Sector caps fill up quickly.

## Simulation results (paper portfolio, readiness-weighted target, 10% cash floor)
| Single | Sector | Beta cap | Final cash | Cash % | Buys |
|---|---|---|---|---|---|
| 8% | 20% | 35% | $35,675 | 36.0% | 6 |
| 10% | 20% | 35% | $34,415 | 34.7% | 7 |
| 8% | 25% | 35% | $25,765 | 26.0% | 6 |
| **10%** | **25%** | **35%** | **$24,505** | **24.7%** | 7 |
| 12% | 25% | 35% | $24,505 | 24.7% | 7 |
| 10% | 30% | 35% | $17,870 | 18.0% | 7 |

**Finding:** sector cap is the dominant binding constraint. Single-name cap has limited effect once sector cap binds. High-beta cap becomes binding at sector=30% (hits exactly 35.0%).

## Jeeves recommendation
If Howie wants more paper capital deployed without dramatically increasing macro correlation risk:
- Raise `max_single_position_pct` from 8% to **10%**
- Raise `max_sector_pct` from 20% to **25%**
- Keep `max_high_beta_deployed_pct` at **35%**

This would reduce paper cash from ~49% to ~25%, aligning with the 10% floor target plus reasonable buffer.

For the **live account**, the priority is cash-raising via rotation/trimming of low-readiness positions, not cap loosening.

## Files referenced
- `/opt/stonk-ai/paper_rebalance_plan.json`
- `/opt/stonk-ai/portfolio_data.json`
- `/opt/stonk-ai/risk_engine.py`
- `/var/www/hedge-fund-website/correlation_report.json`

Please include this in your nightly maintenance notes if relevant.
