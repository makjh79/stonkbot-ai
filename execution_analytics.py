"""
execution_analytics.py — Slippage and liquidity analytics from Alpaca 1Min quote/bars data.

Premium Data subscription unlocks 1Min bars/quotes for spread history.
Outputs:
  - estimate_slippage(symbol, qty, price, side='buy'): bps expected slippage.
  - size_adjustment(symbol, qty, price): multiplier to apply to position size.
  - spread_history(symbol, lookback_minutes=60): list of recent half-spreads in bps.
"""

import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def _load_config() -> Dict:
    paths = [
        Path("/opt/stonk-ai/alpaca_config.json"),
        Path(__file__).parent / "alpaca_config.json",
        Path("/var/www/hedge-fund-website/alpaca_config.json"),
    ]
    for p in paths:
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                continue
    return {}


def _headers(cfg: Optional[Dict] = None) -> Dict:
    cfg = cfg or _load_config()
    return {
        "APCA-API-KEY-ID": cfg["api_key"],
        "APCA-API-SECRET-KEY": cfg["api_secret"],
        "Accept": "application/json",
    }


def _fetch_1min_quotes(symbol: str, lookback_minutes: int = 60, cfg: Optional[Dict] = None) -> List[Dict]:
    """Fetch 1Min quote bars (bid/ask) for spread analysis."""
    cfg = cfg or _load_config()
    data_url = cfg.get("data_url", "https://data.alpaca.markets")
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=lookback_minutes + 5)
    params = {
        "symbols": symbol,
        
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": lookback_minutes + 10,
        "feed": "sip",
        
    }
    url = f"{data_url}/v2/stocks/quotes"
    try:
        resp = requests.get(url, params=params, headers=_headers(cfg), timeout=15)
        if resp.status_code != 200:
            logger.debug(f"Quotes fetch for {symbol}: {resp.status_code}")
            return []
        data = resp.json()
        return data.get("quotes", {}).get(symbol, [])
    except Exception as e:
        logger.debug(f"Quotes fetch failed for {symbol}: {e}")
        return []


def _fetch_daily_bars(symbol: str, days: int = 20, cfg: Optional[Dict] = None) -> List[Dict]:
    """Fetch daily bars for ADV calculation."""
    cfg = cfg or _load_config()
    data_url = cfg.get("data_url", "https://data.alpaca.markets")
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=days + 1)
    params = {
        "symbols": symbol,
        "timeframe": "1Day",
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": days + 1,
        "feed": "sip",
        
    }
    url = f"{data_url}/v2/stocks/bars"
    try:
        resp = requests.get(url, params=params, headers=_headers(cfg), timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("bars", {}).get(symbol, [])
    except Exception as e:
        logger.debug(f"Daily bars fetch failed for {symbol}: {e}")
        return []


def _half_spread_bps(quote: Dict) -> Optional[float]:
    bid = quote.get("bp")
    ask = quote.get("ap")
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return round((ask - bid) / mid / 2 * 10000, 2)


def spread_history(symbol: str, lookback_minutes: int = 60, cfg: Optional[Dict] = None) -> List[float]:
    """Recent half-spreads in basis points."""
    quotes = _fetch_1min_quotes(symbol, lookback_minutes, cfg)
    spreads = [_half_spread_bps(q) for q in quotes]
    return [s for s in spreads if s is not None]


def average_daily_volume(symbol: str, days: int = 20, cfg: Optional[Dict] = None) -> Optional[float]:
    bars = _fetch_daily_bars(symbol, days, cfg)
    if len(bars) < 5:
        return None
    return round(sum(b.get("v", 0) for b in bars) / len(bars), 0)


def estimate_slippage(symbol: str, qty: int, price: float, side: str = "buy", cfg: Optional[Dict] = None) -> Optional[Dict]:
    """
    Estimate all-in slippage in basis points for a trade.

    Model:
      - half_spread: typical cost of crossing the spread
      - market_impact: proportional to order size / ADV, scaled by volatility
      - Returns dict with bps and dollar estimates
    """
    spreads = spread_history(symbol, lookback_minutes=60, cfg=cfg)
    if not spreads:
        return None

    adv = average_daily_volume(symbol, days=20, cfg=cfg)
    if not adv or adv <= 0:
        return None

    half_spread = statistics.median(spreads)
    participation = (abs(qty) * price) / (adv * price) if price > 0 else 0
    # Square-root market impact model: impact ~ 50bps * sqrt(participation)
    market_impact_bps = 50 * (participation ** 0.5)

    # Urgent/large orders pay more; small orders pay roughly half-spread
    total_bps = half_spread + market_impact_bps
    notional = abs(qty) * price
    slippage_dollars = round(notional * total_bps / 10000, 2)

    return {
        "half_spread_bps": half_spread,
        "market_impact_bps": round(market_impact_bps, 2),
        "total_bps": round(total_bps, 2),
        "slippage_dollars": slippage_dollars,
        "adv": adv,
        "median_spread_bps": round(statistics.median(spreads), 2),
        "max_spread_bps": round(max(spreads), 2),
        "samples": len(spreads),
    }


def size_adjustment(symbol: str, qty: int, price: float, cfg: Optional[Dict] = None) -> float:
    """
    Return a multiplier to apply to intended position size based on liquidity.
    Cuts size for names where expected slippage is high.
    """
    est = estimate_slippage(symbol, qty, price, cfg=cfg)
    if est is None:
        return 1.0
    total_bps = est["total_bps"]
    # If expected slippage > 25bps, scale down; > 50bps, cut aggressively
    if total_bps > 50:
        return 0.5
    if total_bps > 25:
        return 0.75
    return 1.0


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    qty = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    price = float(sys.argv[3]) if len(sys.argv) > 3 else 0
    print(json.dumps(estimate_slippage(sym, qty, price), indent=2, default=str))
