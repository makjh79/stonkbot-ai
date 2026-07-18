#!/usr/bin/env python3
"""STONK.AI Outcome Tracker — the measurement layer.

Answers the only question that matters: does the readiness model have edge?

Two cohorts, tracked independently:
  1. SIGNAL cohort — every symbol that enters tier STRONG_NOW or NOW in
     signals.json. Measures whether the model's picks go up afterward,
     regardless of what the bot did. (Model quality.)
  2. TRADE cohort — actual bot BUY fills from trades_log.json. Measures
     forward returns of what the bot really did. (Execution quality.)

Each entry tracks forward returns at 5/10/20 calendar days. Prices come from
local files only (ai_watchlist_live.json -> portfolio_data.json fallback) —
no external API calls.

Single writer of /opt/stonk-ai/signal_outcomes.json and
/var/www/hedge-fund-website/signal_accuracy.json (see OWNERSHIP.md).

Runs via stonkai cron every 15 min. Replaces the defunct signal_tracker.py
pipeline (which wrote into engine-owned signals.json and never closed a
single signal: 494 tracked, win_rate 0).
"""

import json
import logging
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, "/opt/stonk-ai")
try:
    from stonk_utils import atomic_write_json
except Exception:  # fallback for local testing outside the repo
    atomic_write_json = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_DIR = Path("/opt/stonk-ai")
WEB_DIR = Path("/var/www/hedge-fund-website")

SIGNALS_FILE = BOT_DIR / "signals.json"
WATCHLIST_FILE = WEB_DIR / "ai_watchlist_live.json"
PORTFOLIO_FILE = WEB_DIR / "portfolio_data.json"
TRADES_FILE = BOT_DIR / "trades_log.json"
STATE_FILE = BOT_DIR / "signal_outcomes.json"
ACCURACY_FILE = WEB_DIR / "signal_accuracy.json"

TRACK_TIERS = {"STRONG_NOW", "NOW"}
WINDOWS = (5, 10, 20)
# Re-arm: a symbol can be re-tracked once its previous entry is closed
# and it has been absent from tracked tiers for this many days.
REARM_ABSENT_DAYS = 10
# Give up filling a window if we have no price for this many days
STALE_CLOSE_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _load_json(path: Path, default):
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read {path}: {e}")
    return default


def _atomic_write(path: Path, data) -> None:
    if atomic_write_json is not None:
        atomic_write_json(path, data)
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


# -----------------------------------------------------------------------------
# Price lookup (local files only)
# -----------------------------------------------------------------------------

def load_price_map() -> Dict[str, float]:
    prices: Dict[str, float] = {}
    wl = _load_json(WATCHLIST_FILE, {})
    for sym, data in (wl.get("prices") or {}).items():
        p = data.get("price")
        if isinstance(p, (int, float)) and p > 0:
            prices[sym] = float(p)
    pf = _load_json(PORTFOLIO_FILE, {})
    for pos in pf.get("positions", []):
        sym = pos.get("symbol")
        p = pos.get("current") or pos.get("current_price")
        if sym and isinstance(p, (int, float)) and p > 0 and sym not in prices:
            prices[sym] = float(p)
    return prices


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------

def load_state() -> Dict:
    st = _load_json(STATE_FILE, None)
    if not isinstance(st, dict) or "entries" not in st:
        st = {"entries": [], "created_at": _iso(_now())}
    return st


def save_state(st: Dict) -> None:
    st["updated_at"] = _iso(_now())
    _atomic_write(STATE_FILE, st)


# -----------------------------------------------------------------------------
# Cohort intake
# -----------------------------------------------------------------------------

