#!/usr/bin/env python3
"""
STONK.AI v2 Health Check

Runs every 5 minutes as a lightweight monitor. Checks the live trading bot,
data freshness, watchlist integrity, and risk guardrails. Writes a JSON
status file for the website and logs any issues.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BOT_DIR = Path("/opt/stonk-ai")
WEB_DIR = Path("/var/www/hedge-fund-website")
LOG_DIR = BOT_DIR / "logs"
HEALTH_FILE = WEB_DIR / "health_status.json"
ALPACA_CONFIG = BOT_DIR / "alpaca_config.json"

LOG_DIR.mkdir(exist_ok=True)


def now() -> datetime:
    return datetime.now(timezone.utc)


def is_us_market_open() -> bool:
    """Check if US equity market is currently open (Mon-Fri, 9:30-16:00 ET)."""
    now_dt = datetime.now(timezone.utc)
    if now_dt.weekday() >= 5:
        return False
    # EDT (UTC-4): 2nd Sun Mar to 1st Sun Nov
    march_8 = datetime(now_dt.year, 3, 8, tzinfo=timezone.utc)
    mar_dst = march_8 + timedelta(days=(6 - march_8.weekday()))
    nov_1 = datetime(now_dt.year, 11, 1, tzinfo=timezone.utc)
    nov_dst = nov_1 + timedelta(days=(6 - nov_1.weekday()))
    utc_offset = -4 if mar_dst <= now_dt < nov_dst else -5
    et_hour = now_dt.hour + (now_dt.minute / 60) + utc_offset
    return 9.5 <= et_hour < 16.0


def is_weekend_stretch() -> bool:
    """Check if we're in a weekend window (Fri after close through Mon before open)."""
    now_dt = datetime.now(timezone.utc)
    wd = now_dt.weekday()
    hr = now_dt.hour
    return wd >= 5 or (wd == 4 and hr >= 20) or (wd == 0 and hr < 13)


def log(msg: str):
    ts = now().isoformat().replace("+00:00", "Z")
    line = f"{ts} {msg}"
    print(line)
    with open(LOG_DIR / "health_check.log", "a") as f:
        f.write(line + "\n")


def file_age(path: Path) -> float:
    """Return age in seconds."""
    if not path.exists():
        return float("inf")
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (now() - mtime).total_seconds()


