"""
Self-contained patch script to add v3 trend-pullback entry integration to trading_bot.py.
Run from /opt/stonk-ai as:
    python3 v3_rebuild/v3_trading_bot_patch.py
Then:
    python3 -m py_compile trading_bot.py
    restart bot
"""
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("/opt/stonk-ai")
BOT = ROOT / "trading_bot.py"

src = BOT.read_text()

# 1. Add V3_ENABLED to strategy_config import block
old_import = """    SIGNAL_FAIL_OPEN_EXTRA_HARD_CONF,
    OFF_HOURS_BEHAVIOR,
)
from signal_rules import has_required_positive_edge"""
new_import = """    SIGNAL_FAIL_OPEN_EXTRA_HARD_CONF,
    OFF_HOURS_BEHAVIOR,
    V3_ENABLED,
)
from signal_rules import has_required_positive_edge"""
if old_import in src:
    src = src.replace(old_import, new_import, 1)
    print("[1] Added V3_ENABLED import")
else:
    print("[1] V3_ENABLED import already present or block changed")

# 2. Add v3_signal_engine import
if "from v3_rebuild.v3_signal_engine import" not in src:
    src = src.replace(
        "from alert_logger import log_alert\n",
        "from alert_logger import log_alert\nfrom v3_rebuild.v3_signal_engine import compute_trend_pullback_score\n",
        1,
    )
    print("[2] Added v3_signal_engine import")
else:
    print("[2] v3_signal_engine import already present")

# 3. Add _run_v3_entries method just before _is_entry_eligible_for_mode
METHOD = '''    def _run_v3_entries(self, top_signals, current_symbols, portfolio_data, high_beta_symbols):
        """Run v3 trend-pullback entries using live daily bars."""
        from strategy_config import (
            V3_MAX_POSITIONS,
            V3_POSITION_PCT,
            V3_SCORE_THRESHOLD,
            V3_MELTDOWN_QQQ_5D_MAX,
            V3_EARNINGS_BLACKOUT_DAYS,
        )

        symbols = [s["symbol"] for s in top_signals if s["symbol"] not in current_symbols]
        if not symbols:
            logger.info("V3: no symbols to evaluate")
            return

        try:
            _hub = get_data_hub()
            bars = _hub.get_daily_bars(symbols + ["QQQ"], days=220)
            if "QQQ" not in bars or not bars["QQQ"].get("closes"):
                logger.warning("V3: QQQ bars missing; skipping v3 entries")
                return
            qqq_closes = bars["QQQ"]["closes"]
            qqq_5d = (qqq_closes[-1] - qqq_closes[-6]) / qqq_closes[-6] if len(qqq_closes) >= 6 else 0.0
            if qqq_5d < V3_MELTDOWN_QQQ_5D_MAX:
                logger.info(f"V3: QQQ 5d return {qqq_5d:.1%} below meltdown threshold; skipping entries")
                return
        except Exception as e:
            logger.warning(f"V3: failed to fetch daily bars: {e}")
            return

        scored = []
        for sig in top_signals:
            symbol = sig["symbol"]
            if symbol in current_symbols:
                continue
            b = bars.get(symbol)
            if not b or not b.get("closes") or len(b["closes"]) < 200:
                continue
            try:
                score, hard_blocked = compute_trend_pullback_score(
                    b["closes"], b.get("volumes", []), qqq_5d
                )
            except Exception as e:
                logger.debug(f"V3: score failed for {symbol}: {e}")
                continue
            if np.isnan(score):
                continue
            if hard_blocked:
                logger.info(f"V3: {symbol} hard blocked (score {score:.2f})")
                continue
            if score < V3_SCORE_THRESHOLD:
                continue
            scored.append({"sig": sig, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        open_slots = max(0, V3_MAX_POSITIONS - len(current_symbols))
        selected = scored[:open_slots]
        logger.info(f"V3: {len(selected)} candidates selected: {[s['sig']['symbol'] for s in selected]}")

        pv = portfolio_data["account"]["portfolio_value"]
        for item in selected:
            sig = item["sig"]
            symbol = sig["symbol"]
            price = sig.get("price") or sig.get("current_price") or 0
            if price <= 0:
                try:
                    _snap = get_data_hub().get_snapshot(symbol)
                    price = _snap.get("price") if _snap else None
                except Exception:
                    pass
            if price is None or price <= 0:
                logger.info(f"V3: {symbol} no valid price; skipping")
                continue

            earnings = sig.get("earnings") or {}
            if earnings and earnings.get("days_to_earnings", 999) <= V3_EARNINGS_BLACKOUT_DAYS:
                logger.info(f"V3: {symbol} within earnings blackout; skipping")
                continue

            _blocked = self._entry_blocked_by_guardrails(
                symbol,
                price=price,
                iv_30d=((sig.get("options_implied_vol") or {}).get("iv_30d") or 0),
                atr_pct=((sig.get("atr14") or 0) / sig.get("price") if sig.get("price") else 0),
            )
            if _blocked:
                logger.info(f"V3: {symbol} guardrail blocked: {_blocked}")
                continue

            target_notional = pv * V3_POSITION_PCT
            if self._high_beta_buy_blocked(symbol, target_notional, portfolio_data, high_beta_symbols):
                logger.info(f"V3: {symbol} high-beta basket cap")
                continue

            qty = max(1, int(target_notional / price))
            cost = qty * price
            cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
            if cost > (portfolio_data["account"]["cash"] - cash_floor):
                qty = max(0, int((portfolio_data["account"]["cash"] - cash_floor) / price))
                cost = qty * price
            if qty <= 0:
                continue

            trade = {
                "symbol": symbol,
                "qty": qty,
                "action": "BUY",
                "reason": f"V3 trend-pullback entry (score {item['score']:.2f})",
                "intended_notional": cost,
                "readiness_score": sig.get("readiness_score", 0),
                "tier": "PULLBACK",
            }
            self._execute_buy(trade, portfolio_data, is_avg_in=False)

'''

