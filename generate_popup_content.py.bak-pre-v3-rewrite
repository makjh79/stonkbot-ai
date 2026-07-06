#!/usr/bin/env python3
"""
STONK.AI Popup Content Generator v2

Generates fresh, v2-aligned narratives for all holdings every 2 minutes.
Uses the quality-momentum signal engine and actual risk engine stop levels.
Saves to /var/www/hedge-fund-website/popup_content.json
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from signal_engine import COMPANY_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BOT_DIR = Path("/opt/stonk-ai")
WEB_DIR = Path("/var/www/hedge-fund-website")
POPUP_FILE = WEB_DIR / "popup_content.json"
PORTFOLIO_FILE = WEB_DIR / "portfolio_data.json"
WATCHLIST_FILE = WEB_DIR / "ai_watchlist_live.json"
WATCHLIST_NARRATIVES_FILE = WEB_DIR / "watchlist_narratives.json"
SIGNALS_FILE = BOT_DIR / "signals.json"
ENRICHMENT_FILE = BOT_DIR / "signal_enrichment.json"
RISK_STATE_FILE = BOT_DIR / "risk_state.json"
RISK_CONFIG_FILE = BOT_DIR / "risk_config.json"

# 2026 US market holidays (month, day)
MARKET_HOLIDAYS_2026 = {
    (1, 1), (1, 19), (2, 16), (4, 3), (5, 25), (6, 19),
    (7, 4), (9, 7), (10, 12), (11, 11), (11, 26), (12, 25),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def is_market_open() -> bool:
    """Rough US market hours check in UTC (14:30-21:00 UTC, Mon-Fri, no holidays)."""
    n = now()
    if n.weekday() >= 5:
        return False
    if (n.month, n.day) in MARKET_HOLIDAYS_2026:
        return False
    # 14:30-21:00 UTC = 09:30-16:00 ET
    start = n.replace(hour=14, minute=30, second=0, microsecond=0)
    end = n.replace(hour=21, minute=0, second=0, microsecond=0)
    return start <= n <= end


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.error(f"Could not load {path}: {e}")
        return {}


def load_signals_map() -> dict:
    """Map symbol -> signal data from signals.json, merged with enrichment fallback."""
    data = load_json(SIGNALS_FILE)
    signals = data.get("signals", [])
    sig_map = {s["symbol"]: s for s in signals if "symbol" in s}

    # For symbols not actively scored, merge enrichment data so popups still have context
    enrichment = load_json(ENRICHMENT_FILE).get("data", {})
    for symbol, e in enrichment.items():
        if symbol not in sig_map:
            sig_map[symbol] = {
                "symbol": symbol,
                "total_score": 0,
                "momentum_score": 0,
                "quality_score": 0,
                "risk_score": 0,
                "regime_score": 0,
                "thesis": "",
                "drivers": [],
                "sector": e.get("metrics", {}).get("sector", "Other"),
                "earnings": e.get("earnings"),
                "recommendation": e.get("recommendation"),
                "news": e.get("news"),
            }
        else:
            # Ensure enrichment fields are present even for scored symbols
            for key in ("earnings", "recommendation"):
                if key not in sig_map[symbol]:
                    sig_map[symbol][key] = e.get(key)
            # Always merge news from enrichment (has alpaca_url, alpaca_source)
            if "news" not in sig_map[symbol]:
                sig_map[symbol]["news"] = e.get("news")
            elif isinstance(sig_map[symbol].get("news"), dict) and isinstance(e.get("news"), dict):
                sig_map[symbol]["news"].update(e.get("news"))
    return sig_map


def load_risk_state() -> dict:
    return load_json(RISK_STATE_FILE)


def load_risk_config() -> dict:
    if RISK_CONFIG_FILE.exists():
        return load_json(RISK_CONFIG_FILE)
    # Defaults matching risk_engine.py
    return {
        "hard_stop_loss_pct": -0.10,
        "trailing_stop_pct": -0.10,
        "trailing_stop_atr_multiplier": 2.5,
        "trim_profit_pct": 0.25,
        "full_exit_profit_pct": 0.50,
    }


def get_stop_levels(symbol: str, position: dict, risk_config: dict, risk_state: dict, signal_data: dict) -> dict:
    """Compute effective hard stop and trailing stop levels."""
    avg_entry = position.get("avg_entry", 0)
    peak = risk_state.get("position_high_water_marks", {}).get(symbol, avg_entry)
    atr_pct = risk_state.get("position_atr_pct", {}).get(symbol)

    # Hard stop from cost basis
    hard_stop = avg_entry * (1 + risk_config.get("hard_stop_loss_pct", -0.10))

    # Trailing stop from peak, volatility-aware only if ATR% was recorded
    base_trailing_pct = abs(risk_config.get("trailing_stop_pct", -0.10))
    if atr_pct and atr_pct > 0:
        atr_mult = risk_config.get("trailing_stop_atr_multiplier", 2.5)
        trailing_pct = max(base_trailing_pct, atr_pct * atr_mult)
    else:
        trailing_pct = base_trailing_pct

    trailing_stop = peak * (1 - trailing_pct)

    # VWAP stop (from Alpaca paid data)
    vwap = signal_data.get("daily_vwap")
    vwap_stop = round(vwap * 0.98, 2) if vwap and vwap > 0 else None  # 2% below VWAP

    return {
        "hard_stop": round(hard_stop, 2),
        "trailing_stop": round(trailing_stop, 2),
        "vwap_stop": vwap_stop,
        "vwap": round(vwap, 2) if vwap else None,
        "peak": round(peak, 2),
        "trailing_pct": round(trailing_pct * 100, 1),
    }


def signal_label(pl_percent: float, total_score: float, tier: str) -> str:
    if pl_percent >= 25:
        return "PROFIT_ZONE"
    if pl_percent <= -8:
        return "WARNING"
    if tier == "NOW":
        return "STRONG"
    if tier == "WATCH":
        return "GREEN"
    if total_score >= 45:
        return "HOLD"
    return "TRACKING"


def generate_risk(
    symbol: str,
    pl_percent: float,
    signal_data: dict,
    watchlist_data: dict,
    stops: dict,
) -> str:
    """Build a macro/sector-aware risk description. Keep technical stops as a short suffix."""
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    vol = signal_data.get("volatility_20d")
    atr_pct = signal_data.get("atr14", 0) / signal_data.get("price", 1) * 100 if signal_data.get("price", 0) > 0 else 0
    spy_corr = signal_data.get("spy_corr_20d")
    regime = signal_data.get("regime_score", 50)

    macro_risks = []

    if sector in ("Semiconductors", "AI/Growth", "Cybersecurity", "Cloud/Data"):
        macro_risks.append("rate and AI capex cycles")
    elif sector in ("Fintech", "Consumer/Platform"):
        macro_risks.append("consumer spending and regulatory environment")
    elif sector in ("EV/Mobility", "Retail/Lifestyle"):
        macro_risks.append("demand and margin pressure")
    elif sector == "Tech Giants":
        macro_risks.append("antitrust scrutiny and cloud/AI spending")

    if vol is not None and vol > 0.35:
        macro_risks.append(f"elevated volatility ({vol*100:.0f}% annualized)")
    elif atr_pct and atr_pct > 3.5:
        macro_risks.append("wide daily price swings")

    if spy_corr is not None and spy_corr > 0.70:
        macro_risks.append("high market correlation")
    elif spy_corr is not None and spy_corr < 0.30:
        macro_risks.append("moves independently of the broad market")

    if regime < 40:
        macro_risks.append("cautious macro regime")

    earnings = signal_data.get("earnings")
    rec = signal_data.get("recommendation")
    if earnings:
        spct = earnings.get("surprise_pct", 0)
        if abs(spct) < 1:
            macro_risks.append("limited recent earnings surprise")
    if rec and rec.get("bearish_pct", 0) >= 20:
        macro_risks.append(f"analyst disagreement ({rec.get('bearish_pct', 0):.0f}% bearish)")

    if pl_percent <= -8:
        macro_risks.append("position is under pressure; further deterioration would challenge thesis")
    elif pl_percent >= 25:
        macro_risks.append("profit giveback risk")

    if not macro_risks:
        macro_risks.append("general equity market risk")

    risk_body = f"Main risk drivers: {', '.join(macro_risks)}."
    stop_note = f"Technical guardrails: -10% hard stop at ${stops['hard_stop']:.2f}, volatility-aware trailing stop at ${stops['trailing_stop']:.2f}."
    return f"{risk_body} {stop_note}"


def generate_catalyst(
    symbol: str,
    pl_percent: float,
    signal_data: dict,
    watchlist_data: dict,
) -> str:
    """Build a real, enrichment-driven catalyst sentence."""
    enrichment = signal_data or {}
    catalysts = []

    earnings = enrichment.get("earnings")
    if earnings:
        spct = earnings.get("surprise_pct", 0)
        direction = earnings.get("direction", "beat")
        if abs(spct) >= 5:
            catalysts.append(
                f"Recent earnings {direction} by {abs(spct):.1f}% is the core driver."
            )
        elif abs(spct) > 0:
            catalysts.append(
                f"Recent earnings {direction} by {abs(spct):.1f}% supports the setup."
            )

    rec = enrichment.get("recommendation")
    if rec:
        bullish_pct = rec.get("bullish_pct", 0)
        if bullish_pct >= 80:
            catalysts.append(f"Wall Street is heavily bullish ({bullish_pct:.0f}% buy/strong-buy).")
        elif bullish_pct >= 60:
            catalysts.append(f"Analyst sentiment is net bullish ({bullish_pct:.0f}% buy/strong-buy).")
        elif rec.get("bearish_pct", 0) >= 25:
            catalysts.append(f"Some analyst skepticism exists ({rec.get('bearish_pct', 0):.0f}% sell).")

    news = enrichment.get("news")
    if news and news.get("sample_headline"):
        label = news.get("sentiment_label", "neutral")
        headline = news.get("sample_headline", "")
        if label == "bullish" and headline:
            catalysts.append(f"Positive news flow: '{headline[:60]}{'...' if len(headline) > 60 else ''}'")
        elif label == "bearish" and headline:
            catalysts.append(f"Cautious news tone: '{headline[:60]}{'...' if len(headline) > 60 else ''}'")

    tier = watchlist_data.get("signal_tier") or signal_tier(enrichment.get("total_score", 0))
    if tier == "NOW":
        catalysts.append("Quality-momentum score is in the highest-conviction NOW tier.")
    elif tier == "WATCH":
        catalysts.append("Signal score is close to entry threshold; watching for confirmation.")

    if pl_percent >= 25:
        catalysts.append("Profit zone reached; consider trimming 1/3 at +25% or full exit at +50%.")
    elif pl_percent >= 5:
        catalysts.append("Momentum continues to work; monitoring for +25% trim level.")
    elif pl_percent <= -8:
        catalysts.append("Under pressure; needs price stabilization or momentum reversal.")
    elif not catalysts:
        catalysts.append("Holding for momentum confirmation.")

    return " ".join(catalysts[:3])


def generate_dynamic_narrative(symbol: str, position: dict, watchlist_data: dict, signal_data: dict, risk_config: dict, risk_state: dict) -> dict:
    pl_percent = position.get("unrealized_plpc", 0)
    price = position.get("current", 0)
    avg_entry = position.get("avg_entry", 0)
    qty = position.get("qty", 0)
    market_value = position.get("market_value", 0)

    total_score = signal_data.get("total_score", 0)
    momentum_score = signal_data.get("momentum_score", 0)
    quality_score = signal_data.get("quality_score", 0)
    risk_score = signal_data.get("risk_score", 0)
    regime_score = signal_data.get("regime_score", 0)
    thesis = signal_data.get("thesis", "")
    drivers = signal_data.get("drivers", [])
    enrichment_earnings = signal_data.get("earnings")
    enrichment_rec = signal_data.get("recommendation")
    enrichment_news = signal_data.get("news")
    tier = watchlist_data.get("signal_tier") or signal_tier(total_score)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")

    # Build a fallback thesis for tracking/non-scored holdings using enrichment
    if not thesis and (enrichment_earnings or enrichment_rec or enrichment_news):
        evidence_parts = []
        if enrichment_earnings:
            spct = enrichment_earnings.get("surprise_pct", 0)
            direction = enrichment_earnings.get("direction", "beat")
            evidence_parts.append(f"latest earnings {direction} by {abs(spct):.1f}%")
        if enrichment_rec:
            bpct = enrichment_rec.get("bullish_pct", 0)
            if bpct >= 60:
                evidence_parts.append(f"{bpct:.0f}% of analysts bullish")
        if enrichment_news and enrichment_news.get("sentiment_label") in ("bullish", "bearish"):
            evidence_parts.append(f"news reads {enrichment_news.get('sentiment_label')}")

        evidence_sentence = ""
        if evidence_parts:
            evidence_sentence = "Evidence: " + ", ".join(evidence_parts) + "."

        thesis = (
            f"{symbol} is a held position without an active quality-momentum signal. "
            f"It remains in the portfolio and is being monitored. {evidence_sentence} "
            f"Risk management uses the standard -10% hard stop and volatility-aware trailing stop."
        )

    stops = get_stop_levels(symbol, position, risk_config, risk_state, signal_data)

    signal = signal_label(pl_percent, total_score, tier)

    # Narrative blocks — use engine thesis if available, otherwise fallback
    if thesis:
        base_thesis = thesis
    else:
        base_thesis = (
            f"Quality-momentum position in {symbol} ({sector}). Score {total_score:.0f}: "
            f"momentum {momentum_score:.0f}, quality {quality_score:.0f}, risk {risk_score:.0f}, macro {regime_score:.0f}."
        )

    if pl_percent >= 25:
        thesis = f"{base_thesis} Currently in the profit zone at +{pl_percent:.1f}%."
        catalyst = generate_catalyst(symbol, pl_percent, signal_data, watchlist_data)
        risk = generate_risk(symbol, pl_percent, signal_data, watchlist_data, stops)
        confidence = f"{min(95, int(total_score + 10))}% - Thesis validated." if total_score > 0 else "N/A - Not actively scored; monitored for re-entry."

    elif pl_percent >= 5:
        thesis = f"{base_thesis} Position working (+{pl_percent:.1f}%)."
        catalyst = generate_catalyst(symbol, pl_percent, signal_data, watchlist_data)
        risk = generate_risk(symbol, pl_percent, signal_data, watchlist_data, stops)
        confidence = f"{int(total_score)}% - On track." if total_score > 0 else "N/A - Not actively scored; monitored for re-entry."

    elif pl_percent <= -8:
        thesis = f"{base_thesis} Currently under pressure ({pl_percent:.1f}%) — re-evaluating if thesis is intact."
        catalyst = generate_catalyst(symbol, pl_percent, signal_data, watchlist_data)
        risk = generate_risk(symbol, pl_percent, signal_data, watchlist_data, stops)
        confidence = f"{max(20, int(total_score - 15))}% - Under pressure." if total_score > 0 else "N/A - Not actively scored; monitored for re-entry."

    else:
        thesis = base_thesis
        catalyst = generate_catalyst(symbol, pl_percent, signal_data, watchlist_data)
        risk = generate_risk(symbol, pl_percent, signal_data, watchlist_data, stops)
        confidence = f"{int(total_score)}% - Conviction maintained." if total_score > 0 else "N/A - Not actively scored; monitored for re-entry."

    readiness = signal_data.get("readiness_score", 0)
    entry_eligible = signal_data.get("entry_eligible", False)
    confirmation_count = signal_data.get("confirmation_count", 0)
    tier_reason = signal_data.get("tier_reason", "")
    confirmations = signal_data.get("confirmations", {})

    result = {
        "thesis": thesis,
        "catalyst": catalyst,
        "risk": risk,
        "confidence": confidence,
        "signal": signal,
        "tier": tier,
        "readiness_score": round(readiness, 1) if readiness else None,
        "entry_eligible": entry_eligible,
        "confirmation_count": confirmation_count,
        "tier_reason": tier_reason,
        "confirmations": confirmations,
        "company": signal_data.get("company") or COMPANY_NAMES.get(symbol, symbol),
        "entryReason": f"Quality-momentum entry near avg cost ${avg_entry:.2f}",
        "stopReason": f"Hard stop ${stops['hard_stop']:.2f} (-10%); trailing ${stops['trailing_stop']:.2f}",
        "totalScore": round(total_score, 1) if total_score > 0 else None,
        "momentumScore": round(momentum_score, 1) if momentum_score > 0 else None,
        "qualityScore": round(quality_score, 1) if quality_score > 0 else None,
        "riskScore": round(risk_score, 1) if risk_score > 0 else None,
        "regimeScore": round(regime_score, 1) if regime_score > 0 else None,
        "plPercent": pl_percent,
        "price": price,
        "qty": qty,
        "marketValue": market_value,
        "avgEntry": avg_entry,
        "hardStop": stops["hard_stop"],
        "trailingStop": stops["trailing_stop"],
        "vwapStop": stops.get("vwap_stop"),
        "lastUpdated": now().isoformat().replace("+00:00", "Z"),
        "drivers": drivers,
        # Alpaca news headline (from paid news API)
        "alpacaNewsHeadline": signal_data.get("news", {}).get("alpaca_headline") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSentiment": signal_data.get("news", {}).get("alpaca_sentiment") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsUrl": signal_data.get("news", {}).get("alpaca_url") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSource": signal_data.get("news", {}).get("alpaca_source") if isinstance(signal_data.get("news"), dict) else None,
        "optionsImpliedVol": signal_data.get("options_implied_vol"),
        "momentum20d": signal_data.get("momentum_20d"),
        "momentum50d": signal_data.get("momentum_50d"),
        "regimeScore": signal_data.get("regime_score"),
        "strategyType": signal_data.get("strategy_type", "momentum"),
        "volatility20d": signal_data.get("volatility_20d"),
        "spyCorr20d": signal_data.get("spy_corr_20d"),
        "atr14": signal_data.get("atr14"),
        # New: real VWAP and intraday data from Alpaca paid API
        "dailyVwap": signal_data.get("daily_vwap"),
        "prevClose": signal_data.get("prev_close"),
        "intradayVwap": signal_data.get("intraday_vwap"),
        "intradayVolRatio": signal_data.get("intraday_vol_ratio"),
        "vwapDeviation": round((price - signal_data.get("daily_vwap", price)) / signal_data.get("daily_vwap", price) * 100, 2) if signal_data.get("daily_vwap") and price else None,
    }

    # Keep legacy keys for frontend compatibility
    result["rsi"] = signal_data.get("rsi14", 50)
    result["aiScore"] = int(min(100, max(30, total_score))) if total_score > 0 else None
    result["isScored"] = total_score > 0

    return result


def generate_watchlist_narrative(
    symbol: str,
    signal_data: dict,
    watchlist_data: dict,
) -> dict:
    """Generate real strategy/catalyst/risk narrative for a watchlist symbol."""
    total_score = signal_data.get("total_score", 0)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or COMPANY_NAMES.get(symbol, symbol)
    price = watchlist_data.get("price") or signal_data.get("price", 0)
    vol = signal_data.get("volatility_20d")
    rsi = signal_data.get("rsi14")
    spy_corr = signal_data.get("spy_corr_20d")
    regime = signal_data.get("regime_score", 50)
    momentum_20d = signal_data.get("momentum_20d")

    # Strategy: sector + momentum + score based
    if total_score >= 55:
        strategy = f"{company} ranks in the highest-conviction NOW tier with a quality-momentum score of {total_score:.0f}/100."
    elif total_score >= 45:
        strategy = f"{company} is a WATCH candidate with a quality-momentum score of {total_score:.0f}/100, close to entry threshold."
    elif total_score > 0:
        strategy = f"{company} is scored {total_score:.0f}/100 on the quality-momentum model but remains below active entry threshold."
    else:
        strategy = f"{company} is a TRACKING name in the 75-stock universe with no active quality-momentum signal yet."

    if sector:
        sector_phrase = {
            "Semiconductors": "semiconductor / chip-cycle exposure",
            "AI/Growth": "AI / high-growth software exposure",
            "Tech Giants": "mega-cap tech compounder",
            "Fintech": "fintech / digital payments exposure",
            "Consumer/Platform": "consumer / platform growth exposure",
            "Cloud/Data": "cloud / data infrastructure exposure",
            "EV/Mobility": "EV / mobility transition exposure",
            "Retail/Lifestyle": "consumer retail / lifestyle brand",
            "Cybersecurity": "cybersecurity / enterprise software exposure",
        }.get(sector, f"{sector.lower()} exposure")
        strategy += f" Sector: {sector_phrase}."

    # Catalyst
    catalysts = []
    earnings = signal_data.get("earnings")
    rec = signal_data.get("recommendation")
    news = signal_data.get("news")
    if earnings and earnings.get("surprise_pct", 0) != 0:
        catalysts.append(f"latest earnings {earnings.get('direction', 'beat')} by {abs(earnings.get('surprise_pct', 0)):.1f}%")
    if rec:
        bpct = rec.get("bullish_pct", 0)
        if bpct >= 60:
            catalysts.append(f"{bpct:.0f}% analyst buy/strong-buy rating")
    if news and news.get("sample_headline"):
        label = news.get("sentiment_label", "neutral")
        if label in ("bullish", "bearish"):
            catalysts.append(f"recent news reads {label}")
    if momentum_20d is not None and momentum_20d > 0.10:
        catalysts.append(f"20-day momentum +{momentum_20d*100:.1f}%")
    elif momentum_20d is not None and momentum_20d < -0.10:
        catalysts.append(f"20-day momentum -{abs(momentum_20d)*100:.1f}% (potential reversal watch)")

    catalyst = " ".join(catalysts[:3]) if catalysts else "Awaiting next catalyst; monitor signal score and volume."

    # Risk: macro/sector aware
    risk_parts = []
    if sector in ("Semiconductors", "AI/Growth", "Cybersecurity", "Cloud/Data"):
        risk_parts.append("rate and AI capex cycles")
    elif sector in ("Fintech", "Consumer/Platform"):
        risk_parts.append("consumer spending and regulatory environment")
    elif sector in ("EV/Mobility", "Retail/Lifestyle"):
        risk_parts.append("demand and margin pressure")
    elif sector == "Tech Giants":
        risk_parts.append("antitrust scrutiny and cloud/AI spending")

    if vol is not None and vol > 0.35:
        risk_parts.append(f"elevated volatility ({vol*100:.0f}% annualized)")
    if spy_corr is not None and spy_corr > 0.70:
        risk_parts.append("high correlation with the broad market")
    if regime < 40:
        risk_parts.append("cautious macro regime")
    if not risk_parts:
        risk_parts.append("general equity market risk")

    risk = f"Main risks: {', '.join(risk_parts)}."

    return {
        "symbol": symbol,
        "company": company,
        "strategy": strategy,
        "catalyst": catalyst,
        "risk": risk,
        "total_score": round(total_score, 1) if total_score > 0 else None,
        "tier": watchlist_data.get("signal_tier") or signal_tier(total_score),
        "last_updated": now().isoformat().replace("+00:00", "Z"),
    }


def signal_tier(total_score: float) -> str:
    if total_score >= 55:
        return "NOW"
    if total_score >= 45:
        return "WATCH"
    if total_score > 0:
        return "MONITOR"
    return "TRACKING"


def generate_popup_content():
    # Always generate — news from Alpaca is available 24/7
    # Intraday data will be empty when market is closed (handled gracefully)
    _market_open = is_market_open()
    if not _market_open:
        logger.info("Markets closed — generating with available data (news, VWAP, signals)")

    portfolio = load_json(PORTFOLIO_FILE)
    watchlist = load_json(WATCHLIST_FILE).get("prices", {})
    signals_map = load_signals_map()
    risk_config = load_risk_config()
    risk_state = load_risk_state()

    positions = portfolio.get("positions", [])
    if not positions:
        logger.warning("No positions in portfolio")
        return None

    popup_data = {
        "timestamp": now().isoformat().replace("+00:00", "Z"),
        "holdings": {},
    }

    # Generate real narratives for every symbol on the watchlist
    watchlist_narratives = {
        "timestamp": now().isoformat().replace("+00:00", "Z"),
        "narratives": {},
    }
    for symbol, wdata in watchlist.items():
        signal_data = signals_map.get(symbol, {})
        try:
            narrative = generate_watchlist_narrative(symbol, signal_data, wdata)
            watchlist_narratives["narratives"][symbol] = narrative
        except Exception as e:
            logger.error(f"Failed to generate watchlist narrative for {symbol}: {e}")

    try:
        WATCHLIST_NARRATIVES_FILE.write_text(json.dumps(watchlist_narratives, indent=2))
        logger.info(f"Saved watchlist narratives for {len(watchlist_narratives['narratives'])} symbols")
    except Exception as e:
        logger.error(f"Failed to save watchlist narratives: {e}")

    for position in positions:
        symbol = position.get("symbol")
        if not symbol:
            continue
        watchlist_data = watchlist.get(symbol, {})
        signal_data = signals_map.get(symbol, {})
        try:
            narrative = generate_dynamic_narrative(
                symbol, position, watchlist_data, signal_data, risk_config, risk_state
            )
            popup_data["holdings"][symbol] = narrative
            logger.info(f"Generated popup content for {symbol}: {narrative['signal']}")
        except Exception as e:
            logger.error(f"Failed to generate narrative for {symbol}: {e}")

    try:
        POPUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        POPUP_FILE.write_text(json.dumps(popup_data, indent=2))
        logger.info(f"Saved popup content for {len(popup_data['holdings'])} holdings")
    except Exception as e:
        logger.error(f"Failed to save popup content: {e}")
        return None

    return popup_data


if __name__ == "__main__":
    logger.info("=== STONK.AI Popup Content Generator v2 Starting ===")
    result = generate_popup_content()
    if result:
        logger.info(f"Successfully generated content for {len(result['holdings'])} positions")
    else:
        logger.info("No popup data generated")
