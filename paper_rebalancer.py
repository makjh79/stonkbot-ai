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
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from readiness_score import compute_confirmation_count

# High-beta basket cap config (matches risk_engine.py / trading_bot.py)
MAX_HIGH_BETA_DEPLOYED_PCT = 0.35
HIGH_BETA_SPY_BETA_THRESHOLD = 1.2
HIGH_BETA_SPY_CORR_THRESHOLD = 0.70
CORRELATION_REPORT_PATH = Path("/var/www/hedge-fund-website/correlation_report.json")

PORTFOLIO_FILE = Path("/var/www/hedge-fund-website/portfolio_data.json")
SIGNALS_FILE = Path("/opt/stonk-ai/signals.json")
OUTPUT_FILE = Path("/opt/stonk-ai/paper_rebalance_plan.json")
HISTORY_FILE = Path("/opt/stonk-ai/paper_rebalance_history.json")

# How much of the portfolio to deploy into entry-eligible ideas
DEPLOYABLE_PCT = 0.95  # keep 10% cash buffer

# Sector diversification: max % of portfolio in any single sector
MAX_SECTOR_PCT = 0.35  # 30% of total portfolio per sector (existing positions are not forcibly trimmed unless overage exceeds this buffer)
SECTOR_TRIM_BUFFER_PCT = 0.05  # only trim existing sector positions if they exceed cap + buffer
MAX_SINGLE_TARGET_PCT = 0.10  # align with live bot's 8% max single position cap

# Lower-threshold gate for diversification-only candidates
# These do NOT qualify for the core momentum entry gate; they are used only to
# fill remaining deployable capital after high-beta and sector caps are applied.
# Paper-only entry gate: looser than live bot so the simulation can deploy capital
PAPER_READINESS_MIN = 70.0
PAPER_CONFIRMATIONS_MIN = 3

DIVERSIFICATION_READINESS_MIN = 65.0
MIN_ELIGIBLE_TARGET_PCT = 0.05  # floor allocation for entry-eligible names (5%)
DIVERSIFICATION_CONFIRMATIONS_MIN = 2



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

def load_high_beta_symbols() -> set:
    """Load high-beta symbols from the correlation report."""
    try:
        data = json.loads(CORRELATION_REPORT_PATH.read_text())
        basket = set()
        for symbol, metrics in data.get("betas", {}).items():
            beta = metrics.get("spy")
            corr = metrics.get("spy_corr")
            if (beta is not None and beta > HIGH_BETA_SPY_BETA_THRESHOLD) or (corr is not None and corr > HIGH_BETA_SPY_CORR_THRESHOLD):
                basket.add(symbol)
        return basket
    except Exception:
        return set()





def _symbol_sector(symbol: str) -> str:
    """Return sector for a symbol using the same mapping as signal_engine.py."""
    sectors = {
        "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "NFLX", "CRM", "ORCL", "ADBE", "INTU", "IBM", "INTC", "SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW", "NET", "DDOG", "OKTA", "PATH", "PLTR", "UBER", "ABNB", "EXPE", "SPOT", "ROKU", "PINS", "SNAP", "TTD", "SHOP"],
        "Semiconductors": ["AMD", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON", "AVGO", "TXN"],
        "Cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "CYBR", "S"],
        "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY", "PYPL", "FIS", "V", "GS", "MS", "BLK", "SCHW"],
        "Consumer/Platform": ["UBER", "DKNG", "SHOP", "TTD", "ROKU", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "ELF", "APP", "DUOL", "CHWY", "ETSY", "LULU", "NKE", "COST", "WMT", "HD"],
        "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
        "Healthcare": ["UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "VRTX", "BMY", "REGN", "GILD", "ISRG", "ZBH", "ILMN", "SGEN"],
        "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY"],
        "Industrials": ["GE", "CAT", "UNP", "HON", "UPS", "RTX", "LMT", "DE"],
        "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "V"],
        "Communications/Media": ["DIS", "CMCSA", "TMUS", "CHTR", "WBD", "PARA"],
    }
    for sector, symbols in sectors.items():
        if symbol in symbols:
            return sector
    return "Other"


def _compute_sector_exposures(targets: dict, positions: dict) -> dict:
    """Return sector -> total target market value (current + planned)."""
    exposures = {}
    for sym, pos in positions.items():
        sector = _symbol_sector(sym)
        exposures[sector] = exposures.get(sector, 0.0) + float(pos.get("market_value", 0) or 0)
    for sym, val in targets.items():
        sector = _symbol_sector(sym)
        exposures[sector] = exposures.get(sector, 0.0) + val
    return exposures

