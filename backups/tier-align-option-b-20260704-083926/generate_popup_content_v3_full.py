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



def _what_it_is(symbol, signal_data, sector, company):
    """One sentence: what the company does."""
    sector_desc = {
        "Semiconductors": "semiconductor company",
        "AI/Growth": "AI and growth software company",
        "Tech Giants": "mega-cap technology company",
        "Fintech": "fintech and digital payments company",
        "Consumer/Platform": "consumer platform company",
        "Cloud/Data": "cloud and data infrastructure company",
        "EV/Mobility": "electric vehicle and mobility company",
        "Retail/Lifestyle": "retail and lifestyle brand",
        "Cybersecurity": "cybersecurity company",
        "Healthcare": "healthcare company",
        "Energy": "energy company",
        "Industrials": "industrial company",
        "Financials": "financial services company",
        "Communications": "communications and media company",
        "Tech Expansion": "established technology company",
    }
    what = sector_desc.get(sector, "company")
    if company and company != symbol:
        return f"{company} is a {what} in the {sector} sector."
    return f"{symbol} is a {what} in the {sector} sector."


def _why_bot_bought(signal_data, position, thesis_data=None):
    """Why the bot bought it — from entry confirmations and readiness."""
    entry_readiness = thesis_data.get("entry_readiness", 0) if thesis_data else signal_data.get("readiness_score", 0)
    confirmations = thesis_data.get("confirmations", {}) if thesis_data else signal_data.get("confirmations", {})
    entry_price = position.get("avg_entry", 0)

    reasons = []
    conf_names = {
        "volume_confirmed": "volume confirmation",
        "macd_turning": "MACD turning positive",
        "above_ema": "price above 20-day EMA",
        "sector_strong": "strong sector momentum",
        "intraday_confirmed": "positive intraday flow",
        "options_confirmed": "low options volatility",
        "relvol_confirmed": "relative volume surge",
        "vwap_confirmed": "price above VWAP",
    }
    for key, label in conf_names.items():
        if confirmations.get(key):
            reasons.append(label)

    rsi_signal = confirmations.get("rsi_signal", "")
    if rsi_signal == "oversold":
        reasons.append("RSI oversold (bounce potential)")
    elif rsi_signal and rsi_signal != "overbought":
        reasons.append(f"RSI in {rsi_signal} range")

    if entry_readiness >= 80:
        conviction = "high conviction"
    elif entry_readiness >= 72:
        conviction = "standard conviction"
    else:
        conviction = "moderate conviction"

    if reasons:
        return f"Bot entered at ${entry_price:.2f} with {conviction} (readiness {entry_readiness:.0f}). Signals: {', '.join(reasons[:4])}."
    return f"Bot entered at ${entry_price:.2f} with {conviction} (readiness {entry_readiness:.0f})."


def _how_its_doing(position, signal_data, watchlist_data):
    """Current P&L status in plain English."""
    pl_pct = position.get("unrealized_plpc", 0)
    readiness = signal_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")

    parts = []
    if pl_pct >= 25:
        parts.append(f"Up {pl_pct:.1f}% from entry — in profit zone")
    elif pl_pct >= 5:
        parts.append(f"Up {pl_pct:.1f}% — momentum working")
    elif pl_pct >= -5:
        parts.append(f"Roughly flat ({pl_pct:+.1f}%) — waiting for direction")
    elif pl_pct >= -10:
        parts.append(f"Down {pl_pct:.1f}% — under pressure")
    else:
        parts.append(f"Down {abs(pl_pct):.1f}% — thesis at risk")

    if tier == "STRONG_NOW":
        parts.append("still rated STRONG NOW")
    elif tier == "NOW":
        parts.append("still rated NOW")
    elif tier == "WATCH":
        parts.append("dropped to WATCH")
    elif tier == "MONITOR":
        parts.append("dropped to MONITOR — weak signal")

    if readiness > 0:
        parts.append(f"(readiness {readiness:.0f})")

    return ". ".join(parts) + "."


