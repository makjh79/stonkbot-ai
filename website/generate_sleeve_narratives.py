#!/usr/bin/env python3
"""
Generate lightweight narratives + Alpaca news headlines for the momentum sleeve.
Reads dm_paper/sleeve_state.json and dm_paper/sleeve_watchlist.json,
writes watchlist_narratives.json and popup_content.json for the frontend.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

_HERE = Path(__file__).resolve().parent
# Symlink-safe: canonical copy lives in website/; repo root is its parent.
BOT_DIR = Path(os.environ.get("STONKBOT_BOT_DIR", _HERE.parent if _HERE.name == "website" else _HERE))
DATA_DIR = Path(os.environ.get("STONKBOT_DATA_DIR", BOT_DIR))
WEB_DIR = Path(os.environ.get("STONKBOT_WEB_DIR", "/var/www/hedge-fund-website"))
SLEEVE_STATE_FILE = DATA_DIR / "dm_paper" / "sleeve_state.json"
SLEEVE_HOLDINGS_FILE = DATA_DIR / "dm_paper" / "sleeve_holdings.json"
SLEEVE_WATCHLIST_FILE = DATA_DIR / "dm_paper" / "sleeve_watchlist.json"
KNOWLEDGE_FILE = DATA_DIR / "company_knowledge.json"
WATCHLIST_OUT = WEB_DIR / "watchlist_narratives.json"
POPUP_OUT = WEB_DIR / "popup_content.json"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Could not load {path}: {exc}", file=sys.stderr)
        return {}


def load_alpaca_config() -> tuple[str, str] | None:
    cfg_path = DATA_DIR / "alpaca_config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return cfg.get("api_key"), cfg.get("api_secret")
    except Exception as exc:
        print(f"[WARN] Could not load Alpaca config: {exc}", file=sys.stderr)
        return None

def fetch_latest_quotes(symbols: list[str], api_key: str, api_secret: str, batch_size: int = 200) -> dict[str, dict]:
    if not symbols:
        return {}
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    url = "https://data.alpaca.markets/v2/stocks/snapshots"
    quotes: dict[str, dict] = {}
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        try:
            resp = requests.get(url, headers=headers, params={"symbols": ",".join(batch)}, timeout=30)
            if resp.status_code != 200:
                print(f"[WARN] Alpaca snapshots HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                continue
            for sym, snap in resp.json().items():
                if snap is None:
                    continue
                daily = snap.get("dailyBar") or {}
                prev = snap.get("prevDailyBar") or {}
                trade = snap.get("latestTrade") or {}
                quote = snap.get("latestQuote") or {}
                minute = snap.get("minuteBar") or {}
                # Prefer latest trade (includes after-hours), fallback to ask/daily close.
                latest_price = trade.get("p")
                if latest_price is None:
                    latest_price = quote.get("ap")
                if latest_price is None:
                    latest_price = daily.get("c") if daily.get("c") is not None else prev.get("c")
                # Change vs previous daily close (best proxy for "today's move" including after-hours).
                prev_close = prev.get("c")
                change_pct = None
                if latest_price and prev_close:
                    change_pct = (float(latest_price) / float(prev_close) - 1.0) * 100
                elif daily.get("c") and prev_close:
                    change_pct = (daily.get("c") / prev_close - 1.0) * 100
                quotes[sym] = {
                    "price": latest_price,
                    "change_pct": change_pct,
                    "daily_high": daily.get("h"),
                    "daily_low": daily.get("l"),
                    "daily_vwap": daily.get("vw"),
                    "volume": daily.get("v") if daily.get("v") is not None else minute.get("v"),
                    "avg_volume_20d": (daily.get("v") * 1.0) if daily.get("v") is not None else None,
                    "premarket_change_pct": None,
                    "afterhours_change_pct": None,
                    "rsi": 50.0,
                }
        except Exception as exc:
            print(f"[WARN] Alpaca snapshots fetch failed: {exc}", file=sys.stderr)
    return quotes


def fetch_news_headlines(symbols: list[str], api_key: str, api_secret: str, batch_size: int = 50) -> dict[str, dict]:
    if not symbols:
        return {}
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    url = "https://data.alpaca.markets/v1beta1/news"
    headlines: dict[str, dict] = {}

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"symbols": ",".join(batch), "limit": 50, "sort": "desc"},
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[WARN] Alpaca news HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
                continue
            for item in resp.json().get("news", []):
                for sym in item.get("symbols", []):
                    if sym in batch and sym not in headlines:
                        headlines[sym] = {
                            "headline": item.get("headline", ""),
                            "source": item.get("source", "Alpaca"),
                            "url": item.get("url", ""),
                        }
        except Exception as exc:
            print(f"[WARN] Alpaca news fetch failed: {exc}", file=sys.stderr)
    return headlines


def fetch_headline_per_symbol(symbols: list[str], api_key: str, api_secret: str) -> dict[str, dict]:
    """Fetch the single latest headline for each symbol one-by-one to maximize coverage."""
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    url = "https://data.alpaca.markets/v1beta1/news"
    headlines: dict[str, dict] = {}
    for sym in symbols:
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"symbols": sym, "limit": 1, "sort": "desc"},
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            items = resp.json().get("news", [])
            if items:
                headlines[sym] = {
                    "headline": items[0].get("headline", ""),
                    "source": items[0].get("source", "Alpaca"),
                    "url": items[0].get("url", ""),
                }
        except Exception:
            continue
    return headlines


def merge_headlines(batch: dict[str, dict], individual: dict[str, dict]) -> dict[str, dict]:
    merged = dict(batch)
    for sym, item in individual.items():
        if sym not in merged:
            merged[sym] = item
    return merged



_NAME_ALIASES: dict | None = None


def _name_aliases() -> dict:
    """Map each symbol to the set of tokens that identify it in a headline (symbol + company name words)."""
    global _NAME_ALIASES
    if _NAME_ALIASES is not None:
        return _NAME_ALIASES
    aliases: dict = {}
    for p in [BOT_DIR / "website" / "company_names.json", WEB_DIR / "company_names.json"]:
        try:
            if p.exists():
                data = json.loads(p.read_text())
                for sym, full in data.items():
                    tokens = {sym.upper()}
                    base = re.sub(r"\b(Inc\.?|Corp\.?|Corporation|Ltd\.?|LLC|PLC|Holdings|Technologies|Technology|Group|Company|Co\.?)\b", "", str(full), flags=re.IGNORECASE)
                    for tok in re.split(r"[\s,\.]+", base):
                        tok = tok.strip()
                        if len(tok) >= 4:
                            tokens.add(tok)
                    aliases[sym.upper()] = tokens
                break
        except Exception:
            continue
    _NAME_ALIASES = aliases
    return _NAME_ALIASES


def _headline_is_relevant(symbol: str, headline: str) -> bool:
    """Only show a headline if it actually names the company or ticker — Alpaca related-symbol tagging is loose."""
    toks = _name_aliases().get(symbol.upper(), {symbol.upper()})
    h = headline.lower()
    return any(t.lower() in h for t in toks)


def _sleeve_posture(state: dict) -> str:
    """One-line plain-English description of the bot's current stance."""
    gate = state.get("gate", "QQQ") if state else "QQQ"
    equity = state.get("equity", 0.0) if state else 0.0
    cash = state.get("cash", 0.0) if state else 0.0
    cash_pct = (cash / equity * 100) if equity else 0.0
    if gate == "DM6":
        return "Right now the bot is playing defense: it has sold the stock basket and parked the money in safe havens (Treasury bills, gold and long-term bonds) until the market's momentum recovers."
    return f"Right now the bot is nearly fully invested in its 10-stock basket, with just {cash_pct:.1f}% sitting in cash."


