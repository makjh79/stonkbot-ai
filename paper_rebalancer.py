"""
Paper allocation rebalancer for StonkBOT.

Reads current portfolio and signals, computes a target-weight allocation
proportional to readiness score for entry-eligible symbols, and produces a
rebalance plan. Does NOT execute trades — this is for analysis only.

Output: /opt/stonk-ai/paper_rebalance_plan.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PORTFOLIO_FILE = Path("/var/www/hedge-fund-website/portfolio_data.json")
SIGNALS_FILE = Path("/opt/stonk-ai/signals.json")
OUTPUT_FILE = Path("/opt/stonk-ai/paper_rebalance_plan.json")
HISTORY_FILE = Path("/opt/stonk-ai/paper_rebalance_history.json")

# How much of the portfolio to deploy into entry-eligible ideas
DEPLOYABLE_PCT = 0.90  # keep 10% cash buffer


def load_signals() -> list[dict]:
    try:
        data = json.loads(SIGNALS_FILE.read_text())
        # signals.json may be { "signals": [...] } or a raw list
        signals = data.get("signals", []) if isinstance(data, dict) else data
        return [s for s in signals if s.get("symbol")]
    except Exception as exc:
        print(f"[WARN] Could not load signals: {exc}")
        return []


def load_portfolio() -> dict:
    try:
        return json.loads(PORTFOLIO_FILE.read_text())
    except Exception as exc:
        print(f"[WARN] Could not load portfolio: {exc}")
        return {}


def compute_rebalance_plan(signals: list[dict], portfolio: dict) -> dict:
    pv = portfolio.get("account", {}).get("portfolio_value", 0)
    if pv <= 0:
        return {"error": "Invalid portfolio value"}

    eligible = [
        s for s in signals
        if s.get("entry_eligible", False)
        and s.get("readiness_score", 0) > 0
    ]

    if not eligible:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "portfolio_value": pv,
            "deployable_value": round(pv * DEPLOYABLE_PCT, 2),
            "eligible_symbols": 0,
            "plan": [],
            "note": "No entry-eligible symbols today. No rebalancing needed.",
        }

    total_readiness = sum(s.get("readiness_score", 0) for s in eligible)
    deployable_value = pv * DEPLOYABLE_PCT

    # Build current position lookup
    positions = {
        p.get("symbol"): {
            "market_value": float(p.get("market_value", 0) or 0),
            "qty": p.get("qty", 0),
            "weight_pct": float(p.get("market_value", 0) or 0) / pv * 100,
        }
        for p in portfolio.get("positions", [])
        if p.get("symbol")
    }

    plan = []
    for s in eligible:
        sym = s.get("symbol")
        readiness = s.get("readiness_score", 0)
        target_pct = (readiness / total_readiness) * DEPLOYABLE_PCT * 100
        target_value = deployable_value * (readiness / total_readiness)
        current = positions.get(sym, {})
        current_value = current.get("market_value", 0)
        current_pct = current.get("weight_pct", 0)
        delta_value = target_value - current_value

        action = "HOLD"
        if delta_value > pv * 0.005:  # 0.5% of portfolio minimum move
            action = "BUY"
        elif delta_value < -pv * 0.005:
            action = "TRIM"

        plan.append({
            "symbol": sym,
            "readiness": round(readiness, 2),
            "tier": s.get("tier"),
            "display_tier": "STRONG" if s.get("tier") == "STRONG_NOW" else "ACTIVE" if s.get("tier") == "NOW" else s.get("tier"),
            "price": round(s.get("price", 0), 4),
            "current_pct": round(current_pct, 2),
            "target_pct": round(target_pct, 2),
            "current_value": round(current_value, 2),
            "target_value": round(target_value, 2),
            "delta_value": round(delta_value, 2),
            "action": action,
        })

    # Also include held positions that are not entry-eligible as "not in plan"
    not_eligible_held = [
        {
            "symbol": sym,
            "current_pct": round(pos["weight_pct"], 2),
            "current_value": round(pos["market_value"], 2),
            "note": "Held but not entry-eligible; no target allocation in readiness model.",
        }
        for sym, pos in positions.items()
        if sym not in {s.get("symbol") for s in eligible}
    ]

    plan.sort(key=lambda x: x["target_pct"], reverse=True)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "portfolio_value": round(pv, 2),
        "deployable_value": round(deployable_value, 2),
        "cash": round(portfolio.get("account", {}).get("cash", 0), 2),
        "eligible_symbols": len(eligible),
        "total_readiness": round(total_readiness, 2),
        "plan": plan,
        "not_eligible_held": not_eligible_held,
        "note": "Paper plan only. Trades are NOT executed.",
    }




def update_history(plan: dict) -> None:
    """Append current plan to history and compute simulated daily return from prior prices."""
    ts = datetime.now(timezone.utc)
    today = ts.strftime("%Y-%m-%d")
    current_prices = {p["symbol"]: p.get("price", 0) for p in plan.get("plan", [])}
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text())
        except Exception:
            history = []

    simulated_return_pct = None
    if history:
        prev = history[-1]
        prev_prices = prev.get("prices", {})
        prev_weights = prev.get("target_weights", {})
        if prev_prices and prev_weights:
            total_weight = sum(prev_weights.values())
            if total_weight > 0:
                weighted_return = 0.0
                for sym, w in prev_weights.items():
                    p0 = prev_prices.get(sym, 0)
                    p1 = current_prices.get(sym, 0)
                    if p0 > 0 and p1 > 0:
                        weighted_return += (w / total_weight) * (p1 / p0 - 1)
                simulated_return_pct = round(weighted_return * 100, 4)

    target_weights = {p["symbol"]: p.get("target_pct", 0) for p in plan.get("plan", [])}
    entry = {
        "date": today,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "portfolio_value": plan.get("portfolio_value"),
        "deployable_value": plan.get("deployable_value"),
        "simulated_return_pct": simulated_return_pct,
        "target_weights": target_weights,
        "prices": current_prices,
        "plan_summary": [
            {"symbol": p["symbol"], "action": p["action"], "target_pct": p["target_pct"]}
            for p in plan.get("plan", [])
        ],
    }
    history.append(entry)
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return simulated_return_pct

def main():
    signals = load_signals()
    portfolio = load_portfolio()
    plan = compute_rebalance_plan(signals, portfolio)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    sim_return = update_history(plan)
    print(f"[DONE] Wrote rebalance plan to {OUTPUT_FILE}")
    if sim_return is not None:
        print(f"[INFO] Simulated daily return from previous plan: {sim_return:.4f}%")
    print(json.dumps({
        "portfolio_value": plan.get("portfolio_value"),
        "deployable_value": plan.get("deployable_value"),
        "eligible_symbols": plan.get("eligible_symbols"),
        "buys": sum(1 for p in plan.get("plan", []) if p.get("action") == "BUY"),
        "trims": sum(1 for p in plan.get("plan", []) if p.get("action") == "TRIM"),
    }, indent=2))


if __name__ == "__main__":
    main()