def _what_moves_it(signal_data):
    """Upcoming catalysts from live enrichment data."""
    catalysts = []

    earnings = signal_data.get("earnings")
    if earnings:
        direction = earnings.get("direction", "beat")
        spct = earnings.get("surprise_pct", 0)
        if abs(spct) >= 5:
            catalysts.append(f"Earnings {direction} by {abs(spct):.1f}% — significant")
        elif abs(spct) > 0:
            catalysts.append(f"Earnings {direction} by {abs(spct):.1f}%")
        else:
            catalysts.append("Earnings in line with estimates")

    rec = signal_data.get("recommendation")
    if rec:
        bpct = rec.get("bullish_pct", 0)
        spct_sell = rec.get("sell", 0)
        if bpct >= 80:
            catalysts.append(f"Wall Street heavily bullish ({bpct:.0f}% buy)")
        elif bpct >= 60:
            catalysts.append(f"Analysts net bullish ({bpct:.0f}% buy)")
        elif spct_sell >= 25:
            catalysts.append(f"Analyst skepticism ({spct_sell:.0f}% sell)")

    news = signal_data.get("news")
    headline = None
    if news:
        alpaca_headline = news.get("alpaca_headline") if isinstance(news, dict) else None
        alpaca_sentiment = news.get("alpaca_sentiment") if isinstance(news, dict) else None
        if alpaca_headline:
            headline = alpaca_headline
            sentiment = alpaca_sentiment or news.get("sentiment_label", "neutral")
        else:
            headline = news.get("sample_headline")
            sentiment = news.get("sentiment_label", "neutral")

        if headline and sentiment in ("bullish", "bearish"):
            clean = headline[:80] + ("..." if len(headline) > 80 else "")
            catalysts.append(f"Recent news: {sentiment} — \"{clean}\"")
        elif headline:
            clean = headline[:80] + ("..." if len(headline) > 80 else "")
            catalysts.append(f"Recent news: \"{clean}\"")

    if not catalysts:
        momentum_20d = signal_data.get("momentum_20d", 0)
        if momentum_20d and momentum_20d > 0.10:
            catalysts.append(f"20-day price momentum +{momentum_20d*100:.1f}%")
        elif momentum_20d and momentum_20d < -0.10:
            catalysts.append(f"20-day decline -{abs(momentum_20d)*100:.1f}% (reversal watch)")

    return " ".join(catalysts) if catalysts else "No active catalyst — monitoring signal score and volume."


def _what_kills_it(symbol, position, signal_data, watchlist_data, stops):
    """Specific, non-template risk description."""
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    vol = signal_data.get("volatility_20d")
    iv = signal_data.get("options_implied_vol")
    spy_corr = signal_data.get("spy_corr_20d")

    risks = []

    sector_risks = {
        "Semiconductors": "chip cycle downturn and capex cuts",
        "AI/Growth": "AI hype deflation and rate sensitivity",
        "Tech Giants": "antitrust action and cloud growth slowdown",
        "Fintech": "regulatory crackdown and consumer credit losses",
        "Consumer/Platform": "consumer spending slowdown",
        "Cloud/Data": "enterprise IT spend freeze",
        "EV/Mobility": "EV price war and demand destruction",
        "Retail/Lifestyle": "discretionary spending pullback",
        "Cybersecurity": "competitive pricing pressure",
        "Healthcare": "drug pricing policy and trial failures",
        "Energy": "oil price volatility and transition risk",
        "Industrials": "cyclical demand slowdown",
        "Financials": "credit losses and rate cuts squeezing margins",
        "Communications": "advertising decline and cord-cutting",
        "Tech Expansion": "legacy business decline and execution risk",
    }
    sector_risk = sector_risks.get(sector)
    if sector_risk:
        risks.append(sector_risk)

    if vol and isinstance(vol, (int, float)) and vol > 0.40:
        risks.append(f"high volatility ({vol*100:.0f}% annualized)")
    if iv and isinstance(iv, (int, float)) and iv > 0.6:
        risks.append(f"elevated options IV ({iv*100:.0f}%) — market expects big swings")
    if spy_corr and spy_corr > 0.75:
        risks.append("moves closely with the market — limited diversification")

    hard_stop = stops.get("hard_stop", 0)
    trailing = stops.get("trailing_stop", 0)
    vwap_stop = stops.get("vwap_stop")

    stop_parts = [f"Hard stop at ${hard_stop:.2f} (-10% from entry)"]
    if trailing and trailing > 0:
        stop_parts.append(f"trailing stop at ${trailing:.2f}")
    if vwap_stop and vwap_stop > 0:
        stop_parts.append(f"VWAP stop at ${vwap_stop:.2f}")

    risk_desc = ""
    if risks:
        risk_desc = "Key risks: " + ", ".join(risks) + ". "
    risk_desc += "Stops: " + "; ".join(stop_parts) + "."

    return risk_desc


