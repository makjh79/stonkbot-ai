#!/usr/bin/env python3
"""
Monday market-open intraday pipeline test.
Verifies that 15Min bars, VWAP, options sentiment, and intraday confirmations
are all flowing correctly during live market hours.

Run this at 9:35 AM ET (13:35 UTC) on Monday after market open.
"""
import json
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, "/opt/stonk-ai")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

print(f"=== Intraday Pipeline Test — {datetime.now(timezone.utc).isoformat()} ===")

# 1. Test Alpaca data hub
from alpaca_data import get_data_hub
hub = get_data_hub()

print("\n--- 1. Market Status ---")
clock = hub.get_market_clock()
print(f"Market open: {clock.get('is_open') if clock else 'N/A'}")
print(f"Next open: {clock.get('next_open') if clock else 'N/A'}")

print("\n--- 2. Snapshots (real-time) ---")
snaps = hub.get_snapshots(["AAPL", "MSFT", "NVDA", "GOOGL", "META"])
print(f"Got {len(snaps)} snapshots")
for sym, snap in list(snaps.items())[:3]:
    print(f"  {sym}: price={snap.get('price')}, vwap={snap.get('daily_vwap')}, "
          f"prevClose={snap.get('prev_close')}, minuteVol={snap.get('minute_volume')}")

print("\n--- 3. Intraday 15Min Bars ---")
intra = hub.get_intraday_bars(["AAPL", "MSFT", "NVDA"], bars_back=10)
print(f"Got intraday bars for {len(intra)} symbols")
for sym, bars in intra.items():
    print(f"  {sym}: {len(bars)} bars, last close={bars[-1].get('c') if bars else 'N/A'}")

print("\n--- 4. News ---")
news = hub.get_news(["AAPL", "MSFT"], limit=5)
print(f"Got {len(news)} news articles")
for n in news[:3]:
    print(f"  - {n.get('headline', '')[:80]}")

print("\n--- 5. Options ---")
for sym in ["AAPL", "MSFT"]:
    opts = hub.get_options_snapshot(sym)
    if opts:
        print(f"  {sym}: IV={opts.get('avg_implied_vol')}, vol={opts.get('total_options_volume')}, contracts={opts.get('contract_count')}")
    else:
        print(f"  {sym}: No options data")

print("\n--- 6. Signal Generation (with intraday data) ---")
from signal_engine import SignalEngine
engine = SignalEngine()
signals = engine.generate_signals(lookback_days=120)
print(f"Generated {len(signals)} signals")

# Check intraday confirmations
intraday_confirmed = [s for s in signals if s.confirmations and s.confirmations.get("intraday_confirmed")]
options_confirmed = [s for s in signals if s.confirmations and s.confirmations.get("options_confirmed")]
print(f"Signals with intraday confirmation: {len(intraday_confirmed)}")
print(f"Signals with options confirmation: {len(options_confirmed)}")

print("\n--- 7. Top 10 Signals ---")
for s in signals[:10]:
    confs = s.confirmations
    print(f"  {s.symbol}: readiness={s.readiness_score}, tier={s.tier}, "
          f"confs={s.confirmation_count}, "
          f"intraday={'✓' if confs.get('intraday_confirmed') else '✗'}, "
          f"options={'✓' if confs.get('options_confirmed') else '✗'}, "
          f"VWAP={s.daily_vwap}")

print("\n--- 8. Risk Engine (VWAP stops) ---")
from risk_engine import RiskEngine
risk = RiskEngine()
# Load real portfolio
with open("/opt/stonk-ai/portfolio_data.json") as f:
    portfolio = json.load(f)
# Add VWAP data to positions from snapshots
for pos in portfolio.get("positions", []):
    sym = pos.get("symbol")
    if sym in snaps:
        pos["daily_vwap"] = snaps[sym].get("daily_vwap")
exits = risk.check_exits(portfolio)
print(f"Exit signals: {len(exits)}")
for ex in exits:
    print(f"  {ex['symbol']}: {ex['action']} — {ex['reason']}")

print(f"\n=== Pipeline Test Complete — {datetime.now(timezone.utc).isoformat()} ===")