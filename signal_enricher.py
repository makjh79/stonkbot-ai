#!/usr/bin/env python3
"""
STONK.AI Signal Enricher v2.0

Batched, memory-bounded enrichment with incremental saves.
- Processes symbols in small batches (10 at a time)
- Saves after each batch so progress is never lost
- Respects Finnhub rate limits with proper spacing
- Skips symbols already enriched recently (configurable TTL)
- Can run in --news-only mode for lightweight intraday top-ups

Usage:
  python3 signal_enricher.py              # Full enrichment (batched)
  python3 signal_enricher.py --news-only   # News-only top-up
  python3 signal_enricher.py --force       # Force full re-enrichment (ignore TTL)
  python3 signal_enricher.py --batch 0-9   # Enrich only symbols 0-9
"""

import json
import logging
import os
import re
import sys
import time
import gc
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from alpaca_data import get_data_hub

logger = logging.getLogger(__name__)

BOT_DIR = Path("/opt/stonk-ai")
ENRICHMENT_FILE = BOT_DIR / "signal_enrichment.json"
ENRICHMENT_TMP = BOT_DIR / "signal_enrichment.tmp.json"
FINNHUB_KEY_PATHS = [
    Path(__file__).parent / ".secrets" / "finnhub.key",
    Path("/opt/stonk-ai/.secrets/finnhub.key"),
    Path("/root/.openclaw/workspace/.secrets/finnhub.key"),
]

# Finnhub free tier: 60 calls/min. We target ~50/min to be safe.
API_CALL_INTERVAL = 1.3  # seconds between calls (~46/min)
BATCH_SIZE = 10  # symbols per batch
BATCH_SAVE_DELAY = 2  # seconds to pause between batches
ENRICHMENT_TTL_HOURS = 12  # re-enrich if older than this (unless --force)

BULLISH_WORDS = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "rallies",
    "upgrade", "upgrades", "strong", "growth", "bullish", "outperform",
    "breakthrough", "momentum", "record", "exceeds", "exceed", "raised",
    "raise", "boost", "boosts", "jump", "jumps", "gain", "gains", "boom",
}
BEARISH_WORDS = {
    "miss", "misses", "drop", "drops", "fall", "falls", "plunge", "plunges",
    "downgrade", "downgrades", "weak", "slowdown", "bearish", "underperform",
    "cut", "cuts", "decline", "declines", "sink", "sinks", "tumble", "tumbles",
    "loss", "losses", "layoff", "layoffs", "warning", "warns", "risk", "risks",
}


def load_finnhub_key() -> str:
    for p in FINNHUB_KEY_PATHS:
        if p.exists():
            try:
                return p.read_text().strip()
            except Exception:
                continue
    return os.getenv("FINNHUB_API_KEY", "")


_last_call_time = 0.0

