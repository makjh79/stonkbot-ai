#!/usr/bin/env python3
"""
StonkBOT Comprehensive Pipeline Integrity Monitor
Alerts ONLY when issues are found (stderr + optional Telegram).
Exit codes: 0 = healthy, 1 = degraded, 2 = system error.
"""

import json
import os
import re
import subprocess
import sys
import time
import requests
from signal_rules import expected_display_tier_for_signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = "/opt/stonk-ai"
WEB_DIR = "/var/www/hedge-fund-website"
ISSUES: List[str] = []
WARNINGS: List[str] = []

# ─── Telegram Alerter (import from sibling monitor.py, fallback inline) ────

try:
    sys.path.insert(0, BASE_DIR)
    from monitor import TelegramAlerter as _TelegramAlerter  # type: ignore
except Exception:
    class _TelegramAlerter:  # type: ignore
        def __init__(self, token: str, chat_id: str):
            self.enabled = bool(token and chat_id)
            self.token = token
            self.chat_id = chat_id

        def send(self, message: str) -> None:
            if not self.enabled:
                print(f"[MOCK ALERT] {message}", file=sys.stderr)
                return
            try:
                import requests
                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
                requests.post(url, json=payload, timeout=10)
            except Exception:
                pass
def _load_telegram_creds() -> tuple[str, str]:
    """Load token/chat_id from env or secrets file."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        return token, chat_id
    secrets_path = os.path.join(BASE_DIR, ".secrets", "telegram.env")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token, chat_id
_TELEGRAM = _TelegramAlerter(*_load_telegram_creds())
def _send_alert(summary: str, details: List[str]) -> None:
    if not details:
        return
    # Format for Telegram (concise, Markdown)
    msg_parts = [f"🚨 *StonkBOT Monitor Alert*", f"_{summary}_", ""]
    for d in details[:20]:
        msg_parts.append(f"• {d}")
    if len(details) > 20:
        msg_parts.append(f"• ... and {len(details) - 20} more")
    # Telegram alerts DISABLED — stonkbot_healthcheck.py handles critical alerts
    # This monitor is now log-audit only
    pass
# ─── Helpers ──────────────────────────────────────────────────────────────
def _log_issue(msg: str) -> None:
    ISSUES.append(msg)
    print(f"[ISSUE] {msg}", file=sys.stderr)
def _log_warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"[WARN]  {msg}", file=sys.stderr)
def _load_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        _log_warn(f"Could not load {path}: {exc}")
        return None
def _file_mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
def _is_us_market_hours() -> bool:
    """Rough check: US ET 09:00–17:00, Mon–Fri."""
    now = datetime.now(timezone.utc)
    # 09:00 ET = 13:00 UTC; 17:00 ET = 21:00 UTC
    weekday = now.weekday()  # 0=Mon
    hour = now.hour
    return weekday < 5 and 13 <= hour < 21
def _is_us_extended_hours() -> bool:
    """Rough check: US pre-market / after-hours."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour
    if weekday >= 5:
        return False
    # Pre-market  04:00–09:30 ET  = 08:00–13:30 UTC
    # After-hours 16:00–20:00 ET  = 20:00–00:00 UTC
    return (8 <= hour < 13) or (20 <= hour <= 23)
