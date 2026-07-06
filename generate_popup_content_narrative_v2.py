#!/usr/bin/env python3
"""
Narrative v5.5 wrapper — expanded human sentence libraries.
No assembly-line fragments; each field picks from a large set of full sentences.
"""
import sys, os, json, random
from pathlib import Path

BOT_DIR = Path("/opt/stonk-ai")
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)

import importlib.util
_spec = importlib.util.spec_from_file_location("gpc", str(BOT_DIR / "generate_popup_content_v3.py"))
gpc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpc)

# ── Helpers ─────────────────────────────────────────────────────────

def _iv_scalar(iv):
    if iv is None:
        return None
    if isinstance(iv, dict):
        return iv.get("iv_30d") or iv.get("options_implied_vol") or None
    try:
        return float(iv)
    except (TypeError, ValueError):
        return None

def _price_fmt(p):
    return f"${p:.2f}"

def _hash_choice(symbol, options, salt=0):
    return options[(sum(ord(c) for c in symbol) + salt) % len(options)]

def _clean_headline(h):
    if not h:
        return None
    h = h.strip()
    if len(h) > 90:
        h = h[:87] + "..."
    return h

# ── What it is ───────────────────────────────────────────────────────

def new_what_it_is(symbol, signal_data, sector, company):
    note = gpc._COMPANY_NOTES.get(symbol)
    if note:
        return note if note.endswith((".", "!", "?")) else note + "."
    sector_voices = {
        "Semiconductors": [
            f"{symbol} is a chip name; capex cycles and AI share shifts set the price.",
            f"{symbol}: levered to semiconductor capex and the AI build-out.",
            f"{symbol} makes the silicon that powers data centers and devices.",
            f"{symbol} — a semiconductor name that lives and dies by data-center spend.",
        ],
        "Fintech": [
            f"{symbol} is a fintech; rates, credit, and regulation move it.",
            f"{symbol}: a financial-services disruptor swimming in credit-cycle water.",
            f"{symbol} — fintech name, sensitive to funding costs and regulation.",
            f"{symbol} makes money where banking meets software.",
        ],
        "Retail/Lifestyle": [
            f"{symbol} is a consumer name; household budgets are the macro dial.",
            f"{symbol}: retail/consumer discretionary, tied to housing turnover and rates.",
            f"{symbol} sells into wallets that open and close with the cycle.",
            f"{symbol} — consumer-facing name that feels the macro pulse fast.",
        ],
        "Cloud/Data": [
            f"{symbol} is cloud/data infrastructure; enterprise budgets are the driver.",
            f"{symbol}: enterprise software/infrastructure tied to IT spend.",
            f"{symbol} — the picks-and-shovels of data centers.",
        ],
        "Travel/Leisure": [
            f"{symbol}: travel/leisure name that moves with consumer confidence and jet fuel.",
            f"{symbol} makes money when people book trips.",
        ],
    }
    voices = sector_voices.get(sector, [f"{symbol} — {sector.lower()} name."])
    return _hash_choice(symbol, voices)

# ── Holdings: Bot thinking ───────────────────────────────────────────

