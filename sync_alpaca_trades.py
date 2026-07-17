#!/usr/bin/env python3
"""Sync trades from Alpaca to trades_log.json, preserving and inferring rationale.

v2 changes:
- Merges rationale from trade_rationale.json (written by trading_bot.py)
- Infers rationale for trades without explicit rationale based on patterns
- Groups fills by order_id to avoid duplicate entries
"""
import json, urllib.request, ssl, os
from datetime import datetime, timezone
from collections import defaultdict

CFG = json.load(open("/opt/stonk-ai/alpaca_config.json"))
KEY = CFG["api_key"]
SECRET = CFG["api_secret"]

TRADES_LOG = "/opt/stonk-ai/trades_log.json"
WEB_TRADES_LOG = "/var/www/hedge-fund-website/trades_log.json"
RATIONALE_FILE = "/opt/stonk-ai/trade_rationale.json"


def fetch_fills():
    all_fills = []
    page_token = None
    base = "https://paper-api.alpaca.markets/v2/account/activities?activity_type=FILL&direction=asc&page_size=100"
    while True:
        url = base
        if page_token:
            url += "&page_token=" + page_token
        req = urllib.request.Request(url)
        req.add_header("APCA-API-KEY-ID", KEY)
        req.add_header("APCA-API-SECRET-KEY", SECRET)
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, context=ctx)
        fills = json.loads(resp.read())
        valid = [f for f in fills if float(f.get("qty", 0)) > 0]
        all_fills.extend(valid)
        if len(fills) < 100:
            break
        page_token = fills[-1]["id"]
    return all_fills


def load_rationale():
    """Load rationale entries written by trading_bot.py."""
    if not os.path.exists(RATIONALE_FILE):
        return {}
    try:
        data = json.load(open(RATIONALE_FILE))
        # Build lookup by (date, symbol, action)
        lookup = {}
        for entry in data.get("entries", []):
            key = (entry["timestamp"][:10], entry["symbol"], entry["action"])
            lookup[key] = entry.get("reason", "")
        return lookup
    except Exception:
        return {}


def load_existing_rationale():
    """Load rationale from existing trades_log.json."""
    if not os.path.exists(TRADES_LOG):
        return {}
    try:
        data = json.load(open(TRADES_LOG))
        lookup = {}
        for t in data.get("trades", []):
            if t.get("rationale"):
                key = (t["timestamp"][:10], t["symbol"], t["action"])
                lookup[key] = t["rationale"]
            if t.get("strategy") and t.get("strategy") != "manual":
                key = (t["timestamp"][:10], t["symbol"], t["action"])
                lookup.setdefault(key + ("strategy",), t["strategy"])
        return lookup
    except Exception:
        return {}


