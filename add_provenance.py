import re

path = '/opt/stonk-ai/generate_popup_content.py'
with open(path) as f: src = f.read()

# Add sources to generate_dynamic_narrative return dict
old_dn_return = """    result = {
        "whatItIs": _what_it_is(symbol, signal_data, sector, company),
        "whyWeOwnIt": _why_bot_bought(signal_data, position, thesis_data),
        "howItsDoing": _how_its_doing(position, signal_data, watchlist_data),
        "catalyst": _what_moves_it(signal_data),
        "risk": _what_kills_it(symbol, position, signal_data, watchlist_data, stops),
        "confidence": _confidence_level(position, signal_data, watchlist_data),
        "signal": signal_data.get("tier", "MONITOR"),
        "tier": watchlist_data.get("signal_tier", "MONITOR"),
        "readiness_score": readiness,
        "entry_eligible": entry_eligible,
        "tier_reason": tier_reason,
        "confirmations": signal_data.get("confirmations", {}),
        "confirmation_count": signal_data.get("confirmation_count", 0),
        "momentumScore": round(momentum_score, 1) if momentum_score > 0 else None,
        "drivers": _generate_factor_analysis(signal_data) if signal_data else [],
        "company": company or symbol,
        "strategyType": signal_data.get("strategy_type", "unknown"),
    }"""

new_dn_return = """    result = {
        "whatItIs": _what_it_is(symbol, signal_data, sector, company),
        "whyWeOwnIt": _why_bot_bought(signal_data, position, thesis_data),
        "howItsDoing": _how_its_doing(position, signal_data, watchlist_data),
        "catalyst": _what_moves_it(signal_data),
        "risk": _what_kills_it(symbol, position, signal_data, watchlist_data, stops),
        "confidence": _confidence_level(position, signal_data, watchlist_data),
        "signal": signal_data.get("tier", "MONITOR"),
        "tier": watchlist_data.get("signal_tier", "MONITOR"),
        "readiness_score": readiness,
        "entry_eligible": entry_eligible,
        "tier_reason": tier_reason,
        "confirmations": signal_data.get("confirmations", {}),
        "confirmation_count": signal_data.get("confirmation_count", 0),
        "momentumScore": round(momentum_score, 1) if momentum_score > 0 else None,
        "drivers": _generate_factor_analysis(signal_data) if signal_data else [],
        "company": company or symbol,
        "strategyType": signal_data.get("strategy_type", "unknown"),
        "sources": {
            "whatItIs":             "Company profile (internal dataset) | Alpaca ticker lookup",
            "whyWeOwnIt":           "StonkBOT signal engine | Alpaca bars, options, news",
            "howItsDoing":          "StonkBOT signal engine | Alpaca positions + bars",
            "catalyst":             "Alpaca newsfeed + Alpaca bars",
            "risk":                 "StonkBOT risk engine | Alpaca ATR, IV, vol, correlation",
            "confidence":           "StonkBOT signal engine | Alpaca bars, IV, options",
            "confirmations":        "StonkBOT signal engine | Alpaca bars, options, news, IV",
            "momentumScore":        "Alpaca bars API (20d / 50d returns)",
            "price":                "Alpaca latest quote",
            "avgEntry":             "Alpaca positions API",
            "alpacaNewsHeadline":   "Alpaca news API",
            "rsi":                  "Alpaca bars API (14d)",
            "volatility20d":        "Alpaca bars API",
            "spyCorr20d":           "Alpaca bars API",
            "atr14":                "Alpaca bars API",
            "hardStop":             "StonkBOT risk engine (Alpaca ATR-derived)",
            "trailingStop":         "StonkBOT risk engine (Alpaca ATR-derived)",
            "vwapStop":             "StonkBOT risk engine (Alpaca intraday VWAP)",
            "dailyVwap":            "Alpaca bars API",
            "prevClose":            "Alpaca bars API",
            "intradayVwap":          "Alpaca bars API",
            "intradayVolRatio":     "Alpaca bars API",
            "vwapDeviation":        "Alpaca bars API",
            "optionsImpliedVol":    "Alpaca options API",
            "drivers":              "StonkBOT signal engine (Alpaca bars, IV, news)",
            "aiScore":              "StonkBOT engine (Alpaca-derived composite)",
        },
    }"""

