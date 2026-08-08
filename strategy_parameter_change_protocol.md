# Strategy Parameter Change Protocol

Applies to any change in `strategy_config.py`, `signal_rules.py`, `readiness_score.py`,
`signal_engine.py`, `risk_engine.py`, `trading_bot.py`, or any narrative script that
explains the strategy.

## 0. Decision gate
- Strategy changes are only made by owner decision or for data-integrity / safety reasons.
- No "just see what happens" changes. Every change must be pre-registered in `EXPERIMENT.md`.

## 1. Pre-registration
- Update `EXPERIMENT.md` BEFORE changing code:
  - What is changing and why (attribution/evidence).
  - Exact window (start date, end date, or min number of trades).
  - Keep/kill/rollback criteria.
  - Risks and rollback command.
- If the change is complex, pause entries via `ENTRIES_HALTED` while reconciling.

## 2. Single source of truth
- Change parameters ONLY in `strategy_config.py`.
- Run `python3 -c "import strategy_config; strategy_config.validate()"`.
- Re-export `config_truth.json` if website uses it.

## 3. Downstream consistency sweep
Check every consumer of strategy parameters and update if needed:
- `signal_rules.py` — tier/entry helpers.
- `readiness_score.py` — weights, vetoes, entry gate.
- `signal_engine.py` — no hardcoded gates; derive from `strategy_config`.
- `trading_bot.py` — entry eligibility and paper fallback.
- `paper_rebalancer.py` — entry eligibility usage.
- `risk_engine.py` — caps/stops interaction.

## 4. Narrative / LLM prompt sync
- `generate_narratives_llm_batched.py`
- `generate_popup_content_narrative_v2.py`
- `generate_popup_content_v3.py`
- `generate_popup_content_v3_full.py`
- `generate_thinking_explainers.py`

Prompts must not contradict `strategy_config.py`. Hard confirmations and weights in
prompts must mirror the config-of-truth.

## 5. Website sync
Run `website_strategy_sync_checklist.md`:
- About / Live Rules panel.
- Readiness tooltip.
- How it works / strategy cards.
- Race / hero one-liner.
- FAQ.
- Cache-bust query string.
- Deploy to `/var/www/hedge-fund-website`.
- Smoke test.

## 6. Validation
Run `validate_strategy_consistency.py`:
```bash
python3 validate_strategy_consistency.py
```
It checks:
- `REQUIRED_POSITIVE_HARD_KEYS` subset of `HARD_CONFIRMATION_KEYS`.
- `signal_engine.py` does not hardcode a different gate.
- `signal_rules.py` / `readiness_score.py` / `trading_bot.py` use `all()` over
  `REQUIRED_POSITIVE_HARD_KEYS`.
- `strategy_config.validate()` passes.

Also run `py_compile` on all changed files.

## 7. Restart and monitor
- Restart `stonk-ai.service`.
- Run one full signal cycle.
- Check `comprehensive_monitor.py` for `check_strategy_config_drift()` alert.
- Only then decide whether to remove `ENTRIES_HALTED`.

## 8. Measurement
- Use `factor_attribution.py` and `risk_stats.json` to evaluate the change.
- Do not declare success before the pre-registered window/criteria are met.

## 9. Commit and push
- One logical commit with: code changes, docs, protocol, checklist.
- Backup pre-change files to `/opt/stonk-ai/backups/`.

## 10. Rollback
- Revert code, remove `ENTRIES_HALTED` only if rolling forward, and update
  `EXPERIMENT.md` with outcome.