def _confidence_level(position, signal_data, watchlist_data):
    """Plain English confidence — not a fake percentage."""
    pl_pct = position.get("unrealized_plpc", 0)
    readiness = signal_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    entry_readiness = signal_data.get("entry_readiness", 0)

    if tier == "STRONG_NOW" and pl_pct >= 0:
        level = "High conviction — thesis intact and position is profitable"
    elif tier == "NOW" and pl_pct >= 0:
        level = "Standard conviction — on track"
    elif tier == "NOW" and pl_pct < 0:
        level = "Standard conviction — underwater but signal still active"
    elif tier == "WATCH":
        level = "Deteriorating — readiness dropped below entry threshold"
    elif tier == "MONITOR":
        if readiness < 40:
            level = "Thesis broken — readiness below 40, exit imminent"
        else:
            level = "Weak — readiness near exit zone"
    else:
        level = "Monitoring"

    return level


# ─────────────────────────────────────────────────────────────────────
# HOLDINGS narrative (replaces generate_dynamic_narrative)
# ─────────────────────────────────────────────────────────────────────

def generate_dynamic_narrative(symbol, position, watchlist_data, signal_data, risk_config, risk_state):
    pl_percent = position.get("unrealized_plpc", 0)
    price = position.get("current", 0)
    avg_entry = position.get("avg_entry", 0)
    qty = position.get("qty", 0)
    market_value = position.get("market_value", 0)

    total_score = signal_data.get("total_score", 0)
    momentum_score = signal_data.get("momentum_score", 0)
    quality_score = signal_data.get("quality_score", 0)
    risk_score = signal_data.get("risk_score", 0)
    regime_score_val = signal_data.get("regime_score", 0)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or COMPANY_NAMES.get(symbol, symbol)
    drivers = signal_data.get("drivers", [])

    # Load thesis data for entry confirmations
    thesis_data = {}
    try:
        with open(BOT_DIR / "position_theses.json") as f:
            theses = json.load(f)
            thesis_data = theses.get(symbol, {})
    except Exception:
        pass

    stops = get_stop_levels(symbol, position, risk_config, risk_state, signal_data)

    # Build dynamic narratives
    what_it_is = _what_it_is(symbol, signal_data, sector, company)
    why_owned = _why_bot_bought(signal_data, position, thesis_data)
    how_doing = _how_its_doing(position, signal_data, watchlist_data)
    catalyst = _what_moves_it(signal_data)
    risk = _what_kills_it(symbol, position, signal_data, watchlist_data, stops)
    confidence = _confidence_level(position, signal_data, watchlist_data)

    readiness = signal_data.get("readiness_score", 0)
    entry_eligible = signal_data.get("entry_eligible", False)
    confirmation_count = signal_data.get("confirmation_count", 0)
    tier_reason = signal_data.get("tier_reason", "")
    confirmations = signal_data.get("confirmations", {})
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    signal = signal_label(pl_percent, total_score, tier)

    result = {
        "whatItIs": what_it_is,
        "whyWeOwnIt": why_owned,
        "howItsDoing": how_doing,
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
        "company": company,
        "entryReason": why_owned,
        "stopReason": f"Hard stop ${stops['hard_stop']:.2f} (-10%); trailing ${stops['trailing_stop']:.2f}",
        "totalScore": round(total_score, 1) if total_score > 0 else None,
        "momentumScore": round(momentum_score, 1) if momentum_score > 0 else None,
        "qualityScore": round(quality_score, 1) if quality_score > 0 else None,
        "riskScore": round(risk_score, 1) if risk_score > 0 else None,
        "regimeScore": round(regime_score_val, 1) if regime_score_val > 0 else None,
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
        "alpacaNewsHeadline": signal_data.get("news", {}).get("alpaca_headline") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSentiment": signal_data.get("news", {}).get("alpaca_sentiment") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsUrl": signal_data.get("news", {}).get("alpaca_url") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSource": signal_data.get("news", {}).get("alpaca_source") if isinstance(signal_data.get("news"), dict) else None,
        "optionsImpliedVol": signal_data.get("options_implied_vol"),
        "momentum20d": signal_data.get("momentum_20d"),
        "momentum50d": signal_data.get("momentum_50d"),
        "strategyType": signal_data.get("strategy_type", "momentum"),
        "volatility20d": signal_data.get("volatility_20d"),
        "spyCorr20d": signal_data.get("spy_corr_20d"),
        "atr14": signal_data.get("atr14"),
        "dailyVwap": signal_data.get("daily_vwap"),
        "prevClose": signal_data.get("prev_close"),
        "intradayVwap": signal_data.get("intraday_vwap"),
        "intradayVolRatio": signal_data.get("intraday_vol_ratio"),
        "vwapDeviation": round((price - signal_data.get("daily_vwap", price)) / signal_data.get("daily_vwap", price) * 100, 2) if signal_data.get("daily_vwap") and price else None,
        "rsi": signal_data.get("rsi14", 50),
        "aiScore": int(min(100, max(30, total_score))) if total_score > 0 else None,
        "isScored": total_score > 0,
    }

    return result


