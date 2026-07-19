#!/usr/bin/env python3
"""Capture entry-time factor snapshots for new BUY trades.

Runs every 15 min via stonkai cron. For each BUY trade that is not yet
snapshotted AND executed within the capture window, records the symbol's
current signal confirmations from signals.json.

Honesty rule: older unsnapshotted trades are NOT backfilled. Snapshotting
stale signals for old trades would contaminate factor attribution with
lookahead-adjacent data. Data accumulates from deployment time forward.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from stonk_utils import atomic_write_json
from signal_rules import CONFIRMATION_CHIPS, compute_confirmation_count, hard_confirmation_count

BASE = Path("/opt/stonk-ai")
TRADES = BASE / "trades_log.json"
SIGNALS = BASE / "signals.json"
OUT = BASE / "entry_factor_snapshots.json"

CAPTURE_WINDOW_MIN = 45  # cron is */15 + signals refresh */15 -> 45 min covers lag


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def main():
    trades = load_json(TRADES, {}).get("trades", [])
    signals = {s.get("symbol"): s for s in load_json(SIGNALS, {}).get("signals", []) if s.get("symbol")}
    store = load_json(OUT, {"snapshots": {}})
    snaps = store.setdefault("snapshots", {})

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=CAPTURE_WINDOW_MIN)
    added = 0

    for t in trades:
        if (t.get("action") or "").upper() != "BUY":
            continue
        ts, sym = t.get("timestamp", ""), t.get("symbol")
        if not ts or not sym:
            continue
        key = f"{ts}|{sym}"
        if key in snaps:
            continue
        try:
            trade_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        if trade_dt < cutoff:
            continue  # too old to snapshot honestly; skip permanently
        sig = signals.get(sym)
        if not sig:
            continue  # not in current signals; retry next cycle while in window
        conf = sig.get("confirmations", {}) or {}
        snaps[key] = {
            "trade_ts": ts,
            "symbol": sym,
            "price": t.get("price"),
            "qty": t.get("qty"),
            "captured_at": now.isoformat() + "Z",
            "readiness_score": sig.get("readiness_score"),
            "tier": sig.get("tier"),
            "confirmation_count": compute_confirmation_count(conf),
            "hard_confirmation_count": hard_confirmation_count(conf),
            "confirmations": {k: conf.get(k) for k in CONFIRMATION_CHIPS},
        }
        added += 1

    store["last_run"] = now.isoformat() + "Z"
    if added or not OUT.exists():
        atomic_write_json(str(OUT), store)
    print(f"entry_factor_snapshots: {added} new, {len(snaps)} total")


if __name__ == "__main__":
    main()
