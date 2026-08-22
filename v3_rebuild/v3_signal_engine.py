"""
STONK.AI v3 Signal Engine — Trend Pullback Bounce

This module is designed to replace the readiness_score composite as the
entry filter in trading_bot.py. It computes a clean, interpretable
"trend pullback" score for each symbol and returns a normalized signal
dict that trading_bot.py can consume.

Design principles:
- No 18-factor kitchen sink.
- No hard above_EMA veto.
- Use past-only features (no lookahead).
- Calibrate on historical data, not gut feel.
- Output is simple: entry_eligible, score, rank, tier.

Author: Einstein (OpenClaw agent)
Date: 2026-08-22
"""

from typing import List, Dict, Any, Tuple
import numpy as np
import json


# Weights calibrated from 2yr backtest analysis (subject to ongoing tuning)
TREND_PULLBACK_WEIGHTS = {
    "dist_ema200": 1.0,
    "dist_ema50": 1.0,
    "dist_ema20": 0.5,
    "ret_5d": -3.0,  # negative weight = reward recent decline
    "rsi14": -0.1,  # reward low RSI
    "vs_qqq_5d": -1.0,  # reward underperformance vs QQQ
    "vol_ratio": 0.3,
}

# Thresholds
ENTRY_SCORE_THRESHOLD = 0.5  # always-enter default; will be calibrated per market regime
MIN_ENTRY_SCORE = 0.0
HARD_RSI_MAX = 75  # never enter if RSI extreme overbought
HARD_DIST_EMA200_MIN = -0.15  # never enter if >15% below 200d EMA (trend broken)


def _ema(values: List[float], period: int) -> float:
    if len(values) < period:
        return float("nan")
    mult = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = (v - e) * mult + e
    return e


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return float("nan")
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def compute_trend_pullback_score(
    closes: List[float],
    volumes: List[float],
    qqq_5d_return: float,
) -> Tuple[float, bool]:
    """Compute trend pullback score for a single symbol.

    Returns score and hard_blocked flag.
    """
    if len(closes) < 200 or len(volumes) < 20:
        return float("nan"), False

    price = closes[-1]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    rsi14 = _rsi(closes, 14)

    if price <= 0 or np.isnan(ema20) or np.isnan(ema50) or np.isnan(ema200):
        return float("nan"), False

    dist_ema20 = (price - ema20) / ema20
    dist_ema50 = (price - ema50) / ema50
    dist_ema200 = (price - ema200) / ema200

    ret_5d = (price - closes[-6]) / closes[-6]
    vs_qqq_5d = ret_5d - qqq_5d_return

    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # Hard filters mark eligibility; still compute score so we can rank and log.
    hard_blocked = False
    if rsi14 > HARD_RSI_MAX:
        hard_blocked = True
    if dist_ema200 < HARD_DIST_EMA200_MIN:
        hard_blocked = True

    score = 0.0
    score += max(0.0, TREND_PULLBACK_WEIGHTS["dist_ema200"] * dist_ema200)
    score += max(0.0, TREND_PULLBACK_WEIGHTS["dist_ema50"] * dist_ema50)
    score += max(0.0, TREND_PULLBACK_WEIGHTS["dist_ema20"] * dist_ema20)
    score += max(0.0, -TREND_PULLBACK_WEIGHTS["ret_5d"] * ret_5d)
    if rsi14 < 45:
        score += -TREND_PULLBACK_WEIGHTS["rsi14"] * (45 - rsi14)
    score += max(0.0, -TREND_PULLBACK_WEIGHTS["vs_qqq_5d"] * vs_qqq_5d)
    score += min(TREND_PULLBACK_WEIGHTS["vol_ratio"] * max(0.0, vol_ratio - 1.0), 1.0)

    return score, hard_blocked


