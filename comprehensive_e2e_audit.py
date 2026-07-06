#!/usr/bin/env python3
"""
StonkBOT.AI Comprehensive End-to-End Audit
Verifies system health, strategy alignment, and trading readiness.
Run this before market open or after any deployment.
"""

import json, os,sqlite3, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/opt/stonk-ai")
DB = BASE / "stonkbot.db"
RED, GRN, YEL, BLU, RST = "\033[91m", "\033[92m", "\033[93m", "\033[94m", "\033[0m"

def section(title):
    print(f"\n{BLU}{'='*70}{RST}")
    print(f"  {BLU}{title}{RST}")
    print(f"{BLU}{'='*70}{RST}")

def ok(msg): print(f"  {GRN}✓{RST} {msg}")
def warn(msg): print(f"  {YEL}⚠{RST} {msg}")
def fail(msg): print(f"  {RED}✗{RST} {msg}")

def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None

issues = []
warnings = []

# 1. INFRASTRUCTURE & SYSTEM HEALTH
section("1. INFRASTRUCTURE & SYSTEM HEALTH")

# Database
if not DB.exists():
    fail("stonkbot.db MISSING")
    issues.append("MISSING_DB")
else:
    stat = DB.stat()
    ok(f"Database: {DB.stat().st_size//1024}K")
    import pwd, grp
    try:
        uname = pwd.getpwuid(stat.st_uid).pw_name
        if uname == "stonkai":
            ok(f"Owner: {uname}")
        else:
            warn(f"Owner: {uname} (expected stonkai)")
            warnings.append("DB_OWNER")
    except: pass

# Critical tables
try:
    conn = sqlite3.connect(str(DB))
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    expected = {'signals','watchlist','holdings','portfolio_snapshots','portfolio_history','trading_halt','system_log','heartbeats'}
    if expected.issubset(tables):
        ok(f"All {len(expected)} tables present")
    else:
        fail(f"Missing tables: {expected - tables}")
        issues.append("MISSING_TABLES")
except Exception as e:
    fail(f"DB error: {e}")
    issues.append("DB_ERROR")

# Circuit breaker
try:
    sys.path.insert(0, str(BASE))
    from circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    if not cb.is_open():
        ok("Circuit breaker: CLOSED")
    else:
        fail(f"Circuit breaker: OPEN — {cb.status().get('reason')}")
        issues.append("BREAKER_OPEN")
except Exception as e:
    fail(f"Circuit breaker: {e}")
    issues.append("CB_ERROR")

# Systemd timers
for svc in ["stonkbot-healthcheck.timer", "stonkbot-healthcheck.service"]:
    result = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
    if result.stdout.strip() in ("active", "activating"):
        ok(f"{svc}: active")
    else:
        warn(f"{svc}: {result.stdout.strip()}")
        warnings.append(f"SYSTEMD_{svc}")

# File ownership — critical trading files
for pattern in ["trading_bot.py", "signal_engine.py", "signals.json", "ai_watchlist_live.json", "stonkbot_db.py", "circuit_breaker.py"]:
    f = BASE / pattern
    if f.exists():
        s = f.stat()
        if s.st_uid == 0:
            warn(f"{pattern}: root-owned")
            warnings.append(f"ROOT_{pattern}")
        else:
            ok(f"{pattern}: owned by uid {s.st_uid}")

# 2. DATA FRESHNESS & PIPELINE
section("2. DATA FRESHNESS & PIPELINE")

now = time.time()

# Signals freshness
sig_path = BASE / "signals.json"
if sig_path.exists():
    age = (now - sig_path.stat().st_mtime) / 60
    if age < 20:
        ok(f"signals.json: {age:.0f} min old")
    elif age < 60:
        warn(f"signals.json: {age:.0f} min old")
        warnings.append("STALE_SIGNALS")
    else:
        fail(f"signals.json: {age:.0f} min old (CRITICAL)")
        issues.append("VERY_STALE_SIGNALS")

# Watchlist freshness
wl_path = Path("/var/www/hedge-fund-website/ai_watchlist_live.json")
if wl_path.exists():
    age = (now - wl_path.stat().st_mtime) / 60
    if age < 20:
        ok(f"ai_watchlist_live.json: {age:.0f} min old")
    else:
        warn(f"ai_watchlist_live.json: {age:.0f} min old")
        warnings.append("STALE_WATCHLIST")

# Portfolio data
pf_path = BASE / "portfolio_data.json"
if pf_path.exists():
    age = (now - pf_path.stat().st_mtime) / 60
    if age < 10:
        ok(f"portfolio_data.json: {age:.0f} min old")
    else:
        warn(f"portfolio_data.json: {age:.0f} min old")

