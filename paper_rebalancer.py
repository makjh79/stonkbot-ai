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


def main():
    signals = load_signals()
    portfolio = load_portfolio()
    plan = compute_rebalance_plan(signals, portfolio)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"[DONE] Wrote rebalance plan to {OUTPUT_FILE}")
    print(json.dumps({
        "portfolio_value": plan.get("portfolio_value"),
        "deployable_value": plan.get("deployable_value"),
        "eligible_symbols": plan.get("eligible_symbols"),
        "buys": sum(1 for p in plan.get("plan", []) if p.get("action") == "BUY"),
        "trims": sum(1 for p in plan.get("plan", []) if p.get("action") == "TRIM"),
    }, indent=2))


if __name__ == "__main__":
    main()