def score_row(r: Dict[str, Any]) -> Tuple[float, bool]:
    """Score a single pre-computed feature row (e.g. from features_2yr.json).

    Returns (score, hard_blocked).  Use this for backtesting; use
    compute_trend_pullback_score for live bar streams.
    """
    required = ['dist_ema200', 'dist_ema50', 'dist_ema20', 'ret_5d', 'rsi14', 'vs_qqq_5d', 'vol_ratio']
    if any(r.get(k) is None for k in required):
        return float('nan'), False

    dist_ema200 = r['dist_ema200']
    dist_ema50 = r['dist_ema50']
    dist_ema20 = r['dist_ema20']
    ret_5d = r['ret_5d']
    rsi14 = r['rsi14']
    vs_qqq_5d = r['vs_qqq_5d']
    vol_ratio = r['vol_ratio']

    hard_blocked = False
    if rsi14 > HARD_RSI_MAX:
        hard_blocked = True
    if dist_ema200 < HARD_DIST_EMA200_MIN:
        hard_blocked = True

    score = 0.0
    score += max(0.0, TREND_PULLBACK_WEIGHTS['dist_ema200'] * dist_ema200)
    score += max(0.0, TREND_PULLBACK_WEIGHTS['dist_ema50'] * dist_ema50)
    score += max(0.0, TREND_PULLBACK_WEIGHTS['dist_ema20'] * dist_ema20)
    score += max(0.0, -TREND_PULLBACK_WEIGHTS['ret_5d'] * ret_5d)
    if rsi14 < 45:
        score += -TREND_PULLBACK_WEIGHTS['rsi14'] * (45 - rsi14)
    score += max(0.0, -TREND_PULLBACK_WEIGHTS['vs_qqq_5d'] * vs_qqq_5d)
    score += min(TREND_PULLBACK_WEIGHTS['vol_ratio'] * max(0.0, vol_ratio - 1.0), 1.0)

    return score, hard_blocked


def score_universe(
    symbol_bars: Dict[str, Dict[str, List[float]]],
    qqq_closes: List[float],
) -> List[Dict[str, Any]]:
    """Score all symbols in the universe.

    Args:
        symbol_bars: dict mapping symbol to dict with 'closes' and 'volumes' lists.
        qqq_closes: QQQ daily closes, oldest first.

    Returns:
        List of signal dicts, sorted by score descending.
    """
    if len(qqq_closes) < 6:
        return []

    qqq_5d_return = (qqq_closes[-1] - qqq_closes[-6]) / qqq_closes[-6]

    signals = []
    for symbol, data in symbol_bars.items():
        closes = data.get("closes", [])
        volumes = data.get("volumes", [])
        score, hard_blocked = compute_trend_pullback_score(closes, volumes, qqq_5d_return)
        if np.isnan(score):
            continue

        entry_eligible = (not hard_blocked) and score >= ENTRY_SCORE_THRESHOLD

        signals.append({
            "symbol": symbol,
            "v3_score": round(score, 4),
            "v3_entry_eligible": entry_eligible,
            "v3_tier": "PULLBACK",
            "v3_qqq_5d_return": round(qqq_5d_return, 4),
        })

    signals.sort(key=lambda x: x["v3_score"], reverse=True)
    for i, s in enumerate(signals):
        s["v3_rank"] = i + 1

    return signals


def select_entries(
    signals: List[Dict[str, Any]],
    max_positions: int = 15,
    score_threshold: float = ENTRY_SCORE_THRESHOLD,
) -> List[str]:
    """Select symbols to enter given current signals."""
    selected = []
    for s in signals:
        if s["v3_score"] < score_threshold:
            break
        selected.append(s["symbol"])
        if len(selected) >= max_positions:
            break
    return selected


if __name__ == "__main__":
    # Simple sanity check using 2yr data
    bars = json.load(open("/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json"))
    qqq = bars["QQQ"]
    signals = score_universe(
        {s: {"closes": d["closes"], "volumes": d["volumes"]} for s, d in bars.items() if s not in ("SPY", "QQQ")},
        qqq["closes"],
    )
    print(f"Scored {len(signals)} symbols")
    print("Top 10:")
    for s in signals[:10]:
        print(f"  {s['symbol']:<5} score={s['v3_score']:.2f} eligible={s['v3_entry_eligible']}")
