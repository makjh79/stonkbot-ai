#!/usr/bin/env python3
"""Per-factor attribution: which confirmation chips actually predict wins?

Pairs closed trades (FIFO round trips from trades_log.json) with entry-time
factor snapshots (entry_factor_snapshots.json, captured at trade time).
Older trades without snapshots contribute readiness/confirmation-count
stats only, parsed from trade_rationale.json.

Outputs factor_attribution.json (web root + /opt copy) for the site's
"What the data says" section. Read-only on inputs; runs nightly via cron.

Labels mirror signal_rules.active_confirmation_labels — keep in sync.
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from stonk_utils import atomic_write_json
from signal_rules import CONFIRMATION_CHIPS, TIER_STRONG_NOW_MIN

BASE = Path("/opt/stonk-ai")
WEB = Path("/var/www/hedge-fund-website")
TRADES = BASE / "trades_log.json"
SNAPSHOTS = BASE / "entry_factor_snapshots.json"
RATIONALE = BASE / "trade_rationale.json"

CHIP_LABELS = {
    "momentum_score": "MOM", "rsi_signal": "RSI", "volume_confirmed": "VOL",
    "macd_turning": "MACD", "above_ema": "EMA", "sector_strong": "SEC",
    "intraday_confirmed": "INT", "options_confirmed": "OPT",
    "relvol_confirmed": "RVOL", "vwap_confirmed": "VWAP",
    "momentum_5m_up": "5M", "near_term_bullish_flow": "OF",
    "spread_ok": "SPR", "bid_ask_bullish": "QBI", "no_corporate_action_risk": "CA",
}
READINESS_RE = re.compile(r"readiness\s+([\d.]+),\s*(\d+)\s*/\s*\d+\s*conf")
MIN_FACTOR_N = 20  # frontend hides factors below this total sample


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def round_trips(trades):
    positions = defaultdict(list)
    closed = []
    for t in sorted(trades, key=lambda x: x.get("timestamp", "")):
        action = (t.get("action") or "").upper()
        sym = t.get("symbol")
        if not sym:
            continue
        if action == "BUY":
            positions[sym].append(t)
        elif action == "SELL" and positions[sym]:
            buy = positions[sym].pop(0)
            bp, sp = float(buy.get("price") or 0), float(t.get("price") or 0)
            if bp > 0:
                closed.append({
                    "symbol": sym,
                    "buy_ts": buy.get("timestamp", ""),
                    "sell_ts": t.get("timestamp", ""),
                    "pnl_pct": (sp - bp) / bp,
                })
    return closed


def parse_rationale(entries):
    """BUY rationale entries -> list of (ts, symbol, readiness, conf_count)."""
    out = []
    for e in entries:
        if (e.get("action") or "").upper() != "BUY":
            continue
        m = READINESS_RE.search(e.get("reason") or "")
        if m and e.get("symbol") and e.get("timestamp"):
            out.append((e["timestamp"], e["symbol"], float(m.group(1)), int(m.group(2))))
    return out


def match_rationale(buy_ts, symbol, parsed):
    """Nearest same-symbol rationale BUY within 10 minutes."""
    best = None
    try:
        bt = datetime.fromisoformat(buy_ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None
    for ts, sym, readiness, conf_count in parsed:
        if sym != symbol:
            continue
        try:
            rt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        dt = abs((rt - bt).total_seconds())
        if dt <= 600 and (best is None or dt < best[0]):
            best = (dt, readiness, conf_count)
    return best[1:] if best else None


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx * vy) ** 0.5


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def main():
    trades = load_json(TRADES, {}).get("trades", [])
    closed = round_trips(trades)
    snaps = load_json(SNAPSHOTS, {}).get("snapshots", {})
    rationale = parse_rationale(load_json(RATIONALE, {}).get("entries", []))

    # Join round trips with entry data
    chip_rows = defaultdict(lambda: {"act": [], "inact": []})  # chip -> pnl lists
    readiness_pairs = []  # (readiness, pnl)
    conf_pairs = []       # (conf_count, pnl)
    n_snap = n_rat = 0
    holding_days = []

    for ct in closed:
        pnl = ct["pnl_pct"]
        key = f"{ct['buy_ts']}|{ct['symbol']}"
        snap = snaps.get(key)
        if snap and isinstance(snap.get("confirmations"), dict):
            n_snap += 1
            conf = snap["confirmations"]
            for chip, test in CONFIRMATION_CHIPS.items():
                if chip not in conf:
                    continue
                try:
                    active = bool(test(conf[chip]))
                except Exception:
                    continue
                chip_rows[chip]["act" if active else "inact"].append(pnl)
            if snap.get("readiness_score") is not None:
                readiness_pairs.append((float(snap["readiness_score"]), pnl))
            if snap.get("confirmation_count") is not None:
                conf_pairs.append((float(snap["confirmation_count"]), pnl))
        else:
            rat = match_rationale(ct["buy_ts"], ct["symbol"], rationale)
            if rat:
                n_rat += 1
                readiness_pairs.append((rat[0], pnl))
                conf_pairs.append((float(rat[1]), pnl))
        try:
            b = datetime.fromisoformat(ct["buy_ts"].replace("Z", "+00:00"))
            s = datetime.fromisoformat(ct["sell_ts"].replace("Z", "+00:00"))
            holding_days.append((s - b).days)
        except Exception:
            pass

    factors = {}
    for chip, label in CHIP_LABELS.items():
        rows = chip_rows.get(chip, {"act": [], "inact": []})
        a, i = rows["act"], rows["inact"]
        if not a and not i:
            factors[chip] = {"label": label, "n_active": 0, "n_inactive": 0}
            continue
        wr_a = mean([1.0 if p > 0 else 0.0 for p in a])
        wr_i = mean([1.0 if p > 0 else 0.0 for p in i])
        factors[chip] = {
            "label": label,
            "n_active": len(a),
            "n_inactive": len(i),
            "win_rate_active": round(wr_a, 3) if wr_a is not None else None,
            "win_rate_inactive": round(wr_i, 3) if wr_i is not None else None,
            "avg_pnl_active_pct": round(mean(a) * 100, 2) if a else None,
            "avg_pnl_inactive_pct": round(mean(i) * 100, 2) if i else None,
            "edge_pp": round((wr_a - wr_i) * 100, 1) if (wr_a is not None and wr_i is not None) else None,
        }

    # Readiness / confirmation-count as continuous factors
    if readiness_pairs:
        rs = [p[0] for p in readiness_pairs]
        pnls = [p[1] for p in readiness_pairs]
        prime = [p for r, p in readiness_pairs if r >= TIER_STRONG_NOW_MIN]
        sub = [p for r, p in readiness_pairs if r < TIER_STRONG_NOW_MIN]
        r_corr = corr(rs, pnls)
        factors["readiness_score"] = {
            "label": "READINESS", "n": len(rs),
            "correlation": round(r_corr, 3) if r_corr is not None else None,
            "avg_pnl_prime_pct": round(mean(prime) * 100, 2) if prime else None,
            "avg_pnl_subprime_pct": round(mean(sub) * 100, 2) if sub else None,
            "prime_threshold": TIER_STRONG_NOW_MIN,
        }
    if conf_pairs:
        cs = [p[0] for p in conf_pairs]
        pnls = [p[1] for p in conf_pairs]
        c_corr = corr(cs, pnls)
        factors["confirmation_count"] = {
            "label": "CONF COUNT", "n": len(cs),
            "correlation": round(c_corr, 3) if c_corr is not None else None,
        }

    wins = [c for c in closed if c["pnl_pct"] > 0]
    losses = [c for c in closed if c["pnl_pct"] <= 0]
    gross_win = sum(c["pnl_pct"] for c in wins)
    gross_loss = abs(sum(c["pnl_pct"] for c in losses))

    # Takeaway from sufficient chips only
    takeaway = None
    sufficient = [(f["label"], f["edge_pp"]) for f in factors.values()
                  if f.get("edge_pp") is not None and f.get("n_active", 0) >= 10 and f.get("n_inactive", 0) >= 5]
    if sufficient:
        best = max(sufficient, key=lambda x: x[1])
        worst = min(sufficient, key=lambda x: x[1])
        if best[1] >= 10 or worst[1] <= -10:
            takeaway = f"{best[0]} entries are outperforming ({best[1]:+.0f} pp win rate); {worst[0]} is lagging ({worst[1]:+.0f} pp) — so far."

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "status": "live" if n_snap >= MIN_FACTOR_N else "collecting",
        "sample": {
            "closed_trades": len(closed),
            "with_snapshots": n_snap,
            "with_rationale_only": n_rat,
            "min_factor_n": MIN_FACTOR_N,
        },
        "overall": {
            "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "avg_winner_pct": round(mean([c["pnl_pct"] for c in wins]) * 100, 2) if wins else None,
            "avg_loser_pct": round(mean([c["pnl_pct"] for c in losses]) * 100, 2) if losses else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
            "avg_holding_days": round(mean(holding_days), 1) if holding_days else None,
        },
        "factors": factors,
        "takeaway": takeaway,
        "meta": {
            "method": "FIFO round trips joined with entry-time factor snapshots",
            "note": "Per-chip data accrues from snapshot deployment; readiness/conf-count include older trades via rationale parsing.",
        },
    }

    atomic_write_json(str(WEB / "factor_attribution.json"), out)
    atomic_write_json(str(BASE / "factor_attribution.json"), out)
    print(f"factor_attribution.json written: {len(closed)} round trips, "
          f"{n_snap} with snapshots, {n_rat} rationale-only, status={out['status']}")


if __name__ == "__main__":
    main()