def new_bot_thinking(symbol, position, signal_data, watchlist_data, stops):
    pl = position.get("unrealized_plpc", 0) or 0
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    mom = signal_data.get("momentum_20d", 0) or 0
    hard = stops.get("hard_stop", 0)
    price = position.get("current", 0) or 0
    conf = signal_data.get("confirmations", {}) or {}
    ema_ok = conf.get("above_ema", False)
    macd_ok = conf.get("macd_turning", False)
    vol_ok = conf.get("volume_confirmed", False)
    rsi_ok = conf.get("rsi_neutral_not_overbought", False)

    sentences = []

    if tier == "STRONG_NOW":
        if pl > 8:
            sentences.append(_hash_choice(symbol, [
                "This is the bot's highest-conviction live bet, and the tape is agreeing.",
                "Highest-conviction position. The market has noticed the setup.",
                "A-tier setup moving the right way — the bot is letting it run.",
                "This is the strongest signal the bot holds right now, and it's working.",
                "Top-tier conviction. Price action is backing the thesis so far.",
            ]))
        elif pl > 0:
            if ema_ok and macd_ok and vol_ok:
                sentences.append("Highest-conviction setup with trend, momentum, and volume all green. The bot would add if cash allowed.")
            else:
                sentences.append(_hash_choice(symbol, [
                    "Highest-conviction setup. The bot already has size, so it's not chasing.",
                    "A-tier signal. Sizing rules cap how much more the bot can add.",
                    "Strong setup; the only missing input is dry powder.",
                    "The signal is green, but the position has enough room already.",
                ]))
        else:
            sentences.append(_hash_choice(symbol, [
                "Highest-conviction setup, currently underwater. The hard stop is the line in the sand.",
                "A-tier thesis in a drawdown. Bot is giving it room until the stop gets hit or the trend reclaims.",
                "Strong signal, weak price. The stop decides whether the thesis survives.",
            ]))
    elif tier == "NOW":
        if pl > 5:
            sentences.append(_hash_choice(symbol, [
                "Clean setup, working higher. Bot is holding for continuation.",
                "Good signal, good price action. No reason to take profits yet.",
                "The setup is valid and the P&L is green. Bot is being patient.",
            ]))
        elif pl > -2:
            sentences.append(_hash_choice(symbol, [
                "Clean setup, roughly flat. No reason to exit, no edge to add.",
                "Valid signal, no real move yet. Bot is waiting for the tape to show its hand.",
                "The thesis is intact; price just hasn't picked a direction.",
            ]))
        else:
            sentences.append(_hash_choice(symbol, [
                "Clean setup, underwater. Giving it room until the stop or a trend reclaim.",
                "Valid signal, but price is soft. The bot is honoring the stop.",
                "Thesis still alive; price isn't. Stop below will end it.",
            ]))
    elif tier == "WATCH":
        sentences.append(_hash_choice(symbol, [
            "Readiness has slipped. Bot is watching, not adding.",
            "Signal cooled into WATCH. The bot is on the sidelines for now.",
            "No longer entry-ready. Bot is waiting for confirmation to return.",
        ]))
    else:
        sentences.append(_hash_choice(symbol, [
            "Signal has faded. Bot is on exit watch.",
            "This has dropped to MONITOR. An exit is likely if it doesn't recover.",
            "Thesis is weakening. Bot is prepared to close the position.",
        ]))

    if mom > 0.25:
        sentences.append(_hash_choice(symbol, ["Momentum is running hot.", "The trend is pushing hard higher.", "Price momentum is clearly bullish."], salt=1))
    elif mom < -0.25:
        sentences.append(_hash_choice(symbol, ["Momentum is negative right now.", "The trend is working against the position.", "Bearish momentum is in control."], salt=1))

    if price and hard and 0 < price <= hard * 1.04:
        sentences.append(f"Price is within 4% of the hard stop at {_price_fmt(hard)}.")

    return " ".join(sentences)

# ── Holdings: P&L context ──────────────────────────────────────────

def new_pnl_context(position, signal_data, stops):
    pl = position.get("unrealized_plpc", 0) or 0
    price = position.get("current", 0) or 0
    avg = position.get("avg_entry", 0) or 0
    hard = stops.get("hard_stop", 0)

    if pl >= 15:
        s = random.choice([
            f"Deep in profit — up {pl:.1f}%",
            f"Crushing it, +{pl:.1f}%",
            f"Up {pl:.1f}% from entry",
            f"Big winner so far, +{pl:.1f}%",
        ])
    elif pl >= 5:
        s = random.choice([
            f"Up {pl:.1f}% — working in the right direction",
            f"Green by {pl:.1f}%, trend backing the thesis",
            f"Holding a {pl:.1f}% gain",
        ])
    elif pl >= -2:
        s = random.choice([
            "Sideways from entry",
            "Essentially flat since entry",
            "No real move yet",
            "Waiting for the tape to pick a direction",
            "Stuck near breakeven",
        ])
    elif pl >= -8:
        s = random.choice([
            f"Under pressure, down {abs(pl):.1f}%",
            f"Soft, down {abs(pl):.1f}%",
            f"Losing {abs(pl):.1f}% but stop still intact",
        ])
    else:
        s = f"Down {abs(pl):.1f}%; hard stop at {_price_fmt(hard)} is the backstop"

    if price and avg:
        s += f". Entry {_price_fmt(avg)}, now {_price_fmt(price)}."
    else:
        s += "."

    return s

# ── Holdings: Catalyst ─────────────────────────────────────────────

