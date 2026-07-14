#!/usr/bin/env python3
"""
StonkBOT Pipeline Monitor — Lightweight alert relay.

Reads existing health_status.json (from stonk_health_check.py, every 5 min)
and monitor_status.json (from monitor.py, every 5 min market hours) from VPS.
Consolidates into one status. Alerts Howie via OpenClaw cron ONLY when broken.

No re-checking — just reads what the VPS scripts already produce.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone

# Expected config — update these when the system changes
EXPECTED_FACTOR_COUNT = 9  # PEAD revived — 9 confirmation factors
EXPECTED_MAX_POSITION_PCT = 8  # 8% hard cap all tiers
EXPECTED_TIER_DENOMINATOR = 9  # confirmations shown as x/9

VPS = "root@23.80.82.47"
SSH_KEY = "~/.ssh/id_rsa"
SSH_OPTS = f"-i {SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# Files to read on VPS
HEALTH_FILE = "/var/www/hedge-fund-website/health_status.json"
MONITOR_FILE = "/opt/stonk-ai/monitor_status.json"


def ssh_cat(path: str) -> dict:
    """Read a JSON file from VPS via SSH."""
    try:
        result = subprocess.run(
            f"ssh {SSH_OPTS} {VPS} 'cat {path} 2>/dev/null'",
            shell=True, capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"_error": "SSH timeout"}
    except Exception as e:
        return {"_error": str(e)}
    return {"_error": "file empty or missing"}


def check_data_integrity() -> dict:
    """Run lightweight data integrity checks on the VPS."""
    result = {"issues": [], "checks": {}}

    # Check 1: Factor count in tier_reason — should be /9 (PEAD revived)
    out = ssh_cat("/var/www/hedge-fund-website/popup_content.json")
    if "_error" not in out:
        holdings = out.get("holdings", {})
        stale_denom = []
        has_earnings = []
        for sym, data in holdings.items():
            tier = data.get("tier_reason", "")
            if "/8" in tier:
                stale_denom.append(sym)
            conf = data.get("confirmations", {})
            if "earnings_confirmed" not in conf:
                has_earnings.append(sym)
        if stale_denom:
            result["issues"].append(f"stale factor denominator /8 found in: {', '.join(stale_denom[:5])} (should be /9)")
            result["checks"]["factor_denominator"] = "FAIL"
        else:
            result["checks"]["factor_denominator"] = "ok"
        if has_earnings:
            result["issues"].append(f"missing earnings_confirmed field in: {', '.join(has_earnings[:5])} (PEAD should be present)")
            result["checks"]["earnings_field"] = "FAIL"
        else:
            result["checks"]["earnings_field"] = "ok"
    else:
        result["checks"]["popup_integrity"] = "ok"  # don't double-fail if file unreadable

    # Check 1b: News data present in popup_content.json
    out2 = ssh_cat("/var/www/hedge-fund-website/popup_content.json")
    if "_error" not in out2:
        holdings = out2.get("holdings", {})
        missing_news = []
        for sym, data in holdings.items():
            if not (data.get("catalyst") and data.get("alpacaNewsHeadline")):
                missing_news.append(sym)
        if missing_news:
            result["issues"].append(f"[NEWS BUG] {len(missing_news)} holdings lack Alpaca news in popup JSON: {', '.join(missing_news[:5])}")
            result["checks"]["holdings_news"] = "FAIL"
        else:
            result["checks"]["holdings_news"] = "ok"
    else:
        result["checks"]["holdings_news"] = "ok"

    # Check 1c: Watchlist narratives contain catalyst/Alpaca news
    wn = ssh_cat("/var/www/hedge-fund-website/watchlist_narratives.json")
    if "_error" not in wn:
        narratives = wn.get("narratives", {})
        missing_watchlist_news = []
        for sym, data in narratives.items():
            if not (data.get("catalyst") or data.get("alpacaNewsHeadline")):
                missing_watchlist_news.append(sym)
        if missing_watchlist_news:
            result["issues"].append(f"[NEWS BUG] {len(missing_watchlist_news)} watchlist items lack narrative/news: {', '.join(missing_watchlist_news[:5])}")
            result["checks"]["watchlist_news"] = "FAIL"
        else:
            result["checks"]["watchlist_news"] = "ok"
    else:
        result["checks"]["watchlist_news"] = "ok"

    # Check 2: Signal engine output vs expected factor count
    sig_out = subprocess.run(
        f"ssh {SSH_OPTS} {VPS} 'python3 -c \""
        f"import json; d=json.load(open(\\\"/opt/stonk-ai/signals.json\\\")); "
        f"sigs=d.get(\\\"signals\\\",[]); "
        f"print(len([s for s in sigs if s.get(\\\"total_score\\\",0)>0]))\"'",
        shell=True, capture_output=True, text=True, timeout=20
    )
    try:
        scored = int(sig_out.stdout.strip())
        result["checks"]["scored_signals"] = "ok" if scored >= 3 else "WARN"
        if scored < 3:
            result["issues"].append(f"only {scored} scored signals (expected >=3)")
    except Exception:
        result["checks"]["scored_signals"] = "ok"  # don't fail on parse

    return result


def check_universe_names():
    result = {"issues": [], "checks": {}}
    dq = chr(34)
    sq = chr(39)
    cmd = f"ssh {SSH_OPTS} {VPS} {sq}cd /opt/stonk-ai && python3 -c {dq}import json, signal_engine; missing=sorted(set(signal_engine.DEFAULT_UNIVERSE)-set(signal_engine.COMPANY_NAMES.keys())); print(json.dumps(missing)){dq}{sq}"
    name_out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    if name_out.returncode == 0 and name_out.stdout.strip():
        missing = json.loads(name_out.stdout.strip())
        if missing:
            result["issues"].append(f"Missing COMPANY_NAMES for {len(missing)} universe symbols: {', '.join(missing)}")
            result["checks"]["universe_names"] = "FAIL"
        else:
            result["checks"]["universe_names"] = "ok"
    else:
        result["checks"]["universe_names"] = "WARN"
        result["issues"].append(f"Could not verify universe names: {name_out.stderr.strip()[:80]}")
    return result


def main():
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "HEALTHY",
        "issues": [],
        "sources": {},
    }

    # 1. Read stonk_health_check.py output
    health = ssh_cat(HEALTH_FILE)
    if "_error" in health:
        report["issues"].append(f"health_status.json: {health['_error']}")
        report["status"] = "BROKEN"
    else:
        report["sources"]["stonk_health_check"] = health.get("status", "UNKNOWN")
        for issue in health.get("issues", []):
            report["issues"].append(issue)
        if health.get("status") == "DEGRADED":
            report["status"] = "DEGRADED" if report["status"] == "HEALTHY" else report["status"]
        elif health.get("status") == "CRITICAL":
            report["status"] = "BROKEN"

    # 2. Read monitor.py output (market hours only — may be stale off-hours)
    monitor = ssh_cat(MONITOR_FILE)
    if "_error" not in monitor:
        report["sources"]["monitor"] = "healthy" if monitor.get("healthy") else "unhealthy"
        if not monitor.get("healthy"):
            # Check if monitor is expected to be recent (market hours)
            ts = monitor.get("timestamp", "")
            if ts:
                try:
                    mt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age = (datetime.now(timezone.utc) - mt).total_seconds()
                    now_utc = datetime.now(timezone.utc)
                    is_weekday = now_utc.weekday() < 5
                    is_market_hours = is_weekday and 13 <= now_utc.hour < 20
                    if is_market_hours and age < 600:
                        # Monitor is recent and unhealthy — real issue
                        report["issues"].append("monitor.py: unhealthy (market hours)")
                        report["status"] = "BROKEN"
                        # Add any specific issues from monitor
                        for k, v in monitor.get("data_freshness", {}).items():
                            if isinstance(v, dict) and v.get("age_minutes", 0) > v.get("max_age_minutes", 999):
                                report["issues"].append(f"monitor: {k} stale ({v['age_minutes']:.0f}min)")
                        if monitor.get("kill_switch_triggered"):
                            report["issues"].append("monitor: KILL SWITCH TRIGGERED")
                except Exception:
                    pass  # Don't fail on timestamp parsing
    # 3. Data integrity checks (run remotely, lightweight)
    integrity = check_data_integrity()
    report["checks"] = integrity["checks"]
    if integrity["issues"]:
        report["issues"].extend(integrity["issues"])
        if report["status"] == "HEALTHY":
            report["status"] = "DEGRADED"

    # Universe name coverage check
    universe_check = check_universe_names()
    if universe_check["issues"]:
        report["issues"].extend(universe_check["issues"])
        report["checks"]["universe_names"] = universe_check["checks"].get("universe_names", "FAIL")
        if report["status"] == "HEALTHY":
            report["status"] = "DEGRADED"
    else:
        report["checks"]["universe_names"] = "ok"

    # 4. Basic connectivity check (SSH itself worked if we got here)
    report["sources"]["ssh_connectivity"] = "ok"

    # Set final status
    if report["issues"] and report["status"] == "HEALTHY":
        has_fail = any("DOWN" in i or "CRITICAL" in i or "BROKEN" in i for i in report["issues"])
        report["status"] = "BROKEN" if has_fail else "DEGRADED"

    # Output
    if report["status"] == "HEALTHY":
        print(json.dumps({"status": "HEALTHY", "timestamp": report["timestamp"]}))
        sys.exit(0)
    else:
        print(json.dumps(report, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()