path = "/opt/stonk-ai/paper_rebalancer.py"
text = open(path).read()

# 1. Exclude high-beta symbols from div_candidates
old_div = '''    # Diversification candidates: near-eligible, used only to fill underweight sectors
    div_candidates = [
        s for s in signals
        if not s.get("entry_eligible", False)
        and s.get("readiness_score", 0) >= DIVERSIFICATION_READINESS_MIN
        and s.get("confirmation_count", 0) >= DIVERSIFICATION_CONFIRMATIONS_MIN
        and s.get("above_ema20", False) or s.get("confirmations", {}).get("above_ema", False)
        and s.get("price", 0) > 0
    ]'''
new_div = '''    # Diversification candidates: near-eligible NON-high-beta symbols used to fill underweight sectors
    def is_high_beta(sym: str) -> bool:
        return sym in high_beta_symbols

    div_candidates = [
        s for s in signals
        if not s.get("entry_eligible", False)
        and s.get("readiness_score", 0) >= DIVERSIFICATION_READINESS_MIN
        and s.get("confirmation_count", 0) >= DIVERSIFICATION_CONFIRMATIONS_MIN
        and (s.get("above_ema20", False) or s.get("confirmations", {}).get("above_ema", False))
        and s.get("price", 0) > 0
        and not is_high_beta(s.get("symbol"))
    ]'''

if old_div in text:
    text = text.replace(old_div, new_div)
    print("fixed div_candidates precedence and excluded high-beta symbols")

# 2. Replace the allocation section from marker to marker
start_marker = "    # ------------------------------------------------------------------\n    # Sector-aware allocation with high-beta cap\n    # ------------------------------------------------------------------"
end_marker = "    # Build plan from final targets"

start = text.find(start_marker)
end = text.find(end_marker)

if start == -1 or end == -1:
    print(f"markers not found: start={start}, end={end}")
else:
    new_block = '''    # ------------------------------------------------------------------
    # Sector-aware allocation with high-beta cap
    # ------------------------------------------------------------------
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
    cap_sectors()

    # Step 2: Fill underweight sectors with non-high-beta div candidates
    freed = 0.0
    div_sorted = sorted(div_candidates, key=lambda s: s.get("readiness_score", 0), reverse=True)
    for s in div_sorted:
        sym = s.get("symbol")
        sector = _symbol_sector(sym)
        exposures = _compute_sector_exposures(targets, positions)
        if exposures.get(sector, 0) >= pv * MAX_SECTOR_PCT:
            continue
        if sym in targets:
            continue
        room = max(0.0, pv * MAX_SECTOR_PCT - exposures.get(sector, 0))
        alloc = min(room, deployable_value * 0.05)
        if alloc > pv * 0.005:
            targets[sym] = alloc
            freed += cap_sectors()

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
            hb_room -= additional

    cap_sectors()

'''
    text = text[:start] + new_block + text[end:]
    open(path, "w").write(text)
    print("rewrote allocator v3")