def check_service_active(service: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "active" in result.stdout
    except Exception:
        return False


def check_disk() -> str:
    try:
        result = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            parts = lines[1].split()
            used = int(parts[4].replace("%", ""))
            if used > 90:
                return f"CRITICAL: disk {used}% full"
            if used > 80:
                return f"WARNING: disk {used}% full"
    except Exception as e:
        return f"disk check error: {e}"
    return ""


def check_alpaca() -> str:
    if not ALPACA_CONFIG.exists():
        return "Alpaca config missing"
    try:
        cfg = json.loads(ALPACA_CONFIG.read_text())
        key = cfg.get("api_key") or cfg.get("key_id")
        secret = cfg.get("secret_key") or cfg.get("api_secret") or cfg.get("secret")
        if not key or not secret:
            return "Alpaca credentials incomplete"
        if not key.startswith(("PK", "AK", "CK")):
            return f"Alpaca key format unexpected: {key[:4]}..."
    except Exception as e:
        return f"Alpaca config error: {e}"
    return ""


def check_signals() -> list:
    issues = []
    signals_file = BOT_DIR / "signals.json"
    age = file_age(signals_file)
    if is_us_market_open():
        max_age = 1800  # 30 min during market hours
    elif is_weekend_stretch():
        max_age = 172800  # 48h weekends
    else:
        max_age = 28800  # 8h after hours
    if age > max_age:
        issues.append(f"signals.json stale ({age/60:.0f} min old)")
    try:
        data = json.loads(signals_file.read_text())
        signals = data.get("signals", [])
        scored = [s for s in signals if s.get("total_score", 0) > 0]
        if len(scored) < 5:
            issues.append(f"only {len(scored)} scored signals (expected > 5)")
    except Exception as e:
        issues.append(f"signals.json unreadable: {e}")
    return issues


def check_watchlist() -> list:
    issues = []
    live_file = WEB_DIR / "ai_watchlist_live.json"
    age = file_age(live_file)
    if is_us_market_open():
        max_age = 1200  # 20 min during market hours
    elif is_weekend_stretch():
        max_age = 172800  # 48h weekends
    else:
        max_age = 28800  # 8h after hours
    if age > max_age:
        issues.append(f"ai_watchlist_live.json stale ({age/60:.0f} min old)")
    # Retry up to 3 times with short delay to handle race with stonk-ai writer
    import time
    data = None
    last_err = None
    for attempt in range(3):
        try:
            data = json.loads(live_file.read_text())
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    if data is None:
        issues.append(f"ai_watchlist_live.json unreadable: {last_err}")
        return issues
    try:
        prices = data.get("prices", {})
        if len(prices) != 20:
            issues.append(f"watchlist has {len(prices)} symbols (expected 20)")
        scored = [s for s, d in prices.items() if d.get("is_scored_signal")]
        tracking = [s for s, d in prices.items() if not d.get("is_scored_signal")]
        if len(scored) + len(tracking) != len(prices):
            issues.append("scored/tracking flag inconsistent")
        if len(scored) == 0 and len(prices) > 0:
            issues.append("watchlist has no scored signals (all TRACKING)")
    except Exception as e:
        issues.append(f"ai_watchlist_live.json parse error: {e}")
    return issues


def check_portfolio() -> list:
    issues = []
    pf_file = WEB_DIR / "portfolio_data.json"
    age = file_age(pf_file)
    if age > 600:
        issues.append(f"portfolio_data.json stale ({age/60:.0f} min old)")
    try:
        data = json.loads(pf_file.read_text())
        account = data.get("account", {})
        pv = account.get("portfolio_value", 0)
        cash = account.get("cash", 0)
        if pv <= 0:
            issues.append("portfolio value missing or zero")
        elif cash / pv < 0.05:
            issues.append(f"cash {cash:,.0f} is {cash/pv:.1%} of portfolio (floor 5%)")
    except Exception as e:
        issues.append(f"portfolio_data.json unreadable: {e}")
    return issues


def check_data_fetcher() -> list:
    # data-fetcher.service was duplicate of stonk-ai-data.service — removed
    return []


def main():
    report = {
        "timestamp": now().isoformat().replace("+00:00", "Z"),
        "status": "HEALTHY",
        "issues": [],
        "checks": {},
    }

    # Core services
    core_services = ["stonk-ai.service", "stonk-ai-data.service", "stonk-ai-watchlist.service", "stonk-ai-markets.service"]
    for svc in core_services:
        active = check_service_active(svc)
        report["checks"][svc] = "active" if active else "down"
        if not active:
            report["issues"].append(f"{svc} is not active")

    # Signals
    signal_issues = check_signals()
    report["checks"]["signals"] = "ok" if not signal_issues else "issues"
    report["issues"].extend(signal_issues)

    # Watchlist
    watchlist_issues = check_watchlist()
    report["checks"]["watchlist"] = "ok" if not watchlist_issues else "issues"
    report["issues"].extend(watchlist_issues)

    # Portfolio / cash floor
    portfolio_issues = check_portfolio()
    report["checks"]["portfolio"] = "ok" if not portfolio_issues else "issues"
    report["issues"].extend(portfolio_issues)

    # Alpaca
    alpaca_issue = check_alpaca()
    report["checks"]["alpaca"] = "ok" if not alpaca_issue else "issues"
    if alpaca_issue:
        report["issues"].append(alpaca_issue)

    # Disk
    disk_issue = check_disk()
    report["checks"]["disk"] = "ok" if not disk_issue else "issues"
    if disk_issue:
        report["issues"].append(disk_issue)
        if "CRITICAL" in disk_issue:
            report["status"] = "CRITICAL"

    if report["issues"] and report["status"] != "CRITICAL":
        report["status"] = "DEGRADED"

    # Save website status
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(report, indent=2))

    # Log concise summary
    log(f"Health: {report['status']} | issues={len(report['issues'])}")
    for issue in report["issues"]:
        log(f"  ⚠️ {issue}")

    return 0 if report["status"] == "HEALTHY" else 1


if __name__ == "__main__":
    sys.exit(main())
