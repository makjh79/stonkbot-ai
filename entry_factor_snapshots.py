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
from typing import Dict, Optional
from pathlib import Path

from stonk_utils import atomic_write_json
from signal_rules import CONFIRMATION_CHIPS, compute_confirmation_count, hard_confirmation_count
from readiness_score import SECTOR_PEERS

BASE = Path("/opt/stonk-ai")
TRADES = BASE / "trades_log.json"
SIGNALS = BASE / "signals.json"
ALL_BARS = BASE / "all_bars.json"
RATIONALE = BASE / "trade_rationale.json"
OUT = BASE / "entry_factor_snapshots.json"

CAPTURE_WINDOW_MIN = 45  # cron is */15 + signals refresh */15 -> 45 min covers lag


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def classify_cohort(reason: str, entry_eligible: bool) -> str:
    """Map a BUY rationale reason to an entry cohort.

    Rules:
      - v3: reason contains "V3" or "trend-pullback" (case-insensitive).
      - main: reason contains entry_eligible/main-engine language, or no V3
        marker and the symbol's signal is entry_eligible.
      - unknown: otherwise.
    """
    if not reason:
        return "main" if entry_eligible else "unknown"
    rl = reason.lower()
    if "v3" in rl or "trend-pullback" in rl:
        return "v3"
    if "entry_eligible" in rl or "main-engine" in rl or "main engine" in rl:
        return "main"
    # If no V3 marker and the signal passed the entry gate, assume main cohort.
    return "main" if entry_eligible else "unknown"


def build_rationale_index(entries):
    """Index BUY rationale entries by (timestamp, symbol) -> reason.

    Multiple rationales for the same trade are collapsed by taking the first
    V3-looking reason, otherwise the first reason.
    """
    idx = {}
    for e in entries:
        if (e.get("action") or "").upper() != "BUY":
            continue
        ts = e.get("timestamp", "")
        sym = e.get("symbol")
        reason = e.get("reason", "")
        if not ts or not sym:
            continue
        key = (ts, sym)
        existing = idx.get(key)
        if existing is None:
            idx[key] = reason
        else:
            # Prefer V3-marked rationale if present.
            rl = reason.lower()
            if "v3" in rl or "trend-pullback" in rl:
                idx[key] = reason
    return idx


def nearest_rationale(buy_ts, symbol, rationale_index):
    """Return the closest rationale reason within 10 minutes of buy_ts."""
    best = None
    try:
        bt = datetime.fromisoformat(buy_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None
    for (ts, sym), reason in rationale_index.items():
        if sym != symbol:
            continue
        try:
            rt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        dt = abs((rt - bt).total_seconds())
        if dt <= 600 and (best is None or dt < best[0]):
            best = (dt, reason)
    return best[1] if best else None

SNAPSHOT_READINESS_MIN = 70.0  # measurement-only threshold; aligned with ENTRY_READINESS_MIN


def compute_sector_volume_flow(symbol: str, sector: str, all_bars: Optional[Dict]) -> Dict:
    """
    Measure-only sector volume-flow metrics.

    For the symbol's sector peers, compute:
      - sector_volume_ratio: median 5d/20d volume ratio of peers
      - peers_with_volume_surge: fraction of peers with 5d/20d volume >= 1.25x
      - peers_with_price_up_5d: fraction of peers with 5-day return positive
      - peer_count: number of peers used in calculation
      - sector_label: sector name

    Returns empty dict if no peer bar data available. Does NOT affect trading.
    """
    if not all_bars or not sector:
        return {}

    peers = SECTOR_PEERS.get(sector, [])
    peers = list(dict.fromkeys(([symbol] if symbol else []) + list(peers)))

    ratios, up_5d = [], []
    for s in peers:
        bars = all_bars.get(s)
        if not isinstance(bars, dict):
            continue
        volumes = bars.get("volumes", [])
        closes = bars.get("closes", [])
        if len(volumes) >= 20 and len(closes) >= 6:
            recent_vol = sum(volumes[-5:]) / 5
            avg_vol = sum(volumes[-20:]) / 20
            ratio = recent_vol / avg_vol if avg_vol > 0 else 0.0
            ratios.append(ratio)
            ret5 = (closes[-1] - closes[-6]) / closes[-6] if closes[-6] > 0 else 0.0
            up_5d.append(ret5 > 0)

    n = len(ratios)
    if n == 0:
        return {}

    ratios_sorted = sorted(ratios)
    median_ratio = ratios_sorted[n // 2] if n % 2 else (ratios_sorted[n // 2 - 1] + ratios_sorted[n // 2]) / 2
    return {
        "sector_volume_ratio": round(median_ratio, 2),
        "peers_with_volume_surge": round(sum(1 for r in ratios if r >= 1.25) / n, 2),
        "peers_with_price_up_5d": round(sum(up_5d) / n, 2),
        "peer_count": n,
        "sector_label": sector,
    }


def main():
    trades = load_json(TRADES, {}).get("trades", [])
    signals = {s.get("symbol"): s for s in load_json(SIGNALS, {}).get("signals", []) if s.get("symbol")}
    all_bars_store = load_json(ALL_BARS, {}).get("bars", {})
    store = load_json(OUT, {"snapshots": {}})
    snaps = store.setdefault("snapshots", {})

    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=CAPTURE_WINDOW_MIN)
    added = 0
    cohorts_backfilled = 0

    rationale_index = build_rationale_index(load_json(RATIONALE, {}).get("entries", []))

    # ---- Additive cohort backfill for existing snapshots ----
    # Existing snapshots may pre-date cohort tagging. Derive their cohort from
    # the nearest BUY rationale without touching any other field.
    for key, snap in snaps.items():
        if snap.get("cohort"):
            continue
        ts = snap.get("trade_ts")
        sym = snap.get("symbol")
        if not ts or not sym:
            continue
        sig = signals.get(sym)
        entry_eligible = bool(sig.get("entry_eligible")) if sig else False
        reason = nearest_rationale(ts, sym, rationale_index)
        snap["cohort"] = classify_cohort(reason, entry_eligible)
        cohorts_backfilled += 1

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
        sector = sig.get("sector", "Other")
        sector_flow = compute_sector_volume_flow(sym, sector, all_bars_store)
        reason = nearest_rationale(ts, sym, rationale_index)
        entry_eligible = bool(sig.get("entry_eligible"))
        cohort = classify_cohort(reason, entry_eligible)
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
            "sector_volume_flow": sector_flow,
            "cohort": cohort,
        }
        added += 1

    store["last_run"] = now.isoformat() + "Z"
    store["meta"] = {"sector_volume_flow_enabled": True}
    # Write if there are new snapshots, cohort backfills, or the file does not exist.
    if added or cohorts_backfilled or not OUT.exists():
        atomic_write_json(str(OUT), store)
    print(f"entry_factor_snapshots: {added} new, {cohorts_backfilled} cohorts backfilled, {len(snaps)} total")


if __name__ == "__main__":
    main()