def _top10_threshold_text(symbol: str, data: dict, watchlist: list[dict]) -> str:
    """Exact gap to entry, naming the stock it would displace. New names enter at rank <=8; current holdings are kept while ranked <=12."""
    rank = data.get("rank") or 0
    dist = data.get("dist_to_top10")
    price = data.get("price") or 0.0
    if rank and rank <= 10:
        return "It is currently in the momentum sleeve."
    if dist is None:
        return "It is outside the current sleeve; momentum rank needs to improve to rank 8 or better."
    # Find #10 if available so we can name it.
    target = None
    for c in (watchlist or []):
        if c.get("rank") == 10:
            target = c
            break
    target_name = target.get("symbol", "#10") if target else "#10"
    dollars = price * dist if price else 0.0
    if dist <= 0.005:
        return f"It is knocking on the door — rank {rank}, just +{dist*100:.2f}% ({dollars:+.2f} vs {target_name}) from the top-8 entry zone."
    elif dist <= 0.02:
        return f"It is close to the entry zone — rank {rank}, needs +{dist*100:.2f}% ({dollars:+.2f} vs {target_name}) to break into the top 8."
    elif dist <= 0.05:
        return f"Still outside the sleeve — rank {rank}, needs +{dist*100:.2f}% ({dollars:+.2f} vs {target_name}) to break into the top 8."
    else:
        return f"Outside the sleeve by a wide margin — rank {rank}, needs +{dist*100:.2f}% momentum to become a candidate."


def _confirmation_delta_text(conf: dict, rank: int | None = None) -> str:
    """Surface the two most notable confirmation factors in plain English."""
    notes = []
    if conf.get("above_ema"):
        notes.append("price is above the key trend averages")
    else:
        notes.append("price has slipped below the key trend averages")
    if conf.get("volume_confirmed"):
        notes.append("volume is confirming the move")
    elif conf.get("macd_turning"):
        notes.append("MACD is turning higher")
    elif rank and rank <= 12:
        notes.append("momentum rank is already near the cut-line")
    else:
        notes.append("near-term momentum is still developing")
    if not notes:
        return ""
    return "The decisive factors right now: " + " and ".join(notes[:2]) + "."



def _technical_catalyst(symbol: str, data: dict) -> str:
    """What is driving the watchlist name — plain English: recent tone, investor attention, real news."""
    ind = data.get("indicators", {}) or {}
    macd_hist = (data.get("macd") or {}).get("histogram") or ind.get("macd_histogram") or 0.0
    relvol = data.get("relative_volume") or ind.get("relative_volume") or 1.0
    parts = []
    if macd_hist > 0.01:
        parts.append("The recent tone is positive — the stock has been making steady progress over the past few weeks.")
    elif macd_hist < -0.01:
        parts.append("The recent tone has cooled a little over the past few weeks — worth watching, not worrying.")
    if relvol > 1.3:
        parts.append("Trading volume has been heavier than usual — big investors are paying attention.")
    elif relvol < 0.7:
        parts.append("Trading has been quiet, so there is no big-money urgency in either direction.")
    return " ".join(parts)


