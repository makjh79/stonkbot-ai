#!/usr/bin/env python3
"""
STONK.AI Watchlist Feedback Tracker

Tracks outcomes for watchlist stocks that were NOT bought, for self-tuning.
Runs via cron daily after market close.

For each stock in the NOW tier that wasn't bought (cash constraint, etc.),
we track what happened 5/10/20 days later to evaluate tier accuracy.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Paths
BOT_DIR = Path("/opt/stonk-ai")
SIGNALS_FILE = BOT_DIR / "signals.json"
FEEDBACK_FILE = BOT_DIR / "watchlist_feedback.json"
TRACKING_FILE = BOT_DIR / "watchlist_feedback_tracking.json"
PORTFOLIO_FILE = Path("/var/www/hedge-fund-website/portfolio_data.json")

# Alpaca config for price fetching
ALPACA_CONFIG_PATHS = [
    BOT_DIR / "alpaca_config.json",
    Path("/var/www/hedge-fund-website/alpaca_config.json"),
]


def load_config() -> Dict:
    for p in ALPACA_CONFIG_PATHS:
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                continue
    return {}


def load_signals() -> List[Dict]:
    if not SIGNALS_FILE.exists():
        return []
    try:
        with open(SIGNALS_FILE) as f:
            return json.load(f).get("signals", [])
    except Exception:
        return []


def load_tracking() -> Dict:
    if not TRACKING_FILE.exists():
        return {"tracked": []}
    try:
        with open(TRACKING_FILE) as f:
            return json.load(f)
    except Exception:
        return {"tracked": []}


def save_tracking(data: Dict):
    try:
        with open(TRACKING_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save tracking file: {e}")


def load_feedback() -> Dict:
    if not FEEDBACK_FILE.exists():
        return {"tracked": [], "stats": {}}
    try:
        with open(FEEDBACK_FILE) as f:
            return json.load(f)
    except Exception:
        return {"tracked": [], "stats": {}}


def save_feedback(data: Dict):
    try:
        with open(FEEDBACK_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save feedback file: {e}")


def get_held_symbols() -> set:
    """Get currently held symbols from portfolio data."""
    if not PORTFOLIO_FILE.exists():
        return set()
    try:
        with open(PORTFOLIO_FILE) as f:
            data = json.load(f)
        return {p["symbol"] for p in data.get("positions", [])}
    except Exception:
        return set()


def fetch_historical_price(symbol: str, days_ago: int, config: Dict) -> Optional[float]:
    """Fetch closing price N days ago using Alpaca data API."""
    try:
        import requests
        api_key = config.get("api_key") or config.get("APCA_API_KEY_ID")
        api_secret = config.get("api_secret") or config.get("APCA_API_SECRET_KEY")
        data_url = config.get("data_url", "https://data.alpaca.markets")

        if not api_key or not api_secret:
            return None

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_ago + 10)

        url = f"{data_url}/v2/stocks/bars"
        params = {
            "symbols": symbol,
            "timeframe": "1Day",
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "limit": days_ago + 10,
            "feed": "sip",
            "adjustment": "all",
        }
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None
        bars = resp.json().get("bars", {}).get(symbol, [])
        if not bars or len(bars) < days_ago:
            return None
        # Get the close from days_ago trading days ago
        idx = len(bars) - days_ago - 1
        if idx < 0:
            idx = 0
        close = bars[idx].get("c")
        return float(close) if close else None
    except Exception as e:
        logger.debug(f"Could not fetch historical price for {symbol}: {e}")
        return None


def fetch_current_price(symbol: str, config: Dict) -> Optional[float]:
    """Fetch current/latest price for a symbol."""
    try:
        import requests
        api_key = config.get("api_key") or config.get("APCA_API_KEY_ID")
        api_secret = config.get("api_secret") or config.get("APCA_API_SECRET_KEY")
        data_url = config.get("data_url", "https://data.alpaca.markets")

        if not api_key or not api_secret:
            return None

        r = requests.get(
            f"{data_url}/v2/stocks/quotes/latest",
            params={"symbols": symbol, "feed": "sip"},
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": api_secret,
                "Accept": "application/json",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        quote = r.json().get("quotes", {}).get(symbol, {})
        price = quote.get("ap") or quote.get("bp") or quote.get("p")
        return float(price) if price else None
    except Exception:
        return None


def add_new_tracks(signals: List[Dict], held: set, tracking: Dict):
    """Add NOW and WATCH tier stocks that aren't held to tracking."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = {t["symbol"] for t in tracking["tracked"] if not t.get("bought", False)}

    for sig in signals:
        symbol = sig.get("symbol", "")
        tier = sig.get("tier", "")
        readiness = sig.get("readiness_score", 0)
        price = sig.get("price", 0)

        # Track NOW and WATCH tiers that aren't held
        if tier not in ("NOW", "WATCH"):
            continue
        if symbol in held:
            continue
        if symbol in existing:
            continue
        if price <= 0:
            continue

        tracking["tracked"].append({
            "symbol": symbol,
            "date_added": today,
            "tier": tier,
            "readiness": readiness,
            "price_then": price,
            "bought": False,
            "price_5d": None,
            "price_10d": None,
            "price_20d": None,
            "return_5d": None,
            "return_10d": None,
            "return_20d": None,
            "would_have_been_profitable": None,
        })
        existing.add(symbol)
        logger.info(f"Tracking {symbol} ({tier}, readiness={readiness:.1f}, price=${price:.2f})")


