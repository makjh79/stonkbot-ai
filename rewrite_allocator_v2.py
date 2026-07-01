import re

path = "/opt/stonk-ai/paper_rebalancer.py"
text = open(path).read()

# Lower diversification thresholds
if 'DIVERSIFICATION_READINESS_MIN = 70.0' in text:
    text = text.replace('DIVERSIFICATION_READINESS_MIN = 70.0', 'DIVERSIFICATION_READINESS_MIN = 65.0')
    text = text.replace('DIVERSIFICATION_CONFIRMATIONS_MIN = 3', 'DIVERSIFICATION_CONFIRMATIONS_MIN = 2')
    print("lowered div thresholds to 65/2")

# Find and replace allocation block: from "    # ------------------------------------------------------------------\n    # Sector-aware allocation with high-beta cap" to "    # Also include held positions..."
start_marker = "    # ------------------------------------------------------------------\n    # Sector-aware allocation with high-beta cap\n    # ------------------------------------------------------------------"
end_marker = "    # Also include held positions that are not entry-eligible as \"not in plan\""

start = text.find(start_marker)
end = text.find(end_marker)

if start == -1 or end == -1:
    print(f"markers not found: start={start}, end={end}")
else:
    new_block = '''    # ------------------------------------------------------------------
    # Sector-aware allocation with high-beta cap
    # ------------------------------------------------------------------
    def is_high_beta(sym: str) -> bool:
        return sym in high_beta_symbols

    # Split eligible by high-beta status
    hb_eligible = [s for s in eligible if is_high_beta(s.get("symbol"))]
    non_hb_eligible = [s for s in eligible if not is_high_beta(s.get("symbol"))]

    targets = {}

    # Step 1: Allocate deployable capital to non-high-beta eligible symbols first
    # (diversification priority). Proportional to readiness, capped by sector.
    non_hb_readiness = sum(s.get("readiness_score", 0) for s in non_hb_eligible) or 1.0
    for s in non_hb_eligible:
        sym = s.get("symbol")
        targets[sym] = deployable_value * (s.get("readiness_score", 0) / non_hb_readiness)

    # Step 2: Cap sectors (block-only: do not trim existing positions)
    def cap_sectors(targets: dict) -> float:
        freed = 0.0
        for _ in range(3):
            exposures = _compute_sector_exposures(targets, positions)
            any_over = False
            for sector, exp in exposures.items():
                cap_value = pv * MAX_SECTOR_PCT
                if exp > cap_value:
                    any_over = True
                    sector_syms = [sym for sym in targets if _symbol_sector(sym) == sector]
                    current_sector_mv = sum(positions.get(sym, {}).get("market_value", 0) for sym in sector_syms)
                    target_total = sum(targets[sym] for sym in sector_syms)
                    new_total = max(current_sector_mv, cap_value)
                    if target_total > 0:
                        scale = new_total / target_total
                        for sym in sector_syms:
                            old = targets[sym]
                            new = old * scale
                            targets[sym] = new
                            freed += max(0.0, old - new)
            if not any_over:
                break
        return freed

    freed = cap_sectors(targets)

    # Step 3: Fill underweight sectors with div candidates, using freed capital
    div_sorted = sorted(div_candidates, key=lambda s: s.get("readiness_score", 0), reverse=True)
    for s in div_sorted:
        if freed <= pv * 0.005:
            break
        sym = s.get("symbol")
        sector = _symbol_sector(sym)
        exposures = _compute_sector_exposures(targets, positions)
        if exposures.get(sector, 0) >= pv * MAX_SECTOR_PCT:
            continue
        if sym in targets:
            continue
        room = max(0.0, pv * MAX_SECTOR_PCT - exposures.get(sector, 0))
        alloc = min(freed, room, deployable_value * 0.05)
        if alloc > pv * 0.005:
            targets[sym] = alloc
            freed -= alloc
            cap_sectors(targets)

    # Step 4: Allocate remaining deployable capital to high-beta eligible,
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

    cap_sectors(targets)

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

'''
    text = text[:start] + new_block + text[end:]
    open(path, "w").write(text)
    print("rewrote allocation block")