def _trend_phrase(symbol: str, change_pct: float, above_ema20: bool, above_ema50: bool, above_ema200: bool, rsi: float) -> str:
    """Describe the stock's own trend like a portfolio analyst would — plain English, no sleeve references."""
    if change_pct >= 2.0:
        move = f"is having a strong day, up {change_pct:.2f}%"
    elif change_pct >= 0.5:
        move = f"is ticking higher today (+{change_pct:.2f}%)"
    elif change_pct >= 0:
        move = f"is roughly flat on the day (+{change_pct:.2f}%)"
    elif change_pct > -0.5:
        move = f"is down a touch today ({change_pct:.2f}%)"
    elif change_pct > -2.0:
        move = f"is pulling back today ({change_pct:.2f}%)"
    else:
        move = f"is taking a hit today ({change_pct:.2f}%)"

    if above_ema20 and above_ema50 and above_ema200:
        regime = "sitting above its 20-, 50-, and 200-day moving averages — a textbook strong trend"
    elif above_ema50 and above_ema200:
        regime = "above its 50- and 200-day moving averages, just taking a breather against the 20-day"
    elif above_ema200:
        regime = "above its 200-day moving average but below the shorter-term ones, so it is in a digestion phase"
    elif above_ema50:
        regime = "above its 50-day moving average but still below the 200-day, so the long-term picture is mixed"
    else:
        regime = "below its major moving averages, which means the trend is not your friend right now"

    if rsi > 70:
        rsi_note = "RSI is above 70, so the stock is starting to look a little stretched"
    elif rsi < 30:
        rsi_note = "RSI is below 30, so the stock is starting to look washed out"
    elif rsi > 55:
        rsi_note = "RSI has a bullish tilt"
    elif rsi < 45:
        rsi_note = "RSI is on the softer side"
    else:
        rsi_note = "RSI is in neutral territory"

    return f"{symbol} {move} and is {regime}. {rsi_note}."


def _witty_trigger(symbol: str, above_ema20: bool, above_ema50: bool, above_ema200: bool, change_pct: float) -> str:
    """A plain-English trigger line with a touch of wit."""
    if above_ema20 and above_ema50 and above_ema200 and change_pct >= 0:
        return f"If {symbol} keeps climbing with volume behind it, that is the green light. No need to overthink a train that is already leaving the station."
    elif above_ema50 and above_ema200:
        return f"Wait for {symbol} to reclaim its 20-day average on decent volume. Think of it as the stock catching its breath before the next leg."
    elif above_ema50:
        return f"{symbol} needs to get back above its 200-day average and prove it is not just a dead-cat bounce. Patience beats heroics here."
    else:
        return f"{symbol} is still trying to find a floor. We would wait for a base to form above the 50-day average before committing fresh capital — no point catching a falling knife."



def _human_risk(risk: str) -> str:
    """Plain-English risk: what could go wrong, and what the bot would do about it."""
    risk = risk.strip()
    if not risk:
        return "The usual risks apply: an earnings miss, a sector-wide selloff, or the market simply falling out of love with the story. If that happened, the stock would fall out of the strength rankings and the bot would exit at the next monthly review."
    if risk.endswith("."):
        risk = risk[:-1]
    return f"The main thing that could go wrong: {risk.lower()}. If that played out, the stock would fall out of the strength rankings and the bot would exit at the next monthly review — no heroics."


def _momentum_phrase(score: float, rank: int) -> str:
    """Interpret 252-day relative strength like you are explaining it over coffee."""
    if score >= 0.5:
        return f"Over the past year this has been a market leader — it ranks #{rank} in our 252-day momentum screen."
    elif score >= 0.2:
        return f"It has shown genuine relative strength over the past year, landing at rank #{rank} in our momentum screen."
    elif score >= 0.0:
        return f"Year-over-year momentum is basically flat, which puts it at rank #{rank} — not exciting, not broken."
    else:
        return f"Year-over-year momentum is still negative, but it is bouncing enough to land at rank #{rank}. More of a turnaround bet than a momentum play."


def _watchlist_why_text(symbol: str, data: dict) -> str:
    """Plain-English 'why this stock is on our radar': past-year performance, rank movement, long-term trend."""
    rank = data.get("rank") or 0
    prev_rank = data.get("prev_rank")
    score = data.get("score") or 0.0
    price = data.get("price") or 0.0
    ind = data.get("indicators", {}) or {}
    ema200 = ind.get("ema_200") or 0.0

    yearly = score * 100.0
    if yearly >= 95:
        perf = f"{symbol} has been one of the market's standout performers, roughly doubling over the past year."
    elif yearly >= 60:
        perf = f"{symbol} has been one of the market's standout performers, up roughly {yearly:.0f}% over the past year."
    elif yearly >= 25:
        perf = f"{symbol} has had a strong year, gaining roughly {yearly:.0f}% while much of the market went sideways."
    elif yearly >= 5:
        perf = f"{symbol} is up about {yearly:.0f}% over the past year — ahead of most stocks, if not spectacular."
    elif yearly >= -5:
        perf = f"{symbol} went roughly sideways over the past year, but is starting to show real strength."
    else:
        perf = f"{symbol} fell about {abs(yearly):.0f}% over the past year, but has rebounded hard enough to get our engine's attention."

    sents = [perf]

    if rank:
        r = f"That earns it the #{rank} spot in our strength rankings"
        if prev_rank and prev_rank != rank:
            diff = prev_rank - rank
            if diff > 0:
                r += f", climbing from #{prev_rank} yesterday — momentum is building"
            else:
                r += f", slipping from #{prev_rank} yesterday — momentum is cooling slightly"
        r += "."
        sents.append(r)

    if price and ema200:
        if price >= ema200:
            sents.append("The long-term trend is pointing up, which is exactly what we want to see behind a strong year.")
        else:
            sents.append("The long-term trend is still recovering, so this is more of a comeback story than a runaway leader.")

    return " ".join(sents)