def update_returns(tracking: Dict, config: Dict):
    """Update returns for tracked stocks that have aged enough."""
    today = datetime.now(timezone.utc)

    for entry in tracking["tracked"]:
        if entry.get("bought"):
            continue

        date_added = entry.get("date_added")
        if not date_added:
            continue

        try:
            added_date = datetime.strptime(date_added, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            continue

        days_since = (today - added_date).days

        # Update 5-day return
        if days_since >= 5 and entry.get("return_5d") is None:
            symbol = entry["symbol"]
            price_then = entry.get("price_then", 0)
            if price_then > 0:
                price_5d = fetch_historical_price(symbol, 5, config) or fetch_current_price(symbol, config)
                if price_5d:
                    entry["price_5d"] = round(price_5d, 2)
                    entry["return_5d"] = round((price_5d - price_then) / price_then * 100, 2)
                    logger.info(f"{symbol}: 5d return = {entry['return_5d']}%")

        # Update 10-day return
        if days_since >= 10 and entry.get("return_10d") is None:
            symbol = entry["symbol"]
            price_then = entry.get("price_then", 0)
            if price_then > 0:
                price_10d = fetch_historical_price(symbol, 10, config) or fetch_current_price(symbol, config)
                if price_10d:
                    entry["price_10d"] = round(price_10d, 2)
                    entry["return_10d"] = round((price_10d - price_then) / price_then * 100, 2)
                    logger.info(f"{symbol}: 10d return = {entry['return_10d']}%")

        # Update 20-day return
        if days_since >= 20 and entry.get("return_20d") is None:
            symbol = entry["symbol"]
            price_then = entry.get("price_then", 0)
            if price_then > 0:
                price_20d = fetch_historical_price(symbol, 20, config) or fetch_current_price(symbol, config)
                if price_20d:
                    entry["price_20d"] = round(price_20d, 2)
                    entry["return_20d"] = round((price_20d - price_then) / price_then * 100, 2)
                    # Mark profitable
                    entry["would_have_been_profitable"] = entry["return_20d"] > 0
                    logger.info(f"{symbol}: 20d return = {entry['return_20d']}%")

    # Move completed entries (all 3 returns filled) to feedback file
    completed = []
    remaining = []
    for entry in tracking["tracked"]:
        if (entry.get("return_5d") is not None and
                entry.get("return_10d") is not None and
                entry.get("return_20d") is not None):
            completed.append(entry)
        else:
            remaining.append(entry)
    tracking["tracked"] = remaining
    return completed


def compute_stats(feedback: Dict) -> Dict:
    """Compute tier accuracy statistics from completed entries."""
    tracked = feedback.get("tracked", [])
    if not tracked:
        return {
            "total_tracked": 0,
            "now_tier_accuracy": 0,
            "watch_tier_accuracy": 0,
            "monitor_tier_accuracy": 0,
            "avg_return_now_10d": 0,
            "avg_return_watch_10d": 0,
        }

    now_entries = [t for t in tracked if t.get("tier") == "NOW"]
    watch_entries = [t for t in tracked if t.get("tier") == "WATCH"]

    def accuracy(entries):
        if not entries:
            return 0
        profitable = sum(1 for e in entries if (e.get("return_10d") or 0) > 0)
        return round(profitable / len(entries), 2)

    def avg_return(entries, key="return_10d"):
        vals = [e.get(key) for e in entries if e.get(key) is not None]
        if not vals:
            return 0
        return round(sum(vals) / len(vals), 2)

    return {
        "total_tracked": len(tracked),
        "now_tier_accuracy": accuracy(now_entries),
        "watch_tier_accuracy": accuracy(watch_entries),
        "monitor_tier_accuracy": 0,  # we don't track MONITOR tier
        "avg_return_now_10d": avg_return(now_entries),
        "avg_return_watch_10d": avg_return(watch_entries),
    }


def main():
    logger.info(f"Watchlist Feedback Tracker — {datetime.now(timezone.utc).isoformat()}")

    config = load_config()
    signals = load_signals()
    held = get_held_symbols()
    tracking = load_tracking()
    feedback = load_feedback()

    # Add new tracks
    if signals:
        add_new_tracks(signals, held, tracking)

    # Update returns for aged tracks
    completed = update_returns(tracking, config)
    if completed:
        feedback["tracked"].extend(completed)
        logger.info(f"Moved {len(completed)} completed entries to feedback")

    # Recompute stats
    feedback["stats"] = compute_stats(feedback)
    feedback["last_run"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Save
    save_tracking(tracking)
    save_feedback(feedback)

    stats = feedback["stats"]
    logger.info(
        f"Done. Total tracked: {stats['total_tracked']}, "
        f"NOW accuracy: {stats['now_tier_accuracy']:.0%}, "
        f"WATCH accuracy: {stats['watch_tier_accuracy']:.0%}"
    )


if __name__ == "__main__":
    main()