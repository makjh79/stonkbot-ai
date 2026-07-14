import re

path = "/opt/stonk-ai/generate_popup_content.py"

with open(path, "r") as f:
    content = f.read()

old_func = """def _why_on_watchlist(signal_data, watchlist_data):
    \"\"\"Why this name is on the list. Punchy, data-first, human.\"\"\"
    r = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    entry = watchlist_data.get("entry_eligible") or signal_data.get("entry_eligible", False)
    c = _visible_confirmation_count(signal_data)

    if tier == "STRONG_NOW" and entry:
        return f"Locked and loaded. Readiness at {r:.0f} with {c} green lights firing. Highest-conviction tier — bot deploys 1.5x size the second cash clears."
    elif tier == "NOW" and entry:
        return f"Entry-ready. Readiness at {r:.0f}, {c} confirmations in the green. Bot will buy as soon as portfolio cash frees up."
    elif tier == "WATCH" and entry:
        return f"Mean reversion play. Readiness at {r:.0f}, {c} lights green. Momentum is below the 72 gate but the setup is mathematically valid."
    elif tier == "WATCH":
        gap = max(0, 72 - r)
        if gap > 5 and c < 2:
            return f"Watching from the sidelines. Readiness at {r:.0f} — {gap:.0f} points short of the 72 gate. Only {c} confirmation(s). Needs both momentum and confirmations."
        elif gap > 5:
            return f"Watching from the sidelines. Readiness at {r:.0f} — {gap:.0f} points short of the 72 gate. Already has {c} confirmations green but needs more momentum."
        elif gap > 0 and c < 2:
            return f"Close. Readiness at {r:.0f} — only {gap:.0f} shy of the gate. Only {c} confirmation(s). Needs 2+ green lights to fire."
        elif gap > 0:
            return f"Close. Readiness at {r:.0f} — just {gap:.0f} shy of the 72 entry gate. Already has {c} confirmations green. Waiting on momentum."
        elif c < 2:
            return f"At the gate. Readiness at {r:.0f} clears the 72 gate but only {c} confirmation firing. Needs 2+ green lights to pull the trigger."
        else:
            return f"Close. Readiness at {r:.0f} clears the gate with {c} confirmations but tracking as WATCH."
    elif tier == "MONITOR":
        return f"Tracking only. Readiness at {r:.0f} — nowhere near the entry zone. Waiting for a signal revival."
    else:
        return f"Quiet in the tape. Readiness at {r:.0f}. No trade today.""""

new_func = """def _missing_factors(signal_data):
    \"\"\"List which confirmation factors are NOT green, for gap diagnosis.\"\"\"
    conf = signal_data.get("confirmations", {})
    # momentum may live at top-level or inside confirmations
    mom_score = conf.get("momentum_score", signal_data.get("momentum_score", 0))
    missing = []
    if mom_score < 50:
        missing.append("momentum")
    rsi = conf.get("rsi_signal", "")
    if rsi not in ("bullish", "overbought"):
        missing.append("RSI")
    if not conf.get("volume_confirmed"):
        missing.append("volume")
    if not conf.get("macd_turning"):
        missing.append("MACD")
    if not conf.get("above_ema"):
        missing.append("EMA")
    if not conf.get("sector_strong"):
        missing.append("sector")
    if not conf.get("intraday_confirmed"):
        missing.append("intraday")
    if not conf.get("options_confirmed"):
        missing.append("options")
    if not conf.get("earnings_confirmed"):
        missing.append("PEAD")
    return missing


def _why_on_watchlist(signal_data, watchlist_data):
    \"\"\"Why this name is on the list. Punchy, data-first, human.\"\"\"
    r = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    entry = watchlist_data.get("entry_eligible") or signal_data.get("entry_eligible", False)
    c = _visible_confirmation_count(signal_data)

    if tier == "STRONG_NOW" and entry:
        return f"Locked and loaded. Readiness at {r:.0f} with {c} green lights firing. Highest-conviction tier — bot deploys 1.5x size the second cash clears."
    elif tier == "NOW" and entry:
        return f"Entry-ready. Readiness at {r:.0f}, {c} confirmations in the green. Bot will buy as soon as portfolio cash frees up."
    elif tier == "WATCH" and entry:
        return f"Mean reversion play. Readiness at {r:.0f}, {c} lights green. Momentum is below the 72 gate but the setup is mathematically valid."
    elif tier == "WATCH":
        gap = max(0, 72 - r)
        missing = _missing_factors(signal_data)
        missing_text = nice_join(missing[:3]) + ("+ others" if len(missing) > 3 else "") if missing else "supporting factors"
        if gap > 5 and c < 2:
            return f"Watching from the sidelines. Readiness at {r:.0f} — {gap:.0f} points short of the 72 gate. Only {c} confirmation(s). Needs both momentum and confirmations."
        elif gap > 5:
            return f"Watching from the sidelines. Readiness at {r:.0f} — {gap:.0f} points short of the 72 gate. Already has {c} confirmations green but needs more {missing_text}."
        elif gap > 0 and c < 2:
            return f"Close. Readiness at {r:.0f} — only {gap:.0f} shy of the gate. Only {c} confirmation(s). Needs 2+ green lights to fire."
        elif gap > 0:
            return f"Close. Readiness at {r:.0f} — just {gap:.0f} shy of the 72 entry gate. Already has {c} confirmations green. Missing: {missing_text}."
        elif c < 2:
            return f"At the gate. Readiness at {r:.0f} clears the 72 gate but only {c} confirmation firing. Needs 2+ green lights to pull the trigger."
        else:
            return f"Close. Readiness at {r:.0f} clears the gate with {c} confirmations but tracking as WATCH."
    elif tier == "MONITOR":
        return f"Tracking only. Readiness at {r:.0f} — nowhere near the entry zone. Waiting for a signal revival."
    else:
        return f"Quiet in the tape. Readiness at {r:.0f}. No trade today.""""

if old_func in content:
    content = content.replace(old_func, new_func, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Pattern not found")