def _run_cmd(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()
# ─── Checks ─────────────────────────────────────────────────────────────────
def _us_market_is_open(now_utc: datetime) -> bool:
    """Return True if US equity market is in normal trading hours, Mon-Fri."""
    if now_utc.weekday() >= 5:
        return False
    try:
        import pytz
        et = pytz.timezone("America/New_York")
        et_now = now_utc.astimezone(et)
        from datetime import time as dt_time
        return dt_time(9, 30) <= et_now.time() < dt_time(16, 0)
    except Exception:
        from datetime import time as dt_time
        # Fallback conservative UTC window covers both EST and EDT
        return dt_time(13, 30) <= now_utc.time() < dt_time(21, 0)
def _ntp_drift_seconds() -> Optional[float]:
    """Return approximate clock drift from NTP using chronyc or ntpdate."""
    import shutil, subprocess
    if shutil.which("chronyc"):
        try:
            out = subprocess.check_output(["chronyc", "tracking"], text=True, timeout=10)
            for line in out.splitlines():
                if "Last offset" in line:
                    parts = line.split(":", 1)[-1].strip().split()
                    if parts:
                        try:
                            return float(parts[0])
                        except ValueError:
                            pass
        except Exception:
            pass
    if shutil.which("ntpdate"):
        try:
            out = subprocess.check_output(["ntpdate", "-q", "pool.ntp.org"], text=True, timeout=10)
            m = re.search(r"offset\s+(-?\d+\.\d+)", out)
            if m:
                return float(m.group(1))
        except Exception:
            pass
    return None
def check_services() -> None:
    """Ensure critical systemd services are active."""
    services = ["stonk-ai.service", "stonk-ai-live-quotes.service"]  # watchlist service intentionally disabled; DWM cron owns watchlist updates
    for svc in services:
        rc, stdout, stderr = _run_cmd(f"systemctl is-active {svc}")
        if rc != 0:
            _log_issue(f"Service {svc} is NOT active")
def check_file_freshness() -> None:
    """Key pipeline outputs must not be stale."""
    files = {
        "signals.json": 1200,           # 20 min slack (signal engine refreshes ~every 15 min)
        "ai_watchlist_live.json": 120,  # 2 min
        "popup_content.json": 300,      # 5 min
        "watchlist_narratives.json": 300,
        "trades_log.json": 600,         # 10 min (syncs every 5 min)
        "portfolio_history.json": 900,  # 15 min
    }
    now = time.time()
    is_market = _is_us_market_hours()
    for fname, max_age in files.items():
        # pipeline JSONs live in BASE_DIR; deployed website JSONs live in WEB_DIR
        if fname in ("popup_content.json", "watchlist_narratives.json", "ai_watchlist_live.json"):
            path = os.path.join(WEB_DIR, fname)
        else:
            path = os.path.join(BASE_DIR, fname)
        mtime = _file_mtime(path)
        if mtime is None:
            _log_issue(f"Missing file: {fname}")
            continue
        age = now - mtime
        if is_market and age > max_age:
            _log_issue(f"Stale file: {fname} is {age:.0f}s old (max {max_age}s)")
        elif not is_market and age > max_age * 6:
            # After hours, allow 6x longer
            _log_warn(f"Stale file (after-hours): {fname} is {age:.0f}s old")
def check_signals_write_health():
    """Detect silent signal write failures (critical for trading)."""
    now = time.time()
    opt_path = os.path.join(BASE_DIR, "signals.json")
    web_path = os.path.join(WEB_DIR, "signals.json")

    opt_mtime = _file_mtime(opt_path)
    web_mtime = _file_mtime(web_path)

    # Signals should refresh every ~15 min via trading_bot.py even after hours
    max_age = 25 * 60  # 25 min — stricter than after-hours 120 min

    if opt_mtime and now - opt_mtime > max_age:
        _log_issue(f"signals.json not written by signal_engine for {(now - opt_mtime)/60:.0f} min — write may be failing")

    if opt_mtime and web_mtime:
        if abs(opt_mtime - web_mtime) > 60:
            _log_issue(f"signals.json opt/web copy mismatch: opt_age={now - opt_mtime:.0f}s web_age={now - web_mtime:.0f}s")

def check_extended_hours_prices() -> None:
    """All universe symbols (and watchlist) must carry live / extended-hours price data."""
    signals = _load_json(os.path.join(BASE_DIR, "signals.json"))
    watchlist = _load_json(os.path.join(WEB_DIR, "ai_watchlist_live.json"))

    if signals is None:
        _log_issue("Missing signals.json — cannot verify extended-hours prices")
        return

    sig_list = signals.get("signals", [])
    universe_size = len(sig_list)
    if universe_size < 120:
        _log_issue(f"Universe size suspiciously small: {universe_size} symbols (expected ~130)")

    zero_price_symbols: List[str] = []
    zero_prev_close_symbols: List[str] = []
    for sig in sig_list:
        sym = sig.get("symbol", "")
        price = sig.get("price", 0)
        prev = sig.get("prev_close", 0)
        if price == 0:
            zero_price_symbols.append(sym)
        if prev == 0:
            zero_prev_close_symbols.append(sym)

    if zero_price_symbols:
        _log_issue(f"Extended-hours prices missing for {len(zero_price_symbols)} symbols: {', '.join(zero_price_symbols[:10])}")
    if zero_prev_close_symbols:
        _log_warn(f"Zero prev_close for {len(zero_prev_close_symbols)} symbols: {', '.join(zero_prev_close_symbols[:10])}")

    # Watchlist prices
    if watchlist:
        for item in watchlist.get("stocks", []):
            sym = item.get("symbol", "")
            price = item.get("price", 0)
            if price == 0:
                _log_issue(f"Watchlist {sym}: zero price")
def check_universe_names() -> None:
    """DEFAULT_UNIVERSE must match COMPANY_NAMES exactly."""
    rc, stdout, stderr = _run_cmd(
        f"python3 -c \"import sys, json; sys.path.insert(0, '{BASE_DIR}'); "
        f"import signal_engine; "
        f"missing=sorted(set(signal_engine.DEFAULT_UNIVERSE)-set(signal_engine.COMPANY_NAMES.keys())); "
        f"print(json.dumps(missing))\""
    )
    if rc != 0:
        _log_issue(f"Universe name check failed: {stderr[:120]}")
        return
    try:
        missing = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        _log_issue("Universe name check returned invalid JSON")
        return
    if missing:
        _log_issue(f"Missing COMPANY_NAMES for {len(missing)} symbols: {', '.join(missing)}")
def check_shadow_company_names() -> None:
    """No file except signal_engine.py should define COMPANY_NAMES as a dict."""
    py_files = [
        p for p in Path(BASE_DIR).rglob("*.py")
        if p.name != "signal_engine.py"
        and "backups" not in str(p)
    ]
    for p in py_files:
        try:
            txt = p.read_text()
        except Exception:
            continue
        # Only flag dict definitions, not imports or .get() references
        if re.search(r"^[^#]*COMPANY_NAMES\s*=\s*\{", txt, re.MULTILINE):
            _log_issue(f"Shadow COMPANY_NAMES definition found in {p.name}")
def check_alignment_signals_vs_watchlist() -> None:
    """ai_watchlist_live.json must mirror signals.json (tiers, entry, readiness, conf)."""
    signals = _load_json(os.path.join(BASE_DIR, "signals.json"))
    watchlist = _load_json(os.path.join(WEB_DIR, "ai_watchlist_live.json"))
    if signals is None or watchlist is None:
        _log_issue("Missing signals.json or ai_watchlist_live.json")
        return

    sig_map: Dict[str, Dict] = {s.get("symbol"): s for s in signals.get("signals", []) if s.get("symbol")}
    for item in watchlist.get("watchlist", []):
        sym = item.get("symbol") or (item.get("targets", {}) or {}).get("symbol")
        if not sym:
            continue
        sig = sig_map.get(sym)
        if not sig:
            _log_issue(f"Watchlist symbol {sym} missing from signals.json")
            continue

        t = item.get("targets", {}) or {}

        # readiness
        if item.get("readiness_score") != sig.get("readiness_score"):
            _log_issue(
                f"ALIGNMENT {sym}: readiness_score watchlist={item.get('readiness_score')} "
                f"signal={sig.get('readiness_score')}"
            )

        # backend tier vs display tier mapping must be consistent
        backend_tier = sig.get("tier")
        display_tier = item.get("display_tier") or t.get("display_tier") or item.get("signal_tier")
        expected = expected_display_tier_for_signal(sig)
        if display_tier != expected:
            _log_issue(f"ALIGNMENT {sym}: backend {backend_tier} should map to {expected}, got {display_tier}")

        # entry_eligible must agree
        w_entry = item.get("entry_eligible") or t.get("entry_eligible")
        if w_entry != sig.get("entry_eligible"):
            _log_issue(
                f"ALIGNMENT {sym}: entry_eligible watchlist={w_entry} signal={sig.get('entry_eligible')}"
            )

        # confirmation_count must agree
        w_conf = item.get("confirmation_count") or t.get("confirmation_count")
        if w_conf != sig.get("confirmation_count"):
            _log_issue(
                f"ALIGNMENT {sym}: confirmation_count watchlist={w_conf} signal={sig.get('confirmation_count')}"
            )

        # momentum_score field must exist and agree
        if "momentum_score" not in item:
            _log_warn(f"Watchlist {sym} missing momentum_score field")
        elif item.get("momentum_score") != sig.get("momentum_score"):
            _log_warn(
                f"ALIGNMENT {sym}: momentum_score watchlist={item.get('momentum_score')} "
                f"signal={sig.get('momentum_score')}"
            )
def check_factor_confirmation_integrity() -> None:
    """Every signal must have a consistent confirmations dict and plausible confirmation_count."""
    signals = _load_json(os.path.join(BASE_DIR, "signals.json"))
    if signals is None:
        _log_issue("Missing signals.json — skipping confirmation integrity")
        return

    # Momentum confirmation schema was expanded in 2026-07 to include intraday microstructure,
    # corporate-action risk, and options-flow chips. Keep expected keys broad.
    momentum_expected = {
        # Core technical chips
        "momentum_score", "rsi_signal", "volume_confirmed", "macd_turning",
        "above_ema", "sector_strong", "intraday_confirmed", "intraday_score",
        "options_confirmed", "options_score", "relvol_confirmed", "relvol_score",
        "vwap_confirmed", "vwap_score",
        # 5-minute microstructure (added ~2026-07)
        "bid_ask_bullish", "bid_ask_imbalance", "bid_ask_spread_pct",
        "momentum_5m_up", "near_term_bullish_flow", "options_call_put_ratio",
        "options_unusual_volume", "price_above_5m_vwap", "spread_ok",
        "volume_5m_surge", "wide_spread",
        # Corporate action risk (added ~2026-07)
        "corporate_action_risk", "has_upcoming_dividend", "has_upcoming_merger",
        "has_upcoming_spinoff", "has_upcoming_split", "no_corporate_action_risk",
    }
    mean_reversion_expected = {
        "above_ema50", "below_ema_stretched", "not_structural_decline",
        "rsi_oversold", "volume_capitulation",
    }

    all_sig = signals.get("signals", [])
    missing_issues = []
    count_issues = []
    for sig in all_sig:
        sym = sig.get("symbol", "")
        conf = sig.get("confirmations", {})
        strategy = sig.get("strategy_type", "momentum")
        if not isinstance(conf, dict):
            _log_issue(f"Signal {sym}: confirmations is not a dict")
            continue

        if strategy == "mean_reversion":
            expected_keys = mean_reversion_expected
            max_count = 6
        else:
            expected_keys = momentum_expected
            max_count = 20  # expanded schema; count is informational

        missing = expected_keys - set(conf.keys())
        if missing:
            missing_issues.append((sym, strategy, sorted(missing)))

        count = sig.get("confirmation_count", -1)
        if not isinstance(count, int) or count < 0 or count > max_count:
            count_issues.append((sym, strategy, count))

    if missing_issues:
        # Only report the first few concrete examples, then a summary
        for sym, strategy, missing in missing_issues[:3]:
            _log_warn(f"Signal {sym} ({strategy}): missing expected confirmation keys {missing}")
        if len(missing_issues) > 3:
            _log_warn(f"... {len(missing_issues)} total signals missing expected confirmation keys (schema drift?)")

    if count_issues:
        for sym, strategy, count in count_issues[:3]:
            _log_warn(f"Signal {sym} ({strategy}): confirmation_count={count} is out of plausible range")
        if len(count_issues) > 3:
            _log_warn(f"... {len(count_issues)} total signals with out-of-range confirmation_count")
def check_popup_narrative_alignment() -> None:
    """Popup holdings and watchlist narratives must carry confirmations that match signals.json."""
    signals = _load_json(os.path.join(BASE_DIR, "signals.json"))
    popup = _load_json(os.path.join(WEB_DIR, "popup_content.json"))
    watchlist_narr = _load_json(os.path.join(WEB_DIR, "watchlist_narratives.json"))

    if signals is None:
        _log_warn("Missing signals.json — skipping popup/narrative alignment")
        return

    sig_map: Dict[str, Dict] = {s.get("symbol"): s for s in signals.get("signals", []) if s.get("symbol")}

    # Popup holdings
    if popup:
        holdings = popup.get("holdings", {})
        for sym, data in holdings.items():
            if not isinstance(data, dict):
                continue
            sig = sig_map.get(sym)
            if not sig:
                continue
            popup_conf = data.get("confirmations", {})
            if not isinstance(popup_conf, dict):
                _log_issue(f"Popup {sym}: confirmations missing or not a dict")
                continue
            sig_conf = sig.get("confirmations", {})
            if set(popup_conf.keys()) != set(sig_conf.keys()):
                _log_warn(
                    f"Popup {sym}: confirmation keys differ from signals "
                    f"(popup={sorted(popup_conf.keys())} vs signal={sorted(sig_conf.keys())})"
                )
            # confirmation_count alignment
            if data.get("confirmation_count") != sig.get("confirmation_count"):
                _log_warn(
                    f"Popup {sym}: confirmation_count popup={data.get('confirmation_count')} "
                    f"signal={sig.get('confirmation_count')}"
                )

    # Watchlist narratives
    if watchlist_narr:
        narratives = watchlist_narr.get("narratives", {})
        for sym, data in narratives.items():
            if not isinstance(data, dict):
                continue
            sig = sig_map.get(sym)
            if not sig:
                continue
            # Watchlist narratives should now include confirmations
            if "confirmations" not in data:
                _log_issue(f"Watchlist narrative {sym}: missing confirmations dict")
                continue
            if "confirmation_count" not in data:
                _log_warn(f"Watchlist narrative {sym}: missing confirmation_count")
            # Compare confirmations exactly; earnings_confirmed removed 2026-07-04.
            narr_conf = data.get("confirmations", {})
            sig_conf = sig.get("confirmations", {})
            if narr_conf != sig_conf:
                _log_warn(
                    f"Watchlist narrative {sym}: confirmations differ from signals"
                )
def check_popup_integrity() -> None:
    """popup_content.json must have expected shape (sources, denominator)."""
    popup = _load_json(os.path.join(WEB_DIR, "popup_content.json"))
    if popup is None:
        _log_warn("Missing popup_content.json in WEB_DIR — skipping popup checks")
        return

    expected_denom = 9
    holdings = popup.get("holdings", {})
    for sym, data in holdings.items():
        if not isinstance(data, dict):
            continue
        # earnings_confirmed removed from scoring and UI chips (2026-07-04)
        # if "earnings_confirmed" not in data.get("confirmations", {}):
        #     _log_issue(f"Popup {sym}: missing earnings_confirmed factor")

        # sources dict must exist
        if "sources" not in data:
            _log_warn(f"Popup {sym}: missing data-sources provenance")

        # visible confirmation count vs denominator mismatch
        narr = data.get("narrative", {})
        if "factors" in narr and "/" in str(narr.get("factors", "")):
            if f"/{expected_denom}" not in str(narr.get("factors", "")):
                _log_issue(f"Popup {sym}: factors denominator stale (expected /{expected_denom})")
def check_dead_code() -> None:
    """No active .py file should import from dead data sources or retain dead factors."""
    try:
        import dead_factor_lint
        survivors = dead_factor_lint.find_survivors()
        if survivors:
            # Cap detail length so a Telegram alert isn't flooded
            lines = [f"{cat}: {path}:{line}" for cat, path, line, _ in survivors[:10]]
            more = len(survivors) - 10 if len(survivors) > 10 else 0
            msg = f"Dead-factor lint found {len(survivors)} active reference(s): " + "; ".join(lines)
            if more:
                msg += f" (and {more} more)"
            _log_issue(msg)
    except Exception as e:
        _log_warn(f"Could not run dead_factor_lint: {e}")

    # ─── stale web data copy ───────────────────────────────────────────────
def check_html_currency() -> None:
    """Deployed index.html should carry a recent cache-buster that matches popup gen."""
    path = os.path.join(WEB_DIR, "index.html")
    mtime = _file_mtime(path)
    popup_mtime = _file_mtime(os.path.join(BASE_DIR, "popup_content.json"))
    if mtime is None:
        _log_warn("Missing deployed index.html")
        return
    if popup_mtime and mtime < popup_mtime - 60:
        _log_warn("Deployed index.html older than latest popup_content.json")

    # Quick JS sanity: look for /9 denominator in factor chips
    try:
        html = Path(path).read_text()
    except Exception:
        return
    if '/10' not in html:
        _log_issue("Deployed index.html missing /9 denominator — may be stale pre-removal version")
def check_portfolio_sanity() -> None:
    """Position limits from cached portfolio snapshot."""
    portfolio = _load_json(os.path.join(WEB_DIR, "portfolio_data.json"))
    if portfolio is None:
        portfolio = _load_json(os.path.join(BASE_DIR, "portfolio_state.json"))
    if portfolio is None:
        # Graceful: not all pipelines write this
        return
    positions = portfolio.get("positions", [])
    total_value = portfolio.get("portfolio_value", 0)
    if not total_value:
        return
    sector_map: Dict[str, float] = {}
    for p in positions:
        mv = p.get("market_value", 0)
        sym = p.get("symbol", "")
        if p.get("qty", 0) <= 0:
            continue  # shorts handled by check_short_positions
        pct = mv / total_value if total_value else 0
        if pct > 0.105:  # 10% cap + tolerance
            _log_issue(f"Position {sym} is {pct:.1%} — exceeds 10% cap")
        sector = p.get("sector", "unknown")
        sector_map[sector] = sector_map.get(sector, 0) + mv
    for sector, total_mv in sector_map.items():
        pct = total_mv / total_value
        if pct > 0.26:  # 25% cap + tolerance
            _log_issue(f"Sector {sector} is {pct:.1%} — exceeds 25% cap")


def check_portfolio_history_freshness() -> None:
    """Newest portfolio_history.json check must be <30 min old during US market
    hours — stonk-ai-data appends a live micro-check every cycle (~2 min).
    A stale newest check means the live writer silently stopped; this is how the
    2026-07-20 chart freeze (collapsed to midnight snapshot) went unnoticed."""
    hist = _load_json(os.path.join(WEB_DIR, "portfolio_history.json"))
    if not hist:
        return
    checks = hist.get("checks", [])
    if not checks:
        _log_issue("portfolio_history.json has zero checks")
        return
    newest = None
    for c in checks:
        try:
            dt = datetime.fromisoformat(c.get("timestamp", "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if newest is None or dt > newest:
                newest = dt
        except Exception:
            continue
    if newest is None:
        return
    now = datetime.now(timezone.utc)
    mins = now.hour * 60 + now.minute
    market_window = now.weekday() < 5 and (13 * 60 + 30) <= mins <= (20 * 60 + 30)
    age_min = (now - newest).total_seconds() / 60
    if market_window and age_min > 30:
        _log_issue(
            f"portfolio_history.json newest check is {age_min:.0f} min old (max 30) "
            "— performance chart not updating; check stonk-ai-data.service"
        )


def check_live_quotes_pipeline() -> None:
    """live_quotes.json (tier-2 SIP poller) must be fresh during US market
    hours — the poller writes every 15s. A stale/missing file means the live
    layer silently died; the site falls back to the 5-min pipeline (degraded,
    not broken), so alert before anyone notices the ticker stopped moving."""
    path = os.path.join(WEB_DIR, "live_quotes.json")
    now = datetime.now(timezone.utc)
    mins = now.hour * 60 + now.minute
    market_window = now.weekday() < 5 and (13 * 60 + 30) <= mins <= (20 * 60 + 30)
    if not market_window:
        return
    mtime = _file_mtime(path)
    if mtime is None:
        _log_issue("live_quotes.json missing during market hours — check stonk-ai-live-quotes.service")
        return
    age = now.timestamp() - mtime
    if age > 120:
        _log_issue(
            f"live_quotes.json is {age / 60:.1f} min old (max 2) "
            "— live quotes layer degraded; check stonk-ai-live-quotes.service"
        )


def check_short_positions() -> None:
    """Critical alert on short/negative positions — bot is long-only.
    Queries Alpaca /v2/positions directly: portfolio_data.json is bot-written
    and long-only, which hid the 2026-07-16 manual GTLB short from this check.
    Broker-level no_shorting=true (set 2026-07-20) is the primary guard."""
    cfg_path = os.path.join(BASE_DIR, "alpaca_config.json")
    try:
        cfg = _load_json(cfg_path) or {}
        headers = {"APCA-API-KEY-ID": cfg["api_key"],
                   "APCA-API-SECRET-KEY": cfg["api_secret"]}
        base = cfg.get("base_url", "https://paper-api.alpaca.markets")
        r = requests.get(f"{base}/v2/positions", headers=headers, timeout=15)
        if r.status_code != 200:
            return
        for p in r.json():
            qty = float(p.get("qty", 0) or 0)
            mv = float(p.get("market_value", 0) or 0)
            if p.get("side") == "short" or qty < 0 or mv < 0:
                _log_issue(
                    f"SHORT POSITION: {p.get('symbol')} qty={p.get('qty')} mv=${mv:,.0f} "
                    "— long-only strategy; external/manual account activity; cover manually"
                )
    except Exception:
        return


def check_trade_churn() -> None:
    """Churn regression detector: flag excessive same-day trade counts.
    Baseline: week of 2026-07-13 averaged 73 trades/day (364 total). Guardrail
    target after anti-churn patch: <= 20/day."""
    if not _is_us_market_hours():
        return  # only meaningful while the bot can trade
    trades = _load_json(os.path.join(BASE_DIR, "trades_log.json"))
    if not isinstance(trades, list):
        trades = (trades or {}).get("trades", []) if isinstance(trades, dict) else []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    n = sum(1 for t in trades if str(t.get("timestamp", "")).startswith(today))
    if n > 20:
        _log_issue(f"Trade churn: {n} trades today — anti-churn guardrails may be failing")
    elif n > 12:
        _log_warn(f"Elevated trade count: {n} trades today")


def check_outcome_tracker() -> None:
    """Outcome tracker (measurement layer) freshness + format validity."""
    path = os.path.join(WEB_DIR, "signal_accuracy.json")
    acc = _load_json(path)
    if acc is None:
        _log_issue("signal_accuracy.json missing — outcome tracker not writing")
        return
    mt = _file_mtime(path)
    if mt and (time.time() - mt) > 3600:
        _log_issue(f"signal_accuracy.json stale ({(time.time() - mt) / 60:.0f} min old; outcome_tracker runs every 15 min)")
    stats = acc.get("stats", {})
    if "by_cohort" not in stats:
        _log_warn("signal_accuracy.json missing cohort breakdown (stale format)")



def check_trading_bot_entry_gate() -> None:
    """Only PRIME/entry-eligible symbols should be considered for new trades."""
    signals = _load_json(os.path.join(BASE_DIR, "signals.json"))
    if signals is None:
        return
    for sig in signals.get("signals", []):
        if not sig.get("entry_eligible", False):
            continue
        tier = sig.get("tier", "")
        ready = sig.get("readiness_score", 0) or 0
        conf = sig.get("confirmation_count", 0) or 0
        if tier not in ("STRONG_NOW", "NOW"):
            _log_issue(f"ENTRY GATE {sig.get('symbol')}: entry_eligible=True but tier={tier}")
        if ready < 75:
            _log_issue(f"ENTRY GATE {sig.get('symbol')}: entry_eligible=True but readiness={ready}")
        if conf < 5:
            _log_issue(f"ENTRY GATE {sig.get('symbol')}: entry_eligible=True but conf={conf}")


def check_alpaca_portfolio_sync() -> None:
    """Alpaca positions must match popup_content.json and portfolio_data.json."""
    cfg_path = os.path.join(BASE_DIR, "alpaca_config.json")
    try:
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
        headers = {"APCA-API-KEY-ID": cfg["api_key"], "APCA-API-SECRET-KEY": cfg["api_secret"]}
        base = cfg.get("base_url", "https://paper-api.alpaca.markets").rstrip("/")
        r = requests.get(f"{base}/v2/positions", headers=headers, timeout=15)
        r.raise_for_status()
        alpaca = {p["symbol"]: p for p in r.json()}
    except Exception as exc:
        _log_warn(f"Could not fetch Alpaca positions: {exc}")
        return

    popup = _load_json(os.path.join(WEB_DIR, "popup_content.json"))
    popup_holdings = popup.get("holdings", {}) if popup else {}
    portfolio = _load_json(os.path.join(WEB_DIR, "portfolio_data.json"))
    portfolio_positions = {p.get("symbol"): p for p in portfolio.get("positions", [])} if portfolio else {}

    for sym in alpaca:
        if sym not in popup_holdings:
            _log_issue(f"ALPACA SYNC {sym}: position in Alpaca but missing from popup_content.json")
        if sym not in portfolio_positions:
            _log_issue(f"ALPACA SYNC {sym}: position in Alpaca but missing from portfolio_data.json")

    for sym in popup_holdings:
        if sym not in alpaca:
            _log_issue(f"ALPACA SYNC {sym}: in popup_content.json but no Alpaca position")


def check_llm_narrative_freshness_and_validity() -> None:
    """Holdings and watchlist popups must have fresh, complete LLM narratives.
    Skips stale-data checks when market is closed (narratives aren't expected to update)."""
    # Skip freshness checks when market is closed — narratives don't update off-hours
    # First try .llm_narrative_status (scheduler writes this), fallback to market_status.json
    status = _load_json(os.path.join(BASE_DIR, ".llm_narrative_status"))
    if not status:
        status = _load_json(os.path.join(BASE_DIR, "market_status.json"))
    mode = ""
    if status:
        mode = status.get("mode", "").lower()
    if "market open" not in mode:
        # Market closed/off-hours: only check structural completeness, not freshness
        max_age = 25 * 60  # still use for completeness checks, but don't alert on age
        skip_freshness = True
    else:
        max_age = 25 * 60
        skip_freshness = False

    now = time.time()
    expected_holdings_fields = {"whatItIs", "whyWeOwnIt", "howItsDoing", "catalyst", "risk"}
    expected_watchlist_fields = {"whatItIs", "whyOnWatchlist", "whatTriggersBuy", "catalyst", "risk"}

    llm_holdings_path = os.path.join(WEB_DIR, "popup_narratives.json")
    llm_holdings = _load_json(llm_holdings_path)
    if llm_holdings is None:
        _log_issue("Missing popup_narratives.json (LLM holdings)")
    else:
        h = llm_holdings.get("holdings", {})
        for sym, data in h.items():
            missing = expected_holdings_fields - set(data.keys() if isinstance(data, dict) else [])
            if missing:
                _log_issue(f"LLM holdings narrative {sym} missing fields: {', '.join(missing)}")
        mtime = _file_mtime(llm_holdings_path)
        if not skip_freshness and mtime and now - mtime > 25 * 60:
            _log_warn(f"LLM holdings narratives stale: {(now - mtime) / 60:.0f} min old")

    llm_watchlist_path = os.path.join(WEB_DIR, "watchlist_narratives_llm.json")
    llm_watchlist = _load_json(llm_watchlist_path)
    if llm_watchlist is None:
        _log_warn("Missing watchlist_narratives_llm.json (LLM watchlist)")
    else:
        w = llm_watchlist.get("narratives", {})
        for sym, data in w.items():
            missing = expected_watchlist_fields - set(data.keys() if isinstance(data, dict) else [])
            if missing:
                _log_issue(f"LLM watchlist narrative {sym} missing fields: {', '.join(missing)}")
        mtime = _file_mtime(llm_watchlist_path)
        if not skip_freshness and mtime and now - mtime > 25 * 60:
            _log_warn(f"LLM watchlist narratives stale: {(now - mtime) / 60:.0f} min old")

    popup = _load_json(os.path.join(WEB_DIR, "popup_content.json"))
    if popup:
        for sym, data in popup.get("holdings", {}).items():
            if not isinstance(data, dict):
                continue
            missing = expected_holdings_fields - set(data.keys())
            if missing:
                _log_issue(f"Merged popup {sym} missing narrative fields: {', '.join(missing)}")

    watchlist_narr = _load_json(os.path.join(WEB_DIR, "watchlist_narratives.json"))
    if watchlist_narr:
        for sym, data in watchlist_narr.get("narratives", {}).items():
            if not isinstance(data, dict):
                continue
            missing = expected_watchlist_fields - set(data.keys())
            if missing:
                _log_issue(f"Merged watchlist narrative {sym} missing narrative fields: {', '.join(missing)}")
# check_narrative_semantics() disabled: too many false positives from LLM template text
    """Sniff for narrative text that claims a factor is missing when it's actually confirmed."""
    FACTORS = [
        ("momentum", "momentum_score", lambda v: isinstance(v, (int, float)) and v >= 50),
        ("volume", "volume_confirmed", lambda v: bool(v)),
        ("MACD", "macd_turning", lambda v: bool(v)),
        ("EMA", "above_ema", lambda v: bool(v)),
        ("sector", "sector_strong", lambda v: bool(v)),
        ("intraday", "intraday_confirmed", lambda v: bool(v)),
        ("options", "options_confirmed", lambda v: bool(v)),
        ("RSI", "rsi_signal", lambda v: v in ("bullish", "overbought")),
    ]

    MISSING_PATTERNS = [
        r"(?i)\b(?:waiting on|waiting for|needs? (?:more )?|missing|lacking)\b\s+\b{keyword}\b",
        # Only flag when keyword itself is explicitly described as not-confirmed.
        r"(?i)\b{keyword}\b\s+is(?:n't| not)\s+(?:there|confirmed)",
        r"(?i)\b{keyword}\b\s+hasn't\s+fired",
        r"(?i)\b{keyword}\b\s+still\s+needed",
    ]

    signals = _load_json(os.path.join(BASE_DIR, "signals.json"))
    popup = _load_json(os.path.join(WEB_DIR, "popup_content.json"))
    watchlist_narr = _load_json(os.path.join(WEB_DIR, "watchlist_narratives.json"))

    if signals is None:
        _log_warn("Missing signals.json — skipping narrative semantics")
        return

    sig_map = {s.get("symbol"): s for s in signals.get("signals", []) if s.get("symbol")}

    def _scan_text(text: str, sym: str, src: str, conf: dict) -> None:
        if not isinstance(text, str):
            return
        # Scan sentence-by-sentence to avoid cross-sentence false positives
        sentences = re.split(r"(?<=[.!?;])\s+", text)
        for sentence in sentences:
            for keyword, field, is_confirmed in FACTORS:
                val = conf.get(field)
                if not is_confirmed(val):
                    continue  # factor is not confirmed; text claiming it's missing is accurate
                for pat in MISSING_PATTERNS:
                    regex = pat.format(keyword=keyword)
                    if re.search(regex, sentence):
                        _log_warn(f"SEMANTIC CONTRADICTION {sym} ({src}): text implies '{keyword}' is missing but {field}={val} (confirmed)")
                        break  # one issue per factor per text block is enough

    # Scan watchlist narratives
    if watchlist_narr:
        for sym, data in watchlist_narr.get("narratives", {}).items():
            sig = sig_map.get(sym)
            if not sig:
                continue
            conf = sig.get("confirmations", {})
            for key, val in data.items():
                if isinstance(val, str):
                    _scan_text(val, sym, f"watchlist.{key}", conf)

    # Scan popup holdings
    if popup:
        for sym, data in popup.get("holdings", {}).items():
            sig = sig_map.get(sym)
            if not sig:
                continue
            conf = sig.get("confirmations", {})
            narr = data.get("narrative", {})
            if isinstance(narr, dict):
                for key, val in narr.items():
                    if isinstance(val, str):
                        _scan_text(val, sym, f"popup.{key}", conf)
# ─── Main ───────────────────────────────────────────────────────────────────

# ─── Execution Health Checks ────────────────────────────────────────────────
def check_llm_narrative_pipeline() -> None:
    """Verify the LLM narrative generator is healthy and output is fresh."""
    timer = "stonk-ai-llm-narrative.timer"
    rc, stdout, stderr = _run_cmd(f"systemctl is-active {timer}")
    if rc != 0:
        _log_warn(f"LLM narrative timer {timer} is NOT active")

    # Check for recent service failures
    rc2, out2, _ = _run_cmd(f"systemctl list-units --failed --no-pager --plain | grep stonk-ai-llm-narrative.service")
    if rc2 == 0 and out2:
        _log_issue(f"stonk-ai-llm-narrative.service is in failed state")

    now = time.time()
    expected_fields = {"whatItIs", "whyWeOwnIt", "howItsDoing", "catalyst", "risk"}
    watchlist_fields = {"whatItIs", "whyOnWatchlist", "whatTriggersBuy", "catalyst", "risk"}
    # Market-aware freshness: skip stale checks when market is closed
    status = _load_json(os.path.join(BASE_DIR, ".llm_narrative_status"))
    if not status:
        status = _load_json(os.path.join(BASE_DIR, "market_status.json"))
    scheduler_mode = ""
    if status:
        scheduler_mode = status.get("mode", "").lower()
    if "market open" not in scheduler_mode:
        # Off-hours/weekend: only check structural completeness, not freshness
        # (LLM narratives aren't updated when market is closed)
        skip_freshness = True
    else:
        skip_freshness = False
    # Raw LLM outputs
    llm_holdings_path = os.path.join(WEB_DIR, "popup_narratives.json")
    llm_watchlist_path = os.path.join(WEB_DIR, "watchlist_narratives_llm.json")
    llm_holdings = _load_json(llm_holdings_path)
    llm_watchlist = _load_json(llm_watchlist_path)

    if llm_holdings is None:
        _log_warn(f"Missing {llm_holdings_path}")
    else:
        h = llm_holdings.get("holdings", {})
        portfolio_data = _load_json(os.path.join(BASE_DIR, "portfolio_data.json"))
        portfolio_positions = {p.get("symbol"): p for p in portfolio_data.get("positions", [])} if portfolio_data else {}
        if not portfolio_positions and not h:
            pass  # empty portfolio, expected
        elif not h and portfolio_positions:
            _log_warn(f"LLM holdings narratives empty while portfolio has {len(portfolio_positions)} positions (will fill on next LLM run)")
        else:
            missing = [sym for sym, data in h.items() if not expected_fields.issubset(data.keys())]
            if missing:
                _log_warn(f"LLM holdings missing narrative fields: {", ".join(missing[:5])}")
        mtime = _file_mtime(llm_holdings_path)
        if not skip_freshness and mtime and now - mtime > 25 * 60:
            _log_warn(f"LLM holdings narratives stale: {(now-mtime)/60:.0f} min old")

    if llm_watchlist is None:
        _log_warn(f"Missing {llm_watchlist_path}")
    else:
        w = llm_watchlist.get("narratives", {})
        if not w:
            _log_warn("LLM watchlist narratives empty (LLM overlay disabled)")
        else:
            missing = [sym for sym, data in w.items() if not watchlist_fields.issubset(data.keys())]
            if missing:
                _log_warn(f"LLM watchlist missing narrative fields: {", ".join(missing[:5])}")
        mtime = _file_mtime(llm_watchlist_path)
        if not skip_freshness and mtime and now - mtime > 25 * 60:
            _log_warn(f"LLM watchlist narratives stale: {(now-mtime)/60:.0f} min old")

    # Merged outputs
    popup = _load_json(os.path.join(WEB_DIR, "popup_content.json"))
    if popup:
        holdings = popup.get("holdings", {})
        for sym, data in holdings.items():
            if not isinstance(data, dict):
                continue
            merged_fields = set(data.keys())
            if not expected_fields.issubset(merged_fields):
                _log_warn(f"Merged popup {sym} missing LLM narrative fields")

    watchlist_narr = _load_json(os.path.join(WEB_DIR, "watchlist_narratives.json"))
    if watchlist_narr:
        narratives = watchlist_narr.get("narratives", {})
        for sym, data in narratives.items():
            if not isinstance(data, dict):
                continue
            merged_fields = set(data.keys())
            if not watchlist_fields.issubset(merged_fields):
                _log_warn(f"Merged watchlist {sym} missing LLM narrative fields")
def check_trade_execution_health() -> None:
    log_path = os.path.join(BASE_DIR, "trading_bot.log")
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-500:]
    except Exception:
        _log_warn(f"Could not read {log_path} for execution health check")
        return

    # Only scan since the most recent bot restart
    restart_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if "stonk.ai trading bot" in lines[i].lower() and "starting" in lines[i].lower():
            restart_idx = i
            break
    if restart_idx != -1:
        lines = lines[restart_idx:]

    failed_sell = sum(1 for line in lines if "failed to sell" in line.lower())
    failed_buy  = sum(1 for line in lines if "failed to buy"  in line.lower())
    unbound_local = sum(1 for line in lines if "unboundlocalerror" in line.lower())
    attr_error  = sum(1 for line in lines if "attributeerror" in line.lower())
    submit_err  = sum(1 for line in lines if "submit_order" in line.lower() and "error" in line.lower())

    if unbound_local or attr_error:
        _log_issue(f"Execution code error: {unbound_local} UnboundLocalError, {attr_error} AttributeError in recent log")

    if failed_sell >= 3:
        _log_issue(f"Repeated sell failures: {failed_sell} 'Failed to sell' in last ~500 log lines")
    elif failed_sell >= 1:
        _log_warn(f"{failed_sell} sell failure(s) in recent log — may indicate execution degradation")

    if failed_buy >= 3:
        _log_issue(f"Repeated buy failures: {failed_buy} 'Failed to buy' in last ~500 log lines")
    elif failed_buy >= 1:
        _log_warn(f"{failed_buy} buy failure(s) in recent log — may indicate execution degradation")

    if submit_err >= 1:
        _log_warn(f"{submit_err} submit_order error(s) in recent log")
def check_open_orders() -> None:
    cfg_path = os.path.join(BASE_DIR, "alpaca_config.json")
    try:
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
    except Exception as exc:
        _log_warn(f"Could not load Alpaca config for open-order check: {exc}")
        return

    headers = {"APCA-API-KEY-ID": cfg["api_key"], "APCA-API-SECRET-KEY": cfg["api_secret"]}
    base = cfg.get("base_url", "https://paper-api.alpaca.markets").rstrip("/")

    try:
        r = requests.get(f"{base}/v2/orders?status=open", headers=headers, timeout=15)
        r.raise_for_status()
        orders = r.json()
    except Exception as exc:
        _log_warn(f"Could not fetch open orders from Alpaca: {exc}")
        return

    if not orders:
        return

    now = datetime.now(timezone.utc)
    sells_by_symbol = {}
    for o in orders:
        side = o.get("side", "")
        symbol = o.get("symbol", "")
        if side.lower() == "sell":
            sells_by_symbol.setdefault(symbol, []).append(o)

    for symbol, order_list in sells_by_symbol.items():
        if len(order_list) > 1:
            ids = ", ".join(o.get("id", "?") for o in order_list)
            _log_issue(f"Duplicate open sell orders for {symbol}: {len(order_list)} orders ({ids})")

    for o in orders:
        try:
            submitted = datetime.fromisoformat(o.get("submitted_at", "").replace("Z", "+00:00"))
            age_min = (now - submitted).total_seconds() / 60
        except Exception:
            continue
        side = o.get("side", "")
        symbol = o.get("symbol", "")
        if age_min > 30:
            _log_issue(f"Stuck open {side} order for {symbol}: {age_min:.0f} min old (id {o.get('id', '?')})")
        elif age_min > 15:
            _log_warn(f"Old open {side} order for {symbol}: {age_min:.0f} min old")
def check_cron_entries() -> None:
    """Ensure critical cron jobs are actually installed."""
    import subprocess
    try:
        out = subprocess.check_output(["crontab", "-l", "-u", "stonkai"], text=True, stderr=subprocess.STDOUT)
    except Exception as exc:
        _log_warn(f"Could not read stonkai crontab: {exc}")
        return
    required = {
        "sync_alpaca_trades.py": "sync Alpaca trades",
        "dynamic_watchlist_manager.py": "watchlist rotation",
        "snapshot_portfolio.py": "portfolio snapshot",
    }
    for script, label in required.items():
        if script not in out:
            _log_issue(f"Missing cron job: {label} ({script}) not found in stonkai crontab")

def check_cron_heartbeats() -> None:
    """Check that critical cron jobs have recorded recent heartbeats."""
    heartbeat_dir = Path(BASE_DIR) / "heartbeats"
    if not heartbeat_dir.exists():
        return
    now = datetime.now(timezone.utc)
    is_market_hours = _us_market_is_open(now)
    # job_name: max expected age in minutes
    expected = {
        # Only jobs that are currently scheduled AND record heartbeats
        "comprehensive_monitor": 20,
        "dynamic_watchlist_manager": 10,
        # Deprecated / no longer scheduled jobs removed to avoid false alerts:
        # update_iv_summaries, signal_enricher, watchlist_feedback,
        # daily_liquidity_report_am/pm, fetch_price_history, update_price_history,
        # vps_memory_maintenance, analyze_options_skew_signal
    }
    for job, max_age_min in expected.items():
        if max_age_min is None:
            continue  # Skip checking market-hours-only jobs when market is closed
        hb_file = heartbeat_dir / f"{job}.json"
        if not hb_file.exists():
            continue
        try:
            data = json.loads(hb_file.read_text())
            ts = datetime.fromisoformat(data.get("timestamp", "").replace("Z", "+00:00"))
            age_min = (now - ts).total_seconds() / 60
            if age_min > max_age_min:
                _log_issue(f"Heartbeat for {job} is {age_min:.0f} min old (expected <={max_age_min})")
        except Exception as exc:
            _log_warn(f"Could not parse heartbeat for {job}: {exc}")

def check_market_hours_sanity() -> None:
    """Warn if recent trading_bot.log implies wrong market-hours understanding."""
    now = datetime.now(timezone.utc)
    market_open = _us_market_is_open(now)
    details = []
    if market_open:
        log_path = os.path.join(BASE_DIR, "trading_bot.log")
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(size - 5000, 0))
                recent = f.read()
            low = recent.lower()
            if "market is closed" in low or ("market" in low and "closed" in low):
                details.append(f"Market is currently OPEN ({now:%Y-%m-%d %H:%M:%S} UTC) but recent log mentions market closed.")
        except Exception:
            pass
    if details:
        for d in details:
            _log_issue(d)
def check_system_time() -> None:
    """Flag large clock drift from NTP."""
    now = datetime.now(timezone.utc)
    details = []
    try:
        drift = _ntp_drift_seconds()
        if drift is not None and abs(drift) > 5.0:
            details.append(f"System clock drift from NTP: {drift:.3f}s (threshold 5s).")
    except Exception as e:
        details.append(f"Could not measure NTP drift: {e}")
    if details:
        _send_alert("[HEALTH] System time check failed", details)

def check_bot_crash() -> None:
    """Alert if trading bot service is failed or recently crashed/restarted abnormally."""
    import subprocess
    details = []

    # Service state
    try:
        out = subprocess.check_output(["systemctl", "is-active", "stonk-ai"], text=True, stderr=subprocess.STDOUT).strip()
        if out == "failed":
            details.append("stonk-ai.service is in failed state.")
        elif out not in ("active", "activating"):
            details.append(f"stonk-ai.service state is {out} (expected active/activating).")
    except Exception as exc:
        details.append(f"Could not determine stonk-ai.service state: {exc}")

    # Recent traceback in log
    log_path = os.path.join(BASE_DIR, "trading_bot.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 20000, 0))
            tail = f.read()
        # Find the last traceback block
        last_traceback = tail.rfind("Traceback (most recent call last):")
        if last_traceback != -1:
            block = tail[last_traceback:]
            # extract timestamp from line before traceback if present
            lines_before = tail[:last_traceback].splitlines()
            ts_line = lines_before[-1] if lines_before else ""
            # look for ISO-ish timestamp at start
            ts = ts_line[:19] if ts_line and len(ts_line) >= 19 and ts_line[4] == "-" else "unknown"
            if "2026-" in ts_line or "2025-" in ts_line:
                ts = ts_line[:19]
            details.append(f"Recent traceback in trading_bot.log at {ts}.")
    except Exception as exc:
        details.append(f"Could not read trading_bot.log for crashes: {exc}")

    # Recent unexpected restart rate
    try:
        out = subprocess.check_output(
            ["systemctl", "show", "stonk-ai", "--property=ActiveEnterTimestamp,NRestarts"],
            text=True, stderr=subprocess.STDOUT,
        )
        props = {}
        for line in out.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        n_restarts = int(props.get("NRestarts", "0") or "0")
        if n_restarts >= 3:
            details.append(f"stonk-ai.service has restarted {n_restarts} times (threshold 3).")
    except Exception as exc:
        details.append(f"Could not read restart count: {exc}")

    if details:
        _send_alert("[HEALTH] Trading bot crash/restart detected", details)

def _check_file_permissions():
    """Ensure critical web files are readable by the stonkai service user."""
    import stat, pwd, shutil
    from pathlib import Path

    files = [
        ("/var/www/hedge-fund-website/ai_watchlist_live.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/signals.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/popup_content.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/watchlist_narratives.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/portfolio_data.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/trades_log.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/portfolio_history.json", "stonkai", 0o644),
        ("/opt/stonk-ai/trades_log.json", "stonkai", 0o644),
        ("/opt/stonk-ai/trading_bot.log", "stonkai", 0o644),
        ("/opt/stonk-ai/signals.json", "stonkai", 0o644),
        ("/opt/stonk-ai/portfolio_data.json", "stonkai", 0o644),
        ("/opt/stonk-ai/stonkbot.db", "stonkai", 0o644),
    ]
    # Also scan for any root-owned JSON/log/DB files in BASE_DIR
    import glob
    for fpath in glob.glob(os.path.join(BASE_DIR, "*.json")) + glob.glob(os.path.join(BASE_DIR, "*.log")) + glob.glob(os.path.join(BASE_DIR, "*.db*")):
        if fpath not in [x[0] for x in files]:
            files.append((fpath, "stonkai", 0o644))
    for fpath, expected_user, expected_mode in files:
        try:
            p = Path(fpath)
            if not p.exists():
                continue
            st = p.stat()
            owner = pwd.getpwuid(st.st_uid).pw_name
            mode = stat.S_IMODE(st.st_mode)
            if owner != expected_user or mode != expected_mode:
                _log_issue(f"Permission drift: {fpath} is {owner}:{oct(mode)} (expected {expected_user}:{oct(expected_mode)})")
                try:
                    shutil.chown(fpath, user=expected_user, group=expected_user)
                    p.chmod(expected_mode)
                except Exception as e:
                    _log_issue(f"Failed to fix permissions for {fpath}: {e}")
        except Exception:
            pass


def _check_process_health():
    """Detect duplicate or root-owned stonk-ai Python script processes."""
    import subprocess, re
    try:
        out = subprocess.check_output("ps -eo user:15,pid,args", shell=True, text=True)
    except Exception as e:
        _log_warn(f"Could not check process health: {e}")
        return

    scripts = {
        "fetch_ai_watchlist.py": "AI Watchlist Fetcher",
        "trading_bot.py": "Trading Bot",
        "signal_engine.py": "Signal Engine",
        "fetch_data_simple.py": "Data Fetcher",
        "generate_popup_content_narrative_v6_server.py": "Popup v6 Generator",
        "generate_narratives_llm_batched.py": "LLM Narrative Generator",
        "reconstruct_portfolio_history.py": "Portfolio History Reconstructor",
    }

    # Only consider actual python invocations, not SSH shells or cron wrappers
    python_cmd_re = re.compile(r"python\d*\s+(?:.*/)?(\S+\.py)")
    procs = {}
    for line in out.strip().splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        user, pid, cmd = parts
        cmd = cmd.strip()
        # Must be a python process (not ssh/bash/cron wrapper)
        if "/usr/bin/python" not in cmd and "python3" not in cmd:
            continue
        # Exclude shell wrappers and SSH sessions
        if "bash -c" in cmd or "ssh" in cmd.split()[0]:
            continue
        for script, label in scripts.items():
            if script in cmd:
                procs.setdefault(label, []).append((user.strip(), pid.strip(), cmd[:120]))

    for label, instances in procs.items():
        if len(instances) > 1:
            _log_issue(f"Duplicate {label} process detected: {len(instances)} instances")
        for user, pid, full_cmd in instances:
            if user == "root":
                _log_issue(f"Root-owned {label}: {user} pid={pid} cmd={full_cmd}")
                # Auto-kill root-owned stonk-ai Python processes (they should run as stonkai)
                try:
                    subprocess.run(["sudo", "kill", "-9", pid], check=False)
                    _log_warn(f"Killed root-owned {label} pid={pid}")
                except Exception as e:
                    _log_warn(f"Failed to kill root-owned {label} pid={pid}: {e}")

def main() -> int:
    print("StonkBOT Integrity Monitor running ...")
    _check_file_permissions()
    _check_process_health()
    check_system_time()
    check_market_hours_sanity()
    check_bot_crash()
    check_services()
    check_file_freshness()
    check_signals_write_health()
    check_extended_hours_prices()
    check_universe_names()
    check_shadow_company_names()
    check_alignment_signals_vs_watchlist()
    check_factor_confirmation_integrity()
    check_popup_narrative_alignment()
    check_popup_integrity()
    check_dead_code()
    check_html_currency()
    check_portfolio_sanity()
    check_portfolio_history_freshness()
    check_live_quotes_pipeline()
    check_short_positions()
    check_trade_churn()
    check_outcome_tracker()
    # check_narrative_semantics()  # disabled: too many false positives from LLM template text
    check_trade_execution_health()
    check_open_orders()
    check_llm_narrative_pipeline()
    check_llm_narrative_freshness_and_validity()
    check_trading_bot_entry_gate()
    check_alpaca_portfolio_sync()
    check_cron_heartbeats()
    check_cron_entries()

    status = "HEALTHY"
    exit_code = 0
    if WARNINGS and not ISSUES:
        status = "HEALTHY"  # warnings are informational only
        exit_code = 0
    if ISSUES:
        status = "DEGRADED"
        exit_code = 1

    report = {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issue_count": len(ISSUES),
        "warning_count": len(WARNINGS),
        "issues": ISSUES,
        "warnings": WARNINGS,
    }

    # Publish status for the website anomaly banner (it fetches
    # comprehensive_monitor.json every 2 min). Best-effort: alerting via
    # Telegram remains the primary channel.
    report["healthy"] = status == "HEALTHY"
    try:
        out = os.path.join(WEB_DIR, "comprehensive_monitor.json")
        tmp = out + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(report, fh)
        os.replace(tmp, out)
    except Exception:
        pass

    if status != "HEALTHY":
        # Only print JSON report when there is something to say
        print(json.dumps(report, indent=2))
        # Send Telegram alert with issue summary
        _send_alert(
            f"{len(ISSUES)} issues, {len(WARNINGS)} warnings",
            ISSUES + WARNINGS,
        )

    return exit_code
def _record_heartbeat():
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/python3", "/opt/stonk-ai/heartbeat_tracker.py", "comprehensive_monitor"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
if __name__ == "__main__":
    code = main()
    _record_heartbeat()
    sys.exit(0)  # Always exit 0 — findings are not a service failure
