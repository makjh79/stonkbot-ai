path = "/opt/stonk-ai/paper_rebalancer.py"
text = open(path).read()

# 1. Add sector cap config near top
old_config = '''# How much of the portfolio to deploy into entry-eligible ideas
DEPLOYABLE_PCT = 0.90  # keep 10% cash buffer'''
new_config = '''# How much of the portfolio to deploy into entry-eligible ideas
DEPLOYABLE_PCT = 0.90  # keep 10% cash buffer

# Sector diversification: max % of portfolio in any single sector
MAX_SECTOR_PCT = 0.20  # 20% of total portfolio per sector

# Lower-threshold gate for diversification-only candidates
# These do NOT qualify for the core momentum entry gate; they are used only to
# fill remaining deployable capital after high-beta and sector caps are applied.
DIVERSIFICATION_READINESS_MIN = 70.0
DIVERSIFICATION_CONFIRMATIONS_MIN = 3
'''
if old_config in text and "MAX_SECTOR_PCT" not in text:
    text = text.replace(old_config, new_config)
    print("added sector cap + diversification gate config")

# 2. Add helper functions after load_high_beta_symbols
helper = '''

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
'''
if "def _symbol_sector" not in text:
    text = text.replace("def compute_rebalance_plan", helper + "\ndef compute_rebalance_plan")
    print("added sector helpers")

# 3. Rewrite compute_rebalance_plan logic to include sector-aware allocator
# We will replace the allocation loop with a new helper-based approach.
old_start = '''def compute_rebalance_plan(signals: list[dict], portfolio: dict) -> dict:
    pv = portfolio.get("account", {}).get("portfolio_value", 0)
    if pv <= 0:
        return {"error": "Invalid portfolio value"}

    eligible = [
        s for s in signals
        if s.get("entry_eligible", False)
        and s.get("readiness_score", 0) > 0
    ]'''

new_start = '''def compute_rebalance_plan(signals: list[dict], portfolio: dict) -> dict:
    pv = portfolio.get("account", {}).get("portfolio_value", 0)
    if pv <= 0:
        return {"error": "Invalid portfolio value"}

    eligible = [
        s for s in signals
        if s.get("entry_eligible", False)
        and s.get("readiness_score", 0) > 0
    ]

    # Diversification candidates: near-eligible, used only to fill underweight sectors
    div_candidates = [
        s for s in signals
        if not s.get("entry_eligible", False)
        and s.get("readiness_score", 0) >= DIVERSIFICATION_READINESS_MIN
        and s.get("confirmation_count", 0) >= DIVERSIFICATION_CONFIRMATIONS_MIN
        and s.get("above_ema", False)
        and s.get("price", 0) > 0
    ]'''

if old_start in text and "div_candidates" not in text:
    text = text.replace(old_start, new_start)
    print("added diversification candidate selection")

# 4. Replace the allocation loop body with sector-aware allocator
old_loop = '''    plan = []
    # Apply high-beta basket cap to paper targets
    # If a symbol is in the high-beta basket and the basket is already over cap,
    # do not allocate more to it (treat as hold only).
    def is_high_beta(sym: str) -> bool:
        return sym in high_beta_symbols

    # Pre-calculate how much high-beta room is left (deployed basis)
    high_beta_room_value = max(0.0, deployed * MAX_HIGH_BETA_DEPLOYED_PCT - current_high_beta_mv)
    # Track remaining room as we allocate
    remaining_high_beta_room = high_beta_room_value

    for s in eligible:
        sym = s.get("symbol")
        hb = is_high_beta(sym)
        readiness = s.get("readiness_score", 0)
        raw_target_pct = (readiness / total_readiness) * DEPLOYABLE_PCT * 100
        raw_target_value = deployable_value * (readiness / total_readiness)
        current = positions.get(sym, {})
        current_value = current.get("market_value", 0)
        current_pct = current.get("weight_pct", 0)

        # High-beta basket cap: do not allocate additional capital to high-beta names
        # while the basket is above the cap. If the basket is below cap, allow increases
        # only up to the remaining room.
        if hb:
            if current_high_beta_pct >= MAX_HIGH_BETA_DEPLOYED_PCT:
                target_value = current_value
            else:
                additional = max(0.0, min(raw_target_value - current_value, remaining_high_beta_room))
                target_value = current_value + additional
                remaining_high_beta_room -= additional
        else:
            target_value = raw_target_value

        target_pct = target_value / pv * 100 if pv > 0 else 0.0
        delta_value = target_value - current_value

        action = "HOLD"
        if delta_value > pv * 0.005:  # 0.5% of portfolio minimum move
            action = "BUY"
        elif delta_value < -pv * 0.005:
            action = "TRIM"

        plan.append({'''