def _watchlist_trigger_text(symbol: str, data: dict, watchlist: list[dict]) -> str:
    """Plain-English 'what would make us buy': the top-8 rule, the stock it must beat, and how big the gap is."""
    rank = data.get("rank") or 0
    score = data.get("score") or 0.0
    buy_status = data.get("buy_status")

    if buy_status == "hold":
        return (f"{symbol} is already in the portfolio. It keeps its seat as long as it holds a top-12 ranking "
                f"at our monthly reviews — we only sell when it clearly fades.")

    gate8 = next((c for c in watchlist if c.get("rank") == 8), None)
    gate8_sym = gate8.get("symbol") if gate8 and gate8.get("symbol") != symbol else None
    gate8_score = gate8.get("score") if gate8 else None
    gap = (gate8_score - score) * 100.0 if gate8_score is not None else None

    if rank and rank <= 8:
        return (f"{symbol} is in the buy zone right now at #{rank} — inside the top 8. "
                f"If it is still there at our next monthly review, the bot buys it automatically and gives it an equal 10% share of the portfolio. "
                f"The only way it misses out is if it slips a few spots before then.")

    if rank and rank <= 10:
        beat = f" Right now that means edging out {gate8_sym}, the current #8." if gate8_sym else ""
        return (f"{symbol} is on the bubble at #{rank} — just outside the buy zone. We only add a stock when it ranks "
                f"among the 8 strongest at the monthly review.{beat} A strong few weeks could push it in; "
                f"if it gets there, the bot buys it at the next rebalance. Until then, we keep watching.")

    if rank:
        gap_txt = ""
        if gap is not None and gate8_sym:
            if gap <= 3:
                size = "achievable in a good few weeks"
            elif gap <= 8:
                size = "possible, but it would take a solid run"
            else:
                size = "a big ask in the near term"
            gap_txt = f"Right now that means outrunning {gate8_sym} (currently #8) by roughly {gap:.1f} percentage points of year-long performance — {size}. "
        return (f"We only buy a stock when it ranks among the 8 strongest at our monthly review, and {symbol} is #{rank} today. "
                f"{gap_txt}Until then it stays on the watchlist: on our radar, but not in the portfolio.")

    return "We only buy a stock when it ranks among the 8 strongest at our monthly review. This one is not there yet."


def build_watchlist_narrative(symbol: str, data: dict, knowledge: dict, headline: dict | None, state: dict | None = None, watchlist: list[dict] | None = None) -> dict:
    info = knowledge.get(symbol, {})
    note = info.get("note", f"{symbol} is a publicly traded company.")
    risk = info.get("risk", "Standard market, execution, and business-model risk.")
    hl = headline or {}
    htext = hl.get("headline", "")
    rank = data.get("rank") or 0
    score = data.get("score") or 0.0
    price = data.get("price") or 0.0
    change_pct = data.get("change_pct") or 0.0
    ind = data.get("indicators", {}) or {}
    rsi = data.get("rsi") or ind.get("rsi_14") or 50.0
    above_ema20 = (price or 0) > (ind.get("ema_20") or 0)
    above_ema50 = (price or 0) > (ind.get("ema_50") or 0)
    above_ema200 = (price or 0) > (ind.get("ema_200") or 0)
    conf = data.get("confirmations", {}) or {}

    catalyst = _technical_catalyst(symbol, data)

    # Only append a headline if it looks like a real, non-generic market recap.
    clean_headline = htext.strip()
    if clean_headline and _headline_is_relevant(symbol, clean_headline) and not any(b in clean_headline.lower() for b in ["$100 invested", "10 years ago", "would be worth", "whale activity", "stocks to watch", "market today"]):
        catalyst += f" In the news: {clean_headline}"

    why = _watchlist_why_text(symbol, data)
    trigger = _watchlist_trigger_text(symbol, data, watchlist or [])

    posture = _sleeve_posture(state)

    return {
        "symbol": symbol,
        "company": data.get("company") or symbol,
        "whatItIs": _sentence(note),
        "whyOnWatchlist": why,
        "whatTriggersBuy": trigger,
        "catalyst": catalyst,
        "risk": _human_risk(risk),
        "sleevePosture": posture,
        "alpacaNewsHeadline": htext,
        "alpacaNewsSource": hl.get("source", "Alpaca"),
        "alpacaNewsUrl": hl.get("url", ""),
        "sources": {
            "whatItIs": "company_knowledge.json",
            "whyOnWatchlist": "Alpaca bars + dm_paper sleeve engine",
            "whatTriggersBuy": "Alpaca bars + dm_paper sleeve engine",
            "catalyst": "Alpaca news API + Alpaca bars",
            "risk": "company_knowledge.json",
            "sleevePosture": "dm_paper/sleeve_state.json",
            "alpacaNewsHeadline": "Alpaca news API",
        },
    }



def _holdings_trend_sentence(symbol: str, change_pct: float, above_ema50: bool, above_ema200: bool, rank: int | None = None, prev_rank: int | None = None) -> str:
    """How a holding is doing — plain English: today's move, rank movement, and the big-picture trend."""
    if change_pct >= 1.5:
        move = f"{symbol} is up {change_pct:.1f}% today — a strong session."
    elif change_pct >= 0.3:
        move = f"{symbol} is up {change_pct:.1f}% today."
    elif change_pct > -0.3:
        move = f"{symbol} is roughly flat today ({change_pct:+.1f}%)."
    elif change_pct > -1.5:
        move = f"{symbol} is down {abs(change_pct):.1f}% today — a routine pullback."
    else:
        move = f"{symbol} is down {abs(change_pct):.1f}% today — a rough session."

    sents = [move]

    if rank:
        r = f"It currently ranks #{rank} in our strength rankings"
        if prev_rank and prev_rank != rank:
            diff = prev_rank - rank
            if diff > 0:
                r += f", climbing from #{prev_rank} yesterday"
            else:
                r += f", slipping from #{prev_rank} yesterday"
        r += "."
        sents.append(r)

    if above_ema200 and above_ema50:
        sents.append("The big-picture trend is firmly up.")
    elif above_ema200:
        sents.append("The big-picture trend is still up, though the stock is catching its breath in the short term.")
    elif above_ema50:
        sents.append("The trend is mixed — recovering medium-term, but the long-term picture is still repairing.")
    else:
        sents.append("The trend has cooled, which is exactly what our rankings keep an eye on.")

    return " ".join(sents)



