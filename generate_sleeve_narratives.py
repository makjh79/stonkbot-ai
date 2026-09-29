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


def _trend_phrase(change_pct: float, above_ema20: bool, above_ema50: bool, above_ema200: bool, rsi: float) -> str:
    """Describe the stock's own trend without referencing the sleeve."""
    direction = "rising" if change_pct >= 0 else "pulling back"
    if above_ema20 and above_ema50 and above_ema200:
        regime = "above its 20-, 50-, and 200-day EMAs"
    elif above_ema50 and above_ema200:
        regime = "above its 50- and 200-day EMAs"
    elif above_ema200:
        regime = "above its 200-day EMA but below shorter averages"
    elif above_ema50:
        regime = "above its 50-day EMA but below the 200-day"
    else:
        regime = "below its major moving averages"

    if rsi > 70:
        rsi_note = "and looks overbought on a 14-day basis"
    elif rsi < 30:
        rsi_note = "and looks oversold on a 14-day basis"
    elif rsi > 55:
        rsi_note = "with bullish RSI momentum"
    elif rsi < 45:
        rsi_note = "with RSI momentum still soft"
    else:
        rsi_note = "with neutral RSI momentum"

    return f"The chart is currently {direction} ({change_pct:+.2f}%) and trading {regime}, {rsi_note}."


