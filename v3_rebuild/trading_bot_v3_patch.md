# STONK.AI v3 Patch for `trading_bot.py`

**Draft only. Do not apply tonight.** Review and apply on Monday when fresh.

## Goal

Add a `V3_ENABLED` config flag. When true, use the v3 trend-pullback signal
engine instead of the v2.5 readiness_score composite for entry decisions.

## Changes

### 1. Add import near line 95

```python
from v3_rebuild.v3_signal_engine import score_row
```

### 2. Add config flag

Add to `strategy_config.py`:

```python
V3_ENABLED = False  # Set to True to use trend-pullback engine
V3_MAX_POSITIONS = 15
V3_POSITION_PCT = 0.03
V3_HOLD_DAYS = 5
V3_SCORE_THRESHOLD = 0.5
```

### 3. Add v3 scoring in `run_cycle()` before the existing entry logic

Locate this block:

```python
else:
    # RISK_ON: momentum strategy (default)
    logger.info("Searching for momentum entries (RISK_ON mode)...")
```

Change to:

```python
else:
    if V3_ENABLED:
        logger.info("Searching for v3 trend-pullback entries (RISK_ON mode)...")
        self._run_v3_entries(top_signals, current_symbols)
        return
    # RISK_ON: momentum strategy (default)
    logger.info("Searching for momentum entries (RISK_ON mode)...")
```

### 4. Add `_run_v3_entries()` method

Insert near `_is_entry_eligible_for_mode()`:

```python
def _run_v3_entries(self, top_signals, current_symbols):
    """Run v3 trend-pullback entry logic."""
    from strategy_config import V3_MAX_POSITIONS, V3_POSITION_PCT, V3_SCORE_THRESHOLD

    v3_candidates = []
    for sig in top_signals:
        symbol = sig.get("symbol")
        if symbol in current_symbols:
            continue
        # Compute v3 score from signal features
        row = {
            "dist_ema200": sig.get("dist_ema200"),
            "dist_ema50": sig.get("dist_ema50"),
            "dist_ema20": sig.get("dist_ema20"),
            "ret_5d": sig.get("ret_5d"),
            "rsi14": sig.get("rsi14"),
            "vs_qqq_5d": sig.get("vs_qqq_5d"),
            "vol_ratio": sig.get("vol_ratio"),
        }
        score, hard_blocked = score_row(row)
        if np.isnan(score):
            continue
        if hard_blocked:
            self._log_gate_block(symbol, "v3_hard_block", f"score={score:.2f}", sig.get("price", 0))
            continue
        if score < V3_SCORE_THRESHOLD:
            continue
        sig["v3_score"] = score
        v3_candidates.append(sig)

    v3_candidates.sort(key=lambda s: s.get("v3_score", 0), reverse=True)
    selected = v3_candidates[:V3_MAX_POSITIONS]

    logger.info(f"V3 selected {len(selected)} candidates: {[s['symbol'] for s in selected]}")

    for sig in selected:
        symbol = sig["symbol"]
        price = sig.get("price") or sig.get("current_price") or 0
        _blocked = self._entry_blocked_by_guardrails(
            symbol,
            price=price,
            iv_30d=((sig.get("options_implied_vol") or {}).get("iv_30d") or 0),
            atr_pct=((sig.get("atr14") or 0) / sig.get("price") if sig.get("price") else 0),
        )
        if _blocked:
            continue
        # Use v3 position size cap
        target_pct = V3_POSITION_PCT
        qty = self._size_buy(symbol, price, target_pct=target_pct, tier="PULLBACK")
        if qty <= 0:
            continue
        self._execute_buy(symbol, qty, price, tier="PULLBACK", signal=sig)
```

### 5. Add v3 features to signal generation

`signal_engine.py` must output `dist_ema200`, `dist_ema50`, `dist_ema20`, `ret_5d`,
`rsi14`, `vs_qqq_5d`, `vol_ratio` in each signal dict so `score_row()` can work.

Alternatively, have `_run_v3_entries()` fetch daily bars and call
`compute_trend_pullback_score()` directly. The row-based approach is faster
if signal_engine already computes these features.

### 6. Hold period / exit logic

The current bot exits based on stops/trim/thesis. For v3, add a **time-based
exit** at 5 days. Insert in the position-monitoring section:

```python
# v3 time-based exit
if V3_ENABLED:
    for pos in current_positions:
        entry_date = pos.get("entry_date")
        if entry_date and (today - entry_date) >= V3_HOLD_DAYS:
            self._sell_position(pos, reason="v3_5d_hold_expired")
```

This requires tracking `entry_date` per position; it may already exist in
`portfolio.json`.

### 7. Logging and comparison

When `V3_ENABLED=False`, still optionally compute and log top-3 v3 scores for
comparison. This helps validate before flipping the flag.

## Safety rules for applying

1. Apply only when bot is in Park mode (`ENTRIES_HALTED` present).
2. Set `V3_ENABLED=False` initially.
3. Restart bot and confirm it loads cleanly.
4. Enable side-by-side v3 logging for 1–2 sessions.
5. Then set `V3_ENABLED=True` only in **paper mode**.
6. Run paper for 20+ sessions.
7. Only then consider live mode and remove `ENTRIES_HALTED`.

## Rollback

```bash
cp backups/trading_bot-pre-v3-sidecar-*.py /opt/stonk-ai/trading_bot.py
touch /opt/stonk-ai/ENTRIES_HALUTED
# restart bot
```