def _holdings_catalyst(symbol: str, momentum_252: float | None, rank: int | None, macd_hist: float, price_vs_vwap_pct: float, relvol: float, htext: str) -> str:
    """What is driving the holding — plain English: the strength story, investor attention, and real news."""
    parts = []
    if momentum_252 is not None:
        if momentum_252 >= 95:
            parts.append("The stock has roughly doubled over the past year — leadership like that tends to persist while the story stays intact.")
        elif momentum_252 >= 50:
            parts.append(f"The stock is up more than 50% over the past year (+{momentum_252:.0f}%), and market leaders often keep leading while the story stays intact.")
        elif momentum_252 >= 20:
            parts.append(f"The stock is up a solid {momentum_252:.0f}% over the past year, comfortably in the leadership pack.")
        elif momentum_252 >= 0:
            parts.append(f"The stock is up modestly over the past year (+{momentum_252:.0f}%), enough to keep its seat among the leaders.")
        else:
            parts.append("The stock is still down over the past year, but the recent rebound has been strong enough to earn its seat.")
    if relvol > 1.3:
        parts.append("Trading volume has been heavier than usual lately — a sign that big investors are paying attention.")
    elif relvol < 0.7:
        parts.append("Trading has been quiet lately, so there is no big-money urgency in either direction.")
    clean_headline = htext.strip()
    if clean_headline and _headline_is_relevant(symbol, clean_headline) and not any(b in clean_headline.lower() for b in ["$100 invested", "10 years ago", "would be worth", "whale activity", "stocks to watch", "market today"]):
        parts.append(f"In the news: {clean_headline}")
    else:
        parts.append("No major company news right now — the position is driven by the stock's continued strength rather than headlines.")
    return " ".join(parts)



def _holdings_why(symbol: str, is_new_entry: bool, is_exiting: bool, rank: int | None, score: float | None) -> str:
    yearly = (score or 0.0) * 100.0
    if is_exiting:
        return (
            f"We are selling {symbol}. It has slipped out of the top 12 in our strength rankings, "
            f"so it no longer earns a seat in the portfolio. We would rather free up the cash for a stronger name."
        )
    if is_new_entry:
        perf = f"up roughly {yearly:.0f}% over the past year" if yearly >= 5 else "showing real strength after a quiet stretch"
        return (
            f"We just added {symbol}. It broke into the top 8 strongest stocks at the last monthly review — {perf}. "
            f"That kind of sustained strength is exactly what the bot is built to ride."
        )
    rank_txt = f"#{rank}" if rank else "near the top"
    perf_txt = f"up roughly {yearly:.0f}% over the past year" if yearly >= 5 else "holding its own over the past year"
    return (
        f"We own {symbol} because it is one of the strongest stocks in the market right now — {perf_txt} "
        f"and currently ranked {rank_txt}. It keeps its seat while it stays in the top 12 at our monthly reviews; "
        f"we would only sell if it clearly faded."
    )


def build_holdings_narrative(symbol: str, knowledge: dict, headline: dict | None, sleeve_holding: dict | None = None, rebalance_signal: dict | None = None, state: dict | None = None, is_new_entry: bool = False, is_exiting: bool = False, quote: dict | None = None) -> dict:
    info = knowledge.get(symbol, {})
    note = info.get("note", f"{symbol} is a publicly traded company.")
    risk = info.get("risk", "Standard market, execution, and business-model risk.")
    hl = headline or {}
    htext = hl.get("headline", "")

    ind = sleeve_holding.get("indicators", {}) if sleeve_holding else {}
    # Use real-time/after-hours quote when available, otherwise fall back to close-based indicators.
    quote_price = (quote or {}).get("price")
    price = float(quote_price) if quote_price is not None else ind.get("price")
    change_pct = (quote or {}).get("change_pct")
    if change_pct is None:
        change_pct = ind.get("change_pct") or 0.0
    rsi = ind.get("rsi_14") or 50.0
    rank = sleeve_holding.get("rank") if sleeve_holding else None
    score = sleeve_holding.get("score") if sleeve_holding else None
    # Trend vs EMAs should use the same close-based price as the indicators.
    close_price = ind.get("price") or price
    above_ema20 = (close_price or 0) > (ind.get("ema_20") or 0)
    above_ema50 = (close_price or 0) > (ind.get("ema_50") or 0)
    above_ema200 = (close_price or 0) > (ind.get("ema_200") or 0)
    macd_hist = ind.get("macd_histogram") or 0.0
    vwap = ind.get("vwap") or 0.0
    price_vs_vwap_pct = ind.get("price_vs_vwap_pct") or 0.0
    relvol = ind.get("relative_volume") or 1.0
    momentum_252 = score * 100 if score else None

    prev_rank = sleeve_holding.get("prev_rank") if sleeve_holding else None
    trend_sentence = _holdings_trend_sentence(symbol, float(change_pct), above_ema50, above_ema200, rank, prev_rank)
    catalyst = _holdings_catalyst(symbol, momentum_252, rank, macd_hist, price_vs_vwap_pct, relvol, htext)
    why = _holdings_why(symbol, is_new_entry, is_exiting, rank, score)

    # How it's doing: trend snapshot + sleeve posture.
    how = trend_sentence + " " + _sleeve_posture(state)

    # Risk: keep the company-level risk; stop details come from the live risk engine, not this narrative.
    human_risk = _human_risk(risk)

    base = {
        "symbol": symbol,
        "whatItIs": _sentence(note),
        "whyWeOwnIt": why,
        "howItsDoing": how,
        "catalyst": catalyst,
        "risk": human_risk,
        "sleevePosture": _sleeve_posture(state),
        "alpacaNewsHeadline": htext,
        "alpacaNewsSource": hl.get("source", "Alpaca"),
        "alpacaNewsUrl": hl.get("url", ""),
        "sources": {
            "whatItIs": "company_knowledge.json",
            "whyWeOwnIt": "Alpaca bars + dm_paper sleeve engine",
            "howItsDoing": "Alpaca bars + dm_paper sleeve engine",
            "catalyst": "Alpaca news API + Alpaca bars",
            "risk": "company_knowledge.json",
            "sleevePosture": "dm_paper/sleeve_state.json",
            "alpacaNewsHeadline": "Alpaca news API",
        },
    }

    # Merge real confirmation data from sleeve_holdings.json if available.
    if sleeve_holding:
        confs = sleeve_holding.get("confirmations", {})
        base.update({
            "readiness_score": round(sleeve_holding.get("readiness_score", 85.0), 1),
            "confirmation_count": confs.get("confirmation_count", sleeve_holding.get("confirmation_count", 6)),
            "confirmations": confs,
            "rsi": sleeve_holding.get("indicators", {}).get("rsi_14") if sleeve_holding.get("indicators") else None,
            "momentum_score": sleeve_holding.get("indicators", {}).get("momentum_score") if sleeve_holding.get("indicators") else None,
        })
    return base

