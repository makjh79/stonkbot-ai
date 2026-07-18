#!/usr/bin/env python3
"""P&L attribution by decision type — pure reporting, no strategy changes.

Reads trades_log.json (which already has strategy tags from sync_alpaca_trades.py
and trading_bot.py), reconstructs per-symbol cost basis, and attributes realized
P&L to the decision that caused the sell.

Single writer of:
  /opt/stonk-ai/pnl_attribution.json
  /var/www/hedge-fund-website/pnl_attribution.json

Run via outcome_tracker.py on the same 15-min cron, or standalone.
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, "/opt/stonk-ai")
try:
    from stonk_utils import atomic_write_json
except Exception:
    atomic_write_json = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_DIR = Path("/opt/stonk-ai")
WEB_DIR = Path("/var/www/hedge-fund-website")

TRADES_FILE = BOT_DIR / "trades_log.json"
OPT_FILE = BOT_DIR / "pnl_attribution.json"
WEB_FILE = WEB_DIR / "pnl_attribution.json"

# Strategy buckets used for attribution.
BUY_STRATEGIES = {"entry", "bot", "manual"}
SELL_STRATEGIES = {"stop_loss", "profit_exit", "profit_trim", "rotation", "cash_raise", "trim", "exit", "manual"}
DISPLAY_NAMES = {
    "entry": "Entry",
    "stop_loss": "Stop loss",
    "profit_exit": "Profit exit",
    "profit_trim": "Profit trim",
    "rotation": "Rotation",
    "cash_raise": "Cash raise",
    "trim": "Concentration trim",
    "exit": "Unclassified exit",
    "manual": "Manual",
    "bot": "Bot entry",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


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


def load_trades() -> List[Dict]:
    data = _load_json(TRADES_FILE, {})
    if isinstance(data, dict):
        return data.get("trades", [])
    return data if isinstance(data, list) else []


def normalize_strategy(trade: Dict, action: str) -> str:
    """Map a trade's strategy/rationale to an attribution bucket."""
    strategy = str(trade.get("strategy") or "").lower()
    rationale = str(trade.get("rationale") or "").lower()
    if action == "BUY":
        if strategy in BUY_STRATEGIES:
            return strategy
        if "entry" in rationale or "buy" in rationale:
            return "entry"
        return "manual"
    # SELL side
    if strategy in SELL_STRATEGIES:
        return strategy
    if "stop loss" in rationale or "hard stop" in rationale:
        return "stop_loss"
    if "profit exit" in rationale or "full profit" in rationale:
        return "profit_exit"
    if "profit trim" in rationale:
        return "profit_trim"
    if "rotation" in rationale:
        return "rotation"
    if "cash raise" in rationale:
        return "cash_raise"
    if "concentration" in rationale or "trim" in rationale:
        return "trim"
    if "full sell" in rationale or "exit" in rationale:
        return "exit"
    return "manual"


def compute_attribution(trades: List[Dict]) -> Dict:
    """Reconstruct positions and attribute realized P&L to sell decisions."""
    # Sort chronologically
    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp") or "")

    positions: Dict[str, Dict] = {}  # sym -> {qty, avg_cost}
    daily: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    tag_totals: Dict[str, float] = defaultdict(float)
    tag_trades: Dict[str, int] = defaultdict(int)
    sell_count = 0
    realized_total = 0.0

    for t in sorted_trades:
        sym = t.get("symbol")
        action = str(t.get("action") or "").upper()
        qty = float(t.get("qty") or 0)
        price = float(t.get("price") or 0)
        if not sym or qty <= 0 or price <= 0:
            continue
        day = str(t.get("timestamp") or "")[:10] or "unknown"

        if action == "BUY":
            pos = positions.setdefault(sym, {"qty": 0.0, "avg_cost": 0.0})
            old_qty, old_cost = pos["qty"], pos["avg_cost"]
            new_qty = old_qty + qty
            pos["avg_cost"] = (old_cost * old_qty + price * qty) / new_qty if new_qty > 0 else price
            pos["qty"] = new_qty
        elif action == "SELL":
            pos = positions.get(sym, {"qty": qty, "avg_cost": price})
            sell_qty = min(qty, pos["qty"]) if pos["qty"] > 0 else qty
            avg_cost = pos["avg_cost"] if pos["avg_cost"] > 0 else price
            pnl = sell_qty * (price - avg_cost)
            tag = normalize_strategy(t, "SELL")

            daily[day][tag] += pnl
            tag_totals[tag] += pnl
            tag_trades[tag] += 1
            sell_count += 1
            realized_total += pnl

            # Reduce position
            pos["qty"] = max(0.0, pos["qty"] - sell_qty)
            if pos["qty"] == 0:
                pos["avg_cost"] = 0.0

    # Build daily series sorted by date
    series = []
    for day in sorted(daily.keys()):
        row = {"date": day, "total": round(sum(daily[day].values()), 2)}
        for tag in sorted(SELL_STRATEGIES):
            row[tag] = round(daily[day].get(tag, 0.0), 2)
        series.append(row)

    by_tag = []
    for tag in sorted(SELL_STRATEGIES):
        total = tag_totals.get(tag, 0.0)
        by_tag.append({
            "tag": tag,
            "display": DISPLAY_NAMES.get(tag, tag),
            "realized_pnl": round(total, 2),
            "trades": tag_trades.get(tag, 0),
            "avg_pnl_per_trade": round(total / tag_trades[tag], 2) if tag_trades.get(tag) else None,
        })

    # Sort by biggest money impact (most negative first)
    by_tag.sort(key=lambda x: x["realized_pnl"])

    return {
        "summary": {
            "realized_pnl_total": round(realized_total, 2),
            "sell_trades": sell_count,
            "first_trade_date": series[0]["date"] if series else None,
            "last_trade_date": series[-1]["date"] if series else None,
            "trading_days": len(series),
        },
        "by_tag": by_tag,
        "daily": series,
        "last_updated": _iso(_now()),
    }


def export(payload: Dict) -> None:
    _atomic_write(OPT_FILE, payload)
    _atomic_write(WEB_FILE, payload)


def main() -> int:
    trades = load_trades()
    if not trades:
        logger.warning("No trades found; skipping P&L attribution")
        return 0
    payload = compute_attribution(trades)
    export(payload)
    logger.info(
        f"P&L attribution: total=${payload['summary']['realized_pnl_total']:,.2f} "
        f"sell_trades={payload['summary']['sell_trades']} "
        f"tags={len(payload['by_tag'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
