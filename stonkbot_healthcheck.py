#!/usr/bin/env python3
"""
StonkBOT Unified Healthcheck — Consolidated Version
Replaces both stonkbot_healthcheck.py AND comprehensive_monitor.py

Critical checks → Telegram alert (when something breaks)
Audit checks    → Log only (review weekly)

Usage:
    python3 /opt/stonk-ai/stonkbot_healthcheck.py --check           # systemd
    python3 /opt/stonk-ai/stonkbot_healthcheck.py --report          # manual check
    python3 /opt/stonk-ai/stonkbot_healthcheck.py --deep-audit      # weekly deep scan
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from stonkbot_db import check_stale_jobs, heartbeat, _connect, log_event
from circuit_breaker import CircuitBreaker

DB_PATH = Path(os.environ.get("STONKBOT_DB", "/opt/stonk-ai/stonkbot.db"))
BASE_DIR = Path("/opt/stonk-ai")
WEB_DIR = Path("/var/www/hedge-fund-website")

CRITICAL_JOBS = [
    "signal_engine", "trading_bot", "alpaca_trade_sync",
    "signal_enricher", "market_status_api", "comprehensive_monitor",
]

ALERT_WEBHOOK = os.environ.get("STONKBOT_ALERT_WEBHOOK", "")


# ────────────────────────────────────────────────────────────────────────────
# CRITICAL CHECKS (Telegram if failed)
# ────────────────────────────────────────────────────────────────────────────

def check_signals_stale(conn: sqlite3.Connection, max_minutes: int = 25) -> List[str]:
    """Return warnings if signals are stale. Skips when market is closed."""
    # Check if market is open before flagging stale signals
    try:
        market_status = json.loads(Path("/opt/stonk-ai/market_status.json").read_text())
        if not market_status.get("is_open", True):
            return []  # Market closed — signals won't update
    except:
        pass  # If no market status, proceed with check
    
    warnings = []
    row = conn.execute(
        """
        SELECT MAX(generated_at) as last_gen,
               (strftime('%s', 'now') - strftime('%s', MAX(generated_at))) / 60 as minutes_ago
        FROM signals
        """
    ).fetchone()
    if not row or not row["last_gen"]:
        warnings.append("No signals ever generated")
    elif row["minutes_ago"] > max_minutes:
        warnings.append(f"Signals stale: {row['minutes_ago']} min ago")
    return warnings


def check_portfolio_stale(conn: sqlite3.Connection, max_minutes: int = 30) -> List[str]:
    """Portfolio should update every 5 min during market hours."""
    # Skip if market closed
    try:
        market_status = json.loads(Path("/opt/stonk-ai/market_status.json").read_text())
        if not market_status.get("is_open", True):
            return []
    except:
        pass
    
    warnings = []
    row = conn.execute(
        """
        SELECT MAX(snapshot_at) as last_snap,
               (strftime('%s', 'now') - strftime('%s', MAX(snapshot_at))) / 60 as minutes_ago
        FROM portfolio_snapshots
        """
    ).fetchone()
    if not row or not row["last_snap"]:
        warnings.append("No portfolio snapshots ever recorded")
    elif row["minutes_ago"] > max_minutes:
        warnings.append(f"Portfolio stale: {row['minutes_ago']} min ago")
    return warnings


def check_root_processes() -> List[str]:
    """Detect root-owned stonk processes."""
    warnings = []
    try:
        result = subprocess.run(
            ["pgrep", "-a", "-f", "stonk"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return warnings
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            pid, cmd = parts[0], parts[1]
            if "ssh" in cmd or "bash -c" in cmd or "stonkbot_healthcheck" in cmd:
                continue
            try:
                owner = subprocess.run(
                    ["ps", "-o", "user=", "-p", pid],
                    capture_output=True, text=True, timeout=2
                )
                if owner.stdout.strip() == "root":
                    warnings.append(f"Root-owned process: PID {pid} cmd={cmd[:60]}")
            except Exception:
                pass
    except Exception:
        pass
    return warnings


def check_disk_space(min_free_mb: int = 500) -> List[str]:
    import shutil
    warnings = []
    stat = shutil.disk_usage("/opt/stonk-ai")
    free_mb = stat.free / (1024 * 1024)
    if free_mb < min_free_mb:
        warnings.append(f"Disk low: {free_mb:.0f} MB free")
    return warnings


def check_db_integrity(conn: sqlite3.Connection) -> List[str]:
    warnings = []
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            warnings.append(f"DB integrity check failed: {result}")
    except Exception as e:
        warnings.append(f"DB integrity check error: {e}")
    return warnings


def check_circuit_breaker() -> List[str]:
    """Check breaker state and alert if it was tripped externally."""
    warnings = []
    cb = CircuitBreaker()
    if cb.is_open():
        status = cb.status()
        warnings.append(f"Circuit breaker OPEN — {status.get('reason', 'unknown')} at {status.get('tripped_at', '?')}")
    return warnings


# ────────────────────────────────────────────────────────────────────────────
# AUDIT CHECKS (Log only — run with --deep-audit)
# ────────────────────────────────────────────────────────────────────────────

def check_file_permissions() -> List[str]:
    """Ensure critical files are owned by stonkai with correct permissions."""
    warnings = []
    import stat, pwd
    files = [
        ("/var/www/hedge-fund-website/ai_watchlist_live.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/signals.json", "stonkai", 0o644),
        ("/var/www/hedge-fund-website/popup_content.json", "stonkai", 0o644),
        ("/opt/stonk-ai/stonkbot.db", "stonkai", 0o644),
        ("/opt/stonk-ai/portfolio_data.json", "stonkai", 0o644),
    ]
    for fpath, expected_user, expected_mode in files:
        try:
            p = Path(fpath)
            if not p.exists():
                continue
            st = p.stat()
            try:
                owner = pwd.getpwuid(st.st_uid).pw_name
            except:
                owner = str(st.st_uid)
            mode = stat.S_IMODE(st.st_mode)
            if owner != expected_user or mode != expected_mode:
                warnings.append(
                    f"Permission drift: {fpath} is {owner}:{oct(mode)} "
                    f"(expected {expected_user}:{oct(expected_mode)})"
                )
        except Exception:
            pass
    return warnings


def check_process_health() -> List[str]:
    """Detect duplicate or root-owned stonk-ai Python script processes."""
    warnings = []
    try:
        out = subprocess.check_output("ps -eo user:15,pid,args", shell=True, text=True)
        running_scripts = {}
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            user, pid, cmd = parts
            if "python3" not in cmd:
                continue
            script_name = cmd.strip()
            if ".py " in script_name:
                script_name = script_name.split(".py ", 1)[0].split("/")[-1] + ".py"
            if not any(x in script_name for x in ["trading_bot", "signal_engine", "comprehensive_monitor",
                                                     "alpaca_data", "market_status_api", "watchlist_manager",
                                                     "fetch_ai_watchlist", "generate_popup", "reconstruct",
                                                     "portfolio_history", "options_skew"]):
                continue
            if "ssh" in script_name or "bash -c" in script_name:
                continue
            if user == "root":
                warnings.append(f"Root-owned process: {script_name} (PID {pid})")
            else:
                key = f"{user}:{script_name}"
                running_scripts.setdefault(key, []).append(pid)
        for key, pids in running_scripts.items():
            if len(pids) > 1:
                warnings.append(f"Duplicate {key}: {len(pids)} instances (PIDs {', '.join(pids)})")
    except Exception as e:
        warnings.append(f"Process health check failed: {e}")
    return warnings


def check_narrative_semantics(conn: sqlite3.Connection) -> List[str]:
    """Check for LLM narrative text that claims a factor is missing when it's actually confirmed."""
    warnings = []
    FACTORS = [
        ("momentum", "confirm_momentum", lambda v: v == 1),
        ("volume", "confirm_signal", lambda v: v == 1),  # signal confirmation includes volume
        ("MACD", "confirm_momentum", lambda v: v == 1),  # MACD part of momentum
        ("EMA", "confirm_ema", lambda v: v == 1),
        ("sector", "confirm_sector", lambda v: v == 1),
    ]
    # Try web file first (most current), fallback to DB
    narr_path = WEB_DIR / "watchlist_narratives_llm.json"
    if narr_path.exists():
        data = json.loads(narr_path.read_text()).get("narratives", {})
    else:
        cur = conn.execute("SELECT symbol, narrative FROM watchlist WHERE narrative IS NOT NULL")
        data = {r[0]: r[1] for r in cur.fetchall()}

    for sym, narrative in data.items():
        if not isinstance(narrative, dict):
            text_lower = str(narrative).lower()
        else:
            text_lower = json.dumps(narrative).lower()

        for factor_name, db_col, validator in FACTORS:
            claim_missing = any(phrase in text_lower for phrase in [
                f"{factor_name} is not", f"{factor_name} missing",
                f"no {factor_name}", f"lacks {factor_name}", f"weak {factor_name}"
            ])
            if not claim_missing:
                continue
            sig_cur = conn.execute(f"SELECT {db_col} FROM signals WHERE symbol = ?", (sym,))
            sig_row = sig_cur.fetchone()
            if sig_row and sig_row[0] is not None and validator(sig_row[0]):
                warnings.append(
                    f"SEMANTIC CONTRADICTION {sym}: text implies '{factor_name}' missing "
                    f"but {db_col}={sig_row[0]} (confirmed)"
                )
    return warnings


