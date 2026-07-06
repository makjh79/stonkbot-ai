#!/usr/bin/env python3
"""
Pre-market generation script.
Runs all data generators with market-open bypass so the website
has fresh data with all Alpaca integration before market opens.

Run at 9:25 AM ET (13:25 UTC) Monday before market open.
"""
import json
import sys
import logging
import os
from datetime import datetime, timezone

os.chdir("/opt/stonk-ai")
sys.path.insert(0, "/opt/stonk-ai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

now = datetime.now(timezone.utc)
print(f"=== Pre-Market Generation — {now.isoformat()} ===\n")

# 1. Fetch fresh portfolio data (with VWAP from snapshots)
print("--- 1. Portfolio Data (with VWAP) ---")
from fetch_data_simple import fetch_and_save
ok = fetch_and_save()
print(f"  Result: {'OK' if ok else 'FAILED'}")

# 2. Generate fresh signals (with options, intraday, VWAP)
print("\n--- 2. Signal Generation ---")
from signal_engine import SignalEngine
engine = SignalEngine()
signals = engine.generate_signals(lookback_days=120)
print(f"  Generated {len(signals)} signals")
# Save
engine.save_signals(signals)
print(f"  Saved to signals.json")

# 3. Update watchlist
print("\n--- 3. Watchlist Update ---")
from dynamic_watchlist_manager import update_watchlist
update_watchlist()
print(f"  Watchlist updated")

# 4. Generate popup content (bypass market-closed check)
print("\n--- 4. Popup Content (force-generated) ---")
import generate_popup_content as gpc
gpc.is_market_open = lambda: True  # bypass market check
popup = gpc.generate_popup_content()
if popup and "holdings" in popup:
    print(f"  Generated popups for {len(popup['holdings'])} holdings")
    # Verify VWAP and news
    for sym, h in list(popup["holdings"].items())[:3]:
        print(f"  {sym}: vwap={h.get('dailyVwap')}, vwapStop={h.get('vwapStop')}, news={h.get('alpacaNewsHeadline','')[:50]}")
else:
    print("  FAILED — no popup data")

# 5. Update signal enrichment (news-only, fresh Alpaca headlines)
print("\n--- 5. Signal Enrichment (news refresh) ---")
from signal_enricher import enrich_symbol, load_finnhub_key, load_enrichment, save_enrichment
api_key = load_finnhub_key()
enrichment = load_enrichment()
# Only refresh top 20 symbols to be quick
top_syms = [s.symbol for s in signals[:20]]
for sym in top_syms:
    try:
        result = enrich_symbol(sym, api_key, news_only=True)
        enrichment[sym]["news"] = result.get("news")
        enrichment[sym]["fetched_at"] = result.get("fetched_at")
    except Exception as e:
        print(f"  {sym}: failed ({e})")
save_enrichment(enrichment)
print(f"  Refreshed enrichment for {len(top_syms)} top symbols")

# 6. Sync all data to website
print("\n--- 6. Sync to Website ---")
import shutil
# portfolio_data already saved by fetch_and_save
# signals already saved
# watchlist already saved
# popup content already saved
# enrichment sync to website
shutil.copy("/opt/stonk-ai/signal_enrichment.json", "/var/www/hedge-fund-website/signal_enrichment.json")
print("  All data synced to website")

# 7. Final verification
print("\n--- 7. Verification ---")
with open("/opt/stonk-ai/portfolio_data.json") as f:
    pd = json.load(f)
positions = pd.get("positions", [])
vwap_count = sum(1 for p in positions if p.get("daily_vwap") is not None)
print(f"  portfolio_data: {len(positions)} positions, {vwap_count} with VWAP")

with open("/opt/stonk-ai/signals.json") as f:
    sd = json.load(f)
sigs = sd.get("signals", [])
print(f"  signals.json: {len(sigs)} signals")

with open("/var/www/hedge-fund-website/popup_content.json") as f:
    pc = json.load(f)
holdings = pc.get("holdings", {})
has_vwap = sum(1 for h in holdings.values() if h.get("dailyVwap") is not None)
has_stop = sum(1 for h in holdings.values() if h.get("vwapStop") is not None)
has_news = sum(1 for h in holdings.values() if h.get("alpacaNewsHeadline"))
print(f"  popup_content: {len(holdings)} holdings, {has_vwap} VWAP, {has_stop} vwapStop, {has_news} news")

print(f"\n=== Pre-Market Generation Complete — {datetime.now(timezone.utc).isoformat()} ===")