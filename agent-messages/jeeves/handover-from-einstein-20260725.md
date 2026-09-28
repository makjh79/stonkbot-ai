# Handover: Amendment 1 — Stop Architecture Rework (LIVE for Monday Jul 27)
From: Einstein · 2026-07-25 10:30 HKT · Commit b68ef9a (pushed, deployed, service restarted clean)

## What happened
Howie approved amending the experiment early (07:22 HKT "Do it"). Amendment 1 was written into EXPERIMENT.md and committed (1aee4a1) BEFORE any code change. Evidence: analysis/amendment1-evidence.md.

## Why (data, Jul 7–24, 447 FIFO round trips)
- PF 0.323, median hold 3.6 HOURS (252/447 same-day, PF 0.178) — the bot was scalping.
- Whipsaw tax $7,872 ≈ entire window realized loss (−$7,272). Root cause: below-VWAP trailing tightening floored stops at 1× ATR (AAPL −2.5% vs 2.4% ATR → re-bought +3.5% next day).
- QQQ-50DMA gate was backtested and REJECTED (would have blocked the better half: gated PF 0.459 vs allowed 0.218).

## Code changes (all smoke-tested 29/29)
1. risk_engine.py: VWAP trailing tightening RETIRED (vwap_trailing_tighten_enabled=False); VWAP stop buffer 0.5→1.0×ATR; tier caps halved (12/8/5/3→6/4/2.5/1.5%); target_position_risk 0.015→0.0075; re-entry price discipline — within 7 days of a stop-out, re-entry needs price ≤ stop-out price (blocked attempts logged to risk_state blocked_reentries); high-beta basket trim hysteresis (band + min $250 + 4h cooldown).
2. trading_bot.py: guardrails pass price to reentry_price_blocked; record_stop_out passes fill price.
3. Grandfathering: pre-amendment holdings keep legacy caps until fully exited (seeded in risk_state.json: AAPL 12%, ELF 12%, ROKU 5%, PAYO 3%). No forced Monday trims.
4. Diagnostics: trade_quality_report.py (cron 20 7,13,21 HKT) → trade_quality.json; monitor checks freshness 26h.
5. Kill criteria amended (EXPERIMENT.md): Jul 27→Aug 29 or 40 round trips; all-trades PF < 1.0 AND trailing QQQ → shelve entries; median hold < 2 days by Aug 8 → rework failed.

## Watch Monday
- First entries under 6%/4% caps (targets halve automatically via tier_max_position_pct).
- Any RE-ENTRY PRICE BLOCK log lines — expected behavior, not an error.
- trade_quality.json populating (first cron 13:20 HKT Mon).
- Backup of pre-patch code: /opt/stonk-ai/backups/amendment1-20260725/

## Revert
cd /opt/stonk-ai && cp backups/amendment1-20260725/{risk_engine.py,trading_bot.py} . && systemctl restart stonk-ai && git checkout EXPERIMENT.md (or revert commit b68ef9a for git-clean path).

---

## ADDENDUM: Amendment 2 — Event-risk gates (LIVE for Monday Jul 27)
Commit be0ab43 (pushed, deployed, service restarted clean) · Owner directive 10:42 HKT

- **Earnings proximity gate:** no new entries/avg-ins ≤2 calendar days before confirmed earnings (Finnhub daily cache, cron 30 6,13 HKT → earnings_cache.json, 1,498 symbols, fail-open).
- **Implied-move event gate:** earnings 3–7d out → block if IV daily move (iv_30d/√252) > 1.5× ATR% (uses signals' options_implied_vol). Fail-open.
- Both veto-only (prevent trades, never create), logged to logs/gate_blocks.jsonl. Rollback = config flags in risk_engine.py (earnings_gate_enabled / implied_move_gate_enabled).
- **Measure-only:** breadth (% universe > own 50DMA — first read 64.6%), macro-calendar trade flagging, holdings earnings radar ≤7d → all in trade_quality.json.
- Watch: ELF reports Aug 5, PAYO Aug 6 — radar flags them from ~Jul 29.
- Gate smoke 8/8 (ran as stonkai; trading_bot import has root+singleton guards — harness execs source with lock neutralized).
