#!/usr/bin/env python3
"""Fetch Finnhub company news and score sentiment with VADER.

Writes one JSON file per ticker to OUTPUT_DIR:
  {TICKER}.json -> {
    "symbol": "TICKER",
    "timestamp": ISO,
    "tone": "bullish" | "bearish" | "neutral",
    "toneScore": float(-1..1),
    "mentionCount24h": int,
    "sparkline": [float],  # last 7 daily avg scores
    "headlines": [...],
    "dataSource": "Finnhub News + VADER"
  }
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
SECRETS_DIR = Path.home() / ".openclaw" / "workspace" / ".secrets"
API_KEY_PATH = SECRETS_DIR / "finnhub.key"

# Tickers currently shown in the watchlist popup
WATCHLIST_TICKERS = [
    "COIN", "NET", "PATH", "SHOP", "SQ", "NIO", "GM", "ORCL",
    "AAPL", "TSLA", "NVDA", "META", "GOOGL", "TWLO", "ASAN",
]

# Where to write sentiment JSON files
OUTPUT_DIR = Path(os.environ.get("SENTIMENT_OUTPUT_DIR", BASE_DIR / "website" / "sentiment"))

# Finnhub free tier: 60 calls/minute. Sleep between calls to be polite.
SLEEP_SECONDS = 1.2

DAYS_BACK = 7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    if not API_KEY_PATH.exists():
        raise FileNotFoundError(f"Finnhub API key not found at {API_KEY_PATH}")
    return API_KEY_PATH.read_text().strip()


def finnhub_news(symbol: str, api_key: str, from_date: str, to_date: str):
    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": symbol,
        "from": from_date,
        "to": to_date,
        "token": api_key,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)}h ago"
    return f"{delta.days}d ago"


def build_sentiment(symbol: str, articles: list, analyzer: SentimentIntensityAnalyzer):
    if not articles:
        return None

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    scored = []
    for art in articles:
        title = (art.get("headline") or "").strip()
        if not title:
            continue
        source = art.get("source", "Finnhub")
        url = art.get("url", "#")
        ts_epoch = art.get("datetime")
        if not ts_epoch:
            continue
        art_dt = datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc)
        vs = analyzer.polarity_scores(title)
        compound = vs["compound"]
        scored.append({
            "title": title,
            "source": source,
            "url": url,
            "sentiment": round(compound, 3),
            "published": art_dt.isoformat(),
            "publishedRelative": relative_time(art_dt),
        })

    # 24h mention count
    mention_count_24h = sum(1 for s in scored if datetime.fromisoformat(s["published"]) >= cutoff_24h)

    # Overall tone from average of all scored articles in window
    avg_score = sum(s["sentiment"] for s in scored) / len(scored)

    if avg_score >= 0.05:
        tone = "bullish"
    elif avg_score <= -0.05:
        tone = "bearish"
    else:
        tone = "neutral"

    # 7-day sparkline: daily average sentiment
    daily_buckets = {}
    for s in scored:
        day = datetime.fromisoformat(s["published"]).date().isoformat()
        daily_buckets.setdefault(day, []).append(s["sentiment"])

    last_7_days = [(now.date() - timedelta(days=i)).isoformat() for i in range(DAYS_BACK - 1, -1, -1)]
    sparkline = [round(sum(daily_buckets.get(d, [0.0])) / len(daily_buckets.get(d, [1])), 3) for d in last_7_days]

    # Top 3 most recent headlines
    top_headlines = sorted(scored, key=lambda x: x["published"], reverse=True)[:3]

    return {
        "symbol": symbol,
        "timestamp": now.isoformat(),
        "tone": tone,
        "toneScore": round(avg_score, 3),
        "mentionCount24h": mention_count_24h,
        "sparkline": sparkline,
        "headlines": top_headlines,
        "dataSource": "Finnhub News + VADER",
    }


def write_json(symbol: str, payload: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{symbol}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api_key = load_api_key()
    analyzer = SentimentIntensityAnalyzer()

    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=DAYS_BACK)

    failed = []
    for symbol in WATCHLIST_TICKERS:
        try:
            articles = finnhub_news(symbol, api_key, str(from_date), str(to_date))
            payload = build_sentiment(symbol, articles, analyzer)
            if payload:
                write_json(symbol, payload)
            else:
                # No articles found — write a neutral fallback so the popup still loads
                fallback = {
                    "symbol": symbol,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "tone": "neutral",
                    "toneScore": 0.0,
                    "mentionCount24h": 0,
                    "sparkline": [0.0] * DAYS_BACK,
                    "headlines": [],
                    "dataSource": "Finnhub News + VADER — no recent coverage",
                }
                write_json(symbol, fallback)
                failed.append(f"{symbol}: no articles (wrote fallback)")
        except Exception as e:
            failed.append(f"{symbol}: {e}")
        time.sleep(SLEEP_SECONDS)

    if failed:
        print("\nFailures:")
        for msg in failed:
            print(f"  - {msg}")
        sys.exit(1 if len(failed) == len(WATCHLIST_TICKERS) else 0)

    print("\nAll sentiment files generated.")


if __name__ == "__main__":
    main()