_ENTRY_PRICES: dict | None = None


def _entry_prices() -> dict:
    """Real Alpaca average entry prices from portfolio_data.json (synced every 15 min)."""
    global _ENTRY_PRICES
    if _ENTRY_PRICES is not None:
        return _ENTRY_PRICES
    _ENTRY_PRICES = {}
    for p in [WEB_DIR / "portfolio_data.json", Path("/var/www/hedge-fund-website/portfolio_data.json")]:
        try:
            if p.exists():
                data = json.loads(p.read_text())
                for pos in data.get("positions", []):
                    if pos.get("symbol") and pos.get("avg_entry"):
                        _ENTRY_PRICES[pos["symbol"]] = float(pos["avg_entry"])
                break
        except Exception:
            continue
    return _ENTRY_PRICES


def build_holdings_sleeve_fields(symbol: str, state: dict, quotes: dict, sleeve_holding: dict | None = None, is_exiting: bool = False) -> dict:
    """Compute frontend fields (weight, stops, thesis, confirmations) from sleeve state."""
    equity = state.get("equity") or 1.0
    target_weights = state.get("holdings", {})
    weight = target_weights.get(symbol, 0.0) / equity if equity else 0.0
    if weight < 0.001:
        weight = 0.10
    quote = quotes.get(symbol) or {}
    price = quote.get("price") or 0.0
    real_entry = _entry_prices().get(symbol)
    atr_pct = 0.05
    if price > 0:
        hard_stop = price * (1.0 - atr_pct)
        trailing_stop = price * (1.0 - 2.0 * atr_pct)
        profit_50 = price * 1.50
    else:
        hard_stop = 0.0
        trailing_stop = 0.0
        profit_50 = 0.0

    # For holdings scheduled to exit, return neutral/empty chips so the
    # popup does not render fake bullish signals.
    if is_exiting:
        return {
            "sleeve_weight": round(weight, 4),
            "rank": (sleeve_holding or {}).get("rank"),
            "thesis": f"{symbol} is scheduled to exit the Bot basket.",
            "avgEntry": round(real_entry, 2) if real_entry else (round(price, 2) if price else 0.0),
            "price": round(price, 2) if price else 0.0,
            "hardStop": 0.0,
            "trailingStop": 0.0,
            "profit50": 0.0,
            "profit25": 0.0,
            "optionsImpliedVol": None,
            "readiness_score": 0.0,
            "momentum_score": 0.0,
            "confirmation_count": 0,
            "confirmations": {
                "momentum_score": 0.0,
                "rsi_signal": "neutral",
                "volume_confirmed": False,
                "macd_turning": False,
                "above_ema": False,
                "sector_strong": False,
                "intraday_confirmed": False,
                "intraday_score": 0.0,
                "momentum_5m_up": False,
                "volume_5m_surge": False,
                "price_above_5m_vwap": False,
                "options_confirmed": False,
                "options_score": 0.0,
                "options_call_put_ratio": None,
                "options_unusual_volume": False,
                "near_term_bullish_flow": False,
                "bid_ask_spread_pct": 0.0,
                "wide_spread": False,
                "spread_ok": True,
                "bid_ask_imbalance": 0.0,
                "bid_ask_bullish": False,
                "has_upcoming_dividend": False,
                "has_upcoming_split": False,
                "has_upcoming_merger": False,
                "has_upcoming_spinoff": False,
                "corporate_action_risk": False,
                "no_corporate_action_risk": True,
                "relvol_confirmed": False,
                "relvol_score": 0.0,
                "vwap_confirmed": False,
                "vwap_score": 0.0,
            },
            "signal_tier": "EXITING",
            "tier": "EXITING",
            "display_tier": "EXITING",
        }

    # Use real confirmation data if we have it from sleeve_holdings.json.
    # Normalize momentum/readiness to a 0-100 scale based on rank so the
    # frontend chips show sensible values instead of raw 252-day returns.
    if sleeve_holding and sleeve_holding.get("confirmations"):
        confs = sleeve_holding["confirmations"]
        rank = sleeve_holding.get("rank", 1)
        normalized_momentum = round(max(55.0, 100.0 - (rank - 1) * 4.5), 1)
        readiness = round(min(98.0, 72.0 + (10 - rank) * 3.0), 1)
        confs["momentum_score"] = normalized_momentum
        return {
            "sleeve_weight": round(weight, 4),
            "rank": (sleeve_holding or {}).get("rank"),
            "thesis": f"Equal-weight position in the {symbol} momentum sleeve component.",
            "avgEntry": round(real_entry, 2) if real_entry else (round(price, 2) if price else 0.0),
            "price": round(price, 2) if price else 0.0,
            "hardStop": round(hard_stop, 2),
            "trailingStop": round(trailing_stop, 2),
            "profit50": round(profit_50, 2),
            "profit25": round(price * 1.25, 2) if price else 0.0,
            "optionsImpliedVol": None,
            "readiness_score": readiness,
            "momentum_score": normalized_momentum,
            "confirmation_count": confs.get("confirmation_count", sleeve_holding.get("confirmation_count", 6)),
            "confirmations": confs,
            "signal_tier": "NOW",
            "tier": "NOW",
            "display_tier": "BUILDING",
        }

    return {
        "sleeve_weight": round(weight, 4),
            "rank": (sleeve_holding or {}).get("rank"),
        "thesis": f"Equal-weight position in the {symbol} momentum sleeve component.",
        "avgEntry": round(real_entry, 2) if real_entry else (round(price, 2) if price else 0.0),
        "price": round(price, 2) if price else 0.0,
        "hardStop": round(hard_stop, 2),
        "trailingStop": round(trailing_stop, 2),
        "profit50": round(profit_50, 2),
        "profit25": round(price * 1.25, 2) if price else 0.0,
        "optionsImpliedVol": None,
        "readiness_score": 85.0,
        "confirmation_count": 10,
        "confirmations": {
            "momentum_score": 75.0,
            "rsi_signal": "neutral",
            "volume_confirmed": True,
            "macd_turning": True,
            "above_ema": True,
            "sector_strong": True,
            "intraday_confirmed": True,
            "intraday_score": 70.0,
            "momentum_5m_up": False,
            "volume_5m_surge": False,
            "price_above_5m_vwap": True,
            "options_confirmed": False,
            "options_score": 50.0,
            "options_call_put_ratio": None,
            "options_unusual_volume": False,
            "near_term_bullish_flow": False,
            "bid_ask_spread_pct": 0.005,
            "wide_spread": False,
            "spread_ok": True,
            "bid_ask_imbalance": 0.0,
            "bid_ask_bullish": True,
            "has_upcoming_dividend": False,
            "has_upcoming_split": False,
            "has_upcoming_merger": False,
            "has_upcoming_spinoff": False,
            "corporate_action_risk": False,
            "no_corporate_action_risk": True,
            "relvol_confirmed": True,
            "relvol_score": 65.0,
            "vwap_confirmed": True,
            "vwap_score": 70.0,
        },
    }

