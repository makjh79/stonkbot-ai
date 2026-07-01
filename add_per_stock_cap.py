path = "/opt/stonk-ai/paper_rebalancer.py"
text = open(path).read()

old_config = """# Sector diversification: max % of portfolio in any single sector
MAX_SECTOR_PCT = 0.30  # 30% of total portfolio per sector (existing positions are not forcibly trimmed unless overage exceeds this buffer)
SECTOR_TRIM_BUFFER_PCT = 0.05  # only trim existing sector positions if they exceed cap + buffer"""
new_config = """# Sector diversification: max % of portfolio in any single sector
MAX_SECTOR_PCT = 0.30  # 30% of total portfolio per sector (existing positions are not forcibly trimmed unless overage exceeds this buffer)
SECTOR_TRIM_BUFFER_PCT = 0.05  # only trim existing sector positions if they exceed cap + buffer
MAX_SINGLE_TARGET_PCT = 0.08  # align with live bot's 8% max single position cap"""
if old_config in text:
    text = text.replace(old_config, new_config)
    print("added config")

old_plan_build = "    # Build plan from final targets\n    plan = []"
new_plan_build = """    # Apply per-stock cap (aligns with live bot's 8% max position)
    for sym in list(targets.keys()):
        targets[sym] = min(targets[sym], pv * MAX_SINGLE_TARGET_PCT)

    # Build plan from final targets
    plan = []"""
if old_plan_build in text:
    text = text.replace(old_plan_build, new_plan_build)
    print("added per-stock cap logic")

open(path, "w").write(text)
print("done")
