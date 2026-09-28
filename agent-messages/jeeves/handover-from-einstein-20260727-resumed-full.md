# Handover: entries RESUMED 2026-07-27 15:20 HKT

**Supersedes the halt portion of handover-from-einstein-20260727-redesign.md.**

Owner chose full resume ~5h after the redesign halt. ENTRIES_HALTED sentinel is REMOVED. Bot trades the new signal live from tonight session.

What stays in force:
- New gate: readiness >= 80 AND >= 6 confirmations AND >= 2 hard (VOL/RVOL/OPT/VWAP/INT), above_ema required
- MACD removed from hard set; MACD+RSI zero-weighted in readiness (still shown in UI)
- Exits/stops/trims unchanged
- entry_factor_snapshots.py + factor_attribution.py crons KEEP RUNNING — validation data still accumulates; rerun attribution at 50-100 snapshot-backed round trips

Implication: live entries now double as validation data, but attribution must separate pre-redesign trades from post-redesign ones (cutoff: 2026-07-27 15:20 HKT).

— Einstein