def finnhub_get(endpoint: str, params: Dict, api_key: str, retries: int = 2) -> Optional[Dict]:
    global _last_call_time
    # Rate limit: ensure minimum interval between calls
    elapsed = time.time() - _last_call_time
    if elapsed < API_CALL_INTERVAL:
        time.sleep(API_CALL_INTERVAL - elapsed)
    
    url = f"https://finnhub.io/api/v1{endpoint}"
    params["token"] = api_key
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
            _last_call_time = time.time()
            if resp.status_code == 429:
                if attempt < retries:
                    wait = 60 + attempt * 30  # longer waits: 60s, 90s
                    logger.warning(f"Finnhub 429 on {endpoint}, waiting {wait}s (attempt {attempt+1}/{retries+1})")
                    time.sleep(wait)
                    continue
                logger.warning(f"Finnhub {endpoint} rate limited after {retries+1} attempts, skipping")
                return None
            if resp.status_code != 200:
                logger.warning(f"Finnhub {endpoint} error {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()
        except Exception as e:
            _last_call_time = time.time()
            logger.warning(f"Finnhub {endpoint} failed: {e}")
            if attempt < retries:
                time.sleep(5)
                continue
            return None
    return None


def basic_sentiment(headlines: List[str]) -> Dict:
    if not headlines:
        return {"score": 50, "label": "neutral", "evidence": []}
    bullish = 0
    bearish = 0
    evidence = []
    for h in headlines:
        h_lower = h.lower()
        b = any(w in h_lower for w in BULLISH_WORDS)
        be = any(w in h_lower for w in BEARISH_WORDS)
        if b and not be:
            bullish += 1
            evidence.append(("bullish", h))
        elif be and not b:
            bearish += 1
            evidence.append(("bearish", h))
    total = bullish + bearish
    if total == 0:
        return {"score": 50, "label": "neutral", "evidence": []}
    score = 50 + int((bullish - bearish) / total * 50)
    label = "bullish" if score > 60 else "bearish" if score < 40 else "neutral"
    return {"score": score, "label": label, "evidence": evidence[:3]}


def fetch_earnings(symbol: str, api_key: str) -> Optional[Dict]:
    # PEAD dropped — Alpaca has no earnings API, Finnhub earnings removed
    return None

def _fetch_earnings_DEPRECATED(symbol: str, api_key: str) -> Optional[Dict]:
    data = finnhub_get("/stock/earnings", {"symbol": symbol}, api_key)
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    latest = data[0]
    estimate = latest.get("estimate")
    actual = latest.get("actual")
    if actual is None or estimate is None:
        return None
    return {
        "period": latest.get("period"),
        "quarter": latest.get("quarter"),
        "year": latest.get("year"),
        "estimate": estimate,
        "actual": actual,
        "surprise": latest.get("surprise"),
        "surprise_pct": latest.get("surprisePercent"),
        "direction": "beat" if actual >= estimate else "miss",
    }


def fetch_news(symbol: str, api_key: str, days: int = 5) -> Optional[Dict]:
    # Finnhub news dropped — using Alpaca news API only
    return None

def _fetch_news_DEPRECATED(symbol: str, api_key: str, days: int = 5) -> Optional[Dict]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    data = finnhub_get(
        "/company-news",
        {"symbol": symbol, "from": str(start), "to": str(end)},
        api_key,
    )
    if not data or not isinstance(data, list):
        return None
    headlines = []
    for item in data[:10]:
        h = item.get("headline", "").strip()
        if h and h not in headlines:
            headlines.append(h)
    sentiment = basic_sentiment(headlines)
    return {
        "headlines": headlines[:5],
        "sentiment_score": sentiment["score"],
        "sentiment_label": sentiment["label"],
        "sample_headline": headlines[0] if headlines else None,
    }


def fetch_alpaca_news(symbols: List[str], limit: int = 5) -> Dict[str, Dict]:
    """
    Fetch news from Alpaca's paid news API.
    Returns per-symbol: {headline, summary, source, created_at, url, sentiment_label}
    """
    hub = get_data_hub()
    news_data = hub.get_news(symbols, limit=limit * len(symbols))
    # Group by symbol
    result = {}
    for article in news_data:
        for sym in article.get("symbols", []):
            if sym not in result:
                result[sym] = {
                    "headline": article.get("headline", ""),
                    "summary": (article.get("summary") or "")[:200],
                    "source": article.get("source", ""),
                    "created_at": article.get("created_at", ""),
                    "url": article.get("url", ""),
                    "sentiment_label": _alpaca_news_sentiment(article.get("headline", "")),
                }
    return result


def _alpaca_news_sentiment(headline: str) -> str:
    """Simple keyword-based sentiment for Alpaca news headlines."""
    bullish_words = ["beat", "surge", "jump", "rise", "gain", "strong", "bullish", "upgrade", "buy", "record", "high", "top", "exceed", "outperform"]
    bearish_words = ["miss", "fall", "drop", "decline", "bearish", "downgrade", "sell", "weak", "low", "cut", "loss", "plunge", "crash", "fear"]

    headline_lower = headline.lower()
    bull_count = sum(1 for w in bullish_words if w in headline_lower)
    bear_count = sum(1 for w in bearish_words if w in headline_lower)

    if bull_count > bear_count:
        return "bullish"
    if bear_count > bull_count:
        return "bearish"
    return "neutral"


def fetch_recommendation(symbol: str, api_key: str) -> Optional[Dict]:
    # Recommendations dropped — analyst ratings are noise, not edge
    return None

def _fetch_recommendation_DEPRECATED(symbol: str, api_key: str) -> Optional[Dict]:
    data = finnhub_get("/stock/recommendation", {"symbol": symbol}, api_key)
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    latest = data[0]
    strong_buy = latest.get("strongBuy", 0)
    buy = latest.get("buy", 0)
    hold = latest.get("hold", 0)
    sell = latest.get("sell", 0)
    strong_sell = latest.get("strongSell", 0)
    total = strong_buy + buy + hold + sell + strong_sell
    if total == 0:
        return None
    bullish = strong_buy + buy
    bearish = sell + strong_sell
    return {
        "period": latest.get("period"),
        "strong_buy": strong_buy,
        "buy": buy,
        "hold": hold,
        "sell": sell,
        "strong_sell": strong_sell,
        "total": total,
        "bullish_pct": round(bullish / total * 100, 1),
        "bearish_pct": round(bearish / total * 100, 1),
    }


def fetch_metrics(symbol: str, api_key: str) -> Optional[Dict]:
    data = finnhub_get("/stock/metric", {"symbol": symbol, "metric": "all"}, api_key)
    if not data:
        return None
    m = data.get("metric", {})
    return {
        "week_52_high": m.get("52WeekHigh"),
        "week_52_low": m.get("52WeekLow"),
        "week_52_high_date": m.get("52WeekHighDate"),
        "week_52_low_date": m.get("52WeekLowDate"),
        "beta": m.get("beta"),
        "pe_ttm": m.get("peTTM"),
        "eps_ttm": m.get("epsTTM"),
        "dividend_yield": m.get("dividendYieldIndicatedAnnual"),
        "market_cap": m.get("marketCapitalization"),
    }


def enrich_symbol(symbol: str, api_key: str, news_only: bool = False) -> Dict:
    if news_only:
        news = fetch_news(symbol, api_key)
        # Add Alpaca news as supplementary source
        try:
            alpaca_data = fetch_alpaca_news([symbol], limit=3)
            if symbol in alpaca_data:
                a_news = alpaca_data[symbol]
                if isinstance(news, dict):
                    news["alpaca_headline"] = a_news.get("headline", "")
                    news["alpaca_sentiment"] = a_news.get("sentiment_label", "neutral")
                    news["alpaca_url"] = a_news.get("url", "")
                    news["alpaca_source"] = a_news.get("source", "")
                else:
                    news = {
                        "headline": a_news.get("headline", ""),
                        "summary": a_news.get("summary", ""),
                        "source": a_news.get("source", ""),
                        "sentiment_label": a_news.get("sentiment_label", "neutral"),
                        "alpaca_headline": a_news.get("headline", ""),
                        "alpaca_sentiment": a_news.get("sentiment_label", "neutral"),
                        "alpaca_url": a_news.get("url", ""),
                        "alpaca_source": a_news.get("source", ""),
                    }
        except Exception as _e:
            logger.debug(f"Alpaca news for {symbol} skipped: {_e}")
        return {
            "news": news,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    # Full enrichment
    news = fetch_news(symbol, api_key)
    try:
        alpaca_data = fetch_alpaca_news([symbol], limit=3)
        if symbol in alpaca_data:
            a_news = alpaca_data[symbol]
            if isinstance(news, dict):
                news["alpaca_headline"] = a_news.get("headline", "")
                news["alpaca_sentiment"] = a_news.get("sentiment_label", "neutral")
                news["alpaca_url"] = a_news.get("url", "")
                news["alpaca_source"] = a_news.get("source", "")
            else:
                news = {
                    "headline": a_news.get("headline", ""),
                    "summary": a_news.get("summary", ""),
                    "source": a_news.get("source", ""),
                    "sentiment_label": a_news.get("sentiment_label", "neutral"),
                    "alpaca_headline": a_news.get("headline", ""),
                    "alpaca_sentiment": a_news.get("sentiment_label", "neutral"),
                    "alpaca_url": a_news.get("url", ""),
                    "alpaca_source": a_news.get("source", ""),
                }
    except Exception as _e:
        logger.debug(f"Alpaca news for {symbol} skipped: {_e}")
    return {
        "earnings": fetch_earnings(symbol, api_key),
        "news": news,
        "recommendation": fetch_recommendation(symbol, api_key),
        "metrics": fetch_metrics(symbol, api_key),
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def load_enrichment(path: Path = ENRICHMENT_FILE) -> Dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data.get("data", {})
    except Exception as e:
        logger.warning(f"Could not load enrichment: {e}")
        return {}


def save_enrichment(enrichment: Dict, path: Path = ENRICHMENT_FILE) -> None:
    """Atomic save: write to tmp, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "finnhub",
        "count": len(enrichment),
        "data": enrichment,
    }
    ENRICHMENT_TMP.write_text(json.dumps(payload, indent=2))
    ENRICHMENT_TMP.rename(path)
    logger.info(f"Saved enrichment ({len(enrichment)} symbols) to {path}")


def load_universe() -> List[str]:
    try:
        from signal_engine import DEFAULT_UNIVERSE
        return DEFAULT_UNIVERSE
    except Exception as e:
        logger.warning(f"Could not import universe: {e}")
        return []


def is_stale(entry: Dict, ttl_hours: float = ENRICHMENT_TTL_HOURS) -> bool:
    if not entry or not entry.get("fetched_at"):
        return True
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - fetched
        return age > timedelta(hours=ttl_hours)
    except Exception:
        return True


def enrich_universe_batched(
    symbols: List[str],
    api_key: str,
    news_only: bool = False,
    force: bool = False,
    batch_range: Optional[tuple] = None,
) -> Dict[str, Dict]:
    """Enrich in batches with incremental saves."""
    enrichment = load_enrichment()
    
    # Filter to stale symbols only (unless --force or --news-only)
    if force or news_only:
        to_process = list(symbols)
    else:
        to_process = [s for s in symbols if is_stale(enrichment.get(s, {}))]
        skipped = len(symbols) - len(to_process)
        if skipped:
            logger.info(f"Skipping {skipped} fresh symbols (TTL {ENRICHMENT_TTL_HOURS}h)")
    
    if batch_range:
        start, end = batch_range
        to_process = to_process[start:end]
        logger.info(f"Batch range: {start}-{end}, processing {len(to_process)} symbols")
    
    if not to_process:
        logger.info("Nothing to enrich — all symbols fresh")
        return enrichment
    
    total = len(to_process)
    logger.info(f"Enriching {total} symbols ({'news-only' if news_only else 'full'}) in batches of {BATCH_SIZE}")
    
    for i, sym in enumerate(to_process):
        try:
            # Merge: for news-only, keep existing data and update news
            if news_only and sym in enrichment:
                news_data = enrich_symbol(sym, api_key, news_only=True)
                enrichment[sym]["news"] = news_data.get("news")
                enrichment[sym]["fetched_at"] = news_data["fetched_at"]
            else:
                enrichment[sym] = enrich_symbol(sym, api_key, news_only=news_only)
            
            logger.info(f"Enriched {i+1}/{total}: {sym}")
        except Exception as e:
            logger.warning(f"Failed to enrich {sym}: {e}")
        
        # Incremental save after each batch
        if (i + 1) % BATCH_SIZE == 0 or (i + 1) == total:
            save_enrichment(enrichment)
            gc.collect()  # prevent memory accumulation
            if (i + 1) < total:
                logger.info(f"Batch checkpoint ({i+1}/{total}), pausing {BATCH_SAVE_DELAY}s")
                time.sleep(BATCH_SAVE_DELAY)
    
    return enrichment


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    
    news_only = "--news-only" in sys.argv
    force = "--force" in sys.argv
    
    # Parse --batch N-M
    batch_range = None
    for arg in sys.argv:
        if arg.startswith("--batch="):
            parts = arg.split("=")[1].split("-")
            batch_range = (int(parts[0]), int(parts[1]))
    
    api_key = load_finnhub_key()
    if not api_key:
        logger.error("No Finnhub API key found")
        return 1
    
    universe = load_universe()
    if not universe:
        logger.error("No universe loaded")
        return 1
    
    logger.info(f"Universe: {len(universe)} symbols")
    enriched = enrich_universe_batched(universe, api_key, news_only=news_only, force=force, batch_range=batch_range)
    save_enrichment(enriched)

    # Copy to web root for frontend access
    import shutil
    web_path = "/var/www/hedge-fund-website/signal_enrichment.json"
    try:
        shutil.copy2(str(ENRICHMENT_FILE), web_path)
        os.chown(web_path, 1000, 1000)  # stonkai:stonkai
        logger.info("Copied enrichment to web root")
    except Exception as e:
        logger.warning(f"Failed to copy enrichment to web root: {e}")
    logger.info(f"Done. Enriched {len(enriched)} symbols total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())