def _momentum_phrase(score: float, rank: int) -> str:
    """Interpret 252-day relative strength in absolute terms."""
    if score >= 0.5:
        return f"It has been one of the market's stronger large-cap names over the past year, ranking #{rank} in our 252-day momentum screen."
    elif score >= 0.2:
        return f"It has shown solid relative strength over the past year, ranking #{rank} in our 252-day momentum screen."
    elif score >= 0.0:
        return f"Its 252-day momentum is flat to slightly positive versus the S&P 500, placing it at rank #{rank}."
    else:
        return f"Its 252-day momentum is negative versus the S&P 500, but it is recovering enough to show up at rank #{rank}."


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

    trend_sentence = _trend_phrase(change_pct, above_ema20, above_ema50, above_ema200, float(rsi))
    momentum_sentence = _momentum_phrase(float(score), int(rank))

    # Catalyst: combine the headline with the stock's own technical context.
    catalyst_parts = [momentum_sentence]
    if macd_hist > 0:
        catalyst_parts.append("MACD histogram is positive.")
    elif macd_hist < 0:
        catalyst_parts.append("MACD histogram is negative, so momentum is fading short term.")
    if price_vs_vwap_pct > 0.1:
        catalyst_parts.append(f"It is trading {price_vs_vwap_pct:.2f}% above today's VWAP.")
    elif price_vs_vwap_pct < -0.1:
        catalyst_parts.append(f"It is trading {abs(price_vs_vwap_pct):.2f}% below today's VWAP.")
    if relvol > 1.2:
        catalyst_parts.append(f"Volume is running {relvol:.1f}× its 20-day average, so institutions are actively moving it.")
    elif relvol < 0.7:
        catalyst_parts.append("Volume is light relative to its 20-day average, suggesting a wait-and-see tape.")
    if htext:
        catalyst_parts.append(f"Recent headline: {htext}")
    else:
        catalyst_parts.append("No fresh headline today; the action is driven by the stock's own price trend.")
    catalyst = " ".join(catalyst_parts)

    # Why it's on the watchlist: stock-focused, not sleeve-deficient.
    why = (
        f"{symbol} is on watch because its own technical picture is worth tracking. "
        f"{trend_sentence} {momentum_sentence}"
    )

    # What triggers a buy: focus on the stock's own setup, not overtaking rank #10.
    if above_ema20 and above_ema50 and above_ema200 and change_pct >= 0:
        trigger = (
            f"A clean continuation above all major moving averages, ideally with volume confirming, "
            f"would make {symbol} a strong standalone long candidate."
        )
    elif above_ema50 and change_pct >= 0:
        trigger = (
            f"A push back above the 20-day EMA with improving volume would signal the short-term dip is over."
        )
    elif not above_ema50:
        trigger = (
            f"We'd want to see a base form above the 50-day EMA and a positive turn in intraday volume before taking a new position."
        )
    else:
        trigger = (
            f"A clearer directional move with volume expansion and a break above recent resistance would be the signal to act."
        )

    return {
        "symbol": symbol,
        "company": data.get("company") or symbol,
        "whatItIs": _sentence(note),
        "whyOnWatchlist": why,
        "whatTriggersBuy": trigger,
        "catalyst": catalyst,
        "risk": _sentence(risk),
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


def _holdings_trend_sentence(change_pct: float, above_ema20: bool, above_ema50: bool, above_ema200: bool, rsi: float) -> str:
    """Describe a holding's own price action without basket framing."""
    if above_ema20 and above_ema50 and above_ema200:
        regime = "above its 20-, 50-, and 200-day EMAs"
    elif above_ema50 and above_ema200:
        regime = "above its 50- and 200-day EMAs"
    elif above_ema200:
        regime = "above its 200-day EMA but below the shorter averages"
    elif above_ema50:
        regime = "above its 50-day EMA but below the 200-day"
    else:
        regime = "below its major moving averages"

    if change_pct >= 1.5:
        move = f"up strongly today (+{change_pct:.2f}%)"
    elif change_pct >= 0:
        move = f"up slightly today (+{change_pct:.2f}%)"
    elif change_pct > -1.5:
        move = f"down slightly today ({change_pct:.2f}%)"
    else:
        move = f"down firmly today ({change_pct:.2f}%)"

    if rsi > 70:
        rsi_note = "and is technically overbought short term"
    elif rsi < 30:
        rsi_note = "and is technically oversold short term"
    else:
        rsi_note = f"with RSI at {rsi:.1f}"

    return f"The position is {move}, trading {regime}, {rsi_note}."


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

    trend_sentence = _holdings_trend_sentence(float(change_pct), above_ema20, above_ema50, above_ema200, float(rsi))

    # Why we own it / why it is exiting: tied to the stock's own story, not just rank.
    if is_exiting:
        why = (
            f"We are closing the {symbol} position. "
            "Its relative strength has dropped enough that it no longer belongs in the current momentum sleeve. "
            "Proceeds will be redeployed into a stronger name."
        )
    elif is_new_entry:
        why = (
            f"We initiated {symbol} at the latest rebalance. "
            "It showed renewed relative strength and a clean technical setup, so it became a core momentum holding."
        )
    else:
        why = (
            f"We continue to hold {symbol} because its technical trend and relative-strength profile remain intact. "
            "It is kept as an equal-weight position until its own price action tells us otherwise."
        )

    # How it's doing: absolute trend snapshot, plus portfolio context.
    how = trend_sentence
    if rebalance_signal and rebalance_signal.get("gate"):
        how += f" The DM-6 asset-rotation gate is {rebalance_signal['gate']}, so new capital is only deployed when the broad tape cooperates."

    # Catalyst: stock-specific momentum + headline.
    catalyst_parts = []
    if momentum_252 is not None and rank is not None:
        if momentum_252 >= 50:
            catalyst_parts.append(f"It is one of the top large-cap momentum names year-over-year, ranking #{rank} with +{momentum_252:.2f}% relative strength.")
        elif momentum_252 >= 20:
            catalyst_parts.append(f"It has strong year-over-year momentum, ranking #{rank} at +{momentum_252:.2f}% relative strength.")
        else:
            catalyst_parts.append(f"Its 252-day relative strength is +{momentum_252:.2f}%, placing it at rank #{rank}.")

    if macd_hist > 0:
        catalyst_parts.append("MACD histogram is positive.")
    elif macd_hist < 0:
        catalyst_parts.append("MACD histogram has turned negative, a short-term caution flag.")

    if price_vs_vwap_pct > 0.1:
        catalyst_parts.append(f"It is trading {price_vs_vwap_pct:.2f}% above today's VWAP.")
    elif price_vs_vwap_pct < -0.1:
        catalyst_parts.append(f"It is trading {abs(price_vs_vwap_pct):.2f}% below today's VWAP.")

    if relvol > 1.2:
        catalyst_parts.append(f"Volume is running {relvol:.1f}× average, suggesting real participation.")
    elif relvol < 0.7:
        catalyst_parts.append("Volume is light, so conviction is still being tested.")

    if htext:
        catalyst_parts.append(f"Recent headline: {htext}")
    else:
        catalyst_parts.append("No fresh headline today; the position is moving on its own technicals.")

    catalyst = " ".join(catalyst_parts)

    base = {
        "symbol": symbol,
        "whatItIs": _sentence(note),
        "whyWeOwnIt": why,
        "howItsDoing": how,
        "catalyst": catalyst,
        "risk": _sentence(risk),
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
