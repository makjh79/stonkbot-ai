# Handover: trading RESUMED, experiment protocol ended (2026-07-27 10:13 HKT)

**From:** Einstein | **To:** Jeeves | **Priority:** HIGH — supersedes
handover-from-einstein-20260727.md

## What happened (timeline)
- 09:54 HKT: Howie ended the experiment; entries halted via sentinel
  (commit c10c693). Service restarted 10:02.
- **10:12 HKT: Howie reversed course — "continue trading per the strategy
  but there should be no more freeze."** Sentinel removed, service
  restarted 10:13, entry gate banner verified live.

## Current state (governs going forward)
- **Bot trades the full A1+A2 strategy normally, effective now.** New
  entries and avg-ins are allowed. Expect normal buy activity from the
  21:30 HKT session onward.
- **No freeze / no pre-registration requirement.** The experiment protocol
  in EXPERIMENT.md is formally ended (see the 10:12 addendum). Kill
  criteria are NOT active.
- The sentinel machinery stays in code, dormant
  (`_entry_blocked_by_guardrails` checks for
  `/opt/stonk-ai/ENTRIES_HALTED` — file absent = no-op). Do not delete the
  check; it's the owner's future circuit breaker.
- Do NOT recreate the sentinel. Do NOT revert c10c693 (it contains the
  EXPERIMENT.md record + .gitignore, and the dormant check is intentional).

## Monitor notes
- "entries halted" log lines should NOT appear anymore. If they do, the
  sentinel file reappeared — investigate, don't assume.
- Normal trading alerts apply. No special thresholds.

## Still running (unchanged)
- factor_attribution.py (3x daily) + entry_factor_snapshots.py (15-min) —
  now accumulating NEW trade snapshots again; this data feeds Einstein's
  factor deep-dive on the 447-trade evidence window + new trades.
- All data fetchers, signal engine, sync, site crons.

## Open items (owner-aware, no action needed from you)
- Site copy still references the Aug 29 verdict — Howie to decide copy.
- Einstein continues the attribution study; results to Howie first,
  then shared here.

Questions → agent-messages/einstein/.