marker = '    def _is_entry_eligible_for_mode(self, sig: dict) -> bool:'
if marker in src and 'def _run_v3_entries' not in src:
    src = src.replace(marker, METHOD + marker, 1)
    print("[3] Inserted _run_v3_entries method")
elif 'def _run_v3_entries' in src:
    print("[3] _run_v3_entries method already present")
else:
    print("[3] ERROR: could not find insertion marker")
    raise SystemExit(1)

# 4. Insert v3 branch at top of RISK_ON entry logic
old_branch = '''        else:
            # RISK_ON: momentum strategy (default)
            logger.info("Searching for momentum entries (RISK_ON mode)...")'''
new_branch = '''        elif V3_ENABLED and self._regime == "RISK_ON":
            # V3: trend-pullback strategy takes over entry decisions in RISK_ON
            logger.info("Searching for v3 trend-pullback entries (RISK_ON mode)...")
            self._run_v3_entries(top_signals, current_symbols, portfolio_data, high_beta_symbols)
            return
        else:
            # RISK_ON: momentum strategy (default)
            logger.info("Searching for momentum entries (RISK_ON mode)...")'''
if old_branch in src:
    src = src.replace(old_branch, new_branch, 1)
    print("[4] Inserted v3 entry branch")
elif 'Searching for v3 trend-pullback' in src:
    print("[4] v3 entry branch already present")
else:
    print("[4] ERROR: could not find RISK_ON entry insertion point")
    raise SystemExit(1)

# 5. Write backup and patched file
backup = ROOT / "backups" / f"trading_bot-pre-v3-final-patch-{datetime.now().strftime('%Y%m%d-%H%M%S')}.py"
shutil.copy2(BOT, backup)
BOT.write_text(src)
print(f"[5] Patched trading_bot.py; backup: {backup}")
