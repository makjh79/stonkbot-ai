# Memory Maintenance Report — 2026-07-05T19:00:53.111859Z

**Summary:** Memory is healthy with substantial July 1–4 operational updates needing consolidation, particularly around 10-factor confirmation chips, PEAD removal, tier alignment, and canonical confirmation count logic.

## Suggested Additions

- **Add:** Backend/frontend tier mapping: backend STRONG_NOW/NOW/WATCH/MONITOR → display PRIME/BUILDING/WATCHING/TRACKING. Only PRIME entry-eligible (readiness ≥77, confirmation_count ≥5, above_ema=True).
  - Reason: Fundamental architectural decision affecting all systems; repeated misalignment caused multiple bugs on July 4.

- **Add:** Confirmation count canonicalization: single source of truth is `compute_confirmation_count()` in `readiness_score.py`; counts only boolean confirmations (MOM/RSI/VOL/MACD/EMA/SEC/INT/OPT/RVOL/VWAP), excludes all 5 numeric scores. Frontend `buildFactorChips()` and `computeCanonicalConfirmationCount()` must match.
  - Reason: Caused multiple mismatches (SOFI 4 vs 3, UBER 6 vs 5, SNOW 7 vs 6); now resolved but needs to be durable knowledge.

- **Add:** Watchlist refresh: `_updateWatchlistTableDirectly()` patches DOM directly from `aiWatchlistPrices`, no text generation or sorting; 15s cadence.
  - Reason: Major infrastructure change replacing unreliable chained path; durable implementation fact.

- **Add:** Comprehensive monitor: silent when healthy (exit 0, 0 issues, 0 warnings); alerts only on degradation. Includes `check_trading_bot_entry_gate()`, `check_alpaca_portfolio_sync()`, `check_llm_narrative_freshness_and_validity()`, `check_alignment_signals_vs_watchlist()`.
  - Reason: Critical monitoring infrastructure; user explicitly requested silent-health behavior.

- **Add:** LLM narrative generator on VPS: `stonk-ai-llm-narrative.timer` every 15 min, 11 holdings + 20 watchlist narratives via `openrouter/moonshotai/kimi-k2.6`, 6-symbol batches. No Mac dependency. Throttled to 60 min during market hours.
  - Reason: Moved from Mac to VPS on 2026-07-01; key infrastructure fact.

- **Add:** Bot v2.5 config: 12% STRONG_NOW position cap, 8% others; readiness multipliers 3.0×/1.5×/0.5×/blocked; top-12 entry cap; 5-day minimum hold; -5% hard cut; cash gate; RISK_OFF STRONG_NOW-only; 5s refresh; bot aligned to watchlist (top 20 symbols only).
  - Reason: Core trading parameters from Einstein's canonical config; needed for consistent bot behavior.

- **Add:** CRWD stock-split auto-detection via `split_guardian.py`.
  - Reason: Infrastructure automation; durable fact.

- **Add:** Jeeves health alert cron: DISABLED — Einstein handles health checks now.
  - Reason: Operational handover fact; prevents confusion about which system is responsible.

- **Add:** Agent workspace paths: Einstein `/root/.openclaw/workspace/` on VPS; Jeeves VPS/Ollama primary; message relay at `/opt/stonk-ai/agent-messages/{einstein,jeeves}/`.
  - Reason: Needed for cross-agent coordination; used for memory sync on July 4.

- **Add:** Cache buster current: `stonkbot_v165` (as of July 4 tier display + conf badge fixes).
  - Reason: Operational reference point; frequent changes make this ephemeral but useful short-term.

## Suggested Removals

- **Remove:** Finnhub key: `~/.openclaw/workspace/.secrets/finnhub.key` (chmod 600) — no longer used, kept for reference only.
  - Reason: Already noted as 'no longer used'; could be removed or kept as historical. Suggest removal to reduce clutter since 'kept for reference only' is itself clutter-sensitive.

- **Remove:** Jeeves health alert cron: every 5 min `*/5 * * * *` (DISABLED)
  - Reason: Superseded by explicit 'DISABLED' note in July 4 memory; the cron line itself is outdated.

- **Remove:** Live/stale indicator removed entirely.
  - Reason: Already captured as done; no longer relevant to current state.

- **Remove:** 🚀 emoji removed from tier labels per Howie preference.
  - Reason: Historical UI decision already implemented; not needed for future operation.

## Contradictions

- **Old:** Confirmation count computed differently in frontend vs backend (SOFI showed 4 in chips but 3 in backend/LLM; UBER 6 vs 5; SNOW 7 vs 6).
  **New:** Single canonical `compute_confirmation_count()` in `readiness_score.py`; all systems derive from `confirmations` dict; monitor flags drift.
  **Resolution:** Use canonical version. Old per-system computation is deprecated.

- **Old:** Watchlist 'AI Score' column showed confusing numeric score; BUILDING symbols appeared as 'Next Buys' via diversification branch.
  **New:** Watchlist shows 'Conf' (confirmations /10) column; only PRIME queued/add candidates appear as 'Next Buys'; diversification branch removed.
  **Resolution:** Use new column and filtering. Old AI Score column and diversification branch removed.

- **Old:** Tier labels showed backend names (STRONG_NOW, NOW, WATCH, MONITOR) in some places.
  **New:** All user-facing displays use PRIME/BUILDING/WATCHING/TRACKING; backend names only in code.
  **Resolution:** Use display_tier consistently; prefer display_tier over signal_tier everywhere.

- **Old:** Readiness weights 9-factor with /9 denominator (signal 25%, sector 25%, EMA 15%, RSI 10%, intraday 10%, MACD 8%, volume 5%, options 5%, relative volume 5%).
  **New:** Readiness weights 10-factor normalized to 100%: signal 20%, sector 30%, EMA 12%, RSI 10%, intraday 10%, MACD 8%, volume 5%, options IV 5%, relative volume 5%, VWAP 5%.
  **Resolution:** Use 10-factor weights; VWAP added, signal reduced, sector increased.

## Low Priority

- Specific backup paths for each July 4 patch (14 files in 2026-07-04-einstein, end-to-end-align, patch-gemini-fixes, tier-align-option-b, e2e-tier-align, 20260704-2345-comprehensive).
  - Backups are ephemeral operational artifacts; only current backup strategy matters.
- Detailed narrative v2/v3 popup content structure (What It Is, Why We Own It, etc.).
  - Content schema is implementation detail; likely to evolve further.
- Specific RSI chip rule change (neutral/oversold now counted).
  - Covered by canonical confirmation count; per-chip rules should follow canonical source.
- Individual cache buster versions (v145 through v165 chronology).
  - Only current value matters operationally; history is in git/deploy logs.
- Lessons learned list (numeric-score exclusion, canonical paths, scheduler status files, case-insensitive mode matching, stub removal, cash-only guard placement, IV migration consumers, thesis-exit minimum hold, broken stubs surviving in production).
  - Valuable but belongs in runbook/lessons doc, not long-term memory; too granular and likely to accumulate.
- Session status summary table (stonk-ai.service v2.5 PAPER, deduped timers, etc.).
  - Ephemeral status snapshot; current state changes continuously.

---

This report was generated by the VPS memory maintenance script. It does not modify MEMORY.md unless explicitly applied.