def intake_signals(st: Dict, prices: Dict[str, float]) -> int:
    """Open SIGNAL-cohort entries for symbols currently in tracked tiers."""
    data = _load_json(SIGNALS_FILE, {})
    sigs = data.get("signals", [])
    now = _now()
    today = now.strftime("%Y-%m-%d")
    added = 0

    open_symbols = {e["symbol"] for e in st["entries"] if e["status"] == "open"}

    for sig in sigs:
        sym = sig.get("symbol")
        tier = sig.get("tier")
        if not sym or tier not in TRACK_TIERS:
            continue
        if sym in open_symbols:
            continue

        # Re-arm guard: skip if a closed entry for this symbol closed recently
        recent_closed = [
            e for e in st["entries"]
            if e["symbol"] == sym and e["status"] == "closed"
            and (now - (_parse(e.get("closed_at") or "2000-01-01") or now)).days < REARM_ABSENT_DAYS
        ]
        if recent_closed:
            continue

        price = prices.get(sym) or sig.get("price") or 0
        if not price or price <= 0:
            continue

        st["entries"].append({
            "cohort": "signal",
            "symbol": sym,
            "tier": tier,
            "readiness": sig.get("readiness_score"),
            "confirmation_count": sig.get("confirmation_count"),
            "entry_date": today,
            "entry_ts": _iso(now),
            "entry_price": round(float(price), 4),
            "returns": {},          # {"5": pct, "10": pct, "20": pct}
            "last_price": float(price),
            "status": "open",
        })
        open_symbols.add(sym)
        added += 1
        logger.info(f"📈 SIGNAL tracked: {sym} tier={tier} R={sig.get('readiness_score')} @ ${price:.2f}")
    return added


def intake_trades(st: Dict) -> int:
    """Open TRADE-cohort entries for actual bot BUY fills."""
    trades = _load_json(TRADES_FILE, [])
    if isinstance(trades, dict):
        trades = trades.get("trades", [])
    now = _now()
    added = 0

    # Existing entries: dedupe on (symbol, entry_date) for trade cohort
    existing_keys = {
        (e["symbol"], e["entry_date"]) for e in st["entries"] if e["cohort"] == "trade"
    }

    for t in trades:
        ts = t.get("timestamp") or t.get("time") or ""
        if not ts:
            continue
        day = ts[:10]
        # Reason field marks buys; trades_log entries lack side, so use rationale text
        reason = str(t.get("rationale") or t.get("reason") or "")
        is_buy = reason.startswith(("Entry", "Avg-in", "Dip buy", "Buy "))
        if not is_buy:
            continue
        sym = t.get("symbol")
        price = t.get("price") or t.get("filled_avg_price") or 0
        if not sym or not isinstance(price, (int, float)) or price <= 0:
            continue
        if (sym, day) in existing_keys:
            continue

        st["entries"].append({
            "cohort": "trade",
            "symbol": sym,
            "tier": None,
            "readiness": None,
            "confirmation_count": None,
            "entry_date": day,
            "entry_ts": ts,
            "entry_price": round(float(price), 4),
            "returns": {},
            "last_price": float(price),
            "status": "open",
            "reason": reason[:120],
        })
        existing_keys.add((sym, day))
        added += 1
    if added:
        logger.info(f"🛒 TRADE cohort: +{added} entries from trades_log")
    return added


# -----------------------------------------------------------------------------
# Outcome updates
# -----------------------------------------------------------------------------

def update_entries(st: Dict, prices: Dict[str, float]) -> int:
    now = _now()
    updated = 0
    for e in st["entries"]:
        if e["status"] != "open":
            continue
        sym = e["symbol"]
        fresh_price = prices.get(sym)
        entry_dt = _parse(e["entry_ts"]) or _parse(e["entry_date"])
        if entry_dt is None:
            continue
        days = (now - entry_dt).days

        if fresh_price and fresh_price > 0:
            e["last_price"] = fresh_price
        else:
            # No fresh price (e.g. symbol left the watchlist): do NOT fill
            # windows with the stale entry price — that would fabricate 0.0%.
            if days >= STALE_CLOSE_DAYS:
                e["status"] = "closed"
                e["closed_at"] = _iso(now)
                e["close_reason"] = "no_price_stale"
            continue

        ret = (fresh_price - e["entry_price"]) / e["entry_price"] * 100

        filled = False
        for w in WINDOWS:
            if str(w) not in e["returns"] and days >= w:
                e["returns"][str(w)] = round(ret, 2)
                filled = True
        if filled:
            updated += 1

        # Close when all windows filled, or entry is ancient
        if all(str(w) in e["returns"] for w in WINDOWS):
            e["status"] = "closed"
            e["closed_at"] = _iso(now)
            e["close_reason"] = "windows_complete"
        elif days >= STALE_CLOSE_DAYS:
            e["status"] = "closed"
            e["closed_at"] = _iso(now)
            e["close_reason"] = "stale"
    return updated