new_loop = '''    # ------------------------------------------------------------------
    # Sector-aware allocation with high-beta cap
    # ------------------------------------------------------------------
    def is_high_beta(sym: str) -> bool:
        return sym in high_beta_symbols

    # Start with raw readiness-proportional targets for entry-eligible symbols
    raw_targets = {}
    for s in eligible:
        sym = s.get("symbol")
        readiness = s.get("readiness_score", 0)
        raw_targets[sym] = deployable_value * (readiness / total_readiness)

    # Step 1: Apply high-beta cap (deployed basis)
    high_beta_room_value = max(0.0, deployed * MAX_HIGH_BETA_DEPLOYED_PCT - current_high_beta_mv)
    remaining_high_beta_room = high_beta_room_value
    for sym in list(raw_targets.keys()):
        if is_high_beta(sym):
            current_value = positions.get(sym, {}).get("market_value", 0)
            raw = raw_targets[sym]
            if current_high_beta_pct >= MAX_HIGH_BETA_DEPLOYED_PCT:
                raw_targets[sym] = current_value
            else:
                additional = max(0.0, min(raw - current_value, remaining_high_beta_room))
                raw_targets[sym] = current_value + additional
                remaining_high_beta_room -= additional

    # Step 2: Apply sector cap (portfolio basis)
    sector_exposures = _compute_sector_exposures(raw_targets, positions)
    freed_capital = 0.0
    for sector, exp in sector_exposures.items():
        cap_value = pv * MAX_SECTOR_PCT
        if exp > cap_value:
            overage = exp - cap_value
            # Scale back this sector's targets proportionally
            sector_symbols = [sym for sym in raw_targets if _symbol_sector(sym) == sector]
            total_sector_target = sum(raw_targets[sym] for sym in sector_symbols)
            if total_sector_target > 0:
                scale = max(0.0, 1.0 - overage / total_sector_target)
                for sym in sector_symbols:
                    freed_capital += raw_targets[sym] * (1.0 - scale)
                    raw_targets[sym] *= scale

    # Step 3: Redeploy freed capital to under-represented sectors using div candidates
    div_candidates_sorted = sorted(div_candidates, key=lambda s: s.get("readiness_score", 0), reverse=True)
    for s in div_candidates_sorted:
        if freed_capital <= 0:
            break
        sym = s.get("symbol")
        sector = _symbol_sector(sym)
        sector_exposures = _compute_sector_exposures(raw_targets, positions)
        if sector_exposures.get(sector, 0) >= pv * MAX_SECTOR_PCT:
            continue
        if sym in raw_targets:
            continue
        # Allocate up to remaining freed capital, but respect sector cap
        room_in_sector = max(0.0, pv * MAX_SECTOR_PCT - sector_exposures.get(sector, 0))
        allocation = min(freed_capital, room_in_sector)
        if allocation > pv * 0.005:  # 0.5% min position
            raw_targets[sym] = allocation
            freed_capital -= allocation

    # Build plan from final targets
    plan = []
    for sym, target_value in raw_targets.items():
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

        plan.append({'''

if old_loop in text and "Step 3: Redeploy freed capital" not in text:
    text = text.replace(old_loop, new_loop)
    print("replaced allocation with sector-aware allocator")

# 5. Add metadata fields to output
old_note = '''        "note": "Paper plan only. Trades are NOT executed.",
        "high_beta_cap": {'''
new_note = '''        "note": "Paper plan only. Trades are NOT executed.",
        "sector_cap": {
            "cap_pct": MAX_SECTOR_PCT * 100,
            "diversification_readiness_min": DIVERSIFICATION_READINESS_MIN,
            "diversification_confirmations_min": DIVERSIFICATION_CONFIRMATIONS_MIN,
            "comment": "Sector-aware allocator caps per-sector exposure and redeploys freed capital to near-eligible diversified ideas."
        },
        "high_beta_cap": {'''
if old_note in text and "sector_cap" not in text:
    text = text.replace(old_note, new_note)
    print("added sector_cap metadata")

open(path, "w").write(text)
print("done")
