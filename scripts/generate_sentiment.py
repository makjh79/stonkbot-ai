#!/usr/bin/env python3
"""Fetch company news from multiple sources and score sentiment.

Sources: Finnhub News + Alpaca News API.
Zero external dependencies beyond Python stdlib + requests.
Outputs match the frontend contract used by loadStockSentiment().
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRETS_DIR = Path("/root/.openclaw/workspace/.secrets")
FINNHUB_KEY_PATH = SECRETS_DIR / "finnhub.key"
ALPACA_CONFIG_PATH = Path("/opt/stonk-ai/alpaca_config.json")

WATCHLIST_TICKERS = [
    "COIN", "NET", "PATH", "SHOP", "SQ", "NIO", "GM", "ORCL",
    "AAPL", "TSLA", "NVDA", "META", "GOOGL", "TWLO", "ASAN",
]

OUTPUT_DIR = Path(os.environ.get("SENTIMENT_OUTPUT_DIR", "/var/www/hedge-fund-website/sentiment"))
SLEEP_SECONDS = 1.2
DAYS_BACK = 7

# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def load_finnhub_key() -> str:
    if not FINNHUB_KEY_PATH.exists():
        raise FileNotFoundError(f"Finnhub API key not found at {FINNHUB_KEY_PATH}")
    return FINNHUB_KEY_PATH.read_text().strip()


def load_alpaca_config() -> dict:
    if not ALPACA_CONFIG_PATH.exists():
        return {}
    with open(ALPACA_CONFIG_PATH, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# News fetchers
# ---------------------------------------------------------------------------

def finnhub_news(symbol: str, api_key: str, from_date: str, to_date: str):
    url = "https://finnhub.io/api/v1/company-news"
    params = {"symbol": symbol, "from": from_date, "to": to_date, "token": api_key}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    out = []
    for art in data:
        ts = art.get("datetime")
        if not ts:
            continue
        out.append({
            "headline": art.get("headline", ""),
            "source": art.get("source", "Finnhub"),
            "url": art.get("url", ""),
            "datetime": int(ts),
        })
    return out


def alpaca_news(symbol: str, config: dict, from_date: str, to_date: str):
    """Fetch news from Alpaca News API."""
    key_id = config.get("api_key")
    secret = config.get("api_secret")
    if not key_id or not secret:
        return []
    url = (
        f"https://data.alpaca.markets/v1beta1/news"
        f"?symbols={symbol}"
        f"&start={from_date}T00:00:00Z"
        f"&end={to_date}T23:59:59Z"
        f"&limit=50"
    )
    headers = {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret,
        "accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        out = []
        for art in data.get("news", []):
            ts = art.get("created_at")
            if not ts:
                continue
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            out.append({
                "headline": art.get("headline", ""),
                "source": art.get("source", "Alpaca"),
                "url": art.get("url", ""),
                "datetime": int(dt.timestamp()),
            })
        return out
    except Exception as e:
        print(f"  Alpaca news error for {symbol}: {e}")
        return []


def merge_articles(articles_list):
    """Merge articles from multiple sources, dedupe by headline (case-insensitive)."""
    seen = set()
    merged = []
    for articles in articles_list:
        for art in articles:
            title = (art.get("headline") or "").strip()
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(art)
    return merged


# ---------------------------------------------------------------------------
# Lightweight sentiment lexicon (AFINN-style, no external deps)
# ---------------------------------------------------------------------------
POSITIVE = {
    "surge", "rally", "soar", "jump", "gain", "gains", "rise", "rises", "rising",
    "bull", "bullish", "outperform", "beat", "beats", "strong", "strength", "growth",
    "profit", "profits", "buy", "upgrade", "upgraded", "upgrade", "positive", "momentum",
    "breakthrough", "record", "high", "highs", "rallying", "surging", "boom", "booming",
    "exceeds", "exceeded", "upside", "opportunity", "opportunities", "success", "successful",
    "launch", "launches", "partnership", "deal", "deals", "expansion", "expanding",
    "adoption", "adopt", "adopts", "integrates", "integration", "approves", "approval",
    "dividend", "dividends", "raise", "raises", "boost", "boosts", "rebound", "rebounds",
    "recover", "recovery", "recovering", "promise", "promising", "confident", "optimistic",
    "target", "targets", "excellent", "outstanding", "robust", "solid", "healthy",
}

NEGATIVE = {
    "fall", "falls", "falling", "drop", "drops", "dropping", "decline", "declines",
    "declining", "plunge", "plunges", "plunging", "crash", "crashes", "crashing",
    "bear", "bearish", "underperform", "miss", "misses", "missed", "weak", "weakness",
    "loss", "losses", "lose", "losing", "sell", "downgrade", "downgraded", "negative",
    "risk", "risks", "risky", "concern", "concerns", "worried", "worry", "fear",
    "fears", "threat", "threats", "warn", "warns", "warning", "cut", "cuts",
    "layoff", "layoffs", "firing", "fire", "fraud", "lawsuit", "litigation", "investigation",
    "probe", "penalty", "fine", "fines", "ban", "banned", "restrict", "restricts",
    "delay", "delays", "postpone", "postponed", "halt", "halts", "suspend", "suspends",
    "recall", "recalls", "deficit", "debt", "bankrupt", "bankruptcy", "default",
    "inflation", "recession", "downturn", "slump", "slumps", "tumble", "tumbles",
    "volatile", "volatility", "uncertain", "uncertainty", "crisis", "trouble",
    "struggle", "struggles", " disappointing", "disappoint", "disappointed", "poor",
    "collapse", "collapses", "collapsing", "plummet", "plummets", "sink", "sinks",
    "slide", "slides", "sliding", "tank", "tanks", "tanking", "pullback", "correction",
}

BOOSTERS = {"very", "extremely", "remarkably", "significantly", "substantially", "sharply", "strongly"}
DAMPENERS = {"slightly", "somewhat", "marginally", "a bit", "barely", "hardly"}
NEGATORS = {"not", "no", "never", "neither", "nor", "without", "lack", "lacks", "absence", "failed", "fails"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)}h ago"
    return f"{delta.days}d ago"


def score_text(text: str) -> float:
    """Return compound-ish sentiment score in [-1, 1]."""
    words = [w.strip(".,!?;:'\"()[]{}-—") for w in text.lower().split()]
    score = 0.0
    i = 0
    while i < len(words):
        word = words[i]
        val = 0.0
        if word in POSITIVE:
            val = 0.35
        elif word in NEGATIVE:
            val = -0.35
        elif word in NEGATORS and i + 1 < len(words) and words[i + 1] in POSITIVE:
            val = -0.25
            i += 1
        elif word in NEGATORS and i + 1 < len(words) and words[i + 1] in NEGATIVE:
            val = 0.25
            i += 1

        # look back one word for boosters/dampeners/negators
        if val != 0.0 and i > 0:
            prev = words[i - 1]
            if prev in BOOSTERS:
                val *= 1.5
            elif prev in DAMPENERS:
                val *= 0.5
            elif prev in NEGATORS:
                val *= -0.8
        score += val
        i += 1

    # Normalize to roughly [-1, 1]
    return max(-1.0, min(1.0, score))


def build_sentiment(symbol: str, articles: list):
    if not articles:
        return None

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    scored = []
    for art in articles:
        title = (art.get("headline") or "").strip()
        if not title:
            continue
        source = art.get("source", "News")
        url = art.get("url", "#")
        ts_epoch = art.get("datetime")
        if not ts_epoch:
            continue
        art_dt = datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc)
        compound = score_text(title)
        scored.append({
            "title": title,
            "source": source,
            "url": url,
            "sentiment": round(compound, 3),
            "published": art_dt.isoformat(),
            "publishedRelative": relative_time(art_dt),
        })

    mention_count_24h = sum(1 for s in scored if datetime.fromisoformat(s["published"]) >= cutoff_24h)
    avg_score = sum(s["sentiment"] for s in scored) / len(scored)

    if avg_score >= 0.05:
        tone = "bullish"
    elif avg_score <= -0.05:
        tone = "bearish"
    else:
        tone = "neutral"

    daily_buckets = {}
    for s in scored:
        day = datetime.fromisoformat(s["published"]).date().isoformat()
        daily_buckets.setdefault(day, []).append(s["sentiment"])

    last_7_days = [(now.date() - timedelta(days=i)).isoformat() for i in range(DAYS_BACK - 1, -1, -1)]
    sparkline = [round(sum(daily_buckets.get(d, [0.0])) / len(daily_buckets.get(d, [1])), 3) for d in last_7_days]

    top_headlines = sorted(scored, key=lambda x: x["published"], reverse=True)[:3]

    return {
        "symbol": symbol,
        "timestamp": now.isoformat(),
        "tone": tone,
        "toneScore": round(avg_score, 3),
        "mentionCount24h": mention_count_24h,
        "sparkline": sparkline,
        "headlines": top_headlines,
        "dataSource": "Finnhub + Alpaca News",
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
    finnhub_key = load_finnhub_key()
    alpaca_config = load_alpaca_config()

    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=DAYS_BACK)

    failed = []
    for symbol in WATCHLIST_TICKERS:
        try:
            fh_articles = finnhub_news(symbol, finnhub_key, str(from_date), str(to_date))
            alp_articles = alpaca_news(symbol, alpaca_config, str(from_date), str(to_date))
            articles = merge_articles([fh_articles, alp_articles])
            payload = build_sentiment(symbol, articles)
            if payload:
                write_json(symbol, payload)
                print(f"  {symbol}: {len(articles)} articles ({len(fh_articles)} Finnhub + {len(alp_articles)} Alpaca)")
            else:
                fallback = {
                    "symbol": symbol,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "tone": "neutral",
                    "toneScore": 0.0,
                    "mentionCount24h": 0,
                    "sparkline": [0.0] * DAYS_BACK,
                    "headlines": [],
                    "dataSource": "Finnhub + Alpaca News — no recent coverage",
                }
                write_json(symbol, fallback)
                failed.append(f"{symbol}: no articles (wrote fallback)")
        except Exception as e:
            failed.append(f"{symbol}: {e}")
        time.sleep(SLEEP_SECONDS)

    if failed:
        print("\nNotices:")
        for msg in failed:
            print(f"  - {msg}")

    print("\nAll sentiment files generated.")


if __name__ == "__main__":
    main()