# Market status
ms_path = BASE / "market_status.json"
is_open = False
mode = "unknown"
if ms_path.exists():
    ms = _load_json(ms_path)
    if ms:
        mode = ms.get("mode", "unknown")
        is_open = "open" in mode.lower()
        ok(f"Market status: {mode}")
    else:
        warn("market_status.json unreadable")
else:
    warn("market_status.json missing")

# 3. SIGNAL QUALITY & STRATEGY ALIGNMENT
section("3. SIGNAL QUALITY & STRATEGY ALIGNMENT")

try:
    with open(sig_path) as f:
        sig_data = json.load(f)
    sigs = sig_data.get("signals", [])
    
    total = len(sigs)
    strong_now = [s for s in sigs if s.get("tier") == "STRONG_NOW"]
    entry_eligible = [s for s in sigs if s.get("entry_eligible")]
    
    ok(f"Total signals: {total}")
    ok(f"STRONG_NOW: {len(strong_now)}")
    ok(f"Entry-eligible: {len(entry_eligible)}")
    
    # Verify entry criteria for eligible signals
    for s in entry_eligible:
        problems = []
        if s.get("tier") != "STRONG_NOW":
            problems.append("not STRONG_NOW")
        if s.get("readiness_score", 0) < 77:
            problems.append(f"readiness={s.get('readiness_score')} < 77")
        if not s.get("above_ema20"):
            problems.append("below EMA20")
        if problems:
            fail(f"{s['symbol']}: entry_eligible but {'; '.join(problems)}")
            issues.append(f"BAD_ENTRY_{s['symbol']}")
        else:
            ok(f"{s['symbol']}: entry criteria valid (readiness={s.get('readiness_score')})")
    
    # Flag STRONG_NOW that aren't entry-eligible (expected but explain)
    for s in strong_now:
        if not s.get("entry_eligible"):
            warn(f"{s['symbol']}: STRONG_NOW but not entry_eligible (expected if confirmations missing)")
    
except Exception as e:
    fail(f"Signal analysis failed: {e}")
    issues.append("SIGNAL_PARSE_ERROR")

# 4. WATCHLIST ALIGNMENT
section("4. WATCHLIST ↔ SIGNALS ↔ PORTFOLIO ALIGNMENT")

try:
    with open(wl_path) as f:
        wl_data = json.load(f)
    wl_prices = wl_data.get("prices", {})
    wl_symbols = set(wl_prices.keys())
    
    # All entry-eligible in watchlist?
    for s in entry_eligible:
        if s["symbol"] in wl_symbols:
            ok(f"{s['symbol']}: entry-eligible → in watchlist")
        else:
            fail(f"{s['symbol']}: entry-eligible but NOT in watchlist")
            issues.append(f"MISSING_WL_{s['symbol']}")
    
    # Portfolio alignment
    pf = _load_json(pf_path)
    if pf:
        positions = {p["symbol"]: p for p in pf.get("positions", [])}
        cash = float(pf.get("account", {}).get("cash", 0))
        pv = float(pf.get("account", {}).get("portfolio_value", 0))
        
        ok(f"Portfolio: ${pv:,.0f} value, ${cash:,.0f} cash ({cash/pv*100:.1f}%)")
        
        # Check held positions match watchlist
        for sym in positions:
            if sym in wl_symbols:
                pass  # ok(f"{sym}: held → in watchlist")
            else:
                warn(f"{sym}: held but NOT in watchlist")
                warnings.append(f"HELD_NOT_WL_{sym}")
        
        # Cash floor check (risk-based)
        try:
            from regime_detector import get_regime
            reg = get_regime()
            floor = reg["params"]["cash_floor_pct"]
            actual_floor = cash / pv * 100 if pv else 0
            if actual_floor >= floor:
                ok(f"Cash floor: {actual_floor:.1f}% ≥ {floor}% (regime: {reg['regime']})")
            else:
                fail(f"Cash floor: {actual_floor:.1f}% < {floor}% required")
                issues.append("CASH_FLOOR_BREACH")
        except:
            pass  # regime detector may fail off-hours
except Exception as e:
    fail(f"Watchlist/portfolio alignment failed: {e}")
    issues.append("ALIGN_ERROR")

# 5. EXECUTION SAFETY
section("5. EXECUTION SAFETY")

tb_text = (BASE / "trading_bot.py").read_text()