# -----------------------------------------------------------------------------
# Stats + website export
# -----------------------------------------------------------------------------

def _window_stats(entries: List[Dict], window: str) -> Dict:
    rets = [e["returns"][window] for e in entries if window in e.get("returns", {})]
    if not rets:
        return {"n": 0, "win_rate": None, "avg_return": None, "median_return": None}
    wins = sum(1 for r in rets if r > 0)
    return {
        "n": len(rets),
        "win_rate": round(wins / len(rets) * 100, 1),
        "avg_return": round(statistics.mean(rets), 2),
        "median_return": round(statistics.median(rets), 2),
    }


def compute_stats(st: Dict) -> Dict:
    entries = st["entries"]
    by_cohort = {}
    for cohort in ("signal", "trade"):
        co = [e for e in entries if e["cohort"] == cohort]
        by_cohort[cohort] = {
            "total": len(co),
            "open": sum(1 for e in co if e["status"] == "open"),
            "windows": {str(w): _window_stats(co, str(w)) for w in WINDOWS},
        }

    # By tier (signal cohort only)
    by_tier = {}
    for tier in TRACK_TIERS:
        te = [e for e in entries if e["cohort"] == "signal" and e.get("tier") == tier]
        if te:
            by_tier[tier] = {str(w): _window_stats(te, str(w)) for w in WINDOWS}

    # Frontend-compatible headline: use 10d window across all entries
    w10 = _window_stats(entries, "10")
    open_entries = [e for e in entries if e["status"] == "open"]
    return {
        "total_signals": len(entries),
        "win_rate": w10["win_rate"] if w10["win_rate"] is not None else 0,
        "avg_return": w10["avg_return"] if w10["avg_return"] is not None else 0,
        "avg_days_to_target": 10,
        "pending_signals": len(open_entries),
        "window_note": "win_rate/avg_return measured at 10 calendar days",
        "by_cohort": by_cohort,
        "by_tier": by_tier,
    }


def export_website(st: Dict, stats: Dict, prices: Dict[str, float]) -> None:
    open_entries = [e for e in st["entries"] if e["status"] == "open"]
    recent = sorted(open_entries, key=lambda e: e["entry_ts"], reverse=True)[:10]
    for e in recent:
        px = prices.get(e["symbol"])
        if px and e["entry_price"] > 0:
            e["unrealized_return"] = round((px - e["entry_price"]) / e["entry_price"] * 100, 2)
    payload = {
        "stats": stats,
        "recent_pending": recent,
        "last_updated": _iso(_now()),
    }
    _atomic_write(ACCURACY_FILE, payload)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    st = load_state()
    prices = load_price_map()
    if not prices:
        logger.warning("No prices available; skipping run")
        return 0

    n_sig = intake_signals(st, prices)
    n_trd = intake_trades(st)
    n_upd = update_entries(st, prices)
    stats = compute_stats(st)
    st["stats"] = stats
    save_state(st)
    export_website(st, stats, prices)

    logger.info(
        f"Outcome tracker: +{n_sig} signal, +{n_trd} trade, {n_upd} updated | "
        f"total={stats['total_signals']} open={stats['pending_signals']} "
        f"10d win_rate={stats['win_rate']}% avg={stats['avg_return']}%"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
