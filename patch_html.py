#!/usr/bin/env python3
"""Patch index.html for PEAD factor chip updates."""
import sys
from pathlib import Path

html_path = Path("/var/www/hedge-fund-website/index.html")

def patch(content, old, new, desc=""):
    if old not in content:
        print(f"ERROR: Could not find: {desc}")
        print(f"  Looking for: {old[:100]}...")
        return content
    content = content.replace(old, new, 1)
    print(f"OK: {desc}")
    return content

content = html_path.read_text()

# 1. Add PEAD factor to factors array in buildFactorChips
old_factors = "                { name: 'OPT', val: conf.options_confirmed, ok: conf.options_confirmed === true, tip: 'Options: implied volatility suggests bullish options positioning' },\n            ];"
new_factors = "                { name: 'OPT', val: conf.options_confirmed, ok: conf.options_confirmed === true, tip: 'Options: implied volatility suggests bullish options positioning' },\n                { name: 'PEAD', val: conf.earnings_confirmed, ok: conf.earnings_confirmed === true, tip: 'PEAD: Post-Earnings Announcement Drift \\u2014 stock within 30 days of an earnings beat' },\n            ];"
content = patch(content, old_factors, new_factors, "add PEAD factor chip")

# 2. Update info tooltip from 8-factor to 9-factor
content = content.replace(
    "8-factor conviction model scoring each stock",
    "9-factor conviction model scoring each stock"
)
print("OK: updated 8-factor -> 9-factor in tooltip")

# 3. Add PEAD to factor criteria in tooltip
old_criteria = "• OPT: implied volatility suggests bullish positioning<br><br>Hover individual chips for each factor criteria."
new_criteria = "• OPT: implied volatility suggests bullish positioning<br>• PEAD: within 30 days of an earnings beat (post-earnings drift)<br><br>Hover individual chips for each factor criteria."
content = content.replace(old_criteria, new_criteria)
print("OK: added PEAD criteria to tooltip")

# 4. Replace all ${count}/8 with ${count}/9
content = content.replace("${count}/8", "${count}/9")
print("OK: replaced all ${count}/8 -> ${count}/9")

# 5. Replace "8 factors" with "9 factors" in main tooltip
content = content.replace("Conviction model: 8 factors scored per stock", "Conviction model: 9 factors scored per stock")
print("OK: updated conviction model tooltip")

# 6. Replace "7-factor conviction model" with "9-factor conviction model"
content = content.replace("7-factor conviction model", "9-factor conviction model")
print("OK: updated 7-factor -> 9-factor")

# 7. Add PEAD to watchlist factors list
old_allfactors = "const allFactors = ['MOM', 'RSI', 'VOL', 'MACD', 'EMA', 'SEC', 'INT', 'OPT'];"
new_allfactors = "const allFactors = ['MOM', 'RSI', 'VOL', 'MACD', 'EMA', 'SEC', 'INT', 'OPT', 'PEAD'];"
content = content.replace(old_allfactors, new_allfactors)
print("OK: added PEAD to allFactors array")

# 8. Add PEAD to factorMap
old_fmap = "'intraday': 'INT', 'options': 'OPT', 'momentum': 'MOM', 'rsi': 'RSI'"
new_fmap = "'intraday': 'INT', 'options': 'OPT', 'momentum': 'MOM', 'rsi': 'RSI', 'earnings': 'PEAD', 'pead': 'PEAD'"
content = content.replace(old_fmap, new_fmap)
print("OK: added PEAD to factorMap")

# 9. Update "Composite of 7 factors"
content = content.replace("Composite of 7 factors", "Composite of 9 factors")
print("OK: updated composite factors text")

html_path.write_text(content)
print("\nindex.html patched successfully!")