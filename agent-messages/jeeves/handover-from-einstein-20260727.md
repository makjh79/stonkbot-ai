# SUPERSEDED — see handover-from-einstein-20260727-resume.md

**The halt described below was REVERSED at 10:12 HKT the same day (owner
decision). Trading resumed per strategy; the experiment protocol (freeze)
is ended. Do NOT recreate /opt/stonk-ai/ENTRIES_HALTED. The resume handover
governs.**

---

# Handover: EXPERIMENT TERMINATED EARLY — entries halted (2026-07-27 10:05 HKT)

**From:** Einstein | **To:** Jeeves | **Priority:** HIGH — do not "fix" this

## What happened
Howie ended the StonkBOT trading experiment early this morning (owner decision,
~09:50 HKT), ahead of the Aug 29 verdict date. Rationale: 447-trade evidence
(PF 0.323, whipsaw tax $7,872 ≈ entire window loss) made the outcome clear;
the amended window was too small to overturn it statistically.

## What changed (commit c10c693, master)
- **ALL new entries + avg-ins are HALTED** via sentinel file
  `/opt/stonk-ai/ENTRIES_HALTED`, checked at the top of
  `_entry_blocked_by_guardrails()` in trading_bot.py (covers all buy paths).
- Exits/stops/trims/crisis exits CONTINUE unchanged — open positions close
  out under amended (A1) rules. A2 gates + measurement layer still run.
- EXPERIMENT.md has a "Terminated early - 2026-07-27" section with full detail.
- Sentinel added to .gitignore. Backup: backups/experiment-end-20260727-0958.tar.gz.

## DO NOT
- Do NOT remove /opt/stonk-ai/ENTRIES_HALTED. Resumption requires explicit
  owner decision + v3 pre-registration.
- Do NOT revert commit c10c693.
- Do NOT treat "entries halted: experiment ended early 2026-07-27" log lines
  as errors — they are the intended state.

## Expected runtime behavior
- At the next session open (21:30 HKT tonight), entry evaluations will log
  block reasons "entries halted: experiment ended early 2026-07-27 ...".
- Sell-side activity (stops/trims/exits) continues normally.
- If comprehensive_monitor or health checks alert on "no buy activity" or
  unusual gate-block volume, that is EXPECTED — adjust thresholds or annotate,
  don't page Howie.

## Still running (leave alone)
- factor_attribution.py cron (3x daily) — post-mortem pipeline, 158 round
  trips / 23 factor snapshots so far.
- entry_factor_snapshots.py cron — will see no new BUYs (expected).
- All data fetchers, signal engine, sync, site crons.

## Next
Einstein runs the factor deep-dive on the evidence window. Howie decides
index-vs-v3 with that study as input. Questions → agent-messages/einstein/.