# Check old block exists (may have been reformatted)
if old_dn_return.strip() not in src:
    print("⚠️ generate_dynamic_narrative return block not found exactly — checking loose match...")
    # Try to replace just around the dict
    pat = re.compile(
        r'(result\s*=\s*\{.*?"strategyType":\s*signal_data\.get\("strategy_type",\s*"unknown"\),\n\s*\})(?!\s*[,}])?',
        re.DOTALL,
    )
    m = pat.search(src)
    if m:
        src = src[:m.start()] + new_dn_return + src[m.end():]
        print("Replaced generate_dynamic_narrative return via regex")
    else:
        print("⚠️ Could not find generate_dynamic_narrative return block")
else:
    src = src.replace(old_dn_return.strip(), new_dn_return.strip())
    print("Replaced generate_dynamic_narrative return block")

# Add sources to generate_watchlist_narrative return dict
old_wn_return = """    return {
        "symbol": symbol,
        "company": company,
        "whatItIs": _what_it_is(symbol, signal_data, sector, company),
        "whyOnWatchlist": _why_on_watchlist(signal_data, watchlist_data),
        "whatTriggersBuy": _what_triggers_buy(signal_data, watchlist_data),
        "catalyst": _what_moves_it(signal_data),
        "risk": _watchlist_risk(signal_data, watchlist_data),
        "signal": signal or "MONITOR",
        "tier": watchlist_data.get("signal_tier") or signal or "MONITOR",
        "readiness": readiness,
        "entry_eligible": entry_eligible,
        "tier_reason": tier_reason,
    }"""

new_wn_return = """    return {
        "symbol": symbol,
        "company": company,
        "whatItIs": _what_it_is(symbol, signal_data, sector, company),
        "whyOnWatchlist": _why_on_watchlist(signal_data, watchlist_data),
        "whatTriggersBuy": _what_triggers_buy(signal_data, watchlist_data),
        "catalyst": _what_moves_it(signal_data),
        "risk": _watchlist_risk(signal_data, watchlist_data),
        "signal": signal or "MONITOR",
        "tier": watchlist_data.get("signal_tier") or signal or "MONITOR",
        "readiness": readiness,
        "entry_eligible": entry_eligible,
        "tier_reason": tier_reason,
        "sources": {
            "whatItIs": "Company profile (internal dataset) | Alpaca ticker lookup",
            "whyOnWatchlist": "StonkBOT signal engine | Alpaca bars, options, news",
            "whatTriggersBuy": "StonkBOT signal engine | Alpaca bars, options, news",
            "catalyst": "Alpaca newsfeed + Alpaca bars",
            "risk": "StonkBOT risk engine | Alpaca IV, vol, correlation",
            "readiness": "StonkBOT signal engine | Alpaca bars, options, IV",
            "confirmations": "StonkBOT signal engine | Alpaca bars, options, news, IV",
        },
    }"""

if old_wn_return.strip() in src:
    src = src.replace(old_wn_return.strip(), new_wn_return.strip())
    print("Replaced generate_watchlist_narrative return block")
else:
    pat2 = re.compile(
        r'(return\s*\{.*?"tier_reason":\s*tier_reason,\n\s*\})(?!\s*[,}])?',
        re.DOTALL,
    )
    m2 = pat2.search(src)
    if m2:
        src = src[:m2.start()] + new_wn_return + src[m2.end():]
        print("Replaced generate_watchlist_narrative return via regex")
    else:
        print("⚠️ Could not find generate_watchlist_narrative return block")

with open(path, 'w') as f:
    f.write(src)
print("Done")
