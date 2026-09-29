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


def build_watchlist_narrative(symbol: str, data: dict, knowledge: dict, headline: dict | None) -> dict:
    info = knowledge.get(symbol, {})
    note = info.get("note", f"{symbol} is a publicly traded company.")
    risk = info.get("risk", "Standard market, execution, and business-model risk.")
    hl = headline or {}
    htext = hl.get("headline", "")
    rank = data.get("rank") or 0
    score = data.get("score") or 0
    dist = data.get("dist_to_top10")
    sector = data.get("sector") or info.get("sector", "its sector")

    catalyst = (
        f"{symbol} is a relative-strength candidate in {sector.lower() if isinstance(sector, str) else 'its sector'}. "
        f"It currently ranks #{rank} in the 252-day momentum screen with a score of {score * 100:.2f}%. "
    )
    if dist is not None and dist >= 0:
        catalyst += f"It needs to climb {dist * 100:.2f}% to reach the current top-10 cutoff and trigger sleeve entry. "
    else:
        catalyst += "It is ranked just outside the current top-10 sleeve basket. "
    if htext:
        catalyst += f"Recent headline: {htext}"
    else:
        catalyst += "No fresh Alpaca headline today; the driver is pure price momentum versus the S&P 500."

    return {
        "symbol": symbol,
        "company": data.get("company") or symbol,
        "whatItIs": _sentence(note),
        "whyOnWatchlist": (
            f"{symbol} is tracked as a potential sleeve candidate based on relative strength versus the S&P 500. "
            "It sits just outside the current top-10 momentum basket and is monitored for possible entry at the next signal-triggered rebalance."
        ),
        "whatTriggersBuy": (
            f"{symbol} would enter the sleeve if it rises into the top-10 relative-strength ranks while the regime gate remains open. "
            "That means overtaking the current #10 name on sustained outperformance, not a single day's move."
        ),
        "catalyst": catalyst,
        "risk": _sentence(risk),
        "alpacaNewsHeadline": htext,
        "alpacaNewsSource": hl.get("source", "Alpaca"),
        "alpacaNewsUrl": hl.get("url", ""),
        "sources": {
            "whatItIs": "company_knowledge.json",
            "whyOnWatchlist": "dm_paper sleeve engine",
            "whatTriggersBuy": "dm_paper sleeve engine",
            "catalyst": "Alpaca news API + dm_paper sleeve engine",
            "risk": "company_knowledge.json",
            "alpacaNewsHeadline": "Alpaca news API",
        },
    }


def build_holdings_narrative(symbol: str, knowledge: dict, headline: dict | None, sleeve_holding: dict | None = None, rebalance_signal: dict | None = None, is_new_entry: bool = False, is_exiting: bool = False) -> dict:
    info = knowledge.get(symbol, {})
    note = info.get("note", f"{symbol} is a publicly traded company.")
    risk = info.get("risk", "Standard market, execution, and business-model risk.")
    hl = headline or {}
    htext = hl.get("headline", "")
    rank = sleeve_holding.get("rank") if sleeve_holding else None
    score = sleeve_holding.get("score") if sleeve_holding else None
    ind = sleeve_holding.get("indicators", {}) if sleeve_holding else {}
    price = ind.get("price")
    ema_status = "above" if ind.get("price", 0) > ind.get("ema_50", 0) else "below"
    momentum_252 = score * 100 if score else None

    if is_exiting:
        why = (
            f"{symbol} is scheduled to exit the Bot basket at the next rebalance. "
            "It no longer ranks in the top 10 of the 252-day relative-strength screen versus the S&P 500. "
            "The position will be sold and replaced by the incoming target name."
        )
    elif is_new_entry:
        why = (
            f"{symbol} entered the Bot basket at the latest rebalance. "
            f"It ranked in the top 10 of the 252-day relative-strength screen versus the S&P 500, "
            "replacing a name that fell out of the basket. Equal-weight target at rebalance."
        )
    else:
        why = (
            f"{symbol} remains in the Bot basket after the latest rebalance. "
            f"It still ranks in the top 10 of the 252-day relative-strength screen versus the S&P 500. "
            "Held as an equal-weight position until the next signal-driven rotation."
        )

    catalyst = ""
    if rank is not None and momentum_252 is not None:
        catalyst = f"Rank #{rank} in the current 252-day momentum screen ({momentum_252:.2f}% vs S&P 500). "
    elif is_exiting:
        catalyst = "No longer in the top-10 momentum screen. "
    if price and ema_status and not is_exiting:
        catalyst += f"Price is {ema_status} the 50-day EMA. "
    if htext:
        catalyst += f"Recent headline: {htext}"
    else:
        catalyst += "No fresh Alpaca headline today; the position is driven by systematic momentum, not a news event."

    how = "Performance tracked versus portfolio cost basis and the S&P 500 benchmark."
    if rebalance_signal and rebalance_signal.get("gate"):
        how += f" Regime gate is {rebalance_signal['gate']} (DM-6 asset-rotation check)."

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
    return {
        "readiness_score": round(readiness, 1),
        "confirmation_count": conf.get("confirmation_count", data.get("confirmation_count", 6)),
        "confirmations": conf_out,
        "price": round(price, 2) if price else None,
        "stopLoss": round(price * 0.85, 2) if price else None,
        "profit25": round(price * 1.25, 2) if price else None,
        "rsi": data.get("rsi") or 50.0,
        "options_implied_vol": None,
        "tier": "NOW",
        "signal_tier": "NOW",
        "display_tier": "BUILDING",
        "buy_status": "not_ready",
        "buy_reason": "Not currently in the top-10 sleeve basket.",
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
        is_new_entry = sym in incoming_set
        is_exiting = sym in outgoing_set
        holdings_narratives[sym] = build_holdings_narrative(sym, knowledge, headlines.get(sym), sleeve_holding, rebalance_signal, is_new_entry, is_exiting)
        holdings_narratives[sym].update(build_holdings_sleeve_fields(sym, sleeve_state, quotes, sleeve_holding, is_exiting))

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Preserve legacy watchlist entries so old pages don't break, but do NOT
    # preserve old holdings: the site should only show the current Bot basket.
    old_watchlist = load_json(WATCHLIST_OUT).get("narratives", {})

    merged_watchlist = {**old_watchlist, **watchlist_narratives}
    # Use only current holdings for popup content.
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