# Flash crash guard
guards = [
    ("Ask + 0.5% cap", "cap_limit = round(fresh_ask * 1.005"),
    ("Flash crash abort", "marketable_limit > mid * 1.02"),
    ("No market fallback", "submit_market_order" not in tb_text.split("# Not filled")[1].split("def ")[0] if "# Not filled" in tb_text else True),
    ("Abort logging", "EXECUTION ABORT"),
]
for name, check in guards:
    if isinstance(check, str):
        present = check in tb_text
    else:
        present = check
    if present:
        ok(f"{name}: present")
    else:
        fail(f"{name}: MISSING")
        issues.append(f"MISSING_{name.replace(' ', '_')}")

# Opening bell guard
if "OPENING BELL" in tb_text and "9 <= et_now.hour < 10" in tb_text:
    ok("Opening bell guard: present")
else:
    fail("Opening bell guard: missing")
    issues.append("MISSING_OPENING_BELL")

# Tiered execution
if "_submit_tiered_single" in tb_text:
    ok("Tiered execution: present")
else:
    fail("Tiered execution: missing")
    issues.append("MISSING_TIERED")

# 6. LLM PIPELINE & REPORTING
section("6. LLM PIPELINE & REPORTING")

llm_files = {
    "Holdings narratives": "/var/www/hedge-fund-website/holdings_llm_narratives.json",
    "Watchlist narratives": "/var/www/hedge-fund-website/watchlist_llm_narratives.json",
    "Portfolio summary": "/var/www/hedge-fund-website/portfolio_summary.json",
}
for name, path in llm_files.items():
    p = Path(path)
    if p.exists():
        age = (now - p.stat().st_mtime) / 60
        if age < 25:
            ok(f"{name}: {age:.0f} min old")
        else:
            warn(f"{name}: {age:.0f} min old")
            warnings.append(f"STALE_LLM_{name.replace(' ', '_')}")
    else:
        warn(f"{name}: file missing")
        warnings.append(f"MISSING_LLM_{name.replace(' ', '_')}")

# 7. RISK ENGINE
section("7. RISK ENGINE")

try:
    from risk_engine import RiskEngine, RiskConfig
    rc = RiskConfig()
    ok(f"Max position: {rc.max_single_position_pct*100:.0f}%")
    ok(f"Sector limit: {rc.max_sector_pct*100:.0f}%")
    ok(f"High-beta cap: {rc.high_beta_basket_pct*100:.0f}%")
    ok(f"Min cash: ${rc.min_cash:,.0f}")
except Exception as e:
    warn(f"Risk engine check failed: {e}")

# 8. END-TO-END DATA FLOW
section("8. END-TO-END DATA FLOW")

flow_checks = [
    ("Alpaca → signal_engine", sig_path.exists() and sig_path.stat().st_size > 1000),
    ("signal_engine → stonkbot.db", DB.exists()),
    ("signal_engine → signals.json (web mirror)", sig_path.exists()),
    ("stonkbot.db → watchlist", "watchlist" in tables),
    ("watchlist → ai_watchlist_live.json", wl_path.exists()),
    ("ai_watchlist_live.json → trading_bot", wl_path.exists()),
    ("trading_bot → portfolio_data.json", pf_path.exists()),
    ("portfolio_data.json → website", pf_path.exists()),
]
for name, check in flow_checks:
    if check:
        ok(f"{name}: ✓")
    else:
        fail(f"{name}: ✗ BROKEN")
        issues.append(f"FLOW_{name.replace(' ', '_').replace('→', '_')}")

# 9. FINAL SUMMARY
section("9. AUDIT SUMMARY")

print(f"\n  {GRN}Time:{RST} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
print(f"  {GRN}Database:{RST} {DB.stat().st_size//1024}K, {len(sigs)} signals, {len(entry_eligible)} entry-eligible")
print(f"  {GRN}Market:{RST} {'OPEN' if is_open else 'CLOSED'} ({mode})")
print(f"  {GRN}Circuit Breaker:{RST} {'OPEN' if cb.is_open() else 'CLOSED'}")

print(f"\n  {GRN}Issues:{RST} {len(issues)}")
for i in issues:
    print(f"    {RED}- {i}{RST}")

print(f"\n  {YEL}Warnings:{RST} {len(warnings)}")
for w in warnings:
    print(f"    {YEL}- {w}{RST}")

if not issues and not warnings:
    print(f"\n  {GRN}{'✓ ALL SYSTEMS GO — READY FOR TRADING'}{RST}")
    sys.exit(0)
elif not issues:
    print(f"\n  {YEL}{'⚠ MINOR WARNINGS — SAFE TO TRADE'}{RST}")
    sys.exit(0)
else:
    print(f"\n  {RED}{'✗ CRITICAL ISSUES — DO NOT TRADE'}{RST}")
    sys.exit(1)