def compute_rebalance_plan(signals: list[dict], portfolio: dict) -> dict:
    pv = portfolio.get("account", {}).get("portfolio_value", 0)
    if pv <= 0:
        return {"error": "Invalid portfolio value"}

    eligible = [
        s for s in signals
        if s.get("readiness_score", 0) >= PAPER_READINESS_MIN
        and compute_confirmation_count(s.get("confirmations", {})) >= PAPER_CONFIRMATIONS_MIN
        and (s.get("above_ema20", False) or s.get("confirmations", {}).get("above_ema", False))
        and s.get("price", 0) > 0
    ]

    # Load high-beta basket and current exposure
    high_beta_symbols = load_high_beta_symbols()
    cash = portfolio.get("account", {}).get("cash", 0)
    equity = portfolio.get("account", {}).get("equity", portfolio.get("account", {}).get("portfolio_value", 0))
    deployed = equity - cash
    current_high_beta_mv = 0.0
    if deployed > 0:
        current_high_beta_mv = sum(
            p.get("market_value", 0)
            for p in portfolio.get("positions", [])
            if p.get("symbol") in high_beta_symbols
        )
    current_high_beta_pct = current_high_beta_mv / deployed if deployed > 0 else 0.0

    # Diversification candidates: near-eligible NON-high-beta symbols used to fill underweight sectors
    div_candidates = [
        s for s in signals
        if not s.get("entry_eligible", False)
        and s.get("readiness_score", 0) >= DIVERSIFICATION_READINESS_MIN
        and s.get("confirmation_count", 0) >= DIVERSIFICATION_CONFIRMATIONS_MIN
        and (s.get("above_ema20", False) or s.get("confirmations", {}).get("above_ema", False))
        and s.get("price", 0) > 0
        and s.get("symbol") not in high_beta_symbols
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
    cash = portfolio.get("account", {}).get("cash", 0)
    equity = portfolio.get("account", {}).get("equity", portfolio.get("account", {}).get("portfolio_value", 0))
    deployed = equity - cash
    current_high_beta_mv = 0.0
    if deployed > 0:
        current_high_beta_mv = sum(
            p.get("market_value", 0)
            for p in portfolio.get("positions", [])
            if p.get("symbol") in high_beta_symbols
        )
    current_high_beta_pct = current_high_beta_mv / deployed if deployed > 0 else 0.0

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

    # ------------------------------------------------------------------
    # Sector-aware allocation with high-beta cap
    # ------------------------------------------------------------------
    def is_high_beta(sym: str) -> bool:
        return sym in high_beta_symbols
    # Split eligible by high-beta status
    hb_eligible = [s for s in eligible if is_high_beta(s.get("symbol"))]
    non_hb_eligible = [s for s in eligible if not is_high_beta(s.get("symbol"))]

    targets = {}

    def sector_current_mv(sector: str) -> float:
        return sum(positions.get(sym, {}).get("market_value", 0) for sym in targets if _symbol_sector(sym) == sector)

    def sector_additions(sector: str) -> float:
        return sum(
            max(0.0, targets[sym] - positions.get(sym, {}).get("market_value", 0))
            for sym in targets if _symbol_sector(sym) == sector
        )

    def cap_sectors() -> float:
        """Scale back additions in sectors over cap. Return freed capital."""
        freed = 0.0
        for _ in range(3):
            any_over = False
            exposures = _compute_sector_exposures(targets, positions)
            for sector, exp in exposures.items():
                cap_value = pv * MAX_SECTOR_PCT
                if exp > cap_value:
                    any_over = True
                    sector_syms = [sym for sym in targets if _symbol_sector(sym) == sector]
                    current_mv = sum(positions.get(sym, {}).get("market_value", 0) for sym in sector_syms)
                    additions = sum(max(0.0, targets[sym] - positions.get(sym, {}).get("market_value", 0)) for sym in sector_syms)
                    if additions > 0:
                        allowed_additions = max(0.0, cap_value - current_mv)
                        scale = allowed_additions / additions if additions > 0 else 0.0
                        scale = max(0.0, min(scale, 1.0))
                        for sym in sector_syms:
                            current_value = positions.get(sym, {}).get("market_value", 0)
                            addition = max(0.0, targets[sym] - current_value)
                            new_addition = addition * scale
                            freed += addition - new_addition
                            targets[sym] = current_value + new_addition
            if not any_over:
                break
        return freed

    # Step 1: Allocate deployable capital to non-high-beta eligible symbols first
    non_hb_readiness = sum(s.get("readiness_score", 0) for s in non_hb_eligible) or 1.0
    for s in non_hb_eligible:
        sym = s.get("symbol")
        targets[sym] = deployable_value * (s.get("readiness_score", 0) / non_hb_readiness)
        # Floor allocation for entry-eligible names to ensure meaningful deployment
        min_target = pv * MIN_ELIGIBLE_TARGET_PCT
        if targets[sym] < min_target:
            targets[sym] = min(min_target, pv * MAX_SINGLE_TARGET_PCT)
    cap_sectors()

    # Step 2: (disabled) Diversification candidates were creating 25+ tiny positions.
    # Re-enable only if you want sector-filling with non-eligible names.
    freed = 0.0


    # Step 3: Allocate remaining deployable capital to high-beta eligible,
    # up to the high-beta basket cap.
    used = sum(targets.values())
    remaining = max(0.0, deployable_value - used)
    hb_readiness = sum(s.get("readiness_score", 0) for s in hb_eligible) or 1.0
    hb_room = max(0.0, deployed * MAX_HIGH_BETA_DEPLOYED_PCT - current_high_beta_mv)
    for s in hb_eligible:
        sym = s.get("symbol")
        current_value = positions.get(sym, {}).get("market_value", 0)
        raw_target = current_value + remaining * (s.get("readiness_score", 0) / hb_readiness)
        if current_high_beta_pct >= MAX_HIGH_BETA_DEPLOYED_PCT:
            targets[sym] = current_value
        else:
            additional = max(0.0, min(raw_target - current_value, hb_room))
            targets[sym] = current_value + additional
            # Floor allocation for entry-eligible high-beta names
            min_target = pv * MIN_ELIGIBLE_TARGET_PCT
            if targets[sym] < min_target:
                targets[sym] = min(min_target, current_value + pv * MAX_SINGLE_TARGET_PCT)
            hb_room -= additional

    cap_sectors()

    # Apply per-stock cap (aligns with live bot's 8% max position)
    for sym in list(targets.keys()):
        targets[sym] = min(targets[sym], pv * MAX_SINGLE_TARGET_PCT)

    # Cash-aware scaling: total buys cannot exceed deployable capital (cash floor)
    available_cash = portfolio.get("account", {}).get("cash", 0)
    cash_floor = pv * (1.0 - DEPLOYABLE_PCT)
    deployable_cash = max(0.0, available_cash - cash_floor)
    # If targets imply buying more than deployable cash, scale back additions
    required_buy = sum(max(0.0, targets[sym] - positions.get(sym, {}).get("market_value", 0)) for sym in targets)
    if required_buy > deployable_cash:
        scale = deployable_cash / required_buy if required_buy > 0 else 1.0
        for sym in targets:
            current_value = positions.get(sym, {}).get("market_value", 0)
            addition = max(0.0, targets[sym] - current_value)
            targets[sym] = current_value + addition * scale

    # Build plan from final targets
    plan = []
    for sym, target_value in targets.items():
        s = next((x for x in signals if x.get("symbol") == sym), {})
        current = positions.get(sym, {})
        current_value = current.get("market_value", 0)
        current_pct = current.get("weight_pct", 0)
        target_pct = target_value / pv * 100 if pv > 0 else 0.0
        delta_value = target_value - current_value

        action = "HOLD"
        if delta_value > pv * 0.005:
            action = "BUY"
        elif delta_value < -pv * 0.005:
            action = "TRIM"

        plan.append({
            "symbol": sym,
            "readiness": round(s.get("readiness_score", 0), 2),
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

    # Compute post-rebalance cash for accurate reporting
    final_deployed = sum(targets.values())
    post_rebalance_cash = max(0.0, pv - final_deployed)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "portfolio_value": round(pv, 2),
        "deployable_value": round(deployable_value, 2),
        "cash": round(post_rebalance_cash, 2),
        "eligible_symbols": len(eligible),
        "total_readiness": round(total_readiness, 2),
        "plan": plan,
        "not_eligible_held": not_eligible_held,
        "note": "Paper plan only. Trades are NOT executed.",
        "sector_cap": {
            "cap_pct": MAX_SECTOR_PCT * 100,
            "diversification_readiness_min": DIVERSIFICATION_READINESS_MIN,
            "diversification_confirmations_min": DIVERSIFICATION_CONFIRMATIONS_MIN,
            "comment": "Sector-aware allocator caps per-sector exposure and redeploys freed capital to near-eligible diversified ideas."
        },
        "high_beta_cap": {
            "cap_pct": MAX_HIGH_BETA_DEPLOYED_PCT * 100,
            "current_pct": round(current_high_beta_pct * 100, 2),
            "high_beta_symbols": sorted(high_beta_symbols),
            "comment": "High-beta targets may be capped to respect the macro-concentration guard."
        },
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
