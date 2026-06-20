#!/usr/bin/env python3
"""
Generate 30-day price history files for sparklines.

For now this creates synthetic history seeded by avg_entry -> current price,
since free historical data APIs (Yahoo, Finnhub candles) are blocked or
paid-only on this server. Replace with real API calls once a reliable
source is available.

Writes JSON files to /var/www/hedge-fund-website/history/{TICKER}.json.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

WEB_ROOT = "/var/www/hedge-fund-website"
HISTORY_DIR = os.path.join(WEB_ROOT, "history")
WORKSPACE = "/root/.openclaw/workspace"
PORTFOLIO_FILE = os.path.join(WORKSPACE, "website/portfolio_data.json")
WATCHLIST_FILE = os.path.join(WORKSPACE, "website/ai_watchlist_live.json")
DAYS = 30


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def load_tickers_with_prices():
    """Load tickers plus avg_entry/current from portfolio_data.json."""
    tickers = {}
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r") as f:
                data = json.load(f)
            for pos in data.get("positions", []):
                sym = pos.get("symbol")
                if sym:
                    tickers[sym] = {
                        "avg_entry": float(pos.get("avg_entry", 0)) or None,
                        "current": float(pos.get("current", 0)) or None,
                    }
        except Exception as e:
            print(f"Failed to load {PORTFOLIO_FILE}: {e}")

    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                data = json.load(f)
            for item in data.get("watchlist", []):
                sym = item.get("symbol")
                if sym and sym not in tickers:
                    tickers[sym] = {
                        "avg_entry": float(item.get("price", 0)) or None,
                        "current": float(item.get("current", 0)) or None,
                    }
        except Exception as e:
            print(f"Failed to load {WATCHLIST_FILE}: {e}")

    return tickers


def generate_history(ticker, avg_entry, current):
    """Generate plausible 30-day close history from start to current price."""
    points = 30
    if current is None or current <= 0:
        current = 100.0
    if avg_entry is None or avg_entry <= 0:
        avg_entry = current * 0.95

    total_change = current - avg_entry
    base_step = total_change / (points - 1)
    volatility = max(abs(total_change) * 0.15, current * 0.015)

    history = []
    today = datetime.now(timezone.utc).date()
    for i in range(points):
        progress = i / (points - 1)
        trend_component = base_step * i
        wave = (progress ** 0.7) * volatility * 0.4 * (1 if total_change >= 0 else -1)
        noise = ((i % 7) / 7 - 0.5) * volatility * 0.5
        price = avg_entry + trend_component + wave + noise
        if i == points - 1:
            price = current
        history.append({
            "date": (today - timedelta(days=(points - 1 - i))).strftime("%Y-%m-%d"),
            "close": round(float(price), 4),
        })

    return {
        "ticker": ticker,
        "currency": "USD",
        "days_requested": DAYS,
        "points": len(history),
        "synthetic": True,
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "history": history,
    }


def main():
    ensure_dir(HISTORY_DIR)
    tickers = load_tickers_with_prices()
    if not tickers:
        print("No tickers found. Exiting.")
        sys.exit(0)

    print(f"Generating {DAYS}-day synthetic history for {len(tickers)} tickers")

    manifest = {
        "tickers": [],
        "days": DAYS,
        "synthetic": True,
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    for ticker, prices in tickers.items():
        history = generate_history(ticker, prices.get("avg_entry"), prices.get("current"))
        out_path = os.path.join(HISTORY_DIR, f"{ticker}.json")
        with open(out_path, "w") as f:
            json.dump(history, f, indent=2)
        print(f"Wrote {out_path} ({history['points']} points)")
        manifest["tickers"].append(ticker)

    manifest_path = os.path.join(HISTORY_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest: {manifest_path}")


if __name__ == "__main__":
    main()
