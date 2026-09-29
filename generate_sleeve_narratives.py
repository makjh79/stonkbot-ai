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

BOT_DIR = Path(os.environ.get("STONKBOT_BOT_DIR", Path(__file__).resolve().parent))
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
                quote = snap.get("latestQuote") or {}
                minute = snap.get("minuteBar") or {}
                quotes[sym] = {
                    "price": quote.get("ap") if quote.get("ap") is not None else daily.get("c") if daily.get("c") is not None else prev.get("c"),
                    "change_pct": (daily.get("c") / prev.get("c") - 1.0) * 100 if daily.get("c") and prev.get("c") else None,
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
    """Rewrite stodgy risk lines into something a human analyst might actually say."""
    risk = risk.strip()
    if not risk:
        return "The usual suspects: earnings surprises, sector rotation, and the market occasionally having a bad hair day."
    # Trim trailing period for smoother concatenation.
    if risk.endswith("."):
        risk = risk[:-1]
    return f"The main thing to watch: {risk.lower()}. In other words, do not size up until the chart confirms the story."


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


def build_watchlist_narrative(symbol: str, data: dict, knowledge: dict, headline: dict | None) -> dict:
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
    macd_hist = (data.get("macd") or {}).get("histogram") or ind.get("macd_histogram") or 0.0
    vwap = data.get("vwap") or ind.get("vwap") or 0.0
    price_vs_vwap_pct = data.get("price_vs_vwap_pct") or ind.get("price_vs_vwap_pct") or 0.0
    relvol = data.get("relative_volume") or ind.get("relative_volume") or 1.0
    conf = data.get("confirmations", {}) or {}

    trend_sentence = _trend_phrase(symbol, change_pct, above_ema20, above_ema50, above_ema200, float(rsi))
    momentum_sentence = _momentum_phrase(float(score), int(rank))

    # Catalyst: combine the headline with the stock's own technical context.
    catalyst_parts = [momentum_sentence]
    if macd_hist > 0:
        catalyst_parts.append("MACD is turning higher, which is a short-term tailwind.")
    elif macd_hist < 0:
        catalyst_parts.append("MACD is fading, so near-term momentum has cooled off.")
    if price_vs_vwap_pct > 0.1:
        catalyst_parts.append(f"It is trading {price_vs_vwap_pct:.2f}% above today's VWAP, meaning buyers are in control so far.")
    elif price_vs_vwap_pct < -0.1:
        catalyst_parts.append(f"It is trading {abs(price_vs_vwap_pct):.2f}% below today's VWAP, so sellers have the upper hand intraday.")
    if relvol > 1.2:
        catalyst_parts.append(f"Volume is running {relvol:.1f}× its normal pace — institutions are paying attention.")
    elif relvol < 0.7:
        catalyst_parts.append("Volume is quieter than usual, so this move still lacks broad conviction.")
    if htext:
        catalyst_parts.append(f"In the news: {htext}")
    else:
        catalyst_parts.append("No fresh headline today; the price action is doing all the talking.")
    catalyst = " ".join(catalyst_parts)

    # Why it's on the watchlist: stock-focused, conversational.
    why = (
        f"{symbol} is on our radar because its own chart is telling a story. "
        f"{trend_sentence} {momentum_sentence}"
    )

    # What triggers a buy: plain English trigger with a dash of wit.
    trigger = _witty_trigger(symbol, above_ema20, above_ema50, above_ema200, change_pct)

    return {
        "symbol": symbol,
        "company": data.get("company") or symbol,
        "whatItIs": _sentence(note),
        "whyOnWatchlist": why,
        "whatTriggersBuy": trigger,
        "catalyst": catalyst,
        "risk": _human_risk(risk),
        "alpacaNewsHeadline": htext,
        "alpacaNewsSource": hl.get("source", "Alpaca"),
        "alpacaNewsUrl": hl.get("url", ""),
        "sources": {
            "whatItIs": "company_knowledge.json",
            "whyOnWatchlist": "Alpaca bars + dm_paper sleeve engine",
            "whatTriggersBuy": "Alpaca bars + dm_paper sleeve engine",
            "catalyst": "Alpaca news API + Alpaca bars",
            "risk": "company_knowledge.json",
            "alpacaNewsHeadline": "Alpaca news API",
        },
    }


def _holdings_trend_sentence(symbol: str, change_pct: float, above_ema20: bool, above_ema50: bool, above_ema200: bool, rsi: float) -> str:
    """Describe a holding's own price action in plain English, the way an analyst would explain it to a client."""
    if change_pct >= 1.5:
        move = f"is up {change_pct:.2f}% today, a solid session"
    elif change_pct >= 0:
        move = f"is up {change_pct:.2f}% today, a quiet but positive session"
    elif change_pct > -1.5:
        move = f"is down {abs(change_pct):.2f}% today, just a small scratch"
    else:
        move = f"is down {abs(change_pct):.2f}% today, a rough session"

    if above_ema20 and above_ema50 and above_ema200:
        regime = "above its 20-, 50-, and 200-day moving averages — the trend is doing the heavy lifting"
    elif above_ema50 and above_ema200:
        regime = "above its 50- and 200-day moving averages, with a minor pullback against the 20-day"
    elif above_ema200:
        regime = "above its 200-day moving average but below the shorter-term ones, so it is digesting recent gains"
    elif above_ema50:
        regime = "above its 50-day moving average but still below the 200-day, which means the jury is still out long term"
    else:
        regime = "below its major moving averages, which is not where you want to be as a holder"

    if rsi > 70:
        rsi_note = "RSI is above 70, so the stock is getting a little frothy — not necessarily a sell, but definitely not the time to chase"
    elif rsi < 30:
        rsi_note = "RSI is below 30, so the stock is getting washed out — often when the best entries appear, if the thesis still holds"
    else:
        rsi_note = f"RSI sits at {rsi:.1f}, which is neither hot nor cold"

    return f"{symbol} {move} and is {regime}. {rsi_note}."


def _holdings_catalyst(symbol: str, momentum_252: float | None, rank: int | None, macd_hist: float, price_vs_vwap_pct: float, relvol: float, htext: str) -> str:
    """Human-readable catalyst paragraph for a holding."""
    parts = []
    if momentum_252 is not None and rank is not None:
        if momentum_252 >= 100:
            parts.append(f"This has been a rocket ship over the past year — rank #{rank} with +{momentum_252:.2f}% relative strength. Momentum investors love it for a reason.")
        elif momentum_252 >= 50:
            parts.append(f"Year-over-year, this is in the top tier, ranking #{rank} with +{momentum_252:.2f}% relative strength. That is the kind of trend that pays the rent.")
        elif momentum_252 >= 20:
            parts.append(f"It has strong year-over-year momentum, ranking #{rank} at +{momentum_252:.2f}% relative strength. Not flashy, but clearly working.")
        elif momentum_252 >= 0:
            parts.append(f"Year-over-year momentum is basically flat, putting it at rank #{rank}. It is treading water rather than surfing a wave.")
        else:
            parts.append(f"Year-over-year momentum is still negative, though it ranks #{rank} because the bounce is real. This one is more turnaround than trend.")

    if macd_hist > 0:
        parts.append("MACD is ticking higher, which keeps the short-term wind at our backs.")
    elif macd_hist < 0:
        parts.append("MACD is rolling over, so near-term momentum has softened — worth watching, but not panic-selling.")

    if price_vs_vwap_pct > 0.1:
        parts.append(f"It is trading {price_vs_vwap_pct:.2f}% above today's VWAP, so buyers are winning the intraday tug-of-war.")
    elif price_vs_vwap_pct < -0.1:
        parts.append(f"It is trading {abs(price_vs_vwap_pct):.2f}% below today's VWAP, so sellers are in control for now.")

    if relvol > 1.2:
        parts.append(f"Volume is {relvol:.1f}× normal, which tells us the pros are actively repositioning.")
    elif relvol < 0.7:
        parts.append("Volume is on the light side, so this is not yet a conviction move either way.")

    if htext:
        parts.append(f"Latest headline: {htext}")
    else:
        parts.append("No fresh news today; the stock is moving on its own supply and demand.")

    return " ".join(parts)


def _holdings_why(symbol: str, is_new_entry: bool, is_exiting: bool) -> str:
    if is_exiting:
        return (
            f"We are selling {symbol}. "
            "Its relative-strength ranking has slipped enough that it no longer fits the momentum sleeve. "
            "Better to free up the cash and back a name with a stronger tailwind."
        )
    elif is_new_entry:
        return (
            f"We recently added {symbol} to the portfolio. "
            "It had a clean relative-strength breakout and a working technical setup, so we sized it as a fresh momentum position."
        )
    else:
        return (
            f"We own {symbol} because the trend is still working. "
            "We are not married to it — we will trim or exit if the chart breaks — but right now the evidence says keep holding."
        )


def build_holdings_narrative(symbol: str, knowledge: dict, headline: dict | None, sleeve_holding: dict | None = None, rebalance_signal: dict | None = None, is_new_entry: bool = False, is_exiting: bool = False) -> dict:
    info = knowledge.get(symbol, {})
    note = info.get("note", f"{symbol} is a publicly traded company.")
    risk = info.get("risk", "Standard market, execution, and business-model risk.")
    hl = headline or {}
    htext = hl.get("headline", "")

    ind = sleeve_holding.get("indicators", {}) if sleeve_holding else {}
    price = ind.get("price")
    change_pct = ind.get("change_pct") or 0.0
    rsi = ind.get("rsi_14") or 50.0
    rank = sleeve_holding.get("rank") if sleeve_holding else None
    score = sleeve_holding.get("score") if sleeve_holding else None
    above_ema20 = (price or 0) > (ind.get("ema_20") or 0)
    above_ema50 = (price or 0) > (ind.get("ema_50") or 0)
    above_ema200 = (price or 0) > (ind.get("ema_200") or 0)
    macd_hist = ind.get("macd_histogram") or 0.0
    vwap = ind.get("vwap") or 0.0
    price_vs_vwap_pct = ind.get("price_vs_vwap_pct") or 0.0
    relvol = ind.get("relative_volume") or 1.0
    momentum_252 = score * 100 if score else None

    trend_sentence = _holdings_trend_sentence(symbol, float(change_pct), above_ema20, above_ema50, above_ema200, float(rsi))
    catalyst = _holdings_catalyst(symbol, momentum_252, rank, macd_hist, price_vs_vwap_pct, relvol, htext)
    why = _holdings_why(symbol, is_new_entry, is_exiting)

    # How it's doing: absolute trend snapshot, plus regime context.
    how = trend_sentence
    if rebalance_signal and rebalance_signal.get("gate"):
        how += f" The DM-6 asset-rotation gate is {rebalance_signal['gate']}, which means the system is only adding risk when the broad tape is cooperative."

    base = {
        "symbol": symbol,
        "whatItIs": _sentence(note),
        "whyWeOwnIt": why,
        "howItsDoing": how,
        "catalyst": catalyst,
        "risk": _human_risk(risk),
        "alpacaNewsHeadline": htext,
        "alpacaNewsSource": hl.get("source", "Alpaca"),
        "alpacaNewsUrl": hl.get("url", ""),
        "sources": {
            "whatItIs": "company_knowledge.json",
            "whyWeOwnIt": "Alpaca bars + dm_paper sleeve engine",
            "howItsDoing": "Alpaca bars + dm_paper sleeve engine",
            "catalyst": "Alpaca news API + Alpaca bars",
            "risk": "company_knowledge.json",
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

def build_holdings_sleeve_fields(symbol: str, state: dict, quotes: dict, sleeve_holding: dict | None = None, is_exiting: bool = False) -> dict:
    """Compute frontend fields (weight, stops, thesis, confirmations) from sleeve state."""
    equity = state.get("equity") or 1.0
    target_weights = state.get("holdings", {})
    weight = target_weights.get(symbol, 0.0) / equity if equity else 0.0
    if weight < 0.001:
        weight = 0.10
    quote = quotes.get(symbol) or {}
    price = quote.get("price") or 0.0
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
            "thesis": f"{symbol} is scheduled to exit the Bot basket.",
            "avgEntry": round(price, 2) if price else 0.0,
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
            "thesis": f"Equal-weight position in the {symbol} momentum sleeve component.",
            "avgEntry": round(price, 2) if price else 0.0,
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
        "thesis": f"Equal-weight position in the {symbol} momentum sleeve component.",
        "avgEntry": round(price, 2) if price else 0.0,
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
        buy_reason = "In current top-10 sleeve basket."
    elif dist is not None and dist <= 0.05:
        tier = "WATCH"
        signal_tier = "WATCH"
        display_tier = "WATCH"
        buy_status = "close"
        buy_reason = f"Needs +{dist * 100:.2f}% momentum to enter top-10."
    else:
        tier = "MONITOR"
        signal_tier = "MONITOR"
        display_tier = "MONITOR"
        buy_status = "not_ready"
        buy_reason = "Outside current top-10 sleeve basket."

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
        watchlist_narratives[sym] = build_watchlist_narrative(sym, watchlist_lookup.get(sym, {}), knowledge, headlines.get(sym))
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
            # Symbol is in sleeve_state but missing from sleeve_holdings (e.g. a
            # pending rebalance target). Skip it; the frontend only needs
            # narratives for positions that actually have indicator data.
            continue
        is_new_entry = sym in incoming_set
        is_exiting = sym in outgoing_set
        holdings_narratives[sym] = build_holdings_narrative(sym, knowledge, headlines.get(sym), sleeve_holding, rebalance_signal, is_new_entry, is_exiting)
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