def infer_rationale(trades):
    """Infer rationale for trades without explicit reasoning.

    Patterns:
    - Sell + same-day buy of different symbol → "Rotation: trim X to fund Y"
    - Sell 1/3 of position with +25%+ gain → "Profit trim at +X%"
    - Full sell at -10% → "Stop loss at -X%"
    - Small sell (<25% of position) → "Cash raise" or "Concentration trim"
    - Initial buy → "Entry signal" or "Quality-momentum entry"
    """
    # Build a timeline and look for patterns
    by_day = defaultdict(list)
    for t in trades:
        day = t["timestamp"][:10]
        by_day[day].append(t)

    # Build position tracking for inferring sell rationale
    positions = {}  # symbol -> {qty, avg_cost}

    for t in sorted(trades, key=lambda x: x["timestamp"]):
        sym = t["symbol"]
        action = t["action"]
        qty = t["qty"]
        price = t["price"]

        if action == "BUY":
            # Track position
            if sym in positions:
                old_qty = positions[sym]["qty"]
                old_cost = positions[sym]["avg_cost"]
                new_qty = old_qty + qty
                positions[sym]["avg_cost"] = (old_cost * old_qty + price * qty) / new_qty
                positions[sym]["qty"] = new_qty
            else:
                positions[sym] = {"qty": qty, "avg_cost": price}

            if not t.get("rationale"):
                # Infer entry reason
                t["rationale"] = f"Buy {qty} {sym} @ ${price:.2f}"
                t["strategy"] = "entry"

        elif action == "SELL":
            pos = positions.get(sym, {"qty": qty, "avg_cost": price})
            sell_pct = qty / pos["qty"] if pos["qty"] > 0 else 1.0
            pnl_pct = (price - pos["avg_cost"]) / pos["avg_cost"] * 100 if pos["avg_cost"] > 0 else 0

            if not t.get("rationale"):
                # Infer sell reason
                day = t["timestamp"][:10]
                day_trades = by_day[day]
                same_day_buys = [x for x in day_trades if x["action"] == "BUY" and x["symbol"] != sym
                                 and abs(x["timestamp"][:19] < t["timestamp"][:19])]

                if sell_pct >= 0.9:
                    if pnl_pct <= -10:
                        t["rationale"] = f"Stop loss at {pnl_pct:+.1f}% (full exit)"
                        t["strategy"] = "stop_loss"
                    elif pnl_pct >= 50:
                        t["rationale"] = f"Full profit exit at {pnl_pct:+.1f}%"
                        t["strategy"] = "profit_exit"
                    else:
                        t["rationale"] = f"Full sell at {pnl_pct:+.1f}%"
                        t["strategy"] = "exit"
                elif sell_pct <= 0.35 and pnl_pct >= 25:
                    t["rationale"] = f"Profit trim at {pnl_pct:+.1f}% (trimmed {sell_pct:.0%})"
                    t["strategy"] = "profit_trim"
                elif same_day_buys:
                    # Dedupe preserving order (multiple buys of same symbol → "AAPL, AAPL" spam)
                    seen = []
                    for x in same_day_buys:
                        if x["symbol"] not in seen:
                            seen.append(x["symbol"])
                    buy_syms = ", ".join(seen[:3])
                    t["rationale"] = f"Rotation: trim {sym} to fund {buy_syms}"
                    t["strategy"] = "rotation"
                elif sell_pct <= 0.25:
                    t["rationale"] = f"Cash raise: trim {sym} ({sell_pct:.0%} of position)"
                    t["strategy"] = "cash_raise"
                else:
                    t["rationale"] = f"Trim {sym} at {pnl_pct:+.1f}% ({sell_pct:.0%})"
                    t["strategy"] = "trim"

            # Update position after sell
            if sym in positions:
                positions[sym]["qty"] = max(0, positions[sym]["qty"] - qty)
                if positions[sym]["qty"] == 0:
                    del positions[sym]

    return trades


def main():
    fills = fetch_fills()

    # Group fills by (day, symbol, side, order_id)
    groups = defaultdict(lambda: {"qty": 0, "total_cost": 0, "times": []})
    for f in fills:
        ts = f["transaction_time"]
        day = ts[:10]
        sym = f["symbol"]
        side = f["side"]
        oid = f.get("order_id", "?")
        key = (day, sym, side, oid)
        qty = float(f["qty"])
        price = float(f["price"])
        groups[key]["qty"] += qty
        groups[key]["total_cost"] += qty * price
        groups[key]["times"].append(ts)

    trades = []
    for (day, sym, side, oid), g in sorted(groups.items()):
        avg_price = g["total_cost"] / g["qty"] if g["qty"] > 0 else 0
        ts = min(g["times"])
        trades.append({
            "timestamp": ts,
            "action": side.upper(),
            "symbol": sym,
            "qty": round(g["qty"]),
            "price": round(avg_price, 2),
            "total_value": round(g["total_cost"], 2),
            "strategy": "manual",
            "rationale": ""
        })

    # Merge rationale from bot's trade_rationale.json
    bot_rationale = load_rationale()
    for t in trades:
        key = (t["timestamp"][:10], t["symbol"], t["action"])
        if key in bot_rationale and not t["rationale"]:
            t["rationale"] = bot_rationale[key]
            t["strategy"] = "bot"

    # Merge rationale from existing trades_log.json
    existing_rationale = load_existing_rationale()
    for t in trades:
        key = (t["timestamp"][:10], t["symbol"], t["action"])
        if key in existing_rationale and not t["rationale"]:
            t["rationale"] = existing_rationale[key]
            # Keep existing strategy if not default
        strat_key = key + ("strategy",)
        if strat_key in existing_rationale and t.get("strategy") == "manual":
            t["strategy"] = existing_rationale[strat_key]

    # Infer rationale for any remaining empty entries
    trades = infer_rationale(trades)

    # Sort and save
    trades.sort(key=lambda x: x["timestamp"])
    new_log = {
        "trades": trades,
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trade_count": len(trades),
    }
    with open(TRADES_LOG, "w") as f:
        json.dump(new_log, f, indent=2)

    import shutil
    shutil.copy(TRADES_LOG, WEB_TRADES_LOG)

    # Count how many have rationale
    with_rationale = sum(1 for t in trades if t.get("rationale"))
    print(f"{new_log['last_updated']}: {len(trades)} trades synced ({with_rationale} with rationale)")


if __name__ == "__main__":
    main()