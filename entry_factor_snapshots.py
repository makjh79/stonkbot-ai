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
OUT = BASE / "entry_factor_snapshots.json"

CAPTURE_WINDOW_MIN = 45  # cron is */15 + signals refresh */15 -> 45 min covers lag


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

SNAPSHOT_READINESS_MIN = 65.0  # measurement-only threshold; entry gate stays at 80.0


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
        }
        added += 1

    store["last_run"] = now.isoformat() + "Z"
    store["meta"] = {"sector_volume_flow_enabled": True}
    if added or not OUT.exists():
        atomic_write_json(str(OUT), store)
    print(f"entry_factor_snapshots: {added} new, {len(snaps)} total")


if __name__ == "__main__":
    main()
