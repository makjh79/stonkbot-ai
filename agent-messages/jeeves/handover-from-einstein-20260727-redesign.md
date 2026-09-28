# Handover from Einstein — Signal Redesign & Entry Halt
**Date:** 2026-07-27 11:50 HKT  
**From:** Einstein (OpenClaw)  
**To:** Jeeves  
**Priority:** HIGH — do not revert without owner approval

---

## What happened

Owner approved **Option C**: halt new entries, rebuild the entry signal from attribution data, validate paper-only for 4–6 weeks.

## Changes made 2026-07-27

### 1. Entries halted
- `/opt/stonk-ai/ENTRIES_HALTED` sentinel in place
- ALL new entries and avg-ins blocked at `_entry_blocked_by_guardrails()`
- Existing 4 positions (AAPL, ELF, PAYO, ROKU) continue on their own exits/stops/trims — untouched
- Service restarted clean at 11:49 HKT

### 2. Signal redesign committed and pushed to GitHub
Commit: `e94565a` on master

**`signal_rules.py`:**
- `ENTRY_READINESS_MIN`: 75.0 → **80.0**
- `ENTRY_MIN_CONFIRMATIONS`: 5 → **6**
- `ENTRY_MIN_HARD_CONFIRMATIONS`: 1 → **2**
- `HARD_CONFIRMATION_KEYS`: removed `macd_turning`, added `vwap_confirmed`
  - New set: `{volume_confirmed, intraday_confirmed, options_confirmed, vwap_confirmed, relvol_confirmed}`

**`readiness_score.py`:**
- `WEIGHT_MACD`: 0.08 → **0.00** (attribution -19pp edge)
- `WEIGHT_RSI`: 0.10 → **0.00** (attribution -13pp edge)
- `WEIGHT_VOLUME`: 0.05 → **0.10** (volume/relvol +31pp edge)
- `WEIGHT_OPTIONS`: 0.05 → **0.10** (options flow +9.8pp edge)
- `WEIGHT_VWAP_DEV`: 0.05 → **0.10** (VWAP +3.1pp edge)
- `WEIGHT_INTRADAY`: 0.10 → **0.05** (intraday -2.2pp edge)
- `WEIGHT_SIGNAL`: 0.20 → **0.25** (compensate for removed factors)
- `WEIGHT_SECTOR`: 0.30 → **0.25** (stabilizer)

**`trading_bot.py`:**
- Halt message updated: "entries halted: signal redesign in progress"
- Startup banner updated: "Entry gate: readiness >= 80 AND >= 6 confirmations"

**`REDESIGN.md`:** added with full rationale, thin-data caveat, and validation protocol.

### 3. Site copy updated
- "Aug 29" references removed (3 occurrences)
- "verdict" changed to "pending validation"
- "real money" changed to "paper capital"
- Deployed to live root, verified identical

## Why

Factor attribution on 23 snapshot-backed round trips showed:
- Composite readiness score has **zero correlation** with outcomes (r = -0.012)
- MACD edge: **-19pp** | RSI edge: **-13pp** | QBI edge: **-25pp**
- Only positive edges: volume/relvol (+31pp, n=2), spread (+22.7pp), options flow (+9.8pp), VWAP (+3.1pp)

The snapshot data is thin (27 snapshots) because `entry_factor_snapshots.py` refuses to backfill old trades honestly. The redesign is a defensible simplification, not a trained model.

## Validation protocol
1. Keep entries halted for **4–6 weeks minimum**
2. Monitor `signals.json` output daily — confirm fewer false positives
3. When entries resume (initially at 0.5–1% size), allow snapshotter to capture ~50–100 honest snapshots
4. Re-run `factor_attribution.py`. Success criteria before sizing up:
   - Profit factor > 1.0
   - Win rate > 40%
   - Readiness correlation > 0.10
   - No factor with edge < -10pp

## What does NOT change
- Existing positions keep current exits/stops/trims
- Paper trading mode unchanged
- Attribution pipeline (`entry_factor_snapshots.py`, `factor_attribution.py`) continues running
- Earnings gate, implied-move gate, sector caps, cooldowns all unchanged

## How to resume entries later
Only when validation passes and owner approves:
```bash
cd /opt/stonk-ai
sudo -u stonkai rm ENTRIES_HALTED
sudo systemctl restart stonk-ai
```

## Backups
- `/opt/stonk-ai/signal_rules.py.bak-20260727-redesign`
- `/opt/stonk-ai/readiness_score.py.bak-20260727-redesign`
- `/opt/stonk-ai/website/index.html.bak-20260727-copy`

## Related docs
- `/opt/stonk-ai/REDESIGN.md` — full redesign rationale
- `/opt/stonk-ai/EXPERIMENT.md` — original protocol (now ended)
- `factor_attribution.json` — latest factor edges

---

**Do not revert the signal changes or remove the halt without explicit owner approval.**
