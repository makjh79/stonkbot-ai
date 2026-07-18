#!/usr/bin/env python3
"""One-off: backfill SPY benchmark_value in portfolio_history.json.

Entries after 2026-07-06 lack benchmark fields (writer changed), which
broke the "Bot vs. Market" comparison series on the site. Anchor matches
the legacy series and market_indices.json: 100000 * SPY_close / 757.09.

Run once as stonkai. Safe to re-run (only fills missing fields).
"""
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/opt/stonk-ai")
from alpaca_data import get_data_hub

SPY_START = 757.09
PATHS = [
    "/opt/stonk-ai/portfolio_history.json",
    "/var/www/hedge-fund-website/portfolio_history.json",
]

hub = get_data_hub()
bars = hub.get_daily_bars("SPY", days_back=20) or []
closes = {}
for b in bars:
    d = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    closes[d] = float(b["c"])
print(f"SPY daily closes for {len(closes)} days, latest {max(closes) if closes else '-'}")

# Fallback: last 15-min bar close per date (daily bars lag ~2 weeks on this feed)
need = {"2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"}
missing = need - set(closes)
if missing:
    intra = hub.get_intraday_bars("SPY", bars_back=520) or []
    for b in intra:
        d = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d in missing:
            closes[d] = float(b["c"])  # last bar of the day wins (bars are chronological)
    print(f"Intraday fallback filled: {sorted(missing & set(closes))}")

for path in PATHS:
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"SKIP {path}: {e}")
        continue
    filled = 0
    for entry in data.get("checks", []):
        if entry.get("benchmark_value"):
            continue
        day = str(entry.get("timestamp", ""))[:10]
        close = closes.get(day)
        if not close:
            # use nearest earlier close (weekends/holidays)
            earlier = [d for d in closes if d <= day]
            close = closes[max(earlier)] if earlier else None
        if close:
            entry["benchmark_value"] = round(100000.0 * close / SPY_START, 2)
            entry["benchmark_symbol"] = "SPY"
            filled += 1
    if filled:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    print(f"{path}: filled {filled} entries")