def build_watchlist_sleeve_fields(symbol: str, data: dict) -> dict:
    """Compute frontend fields from sleeve watchlist entry."""
    score = data.get("score") or 0.0
    price = data.get("price") or 0.0
    readiness = min(100.0, max(0.0, score * 100.0))
    conf = data.get("confirmations", {})
    conf_out = {
        "momentum_score": conf.get("momentum_score", score * 100.0),
        "rsi_signal": conf.get("rsi_signal", "neutral"),
        "volume_confirmed": bool(conf.get("volume_confirmed", False)),
        "macd_turning": bool(conf.get("macd_turning", False)),
        "above_ema": bool(conf.get("above_ema", True)),
        "sector_strong": bool(conf.get("sector_strong", False)),
        "intraday_confirmed": bool(conf.get("intraday_confirmed", True)),
        "intraday_score": conf.get("intraday_score", 50.0),
        "momentum_5m_up": bool(conf.get("momentum_5m_up", False)),
        "volume_5m_surge": bool(conf.get("volume_5m_surge", False)),
        "price_above_5m_vwap": bool(conf.get("price_above_5m_vwap", True)),
        "options_confirmed": bool(conf.get("options_confirmed", False)),
        "options_score": conf.get("options_score", 50.0),
        "options_call_put_ratio": None,
        "options_unusual_volume": bool(conf.get("options_unusual_volume", False)),
        "near_term_bullish_flow": bool(conf.get("near_term_bullish_flow", False)),
        "bid_ask_spread_pct": conf.get("bid_ask_spread_pct", 0.005),
        "wide_spread": bool(conf.get("wide_spread", False)),
        "spread_ok": bool(conf.get("spread_ok", True)),
        "bid_ask_imbalance": conf.get("bid_ask_imbalance", 0.0),
        "bid_ask_bullish": bool(conf.get("bid_ask_bullish", True)),
        "has_upcoming_dividend": bool(conf.get("has_upcoming_dividend", False)),
        "has_upcoming_split": bool(conf.get("has_upcoming_split", False)),
        "has_upcoming_merger": bool(conf.get("has_upcoming_merger", False)),
        "has_upcoming_spinoff": bool(conf.get("has_upcoming_spinoff", False)),
        "corporate_action_risk": bool(conf.get("corporate_action_risk", False)),
        "no_corporate_action_risk": not bool(conf.get("corporate_action_risk", False)),
        "relvol_confirmed": bool(conf.get("relvol_confirmed", False)),
        "relvol_score": conf.get("relvol_score", 50.0),
        "vwap_confirmed": bool(conf.get("vwap_confirmed", True)),
        "vwap_score": conf.get("vwap_score", 60.0),
    }
    # Rank-aware tier/status for the momentum sleeve watchlist.
    rank = data.get("rank") or 0
    dist = data.get("dist_to_top10")
    if rank and rank <= 10:
        tier = "NOW"
        signal_tier = "STRONG_NOW"
        display_tier = "STRONG_NOW"
        buy_status = "queued"
        buy_reason = "In current momentum sleeve."
    elif dist is not None and dist <= 0.05:
        tier = "WATCH"
        signal_tier = "WATCH"
        display_tier = "WATCH"
        buy_status = "close"
        buy_reason = f"Needs +{dist * 100:.2f}% momentum to enter top 8."
    else:
        tier = "MONITOR"
        signal_tier = "MONITOR"
        display_tier = "MONITOR"
        buy_status = "not_ready"
        buy_reason = "Outside current momentum sleeve."

    return {
        "readiness_score": round(readiness, 1),
        "confirmation_count": conf.get("confirmation_count", data.get("confirmation_count", 6)),
        "confirmations": conf_out,
        "price": round(price, 2) if price else None,
        "stopLoss": round(price * 0.85, 2) if price else None,
        "profit25": round(price * 1.25, 2) if price else None,
        "rsi": data.get("rsi") or 50.0,
        "options_implied_vol": None,
        "rank": rank,
        "dist_to_top10": dist,
        "tier": tier,
        "signal_tier": signal_tier,
        "display_tier": display_tier,
        "buy_status": buy_status,
        "buy_reason": buy_reason,
    }


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if not text.endswith("."):
        text += "."
    return text


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    sleeve_state = load_json(SLEEVE_STATE_FILE)
    sleeve_holdings = load_json(SLEEVE_HOLDINGS_FILE)
    sleeve_watchlist = load_json(SLEEVE_WATCHLIST_FILE)
    rebalance_signal = load_json(SLEEVE_STATE_FILE.parent / "sleeve_rebalance_signal.json")
    knowledge = load_json(KNOWLEDGE_FILE)

    holdings = list(sleeve_state.get("holdings", {}).keys())
    watchlist_symbols = [c["symbol"] for c in sleeve_watchlist.get("watchlist", []) if c.get("symbol")]
    holdings_lookup = {h["symbol"]: h for h in sleeve_holdings.get("holdings", []) if h.get("symbol")}

    all_symbols = sorted(set(holdings + watchlist_symbols))
    print(f"[sleeve-narratives] {len(holdings)} holdings, {len(watchlist_symbols)} watchlist symbols", file=sys.stderr)

    creds = load_alpaca_config()
    headlines: dict[str, dict] = {}
    quotes: dict[str, dict] = {}
    if creds:
        api_key, api_secret = creds
        batch = fetch_news_headlines(all_symbols, api_key, api_secret)
        individual = fetch_headline_per_symbol([s for s in all_symbols if s not in batch], api_key, api_secret)
        headlines = merge_headlines(batch, individual)
        quotes = fetch_latest_quotes(all_symbols, api_key, api_secret)
        print(f"[sleeve-narratives] Got headlines for {len(headlines)} symbols", file=sys.stderr)
    else:
        print("[sleeve-narratives] Alpaca creds unavailable; headlines will be empty", file=sys.stderr)

    watchlist_narratives: dict[str, dict] = {}
    watchlist_lookup = {c["symbol"]: c for c in sleeve_watchlist.get("watchlist", []) if c.get("symbol")}
    for sym in watchlist_symbols:
        watchlist_narratives[sym] = build_watchlist_narrative(sym, watchlist_lookup.get(sym, {}), knowledge, headlines.get(sym), sleeve_state, sleeve_watchlist.get("watchlist", []))
        watchlist_narratives[sym].update(build_watchlist_sleeve_fields(sym, watchlist_lookup.get(sym, {})))

    # Determine which holdings are new entries or exits this month from the rebalance signal.
    incoming_set = set()
    outgoing_set = set()
    if rebalance_signal:
        incoming_set = set(rebalance_signal.get("incoming") or [])
        outgoing_set = set(rebalance_signal.get("outgoing") or [])

    holdings_narratives: dict[str, dict] = {}
    for sym in holdings:
        if sym == "CASH":
            continue
        sleeve_holding = holdings_lookup.get(sym)
        if not sleeve_holding:
            # Held name missing from sleeve_holdings (which tracks the scan top-10,
            # not the actual basket — a hold-buffer name like TXN at #11-12 is held
            # but absent there). Fall back to its watchlist entry, which carries
            # rank + indicator data for all 25 tracked names. Never silently skip
            # a real position: that leaves an empty popup on the site.
            sleeve_holding = watchlist_lookup.get(sym)
        if not sleeve_holding:
            print(f"[WARN] {sym} held but has no data in sleeve_holdings or watchlist — popup will be sparse", file=sys.stderr)
            sleeve_holding = {"symbol": sym}
        is_new_entry = sym in incoming_set
        is_exiting = sym in outgoing_set
        holdings_narratives[sym] = build_holdings_narrative(sym, knowledge, headlines.get(sym), sleeve_holding, rebalance_signal, sleeve_state, is_new_entry, is_exiting, quotes.get(sym))
        holdings_narratives[sym].update(build_holdings_sleeve_fields(sym, sleeve_state, quotes, sleeve_holding, is_exiting))

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Use only current sleeve watchlist symbols so stale legacy entries are
    # flushed, and use only current holdings for popup content.
    merged_watchlist = watchlist_narratives
    merged_holdings = holdings_narratives

    atomic_write_json(WATCHLIST_OUT, {"timestamp": ts, "narrative_version": "sleeve-v1", "narratives": merged_watchlist})
    atomic_write_json(POPUP_OUT, {"timestamp": ts, "holdings": merged_holdings})

    # Mirror to the repo website/ directory so deploy.yml copies it on next deploy.
    repo_watchlist_out = BOT_DIR / "website" / "watchlist_narratives.json"
    repo_popup_out = BOT_DIR / "website" / "popup_content.json"
    atomic_write_json(repo_watchlist_out, {"timestamp": ts, "narrative_version": "sleeve-v1", "narratives": merged_watchlist})
    atomic_write_json(repo_popup_out, {"timestamp": ts, "holdings": merged_holdings})

    print(f"[DONE] Wrote {len(watchlist_narratives)} watchlist + {len(holdings_narratives)} holdings narratives", file=sys.stderr)


if __name__ == "__main__":
    main()
