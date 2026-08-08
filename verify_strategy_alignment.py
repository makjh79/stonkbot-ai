#!/usr/bin/env python3
"""verify_strategy_alignment.py — Automated strategy-surface alignment checker.

PURPOSE
-------
Every surface that displays or enforces strategy parameters must agree with
strategy_config.py (the single source of truth). This script derives ALL
expected values from strategy_config imports — it contains NO hardcoded
strategy numbers, so it never needs updating when the strategy changes.

RUN AFTER ANY STRATEGY CHANGE:
    python3 verify_strategy_alignment.py
    exit 0 = aligned, exit 1 = drift detected (details printed)

Wired into comprehensive_monitor.py so drift alerts on Telegram automatically.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE = Path("/opt/stonk-ai")
WEB = Path("/var/www/hedge-fund-website")

sys.path.insert(0, str(BASE))
import strategy_config as sc  # noqa: E402

FAILURES: list[str] = []
WARNINGS: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


# =============================================================================
# 1. strategy_config internal consistency
# =============================================================================
def check_config_valid() -> None:
    issues = sc.validate()
    for i in issues:
        fail(f"strategy_config.validate(): {i}")


# =============================================================================
# 2. config_truth.json matches export_for_website()
# =============================================================================
def check_config_truth() -> None:
    p = WEB / "config_truth.json"
    if not p.exists():
        fail("config_truth.json missing — run trade_quality_report.py")
        return
    try:
        data = json.loads(p.read_text())
    except Exception as e:
        fail(f"config_truth.json unreadable: {e}")
        return
    expected = sc.export_for_website()
    # entry gate
    eg = data.get("entry_gate", {})
    xeg = expected["entry_gate"]
    if eg.get("readiness_min") != xeg["readiness_min"]:
        fail(f"config_truth entry_gate.readiness_min={eg.get('readiness_min')} != config {xeg['readiness_min']}")
    if eg.get("confirmations_min") != xeg["confirmations_min"]:
        fail(f"config_truth confirmations_min drift: {eg.get('confirmations_min')} != {xeg['confirmations_min']}")
    if sorted(eg.get("hard_confirmation_keys", [])) != xeg["hard_confirmation_keys"]:
        fail(f"config_truth hard_confirmation_keys drift: {eg.get('hard_confirmation_keys')} != {xeg['hard_confirmation_keys']}")
    # display-only keys must NOT be in hard keys
    for k in sc.DISPLAY_ONLY_CONFIRMATION_KEYS:
        if k in eg.get("hard_confirmation_keys", []):
            fail(f"config_truth hard keys contain display-only key: {k}")
    # position management
    pm = data.get("position_management", {})
    xpm = expected["position_management"]
    if pm.get("rotation_enabled") != xpm["rotation_enabled"]:
        fail(f"config_truth rotation_enabled={pm.get('rotation_enabled')} != config {xpm['rotation_enabled']}")
    if pm.get("min_hold_days") != xpm["min_hold_days"]:
        fail(f"config_truth min_hold_days drift: {pm.get('min_hold_days')} != {xpm['min_hold_days']}")


# =============================================================================
# 3. Served HTML == source HTML
# =============================================================================
def check_html_sync() -> None:
    src = BASE / "website" / "index.html"
    dst = WEB / "index.html"
    if not src.exists() or not dst.exists():
        fail("index.html missing in source or web root")
        return
    if src.read_text() != dst.read_text():
        fail("SERVED index.html != /opt/stonk-ai/website/index.html — deploy needed")


# =============================================================================
# 4. Key rendered values appear in served HTML (spot-check the guardrail panel)
# =============================================================================
def check_html_values() -> None:
    p = WEB / "index.html"
    if not p.exists():
        return
    html = p.read_text()
    # readiness threshold
    r = int(sc.ENTRY_READINESS_MIN)
    if f"≥{r}" not in html and f">= {r}" not in html and f">={r}" not in html:
        fail(f"HTML missing readiness threshold ≥{r}")
    # wrong readiness thresholds that contradict config
    for wrong in range(60, 100):
        if wrong != r and (f"≥{wrong}" in html and "readiness" in html.lower()):
            # ignore historical annotations containing a year marker
            pat = re.compile(rf"readiness[^<]{{0,40}}≥{wrong}(?!.*2026)")
            if pat.search(html):
                fail(f"HTML contains contradictory readiness ≥{wrong}")
    # hard stop band
    lo = int(sc.HARD_STOP_MIN_PCT * 100)
    hi = int(sc.HARD_STOP_MAX_PCT * 100)
    if f"[{lo}%,{hi}%]" not in html and f"[{lo}%, {hi}%]" not in html:
        fail(f"HTML missing hard-stop band [{lo}%,{hi}%]")
    # stale stop bands that contradict config (common historical values)
    for stale in [(3, 11), (5, 15), (3, 15)]:
        if stale != (lo, hi):
            s = f"[{stale[0]}%,{stale[1]}%]"
            if s in html:
                fail(f"HTML contains stale stop band {s} (config is [{lo}%,{hi}%])")
    # min hold days
    mon = sc.MIN_HOLD_DAYS.get("RISK_ON", 0)
    moff = sc.MIN_HOLD_DAYS.get("RISK_OFF", 0)
    if f"Min hold {mon}d (RISK_ON) / {moff}d (RISK_OFF)" not in html:
        fail(f"HTML missing min-hold line: Min hold {mon}d (RISK_ON) / {moff}d (RISK_OFF)")
    # rotation state
    if not sc.ROTATION_ENABLED and "Rotation disabled" not in html:
        fail("HTML missing 'Rotation disabled' (config ROTATION_ENABLED=False)")
    # Required positive-edge hard confirmations must be named in the HTML.
    # (Website copy is not machine-derived, so we only check that the current
    # config keys are reflected in the human-readable strategy section.)
    required_labels = {
        "vwap_confirmed": ["VWAP", "vwap"],
        "options_confirmed": ["options-flow", "options flow", "options-flow"],
    }
    for key, labels in required_labels.items():
        if key in sc.REQUIRED_POSITIVE_HARD_KEYS:
            if not any(lbl in html for lbl in labels):
                fail(f"HTML missing required hard-confirmation label for {key} (looked for {labels})")
    # Display-only keys must not be described as entry drivers.
    for key in sc.DISPLAY_ONLY_CONFIRMATION_KEYS:
        # Accept only if annotated as "removed" / "display-only" / "veto" / "not used for entry"
        if key == "macd_turning" and "MACD" in html:
            if not any(ph in html for ph in ["display-only", "veto", "not used for entry", "removed"]):
                fail("HTML describes MACD without noting it is display-only / veto / not an entry driver")
        if key == "intraday_confirmed" and "intraday" in html:
            if not any(ph in html for ph in ["display-only", "veto", "not used for entry", "removed"]):
                fail("HTML describes intraday without noting it is display-only / veto / not an entry driver")


# =============================================================================
# 5. JSON freshness (popup/narrative pipelines alive)
# =============================================================================
def check_json_freshness() -> None:
    import time
    now = time.time()
    checks = {
        "popup_content.json": 3600 * 6,          # 6h (cron every 2 min)
        "watchlist_narratives.json": 3600 * 6,
        "watchlist_narratives_llm.json": 3600 * 26,  # LLM timer, allow a day+
        "config_truth.json": 3600 * 26,
        "signal_enrichment.json": 3600 * 30,
    }
    for name, max_age in checks.items():
        p = WEB / name
        if not p.exists():
            warn(f"{name} missing")
            continue
        age = now - p.stat().st_mtime
        if age > max_age:
            fail(f"{name} stale: {age/3600:.1f}h old (max {max_age/3600:.0f}h)")


# =============================================================================
# 6. Consumer files import strategy_config (no parallel hardcoding)
# =============================================================================
def check_consumers_import() -> None:
    consumers = [
        "signal_rules.py",
        "readiness_score.py",
        "trading_bot.py",
        "risk_engine.py",
        "generate_popup_content_v3.py",
        "trade_quality_report.py",
    ]
    for f in consumers:
        p = BASE / f
        if not p.exists():
            warn(f"{f} missing (expected consumer)")
            continue
        txt = p.read_text()
        if "strategy_config" not in txt:
            fail(f"{f} does not import strategy_config — risk of hardcoded drift")


# =============================================================================
# 7. Pipelines scheduled (crontab OR systemd timers — either is fine)
# =============================================================================
def check_crons() -> None:
    try:
        cron_out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        cron_out = ""
    try:
        cron_out += subprocess.run(["crontab", "-u", "stonkai", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        pass
    try:
        timers = subprocess.run(
            ["systemctl", "list-timers", "--all", "--no-pager"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        timers = ""
    combined = cron_out + timers
    # label -> list of acceptable identifiers (any one present = scheduled)
    for identifiers, label in [
        (["signal_enricher.py"], "signal enrichment"),
        (["generate_popup_content", "stonk-ai-popup"], "popup content"),
        (["comprehensive_monitor.py", "stonk-ai-monitor"], "monitor"),
        (["generate_narratives_llm", "stonk-ai-llm-narrative"], "LLM narratives"),
    ]:
        if not any(i in combined for i in identifiers):
            fail(f"pipeline not scheduled: {label} (looked for {identifiers} in crontab+timers)")


def main() -> int:
    check_config_valid()
    check_config_truth()
    check_html_sync()
    check_html_values()
    check_json_freshness()
    check_consumers_import()
    check_crons()

    for w in WARNINGS:
        print(f"WARN: {w}")
    if FAILURES:
        print("STRATEGY ALIGNMENT: DRIFT DETECTED")
        for f_ in FAILURES:
            print(f"  FAIL: {f_}")
        return 1
    print("STRATEGY ALIGNMENT: OK — all surfaces match strategy_config.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