def new_what_moves_it(symbol, signal_data):
    news = signal_data.get("news")
    headline = None
    if isinstance(news, dict):
        headline = news.get("alpaca_headline") or news.get("sample_headline")
    mom = signal_data.get("momentum_20d", 0) or 0

    if headline:
        h = _clean_headline(headline)
        leads = [
            f"The tape is moving on: “{h}.”",
            f"Latest headline: “{h}.”",
            f"News flow: “{h}.”",
            f"Worth watching: “{h}.”",
            f"The catalyst du jour: “{h}.”",
            f"What's driving it: “{h}.”",
            f"Headline in play: “{h}.”",
        ]
        text = _hash_choice(symbol, leads)
    else:
        text = "No fresh headline — the move is purely technical."

    if mom > 0.20:
        text += f" 20-day momentum is +{mom*100:.0f}%."
    elif mom < -0.20:
        text += f" 20-day momentum is {mom*100:.0f}%."

    return text

# ── Holdings: Risk ─────────────────────────────────────────────────

def new_what_kills_it(symbol, position, signal_data, watchlist_data, stops):
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    hard = stops.get("hard_stop", 0)
    price = position.get("current", 0) or 0

    cr = gpc._COMPANY_RISKS.get(symbol)
    if cr:
        risk_body = cr
    else:
        sector_lines = {
            "Semiconductors": "a chip cycle downturn, capex cuts, or AI share loss. The wrong headline can reprice it overnight.",
            "Fintech": "regulatory pressure, credit-loss spikes, or a funding-cost squeeze.",
            "Consumer/Platform": "a consumer-spending pullback and margin compression.",
            "Retail/Lifestyle": "a housing freeze or discretionary-spending slowdown.",
            "Cloud/Data": "enterprise budget freezes and AI investment fatigue.",
            "Travel/Leisure": "a slowdown in travel demand or rising input costs.",
        }
        risk_body = sector_lines.get(sector, "a macro shift or earnings miss.")

    if not risk_body.endswith((".", "!", "?")):
        risk_body += "."
    risk = f"The bear case is {risk_body}"

    if price and hard and hard > 0:
        risk += f" A close below {_price_fmt(hard)} closes the thesis."

    return risk

# ── Watchlist: Why it's on the radar ───────────────────────────────

def new_why_on_watchlist(symbol, signal_data, watchlist_data):
    readiness = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    conf_count = signal_data.get("confirmation_count", 0)

    if tier == "STRONG_NOW":
        return _hash_choice(symbol, [
            f"Readiness {readiness:.0f}, {conf_count} factors green — highest-conviction tier. Bot buys the moment cash is free.",
            f"Locked and loaded. Readiness {readiness:.0f} with {conf_count} confirmations firing.",
            f"A-tier setup: {conf_count} confirmations, readiness {readiness:.0f}.",
            f"Top of the buy list. Readiness {readiness:.0f}, {conf_count} factors aligned.",
        ])
    if tier == "NOW":
        return _hash_choice(symbol, [
            f"Readiness {readiness:.0f} — an entry-ready setup waiting on portfolio cash.",
            f"Clean setup, {conf_count} factors aligned. Just needs room in the portfolio.",
            f"On deck: readiness {readiness:.0f}, {conf_count} confirmations.",
            f"Ready to buy at readiness {readiness:.0f}. Cash is the only gate.",
        ])
    if tier == "WATCH":
        return _hash_choice(symbol, [
            f"Readiness {readiness:.0f} — building a case, but missing a few confirmations.",
            f"Interesting, but not urgent. Readiness {readiness:.0f} keeps it on the radar.",
            f"WATCH tier: {conf_count} confirmations at readiness {readiness:.0f}. One more signal and it gets interesting.",
        ])
    return f"Readiness {readiness:.0f} — early watch, not close to an entry."

# ── Watchlist: What triggers buy ─────────────────────────────────────

def new_what_triggers_buy(symbol, signal_data, watchlist_data):
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    readiness = signal_data.get("readiness_score", 0)
    conf = signal_data.get("confirmations", {}) or {}

    if tier == "STRONG_NOW":
        return _hash_choice(symbol, [
            "Gate is open. The only missing input is cash.",
            "Highest-conviction setup; the trigger is cash availability.",
            "Signal is green. It enters as soon as portfolio cash opens up.",
            "Ready to buy. Just needs an open cash slot.",
            "Top of the queue. Cash is the only gate.",
        ])
    if tier == "NOW":
        return _hash_choice(symbol, [
            f"Readiness {readiness:.0f}. Bot buys when cash frees up and the next candle confirms.",
            f"Clean setup at readiness {readiness:.0f}. Entry on cash release.",
            f"Wants to buy at readiness {readiness:.0f} — waiting for portfolio room.",
        ])

    reasons = []
    if not conf.get("above_ema"):
        reasons.append("reclaim the 20-day EMA")
    if not conf.get("volume_confirmed"):
        reasons.append("see volume confirm")
    if not conf.get("macd_turning"):
        reasons.append("get MACD turning positive")
    if not conf.get("options_confirmed"):
        reasons.append("see options flow turn bullish")

    if reasons:
        return "Bot buys when " + " and ".join(reasons[:2]) + "."
    return "Waiting for readiness to climb back above 72."