def check_factor_integrity(conn: sqlite3.Connection) -> List[str]:
    """Verify entry_eligible consistency — trust the signal engine's computation.
    Don't second-guess individual confirmations; the engine has the full logic."""
    warnings = []
    cur = conn.execute("""
        SELECT symbol, readiness_score, is_entry_eligible, backend_tier
        FROM signals
        WHERE backend_tier = 'STRONG_NOW'
    """)
    for row in cur.fetchall():
        sym, rdy, eligible, tier = row
        if eligible and rdy < 77:
            warnings.append(f"{sym}: entry_eligible=TRUE but readiness={rdy}<77")
        if not eligible and rdy >= 77 and tier == 'STRONG_NOW':
            # STRONG_NOW but not entry_eligible — expected if hard confirmations missing
            pass
    return warnings


# ────────────────────────────────────────────────────────────────────────────
# Alert / Notify
# ────────────────────────────────────────────────────────────────────────────

def get_consecutive_ok_count(conn: sqlite3.Connection) -> int:
    """Count consecutive OK healthchecks (most recent first). Stops at first non-ok."""
    cur = conn.execute("""
        SELECT status FROM heartbeats
        WHERE job_name = 'stonkbot_healthcheck'
        ORDER BY beat_at DESC
        LIMIT 10
    """)
    count = 0
    for row in cur.fetchall():
        if row[0] == 'ok':
            count += 1
        else:
            break
    return count