# ─────────────────────────────────────────────────────────────────────
# WATCHLIST narrative (replaces generate_watchlist_narrative)
# ─────────────────────────────────────────────────────────────────────

def _why_on_watchlist(signal_data, watchlist_data):
    readiness = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    entry_eligible = watchlist_data.get("entry_eligible") or signal_data.get("entry_eligible", False)
    conf_count = signal_data.get("confirmation_count", 0) or watchlist_data.get("confirmation_count", 0)
    strategy_type = signal_data.get("strategy_type") or watchlist_data.get("strategy_type", "momentum")

    if strategy_type == "mean_reversion":
        return f"Mean reversion bounce candidate (readiness {readiness:.0f}, {conf_count}/10 confirmations). Watch for exhaustion, not a new entry."
    if entry_eligible:
        if tier == "STRONG_NOW":
            return f"Entry-ready at STRONG_NOW tier (readiness {readiness:.0f}, {conf_count}/10 confirmations). Highest conviction — bot will buy with 2.0x sizing."
        else:
            return f"Entry-ready at NOW tier (readiness {readiness:.0f}, {conf_count}/10 confirmations). Bot will buy when cash is available."
    elif tier == "WATCH":
        gap = 77 - readiness
        missing_conf = max(0, 5 - conf_count)
        if gap > 0 and missing_conf > 0:
            return f"WATCH tier (readiness {readiness:.0f}). Needs {gap:.0f} more readiness points and {missing_conf} more confirmations to reach entry gate (77 readiness, 5/10 conf)."
        elif gap > 0:
            return f"WATCH tier (readiness {readiness:.0f}). Needs {gap:.0f} more readiness points to reach entry gate (77 readiness, 5/10 conf)."
        elif missing_conf > 0:
            return f"WATCH tier (readiness {readiness:.0f}). Close to entry but missing {missing_conf} confirmations (currently {conf_count}/10, need 5)."
        else:
            return f"WATCH tier (readiness {readiness:.0f}). Close to entry but waiting for price above EMA."
    elif tier == "MONITOR":
        return f"MONITOR tier (readiness {readiness:.0f}). Not close to entry — tracking for signal improvement."
    else:
        return f"Tracking in universe — no active signal (readiness {readiness:.0f})."


