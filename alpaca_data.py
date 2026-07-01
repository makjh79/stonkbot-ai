"""
STONK.AI Unified Alpaca Data Layer

Single source of truth for all market data from Alpaca's paid data API.
Replaces scattered fetch methods across signal_engine, readiness_score,
watchlist manager, etc.

Key endpoints used:
- v2/stocks/snapshots — multi-symbol real-time snapshots (price, daily bar, prev close, minute bar)
- v2/stocks/{symbol}/bars — historical & intraday bars (1Min, 15Min, 1Day)
- v2/stocks/quotes/latest — real-time bid/ask
- v1beta1/news — news articles with sentiment
- v1beta1/options/snapshots — options data (implied vol, volume)

v1.0 — 2026-06-27
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from functools import lru_cache
import threading

logger = logging.getLogger(__name__)

_MUTEX = threading.Lock()
_CACHE: Dict[str, Tuple[float, object]] = {}
_CACHE_TTL = 60  # seconds — short TTL for real-time data


def _load_config() -> Dict:
    """Load Alpaca API config from known paths."""
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


def _get_headers(cfg: Dict) -> Dict:
    return {
        "APCA-API-KEY-ID": cfg["api_key"],
        "APCA-API-SECRET-KEY": cfg["api_secret"],
        "Accept": "application/json",
    }


def _cached(key: str, ttl: int, fetcher):
    """Simple TTL cache for API calls."""
    now = time.time()
    with _MUTEX:
        entry = _CACHE.get(key)
        if entry and (now - entry[0]) < ttl:
            return entry[1]
    val = fetcher()
    with _MUTEX:
        if val is not None:
            _CACHE[key] = (now, val)
    return val


class AlpacaDataHub:
    """Unified data access layer for all Alpaca market data."""

    BATCH_SIZE = 200  # symbols per snapshot request (Alpaca allows large batches)

    def __init__(self, config: Optional[Dict] = None):
        self._cfg = config or _load_config()
        self._headers = _get_headers(self._cfg)
        self._data_url = self._cfg.get("data_url", "https://data.alpaca.markets")

    # ── Snapshots ──────────────────────────────────────────────────────

    def get_snapshots(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Fetch real-time snapshots for multiple symbols in one request.
        Returns per-symbol: dailyBar, prevDailyBar, latestTrade, latestQuote, minuteBar.
        """
        import requests

        results = {}
        # Batch to avoid URL length limits
        for i in range(0, len(symbols), self.BATCH_SIZE):
            batch = symbols[i:i + self.BATCH_SIZE]
            sym_str = ",".join(batch)
            url = f"{self._data_url}/v2/stocks/snapshots?symbols={sym_str}&feed=sip"
            try:
                resp = requests.get(url, headers=self._headers, timeout=15)
                if resp.status_code != 200:
                    logger.warning(f"Snapshot batch failed: {resp.status_code}")
                    continue
                data = resp.json()
                # Alpaca v2 snapshots returns symbols at top level (not nested under "snapshots")
                snaps_dict = data.get("snapshots", data) if isinstance(data, dict) else {}
                for sym, snap in snaps_dict.items():
                    if not isinstance(snap, dict) or "dailyBar" not in snap and "latestQuote" not in snap:
                        continue
                    results[sym] = {
                        "price": snap.get("latestTrade", {}).get("p") or snap.get("dailyBar", {}).get("c"),
                        "daily_open": snap.get("dailyBar", {}).get("o"),
                        "daily_high": snap.get("dailyBar", {}).get("h"),
                        "daily_low": snap.get("dailyBar", {}).get("l"),
                        "daily_close": snap.get("dailyBar", {}).get("c"),
                        "daily_volume": snap.get("dailyBar", {}).get("v"),
                        "daily_vwap": snap.get("dailyBar", {}).get("vw"),
                        "prev_close": snap.get("prevDailyBar", {}).get("c"),
                        "minute_open": snap.get("minuteBar", {}).get("o"),
                        "minute_high": snap.get("minuteBar", {}).get("h"),
                        "minute_low": snap.get("minuteBar", {}).get("l"),
                        "minute_close": snap.get("minuteBar", {}).get("c"),
                        "minute_volume": snap.get("minuteBar", {}).get("v"),
                        "minute_vwap": snap.get("minuteBar", {}).get("vw"),
                        "bid": snap.get("latestQuote", {}).get("bp"),
                        "ask": snap.get("latestQuote", {}).get("ap"),
                        "bid_size": snap.get("latestQuote", {}).get("bs"),
                        "ask_size": snap.get("latestQuote", {}).get("as"),
                        "trade_timestamp": snap.get("latestTrade", {}).get("t"),
                    }
            except Exception as e:
                logger.warning(f"Snapshot batch {i} error: {e}")
        return results

    def get_snapshot(self, symbol: str) -> Optional[Dict]:
        """Single symbol snapshot (convenience)."""
        snaps = self.get_snapshots([symbol])
        return snaps.get(symbol)

    # ── Daily Bars ─────────────────────────────────────────────────────

    def get_daily_bars(self, symbols: List[str], days: int = 120) -> Dict[str, Dict]:
        """
        Fetch historical daily bars for multiple symbols.
        Returns per-symbol: {closes, highs, lows, volumes, vwap, timestamps}
        """
        import requests

        end = datetime.now(timezone.utc) - timedelta(hours=1)
        start = end - timedelta(days=days + 7)
        url = f"{self._data_url}/v2/stocks/bars"
        result = {}
        BATCH = 15  # 15 symbols x ~67 bars = ~1005, fits in 1000 bar limit per page
        symbol_list = list(symbols)
        for i in range(0, len(symbol_list), BATCH):
            batch = symbol_list[i:i + BATCH]
            page_token = None
            batch_result = {}
            # Paginate through all bars for this batch
            for _page in range(10):  # safety limit
                params = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "start": start.strftime("%Y-%m-%d"),
                    "end": end.strftime("%Y-%m-%d"),
                    "limit": 1000,
                    "feed": "sip",
                    "adjustment": "all",
                }
                if page_token:
                    params["page_token"] = page_token
                try:
                    resp = requests.get(url, params=params, headers=self._headers, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"Daily bars batch {i} error: {resp.status_code}")
                        break
                    data = resp.json()
                    bars_data = data.get("bars", {})
                    for symbol, bars in bars_data.items():
                        if symbol not in batch_result:
                            batch_result[symbol] = []
                        batch_result[symbol].extend(bars)
                    page_token = data.get("next_page_token")
                    if not page_token:
                        break
                except Exception as e:
                    logger.warning(f"Daily bars batch {i} failed: {e}")
                    break
            # Process accumulated bars
            for symbol, bars in batch_result.items():
                clean = [b for b in bars if all(b.get(k) is not None for k in ("c", "h", "l", "v"))]
                if clean:
                    result[symbol] = {
                        "closes": [b["c"] for b in clean],
                        "highs": [b["h"] for b in clean],
                        "lows": [b["l"] for b in clean],
                        "volumes": [b["v"] for b in clean],
                        "vwap": [b.get("vw", b["c"]) for b in clean],
                        "timestamps": [b["t"] for b in clean],
                        "trade_counts": [b.get("n", 0) for b in clean],
                    }
        return result

    # ── Intraday Bars (15-minute) ──────────────────────────────────────

    def get_intraday_bars(self, symbols: List[str], bars_back: int = 26, timeframe: str = "15Min") -> Dict[str, List[Dict]]:
        """
        Fetch recent intraday bars for multiple symbols.
        Returns per-symbol: list of {o, h, l, c, v, vw, t}
        Useful for intraday momentum, volume confirmation, VWAP calculations.
        """
        import requests

        end = datetime.now(timezone.utc)
        # Parse timeframe to minutes per bar (e.g. "5Min" → 5, "15Min" → 15)
        try:
            minutes_per_bar = int(''.join(c for c in timeframe if c.isdigit()))
        except ValueError:
            minutes_per_bar = 15
        start = end - timedelta(hours=bars_back * (minutes_per_bar / 60) * 2)  # 2x buffer for market hours
        url = f"{self._data_url}/v2/stocks/bars"
        result = {}
        BATCH = 15  # Keep small to avoid pagination issues
        symbol_list = list(symbols)
        for i in range(0, len(symbol_list), BATCH):
            batch = symbol_list[i:i + BATCH]
            params = {
                "symbols": ",".join(batch),
                "timeframe": timeframe,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": bars_back + 10,
                "feed": "sip",
                "adjustment": "all",
            }
            try:
                resp = requests.get(url, params=params, headers=self._headers, timeout=30)
                if resp.status_code != 200:
                    logger.warning(f"Intraday bars batch {i} error: {resp.status_code}")
                    continue
                data = resp.json()
                for symbol, bars in data.get("bars", {}).items():
                    clean = [b for b in bars if all(b.get(k) is not None for k in ("c", "v"))]
                    result[symbol] = clean[-bars_back:] if len(clean) > bars_back else clean
            except Exception as e:
                logger.warning(f"Intraday bars batch {i} failed: {e}")
        return result

    # ── Latest Quotes ─────────────────────────────────────────────────

    def get_latest_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Fetch latest bid/ask quotes for multiple symbols."""
        import requests

        results = {}
        sym_str = ",".join(symbols)
        url = f"{self._data_url}/v2/stocks/quotes/latest?symbols={sym_str}&feed=sip"
        try:
            resp = requests.get(url, headers=self._headers, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Quotes failed: {resp.status_code}")
                return results
            quotes = resp.json().get("quotes", {})
            for sym, q in quotes.items():
                results[sym] = {
                    "bid": q.get("bp"),
                    "ask": q.get("ap"),
                    "bid_size": q.get("bs"),
                    "ask_size": q.get("as"),
                    "midpoint": ((q.get("bp", 0) + q.get("ap", 0)) / 2) if q.get("bp") and q.get("ap") else None,
                    "timestamp": q.get("t"),
                    "exchange": q.get("bx"),
                }
        except Exception as e:
            logger.warning(f"Latest quotes error: {e}")
        return results

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Quick single-symbol latest price."""
        snap = self.get_snapshot(symbol)
        if snap:
            return snap.get("price") or snap.get("daily_close")
        # Fallback to quote
        quotes = self.get_latest_quotes([symbol])
        if symbol in quotes:
            return quotes[symbol].get("midpoint") or quotes[symbol].get("bid") or quotes[symbol].get("ask")
        return None

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Batch latest prices for multiple symbols."""
        snaps = self.get_snapshots(symbols)
        results = {}
        for sym, snap in snaps.items():
            p = snap.get("price") or snap.get("daily_close")
            if p:
                results[sym] = p
        # Fill gaps with quotes
        missing = [s for s in symbols if s not in results]
        if missing:
            quotes = self.get_latest_quotes(missing)
            for sym, q in quotes.items():
                p = q.get("midpoint") or q.get("bid") or q.get("ask")
                if p:
                    results[sym] = p
        return results

    # ── News & Sentiment ──────────────────────────────────────────────

    def get_news(self, symbols: List[str], limit: int = 10) -> List[Dict]:
        """
        Fetch recent news articles for given symbols.
        Returns list of: {id, headline, summary, source, created_at, sentiment, symbols, url}
        """
        import requests

        sym_str = ",".join(symbols[:50])
        url = f"{self._data_url}/v1beta1/news"
        params = {"symbols": sym_str, "limit": limit}
        try:
            resp = requests.get(url, params=params, headers=self._headers, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"News failed: {resp.status_code}")
                return []
            news = resp.json().get("news", [])
            cleaned = []
            for n in news:
                cleaned.append({
                    "id": n.get("id"),
                    "headline": n.get("headline"),
                    "summary": n.get("summary", ""),
                    "source": n.get("source"),
                    "author": n.get("author"),
                    "created_at": n.get("created_at"),
                    "updated_at": n.get("updated_at"),
                    "url": n.get("url"),
                    "symbols": n.get("symbols", []),
                    "content": n.get("content", ""),
                })
            return cleaned
        except Exception as e:
            logger.warning(f"News error: {e}")
            return []

    # ── Options Snapshots (implied vol, volume) ─────────────────────────

    def get_options_snapshot(self, symbol: str) -> Optional[Dict]:
        """
        Fetch options snapshot for a symbol.
        Returns implied volatility, volume, open interest data.
        """
        import requests

        url = f"{self._data_url}/v1beta1/options/snapshots/{symbol}"
        try:
            resp = requests.get(url, headers=self._headers, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            snaps = data.get("snapshots", {})
            if not snaps:
                return None
            # Aggregate key stats across all contracts
            total_volume = 0
            total_oi = 0
            iv_values = []
            for contract, snap in snaps.items():
                total_volume += snap.get("dailyBar", {}).get("v", 0)
                # Greeks may have implied vol
                greeks = snap.get("greeks", {})
                iv = greeks.get("implied_volatility") or snap.get("impliedVolatility") or snap.get("implied_volatility")
                if iv is not None and 0 < iv < 10:
                    iv_values.append(iv)
            return {
                "total_options_volume": total_volume,
                "total_open_interest": total_oi,
                "avg_implied_vol": sum(iv_values) / len(iv_values) if iv_values else None,
                "contract_count": len(snaps),
            }
        except Exception as e:
            logger.debug(f"Options snapshot for {symbol}: {e}")
            return None

    # ── Market Status ──────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """Check if US market is currently open."""
        import requests

        url = "https://paper-api.alpaca.markets/v2/clock"
        try:
            resp = requests.get(url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("is_open", False)
        except Exception:
            pass
        # Fallback: check by weekday + approx ET hours
        now = datetime.now(timezone.utc)
        # Market hours: 9:30 AM - 4:00 PM ET (UTC-4/5 depending on DST)
        # Simple check: Mon-Fri, 13:30-21:00 UTC (approx, covers DST roughly)
        if now.weekday() >= 5:
            return False
        market_open_utc = now.replace(hour=13, minute=30, second=0, microsecond=0)
        market_close_utc = now.replace(hour=21, minute=0, second=0, microsecond=0)
        return market_open_utc <= now <= market_close_utc

    def get_market_clock(self) -> Optional[Dict]:
        """Get detailed market clock info."""
        import requests

        url = "https://paper-api.alpaca.markets/v2/clock"
        try:
            resp = requests.get(url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # ── Intraday VWAP ──────────────────────────────────────────────────

    def get_intraday_vwap(self, symbols: List[str]) -> Dict[str, float]:
        """
        Calculate real intraday VWAP from 1Min bars.
        More accurate than daily VWAP from daily bar.
        """
        bars_data = self.get_intraday_bars(symbols, bars_back=390, timeframe="1Min")
        result = {}
        for sym, bars in bars_data.items():
            total_value = 0.0
            total_volume = 0
            for bar in bars:
                v = bar.get("v", 0)
                vw = bar.get("vw") or bar.get("c", 0)
                if v > 0 and vw:
                    total_value += vw * v
                    total_volume += v
            if total_volume > 0:
                result[sym] = total_value / total_volume
        return result

    # ── Extended Hours (Pre-market & After-hours) ─────────────────────────

    def get_extended_hours_bars(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Fetch pre-market and after-hours bars for the current trading day.
        
        Pre-market: 4:00-9:25 AM ET (08:00-13:25 UTC)
        After-hours: 4:00-8:00 PM ET (20:00-23:59 UTC)
        
        Returns per-symbol:
          premarket_open, premarket_close, premarket_volume, premarket_change_pct
          afterhours_open, afterhours_close, afterhours_volume, afterhours_change_pct
          prev_close (from yesterday's snapshot)
        
        Uses feed=sip which includes extended hours on all US exchanges.
        """
        import requests
        
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        result = {sym: {} for sym in symbols}
        
        # Get prev_close and latest price from snapshot for fallback
        prev_closes = {}
        latest_prices = {}
        try:
            snaps = self.get_snapshots(symbols)
            for sym, snap in snaps.items():
                pc = snap.get("prev_close")
                if pc:
                    prev_closes[sym] = pc
                price = snap.get("price")
                if price:
                    latest_prices[sym] = price
        except Exception:
            pass
        
        url = f"{self._data_url}/v2/stocks/bars"
        headers = self._headers
        
        # ── Pre-market bars (4:00-9:25 AM ET) ──
        pre_params = {
            "symbols": ",".join(symbols),
            "timeframe": "5Min",
            "start": f"{today}T08:00:00Z",
            "end": f"{today}T13:25:00Z",
            "feed": "sip",
            "adjustment": "all",
            "limit": 200,
        }
        try:
            r = requests.get(url, params=pre_params, headers=headers, timeout=20)
            if r.status_code == 200:
                for sym, bars in r.json().get("bars", {}).items():
                    if not bars:
                        continue
                    open_price = bars[0]["o"]
                    close_price = bars[-1]["c"]
                    volume = sum(b.get("v", 0) for b in bars)
                    result.setdefault(sym, {})
                    result[sym]["premarket_open"] = open_price
                    result[sym]["premarket_close"] = close_price
                    result[sym]["premarket_volume"] = volume
                    # Pre-market change from first bar open to last bar close
                    if open_price and close_price and open_price > 0:
                        result[sym]["premarket_change_pct"] = round((close_price - open_price) / open_price * 100, 2)
        except Exception as e:
            logger.debug(f"Pre-market bars error: {e}")
        
        ah_date = today if now.hour >= 20 else (now - timedelta(days=1)).strftime("%Y-%m-%d")
        # ── After-hours bars (4:00-8:00 PM ET = 20:00-23:59 UTC) ──
        ah_params = {
            "symbols": ",".join(symbols),
            "timeframe": "5Min",
            "start": f"{ah_date}T20:00:00Z",
            "end": f"{ah_date}T23:59:00Z",
            "feed": "sip",
            "adjustment": "all",
            "limit": 200,
        }
        try:
            r = requests.get(url, params=ah_params, headers=headers, timeout=20)
            if r.status_code == 200:
                for sym, bars in r.json().get("bars", {}).items():
                    if not bars:
                        continue
                    open_price = bars[0]["o"]
                    close_price = bars[-1]["c"]
                    volume = sum(b.get("v", 0) for b in bars)
                    result.setdefault(sym, {})
                    result[sym]["afterhours_open"] = open_price
                    result[sym]["afterhours_close"] = close_price
                    result[sym]["afterhours_volume"] = volume
                    if close_price and volume > 0:
                        result[sym]["afterhours_change_pct"] = round((close_price - open_price) / open_price * 100, 2) if open_price else None
        except Exception as e:
            logger.debug(f"After-hours bars error: {e}")
        
        # Snapshot fallback for pre-market / after-hours when bar data is missing
        if (8 <= now.hour < 14 or now.hour >= 20):
            for sym in symbols:
                pc = prev_closes.get(sym)
                price = latest_prices.get(sym)
                if not pc or not price:
                    continue
                if pc <= 0:
                    continue
                # Pre-market fallback (08:00-13:25 UTC)
                if 8 <= now.hour < 14 and "premarket_change_pct" not in result.get(sym, {}):
                    result.setdefault(sym, {})
                    result[sym]["premarket_change_pct"] = round((price - pc) / pc * 100, 2)
                    result[sym]["premarket_close"] = price
                    result[sym]["premarket_volume"] = result[sym].get("premarket_volume", 0)
                # After-hours fallback (20:00-23:59 UTC)
                if now.hour >= 20 and "afterhours_change_pct" not in result.get(sym, {}):
                    result.setdefault(sym, {})
                    result[sym]["afterhours_change_pct"] = round((price - pc) / pc * 100, 2)
                    result[sym]["afterhours_close"] = price
                    result[sym]["afterhours_volume"] = result[sym].get("afterhours_volume", 0)
        
        # Attach prev_close where available
        for sym in result:
            if sym in prev_closes:
                result[sym]["prev_close"] = prev_closes[sym]
                pc = prev_closes[sym]
                pm_close = result[sym].get("premarket_close")
                if pm_close and pc > 0:
                    result[sym]["gap_pct"] = round((pm_close - pc) / pc * 100, 2)
        
        return result

    def get_premarket_change(self, symbol: str) -> Optional[float]:
        """Quick single-symbol pre-market % change."""
        data = self.get_extended_hours_bars([symbol])
        d = data.get(symbol, {})
        return d.get("gap_pct") or d.get("premarket_change_pct")

    # ── Composite: Full Market Picture ─────────────────────────────────

    def get_market_data(self, symbols: List[str], lookback_days: int = 120) -> Dict:
        """
        One-call composite: daily bars + snapshots + intraday bars.
        This is what signal_engine, readiness_score, and watchlist manager should call.
        """
        import concurrent.futures

        result = {"daily": {}, "snapshots": {}, "intraday": {}}

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                "daily": executor.submit(self.get_daily_bars, symbols, lookback_days),
                "snapshots": executor.submit(self.get_snapshots, symbols),
                "intraday": executor.submit(self.get_intraday_bars, symbols, 78, "5Min"),
            }
            for key, future in futures.items():
                try:
                    result[key] = future.result(timeout=30)
                except Exception as e:
                    logger.warning(f"get_market_data/{key} failed: {e}")
                    result[key] = {}

        return result

    # ── Account Info ───────────────────────────────────────────────────

    def get_account(self) -> Optional[Dict]:
        """Fetch paper trading account info."""
        import requests

        url = f"{self._cfg.get('base_url', 'https://paper-api.alpaca.markets')}/v2/account"
        try:
            resp = requests.get(url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def get_positions(self) -> List[Dict]:
        """Fetch current positions."""
        import requests

        url = f"{self._cfg.get('base_url', 'https://paper-api.alpaca.markets')}/v2/positions"
        try:
            resp = requests.get(url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []


# ── Module-level singleton ─────────────────────────────────────────────

_hub: Optional[AlpacaDataHub] = None
_hub_lock = threading.Lock()


def get_data_hub(config: Optional[Dict] = None) -> AlpacaDataHub:
    """Get or create the singleton AlpacaDataHub instance."""
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = AlpacaDataHub(config)
        return _hub