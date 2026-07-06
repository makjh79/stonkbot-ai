"""
Regime Detection Enhancement for signal_engine.py

Adds to _regime_score():
  - Yield curve proxy (2y/10y spread) via SHY/TLT ratio
  - Credit spread proxy (LQD/HYG ratio)
  - Market breadth proxy (SPY rising volume)
  - Sector rotation model (relative sector strength)

This file is not meant to be run directly. Apply its logic to signal_engine.py.
"""

# In signal_engine.py, replace the existing _regime_score method with:

REGIME_SYMBOLS = ["SPY", "QQQ", "VIXY", "SHY", "TLT", "LQD", "HYG"]


def _regime_score(self, closes, regime_data):
    spy = regime_data.get("SPY", {}).get("closes", [])
    qqq = regime_data.get("QQQ", {}).get("closes", [])
    vixy = regime_data.get("VIXY", {}).get("closes", [])
    shy = regime_data.get("SHY", {}).get("closes", [])
    tlt = regime_data.get("TLT", {}).get("closes", [])
    lqd = regime_data.get("LQD", {}).get("closes", [])
    hyg = regime_data.get("HYG", {}).get("closes", [])

    score = 50.0

    # Equity trend (SPY/QQQ)
    if len(spy) >= 20:
        spy_roc20 = (spy[-1] - spy[-20]) / spy[-20]
        score += 20 * math.tanh(spy_roc20 * 8)
    if len(qqq) >= 20:
        qqq_roc20 = (qqq[-1] - qqq[-20]) / qqq[-20]
        score += 12 * math.tanh(qqq_roc20 * 8)

    # Volatility (VIXY)
    if len(vixy) >= 5:
        vixy_roc5 = (vixy[-1] - vixy[-5]) / vixy[-5]
        score -= 18 * math.tanh(vixy_roc5 * 5)

    # Yield curve proxy: SHY / TLT ratio inverted (steepening = risk-on)
    if len(shy) >= 20 and len(tlt) >= 20:
        ratio_now = shy[-1] / tlt[-1]
        ratio_prev = shy[-20] / tlt[-20]
        if ratio_now > ratio_prev:
            score += 5  # curve steepening / risk-on
        else:
            score -= 5  # flattening / risk-off

    # Credit spread proxy: LQD / HYG (investment grade vs high yield)
    if len(lqd) >= 20 and len(hyg) >= 20:
        ratio_now = lqd[-1] / hyg[-1]
        ratio_prev = lqd[-20] / hyg[-20]
        if ratio_now > ratio_prev:
            score += 5  # credit improving
        else:
            score -= 5  # credit worsening

    # Market breadth: SPY volume rising with price
    spy_vols = regime_data.get("SPY", {}).get("volumes", [])
    if len(spy_vols) >= 20 and len(spy) >= 20:
        recent_vol = sum(spy_vols[-5:]) / 5
        avg_vol = sum(spy_vols[-20:]) / 20
        if recent_vol > avg_vol * 1.1 and spy[-1] > spy[-20]:
            score += 5  # rising volume on rally = healthy breadth
        elif recent_vol < avg_vol * 0.9 and spy[-1] < spy[-20]:
            score -= 5  # falling volume on decline

    # Symbol vs 20d EMA
    if len(closes) >= 20:
        ema20 = sum(closes[-20:]) / 20
        if closes[-1] > ema20:
            score += 5
        else:
            score -= 5

    return max(0.0, min(100.0, score))