def _what_triggers_buy(signal_data, watchlist_data):
    readiness = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    conf_count = signal_data.get("confirmation_count", 0) or watchlist_data.get("confirmation_count", 0)
    confirmations = signal_data.get("confirmations", {})
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")

    if tier in ("STRONG_NOW", "NOW") and watchlist_data.get("entry_eligible"):
        return "Entry conditions met — waiting for portfolio cash to deploy."

    missing = []
    if readiness < 77:
        missing.append(f"readiness needs to reach 77 (currently {readiness:.0f})")
    if conf_count < 5:
        missing.append(f"needs 5+ confirmations (currently {conf_count})")

    conf_fields = {
        "volume_confirmed": "volume confirmation",
        "macd_turning": "MACD turning positive",
        "above_ema": "price above 20-day EMA",
        "sector_strong": "sector strength",
        "intraday_confirmed": "intraday momentum",
        "options_confirmed": "low IV (bullish options)",
        "relvol_confirmed": "relative volume surge",
        "vwap_confirmed": "price above VWAP",
    }
    missing_confs = []
    for key, label in conf_fields.items():
        if not confirmations.get(key, False):
            missing_confs.append(label)

    if missing_confs and len(missing_confs) <= 4:
        missing.append(f"missing: {', '.join(missing_confs[:3])}")

    if not missing:
        return "All conditions met — should trigger soon."

    return "To trigger entry: " + "; ".join(missing) + "."


def _watchlist_risk(signal_data, watchlist_data):
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    vol = signal_data.get("volatility_20d")
    iv = signal_data.get("options_implied_vol")
    rsi = signal_data.get("rsi14", 50)

    risks = []
    sector_risks = {
        "Semiconductors": "chip cycle and capex volatility",
        "AI/Growth": "AI sentiment shifts and rate sensitivity",
        "Tech Giants": "antitrust and growth deceleration",
        "Fintech": "regulation and credit losses",
        "Consumer/Platform": "consumer spending cyclicality",
        "Cloud/Data": "enterprise IT budgets",
        "EV/Mobility": "EV price wars and demand",
        "Retail/Lifestyle": "discretionary spending",
        "Cybersecurity": "competitive pricing",
        "Healthcare": "drug pricing policy",
        "Energy": "oil price swings",
        "Industrials": "cyclical demand",
        "Financials": "credit and rate cycles",
        "Communications": "advertising and cord-cutting",
        "Tech Expansion": "legacy decline and execution",
    }
    sr = sector_risks.get(sector)
    if sr:
        risks.append(sr)

    if vol and isinstance(vol, (int, float)) and vol > 0.40:
        risks.append(f"high volatility ({vol*100:.0f}%)")
    if iv and isinstance(iv, (int, float)) and iv > 0.6:
        risks.append(f"elevated IV ({iv*100:.0f}%)")
    if rsi and isinstance(rsi, (int, float)) and rsi > 75:
        risks.append("RSI overbought — pullback risk")

    if not risks:
        risks.append("standard equity market risk")

    return "Risks: " + ", ".join(risks) + "."


def generate_watchlist_narrative(symbol, signal_data, watchlist_data):
    total_score = signal_data.get("total_score", 0)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or COMPANY_NAMES.get(symbol, symbol)
    price = watchlist_data.get("price") or signal_data.get("price", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "TRACKING")
    readiness = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)

    return {
        "symbol": symbol,
        "company": company,
        "whatItIs": _what_it_is(symbol, signal_data, sector, company),
        "whyOnWatchlist": _why_on_watchlist(signal_data, watchlist_data),
        "whatTriggersBuy": _what_triggers_buy(signal_data, watchlist_data),
        "catalyst": _what_moves_it(signal_data),
        "risk": _watchlist_risk(signal_data, watchlist_data),
        "total_score": round(total_score, 1) if total_score else None,
        "readiness_score": round(readiness, 1) if readiness else None,
        "tier": tier,
        "price": price,
        "sector": sector,
        "last_updated": now().isoformat().replace("+00:00", "Z"),
    }


def signal_tier(total_score):
    if total_score >= 55:
        return "NOW"
    if total_score >= 45:
        return "WATCH"
    if total_score > 0:
        return "MONITOR"
    return "TRACKING"


def generate_popup_content():
    _market_open = is_market_open()
    if not _market_open:
        logger.info("Markets closed — generating with available data")

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
    logger.info("=== STONK.AI Popup Content Generator v3 Starting ===")
    result = generate_popup_content()
    if result:
        logger.info(f"Successfully generated content for {len(result['holdings'])} positions")
    else:
        logger.info("No popup data generated")