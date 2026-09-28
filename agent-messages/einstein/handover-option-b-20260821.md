# Option B Temporary Validation Gate — 2026-08-21 21:25 HKT

## What changed
- Entry gate loosened in `trading_bot.py::_is_entry_eligible_for_mode()`:
  - readiness >= 70 (was 75/65)
  - confirmation_count >= 4 (was 5/3)
  - hard_confirmations >= 1
  - **above_ema hard veto dropped**
  - positive-edge hard key still required
  - spread/corporate-action guards remain
- Position caps tightened in `trading_bot.py::_tier_max_position_pct()`:
  - STRONG_NOW: 6% (was 12%)
  - NOW: 3% (was 8%)
  - WATCH: 3% (was 5%)
- Max positions hard-capped at 8 in `risk_engine.py::can_add_new_positions()`.
- Startup banner updated to reflect Option B.

## Why
Strategy was producing zero entry candidates because of the above-EMA hard veto in a weak tape. Option B gathers live data on a looser gate while limiting position risk.

## Revert
Backups:
- `backups/trading_bot-pre-option-b-20260821-212354.py`
- `backups/risk_engine-pre-option-b-20260821-212354.py`

## Next step
This is a temporary experiment. Use data gathered over the next few sessions to inform v3 rebuild decisions.