def send_alert(level: str, messages: List[str], webhook_url: Optional[str] = None) -> bool:
    """Send alert. Prefer webhook, then Telegram, else log to DB."""
    if not messages:
        return True

    msg_text = "\n".join(messages)
    log_event(
        level=level.lower(),
        source="stonkbot_healthcheck",
        message=f"Healthcheck {level}: {len(messages)} issues",
        context={"issues": messages},
    )

    # Webhook
    if webhook_url:
        try:
            import urllib.request
            payload = json.dumps({"text": f"🚨 *StonkBOT {level}*\n{msg_text}"}).encode()
            req = urllib.request.Request(
                webhook_url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception as e:
            log_event("warn", "stonkbot_healthcheck", f"Webhook failed: {e}")

    # Telegram fallback
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            secrets = Path("/opt/stonk-ai/.secrets/telegram.env")
            if secrets.exists():
                for line in secrets.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
                    elif line.startswith("TELEGRAM_CHAT_ID="):
                        chat_id = line.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
        if token and chat_id:
            emoji = "🚨" if level == "CRITICAL" else "⚠️"
            alert_text = f"{emoji} *StonkBOT {level}*\n\n{msg_text}"
            payload = json.dumps({
                "chat_id": chat_id, "text": alert_text,
                "parse_mode": "Markdown", "disable_web_page_preview": True,
            }).encode()
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
            return True
    except Exception as e:
        log_event("warn", "stonkbot_healthcheck", f"Telegram alert failed: {e}")
        return False

    return True


def format_report(warnings: List[str], critical: List[str], stale_jobs: List[Dict], audits: List[str] = None) -> str:
    lines = ["StonkBOT Healthcheck Report"]
    lines.append(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("=" * 50)

    if critical:
        lines.append(f"\n🔴 CRITICAL ({len(critical)}):")
        for c in critical:
            lines.append(f"  {c}")

    if warnings:
        lines.append(f"\n🟡 WARNINGS ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  {w}")

    if stale_jobs:
        lines.append(f"\n⏱️ STALE JOBS ({len(stale_jobs)}):")
        for j in stale_jobs:
            lines.append(f"  {j['job_name']}: {j.get('minutes_ago', '?')} min ago")

    if audits:
        lines.append(f"\n🔍 AUDIT ({len(audits)}):")
        for a in audits:
            lines.append(f"  {a}")

    if not any([critical, warnings, stale_jobs, audits]):
        lines.append("\n✅ All systems healthy")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="StonkBOT unified healthcheck")
    parser.add_argument("--check", action="store_true", help="Run health checks")
    parser.add_argument("--alert", action="store_true", help="Send Telegram alert if degraded")
    parser.add_argument("--report", action="store_true", help="Print report")
    parser.add_argument("--deep-audit", action="store_true", help="Run full audit (log only)")
    parser.add_argument("--webhook-url", default=ALERT_WEBHOOK, help="Override webhook")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[!] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(2)

    conn = _connect()
    warnings = []
    critical = []
    audits = []

    # ── Critical checks (always run) ──
    critical.extend(check_db_integrity(conn))
    critical.extend(check_circuit_breaker())

    stale_jobs = check_stale_jobs(stale_minutes=20)
    critical_stale = [j for j in stale_jobs if j["job_name"] in CRITICAL_JOBS]
    non_critical_stale = [j for j in stale_jobs if j["job_name"] not in CRITICAL_JOBS]

    if critical_stale:
        critical.append(f"{len(critical_stale)} critical jobs stale")
        for j in critical_stale:
            critical.append(f"  {j['job_name']} ({j.get('minutes_ago', '?')} min)")
    if non_critical_stale:
        warnings.append(f"{len(non_critical_stale)} non-critical jobs stale")

    warnings.extend(check_signals_stale(conn))
    warnings.extend(check_portfolio_stale(conn))
    warnings.extend(check_root_processes())
    warnings.extend(check_disk_space())

    # ── Audit checks (only with --deep-audit) ──
    if args.deep_audit:
        audits.extend(check_file_permissions())
        audits.extend(check_process_health())
        audits.extend(check_narrative_semantics(conn))
        audits.extend(check_factor_integrity(conn))

    # ── Circuit breaker logic ──
    cb = CircuitBreaker()
    if critical:
        if not cb.is_open():
            cb.trip("preflight", notes="; ".join(critical[:3]), source="stonkbot_healthcheck")
            critical.append("🛑 CIRCUIT BREAKER TRIPPED — trading halted")
    elif cb.is_open():
        ok_count = get_consecutive_ok_count(conn)
        if ok_count >= 3:
            cb.reset()
            warnings.append(f"✅ Circuit breaker auto-reset after {ok_count} consecutive healthy cycles")
        else:
            warnings.append("Circuit breaker still OPEN — manual reset or wait for 3 clean checks")

    # ── Heartbeat & reporting ──
    heartbeat("stonkbot_healthcheck", status="fail" if critical else ("stale" if warnings else "ok"))

    if args.report or args.deep_audit or (not args.alert and not args.check):
        print(format_report(warnings, critical, stale_jobs, audits))

    if args.alert and (critical or warnings):
        send_alert("CRITICAL" if critical else "WARN", critical + warnings)

    # ── Exit codes ──
    if critical:
        sys.exit(2)
    if warnings:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
