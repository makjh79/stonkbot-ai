"""
Intraday Entry Confirmation Module

Fetches recent 5-minute bars from Alpaca SIP feed and checks
whether a stock has intraday momentum before the bot executes a buy.

This prevents buying into intraday reversals — the daily signal
might be bullish, but if the stock is actively selling off in the
last 15-30 minutes, we wait.

Rules:
  - GREEN: last 5-min bar is green (close >= open) → CONFIRM
  - WEAK_GREEN: last bar red, but 2 of last 3 bars green → CONFIRM (reduce size 20%)
  - RED: last 3 bars all red → SKIP
  - INSUFFICIENT: fewer than 3 bars available → FALLBACK (don't block)

Exit trades (sells) are NEVER gated by this — stops and thesis exits
must fire instantly.
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# How many 5-min bars to fetch (lookback window)
LOOKBACK_BARS = 6  # 30 minutes of data

# Minimum bars needed to make a decision
MIN_BARS_FOR_DECISION = 3


def fetch_recent_5min_bars(
    alpaca_client,
    symbol: str,
    lookback_bars: int = LOOKBACK_BARS,
) -> Optional[List[Dict]]:
    """
    Fetch recent 5-minute bars for a symbol.
    Returns list of {'o': open, 'h': high, 'l': low, 'c': close, 'v': volume, 't': timestamp}
    or None if data unavailable.
    """
    try:
        import requests
        end = datetime.now(timezone.utc)
        # Fetch enough history to cover lookback_bars + buffer
        # 5 min per bar, fetch 2 hours to be safe
        start = end - timedelta(hours=2)

        url = f"{alpaca_client.data_url}/v2/stocks/bars"
        params = {
            "symbols": symbol,
            "timeframe": "5Min",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 50,
            "feed": "sip",
            "adjustment": "all",
        }
        headers = {
            "APCA-API-KEY-ID": alpaca_client.api_key,
            "APCA-API-SECRET-KEY": alpaca_client.api_secret,
            "Accept": "application/json",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.debug(f"5-min bars fetch failed for {symbol}: {resp.status_code}")
            return None

        bars = resp.json().get("bars", {}).get(symbol, [])
        if not bars:
            return None

        # Return the most recent bars
        return bars[-lookback_bars:]
    except Exception as e:
        logger.debug(f"Error fetching 5-min bars for {symbol}: {e}")
        return None


def check_intraday_momentum(bars: List[Dict]) -> Tuple[str, float]:
    """
    Analyze 5-min bars for intraday momentum.

    Returns (decision, size_multiplier):
      - ("CONFIRM", 1.0) — green bar, full size
      - ("CONFIRM", 0.8) — mixed but mostly green, reduce 20%
      - ("SKIP", 0.0) — all red, skip this buy
      - ("FALLBACK", 1.0) — not enough data, don't block
    """
    if not bars or len(bars) < MIN_BARS_FOR_DECISION:
        return ("FALLBACK", 1.0)

    # Classify each bar
    green_count = 0
    red_count = 0
    for bar in bars:
        o = float(bar.get("o", 0))
        c = float(bar.get("c", 0))
        if c >= o:
            green_count += 1
        else:
            red_count += 1

    # Check last bar
    last_bar = bars[-1]
    last_o = float(last_bar.get("o", 0))
    last_c = float(last_bar.get("c", 0))
    last_green = last_c >= last_o

    # Check last 3 bars
    last_3 = bars[-3:]
    last_3_green = sum(1 for b in last_3 if float(b.get("c", 0)) >= float(b.get("o", 0)))

    if last_green:
        # Last bar is green — confirm
        return ("CONFIRM", 1.0)
    elif last_3_green >= 2:
        # Last bar red but 2 of last 3 green — confirm with reduced size
        return ("CONFIRM", 0.8)
    else:
        # Last 3 bars mostly red — skip
        return ("SKIP", 0.0)


def should_execute_buy(
    alpaca_client,
    symbol: str,
    is_market_open: bool,
) -> Tuple[bool, float, str]:
    """
    Main entry point. Returns (should_execute, size_multiplier, reason).

    If market is closed, always returns True (the bot's daily signal is sufficient).
    If market is open, checks intraday 5-min bars before confirming.
    """
    if not is_market_open:
        return (True, 1.0, "market closed — daily signal only")

    bars = fetch_recent_5min_bars(alpaca_client, symbol)
    if bars is None:
        # Can't fetch intraday data — don't block the trade
        return (True, 1.0, "no intraday data — fallback to daily signal")

    decision, multiplier = check_intraday_momentum(bars)

    if decision == "CONFIRM":
        if multiplier < 1.0:
            return (True, multiplier, f"intraday mixed — size reduced to {multiplier}x")
        return (True, 1.0, "intraday confirmed — green 5-min bar")
    elif decision == "SKIP":
        return (False, 0.0, "intraday skip — last 3 bars all red")
    else:
        return (True, 1.0, "insufficient intraday bars — fallback")