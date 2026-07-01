path = "/opt/stonk-ai/paper_rebalancer.py"
text = open(path).read()

# 1. Raise sector cap and make trim-vs-block configurable
old_config = '''# Sector diversification: max % of portfolio in any single sector
MAX_SECTOR_PCT = 0.20  # 20% of total portfolio per sector'''
new_config = '''# Sector diversification: max % of portfolio in any single sector
MAX_SECTOR_PCT = 0.30  # 30% of total portfolio per sector (existing positions are not forcibly trimmed unless overage exceeds this buffer)
SECTOR_TRIM_BUFFER_PCT = 0.05  # only trim existing sector positions if they exceed cap + buffer'''
if old_config in text:
    text = text.replace(old_config, new_config)
    print("raised sector cap to 30%, added trim buffer")

# 2. Replace sector cap logic to avoid trimming existing positions unless severe overage
old_sector_logic = '''    # Step 2: Apply sector cap (portfolio basis)
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
                    raw_targets[sym] *= scale'''

new_sector_logic = '''    # Step 2: Apply sector cap (portfolio basis)
    # Block new additions to sectors already at cap. Only trim existing positions
    # if the sector exceeds cap + buffer (avoid churn from small overages).
    sector_exposures = _compute_sector_exposures(raw_targets, positions)
    freed_capital = 0.0
    for sector, exp in sector_exposures.items():
        cap_value = pv * MAX_SECTOR_PCT
        buffer_value = pv * SECTOR_TRIM_BUFFER_PCT
        if exp > cap_value + buffer_value:
            # Severe overage — trim targets proportionally (but not below current value if possible)
            overage = exp - cap_value
            sector_symbols = [sym for sym in raw_targets if _symbol_sector(sym) == sector]
            total_sector_target = sum(max(0.0, raw_targets[sym] - positions.get(sym, {}).get("market_value", 0)) for sym in sector_symbols)
            if total_sector_target > 0:
                trim_from_new = min(total_sector_target, overage)
                scale = max(0.0, 1.0 - trim_from_new / total_sector_target)
                for sym in sector_symbols:
                    current_value = positions.get(sym, {}).get("market_value", 0)
                    new_addition = max(0.0, raw_targets[sym] - current_value)
                    freed_capital += new_addition * (1.0 - scale)
                    raw_targets[sym] = current_value + new_addition * scale
        elif exp > cap_value:
            # At cap but within buffer — block new additions only, no trims
            sector_symbols = [sym for sym in raw_targets if _symbol_sector(sym) == sector]
            for sym in sector_symbols:
                current_value = positions.get(sym, {}).get("market_value", 0)
                if raw_targets[sym] > current_value:
                    freed_capital += raw_targets[sym] - current_value
                    raw_targets[sym] = current_value'''

if old_sector_logic in text and "Block new additions to sectors already at cap" not in text:
    text = text.replace(old_sector_logic, new_sector_logic)
    print("replaced sector cap logic")

open(path, "w").write(text)
print("done")