# ── Watchlist: Risk ────────────────────────────────────────────────

def new_watchlist_risk(signal_data, watchlist_data):
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    vol = signal_data.get("volatility_20d") or 0
    iv = _iv_scalar(signal_data.get("options_implied_vol"))

    cr = gpc._COMPANY_RISKS.get(signal_data.get("symbol", ""))
    if cr:
        risk = cr
    else:
        sector_lines = {
            "Semiconductors": "a chip cycle downturn or AI capex cut.",
            "Fintech": "regulatory pressure or a credit-loss spike.",
            "Consumer/Platform": "consumer spending pullback.",
            "Retail/Lifestyle": "a housing freeze or discretionary slowdown.",
            "Cloud/Data": "enterprise budget freeze.",
            "Travel/Leisure": "a travel demand slowdown.",
        }
        risk = sector_lines.get(sector, "a macro shift or earnings miss.")

    if not risk.endswith((".", "!", "?")):
        risk += "."

    extra = []
    if vol and vol > 0.45:
        extra.append(f"volatility is {vol*100:.0f}% annualized")
    if iv and iv > 0.6:
        extra.append(f"IV is {iv*100:.0f}%")
    if extra:
        risk = risk[:-1] + " — " + " and ".join(extra) + "."

    return f"What kills it: {risk}"

# ── Wrapper hooks ───────────────────────────────────────────────────

_orig_generate_dynamic_narrative = gpc.generate_dynamic_narrative

def new_generate_dynamic_narrative(symbol, position, watchlist_data, signal_data, risk_config, risk_state):
    result = _orig_generate_dynamic_narrative(symbol, position, watchlist_data, signal_data, risk_config, risk_state)
    pl_percent = position.get("unrealized_plpc", 0) or 0
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or gpc.COMPANY_NAMES.get(symbol, symbol)
    stops = gpc.get_stop_levels(symbol, position, risk_config, risk_state, signal_data)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")

    result.update({
        "whatItIs": new_what_it_is(symbol, signal_data, sector, company),
        "whyWeOwnIt": new_bot_thinking(symbol, position, signal_data, watchlist_data, stops),
        "howItsDoing": new_pnl_context(position, signal_data, stops),
        "catalyst": new_what_moves_it(symbol, signal_data),
        "risk": new_what_kills_it(symbol, position, signal_data, watchlist_data, stops),
        "confidence": "Solid." if pl_percent >= -3 else "Shaky." if pl_percent >= -8 else "Thin.",
        "entryReason": new_bot_thinking(symbol, position, signal_data, watchlist_data, stops),
        "stopReason": f"Hard stop {_price_fmt(stops['hard_stop'])}; trailing {_price_fmt(stops['trailing_stop'])}",
        "entry_eligible": tier in ("STRONG_NOW", "NOW"),
    })
    return result

gpc.generate_dynamic_narrative = new_generate_dynamic_narrative

_orig_generate_watchlist_narrative = gpc.generate_watchlist_narrative

def new_generate_watchlist_narrative(symbol, signal_data, watchlist_data):
    result = _orig_generate_watchlist_narrative(symbol, signal_data, watchlist_data)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or gpc.COMPANY_NAMES.get(symbol, symbol)

    result.update({
        "whatItIs": new_what_it_is(symbol, signal_data, sector, company),
        "whyOnWatchlist": new_why_on_watchlist(symbol, signal_data, watchlist_data),
        "whatTriggersBuy": new_what_triggers_buy(symbol, signal_data, watchlist_data),
        "catalyst": new_what_moves_it(symbol, signal_data),
        "risk": new_watchlist_risk(signal_data, watchlist_data),
    })
    return result

gpc.generate_watchlist_narrative = new_generate_watchlist_narrative

generate_popup_content = gpc.generate_popup_content
get_stop_levels = gpc.get_stop_levels
load_signals_map = gpc.load_signals_map

if __name__ == "__main__":
    gpc.generate_popup_content()
