"""
STONK.AI v3 Hybrid Signal Engine — Regime-Aware Pullback + Momentum

Two signal modules run on the same daily bars:
  * Module A: existing v3 pullback (mean-reversion) — used in CAUTION and RISK_OFF.
  * Module B: momentum/trend-following — used in RISK_ON.

The engine exposes a single scoring function that selects the active module by
regime state, while keeping the same helpers/hard-vetoes for consistency with
v3_signal_engine.

Author: OpenClaw subagent
Date: 2026-08-23
"""

from typing import Dict, Any, Tuple, List
import numpy as np
import json


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Module A — existing v3 pullback (mean-reversion)
# ---------------------------------------------------------------------------

TREND_PULLBACK_WEIGHTS = {
    "dist_ema200": 1.0,
    "dist_ema50": 1.0,
    "dist_ema20": 0.5,
    "ret_5d": -3.0,
    "rsi14": -0.1,
    "vs_qqq_5d": -1.0,
    "vol_ratio": 0.3,
}

HARD_RSI_MAX = 75
HARD_DIST_EMA200_MIN = -0.15


def compute_pullback_score(closes: List[float], volumes: List[float], qqq_5d_return: float) -> Tuple[float, bool, Dict[str, float]]:
    """Mirror of v3_signal_engine.compute_trend_pullback_score.

    Returns (score, hard_blocked, diagnostics).
    """
    if len(closes) < 200 or len(volumes) < 20:
        return float("nan"), False, {}

    price = closes[-1]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    rsi14 = _rsi(closes, 14)

    if price <= 0 or np.isnan(ema20) or np.isnan(ema50) or np.isnan(ema200):
        return float("nan"), False, {}

    dist_ema20 = (price - ema20) / ema20
    dist_ema50 = (price - ema50) / ema50
    dist_ema200 = (price - ema200) / ema200
    ret_5d = (price - closes[-6]) / closes[-6]
    vs_qqq_5d = ret_5d - qqq_5d_return
    avg_vol_20 = sum(volumes[-20:]) / 20
    vol_ratio = volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

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

    return score, hard_blocked, {
        "dist_ema20": dist_ema20,
        "dist_ema50": dist_ema50,
        "dist_ema200": dist_ema200,
        "ret_5d": ret_5d,
        "rsi14": rsi14,
        "vol_ratio": vol_ratio,
    }


def pullback_score_row(r: Dict[str, Any]) -> Tuple[float, bool, Dict[str, float]]:
    """Mirror of v3_signal_engine.score_row using pre-computed features."""
    required = ['dist_ema200', 'dist_ema50', 'dist_ema20', 'ret_5d', 'rsi14', 'vs_qqq_5d', 'vol_ratio']
    if any(r.get(k) is None for k in required):
        return float('nan'), False, {}

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

    return score, hard_blocked, {
        "dist_ema20": dist_ema20,
        "dist_ema50": dist_ema50,
        "dist_ema200": dist_ema200,
        "ret_5d": ret_5d,
        "rsi14": rsi14,
        "vol_ratio": vol_ratio,
    }


# ---------------------------------------------------------------------------
# Module B — momentum/trend-following
# ---------------------------------------------------------------------------

# Score weights (positive attributes only; hard vetoes applied separately)
MOMENTUM_WEIGHTS = {
    "dist_ema20": 1.5,
    "dist_ema50": 1.0,
    "ret_20d": 2.0,
}

MOMENTUM_RSI_MIN = 50
MOMENTUM_RSI_MAX = 75
MOMENTUM_DIST_EMA200_MIN = -0.05


def compute_momentum_score(closes: List[float], volumes: List[float], qqq_5d_return: float) -> Tuple[float, bool, Dict[str, float]]:
    """Trend-following score for RISK_ON regimes.

    Ranks by positive distance from EMAs and 20-day return.
    Hard vetoes: RSI outside 50-75, price < 200d EMA -5%, overheated >75.
    Entry trigger (not part of score): pullback to 5-day EMA or 10-day low.
    """
    if len(closes) < 200 or len(volumes) < 20:
        return float("nan"), False, {}

    price = closes[-1]
    ema5 = _ema(closes, 5)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    rsi14 = _rsi(closes, 14)

    if price <= 0 or np.isnan(ema5) or np.isnan(ema20) or np.isnan(ema50) or np.isnan(ema200):
        return float("nan"), False, {}

    dist_ema5 = (price - ema5) / ema5
    dist_ema20 = (price - ema20) / ema20
    dist_ema50 = (price - ema50) / ema50
    dist_ema200 = (price - ema200) / ema200
    ret_20d = (price - closes[-21]) / closes[-21] if len(closes) >= 21 else float('nan')

    hard_blocked = False
    block_reasons = []
    if rsi14 < MOMENTUM_RSI_MIN or rsi14 > MOMENTUM_RSI_MAX:
        hard_blocked = True
        block_reasons.append(f"rsi14={rsi14:.1f} outside {MOMENTUM_RSI_MIN}-{MOMENTUM_RSI_MAX}")
    if dist_ema200 < MOMENTUM_DIST_EMA200_MIN:
        hard_blocked = True
        block_reasons.append(f"dist_ema200={dist_ema200:.3f} < {MOMENTUM_DIST_EMA200_MIN}")

    # Only positive momentum contributes to rank; avoid chasing breakdowns.
    score = 0.0
    score += MOMENTUM_WEIGHTS["dist_ema20"] * max(0.0, dist_ema20)
    score += MOMENTUM_WEIGHTS["dist_ema50"] * max(0.0, dist_ema50)
    score += MOMENTUM_WEIGHTS["ret_20d"] * max(0.0, ret_20d)

    # Entry trigger: buy dips within uptrends only
    ten_day_low = min(closes[-10:])
    pullback_to_ema5 = price <= ema5
    pullback_to_10d_low = abs(price - ten_day_low) / ten_day_low < 0.005
    entry_trigger = pullback_to_ema5 or pullback_to_10d_low

    diag = {
        "dist_ema5": dist_ema5,
        "dist_ema20": dist_ema20,
        "dist_ema50": dist_ema50,
        "dist_ema200": dist_ema200,
        "ret_20d": ret_20d,
        "rsi14": rsi14,
        "pullback_to_ema5": pullback_to_ema5,
        "pullback_to_10d_low": pullback_to_10d_low,
        "entry_trigger": entry_trigger,
    }

    return score, hard_blocked, diag


def momentum_score_row(r: Dict[str, Any], closes: List[float]) -> Tuple[float, bool, Dict[str, float]]:
    """Momentum scoring using a feature row + raw closes for entry trigger."""
    required = ['dist_ema20', 'dist_ema50', 'dist_ema200', 'ret_20d', 'rsi14']
    if any(r.get(k) is None for k in required):
        return float('nan'), False, {}
    if len(closes) < 21:
        return float('nan'), False, {}

    dist_ema20 = r['dist_ema20']
    dist_ema50 = r['dist_ema50']
    dist_ema200 = r['dist_ema200']
    ret_20d = r['ret_20d']
    rsi14 = r['rsi14']

    hard_blocked = False
    if rsi14 < MOMENTUM_RSI_MIN or rsi14 > MOMENTUM_RSI_MAX:
        hard_blocked = True
    if dist_ema200 < MOMENTUM_DIST_EMA200_MIN:
        hard_blocked = True

    score = 0.0
    score += MOMENTUM_WEIGHTS["dist_ema20"] * max(0.0, dist_ema20)
    score += MOMENTUM_WEIGHTS["dist_ema50"] * max(0.0, dist_ema50)
    score += MOMENTUM_WEIGHTS["ret_20d"] * max(0.0, ret_20d)

    price = closes[-1]
    ema5 = _ema(closes, 5)
    ten_day_low = min(closes[-10:])
    pullback_to_ema5 = (not np.isnan(ema5)) and price <= ema5
    pullback_to_10d_low = abs(price - ten_day_low) / ten_day_low < 0.005
    entry_trigger = pullback_to_ema5 or pullback_to_10d_low

    diag = {
        "dist_ema20": dist_ema20,
        "dist_ema50": dist_ema50,
        "dist_ema200": dist_ema200,
        "ret_20d": ret_20d,
        "rsi14": rsi14,
        "pullback_to_ema5": pullback_to_ema5,
        "pullback_to_10d_low": pullback_to_10d_low,
        "entry_trigger": entry_trigger,
    }

    return score, hard_blocked, diag


# ---------------------------------------------------------------------------
# Hybrid dispatcher
# ---------------------------------------------------------------------------

PULLBACK_SCORE_THRESHOLD = 0.5
MOMENTUM_SCORE_THRESHOLD = 0.0


def score_symbol(
    regime: str,
    closes: List[float],
    volumes: List[float],
    qqq_5d_return: float,
    feature_row: Dict[str, Any] = None,
) -> Tuple[float, bool, str, Dict[str, Any]]:
    """Return (score, hard_blocked, module, diagnostics).

    Regime mapping (mirrors deployed v3 logic):
      RISK_ON  -> Module B (momentum)
      CAUTION  -> Module A (pullback)
      RISK_OFF -> Module A (pullback)
    """
    if regime == "RISK_ON":
        if feature_row is not None:
            score, blocked, diag = momentum_score_row(feature_row, closes)
        else:
            score, blocked, diag = compute_momentum_score(closes, volumes, qqq_5d_return)
        return score, blocked, "momentum", diag
    else:
        if feature_row is not None:
            score, blocked, diag = pullback_score_row(feature_row)
        else:
            score, blocked, diag = compute_pullback_score(closes, volumes, qqq_5d_return)
        return score, blocked, "pullback", diag


def entry_eligible(module: str, score: float, diag: Dict[str, Any]) -> bool:
    """Module-specific eligibility, including momentum pullback trigger."""
    if module == "momentum":
        return score >= MOMENTUM_SCORE_THRESHOLD and diag.get("entry_trigger", False)
    return score >= PULLBACK_SCORE_THRESHOLD


def select_entries(
    signals: List[Dict[str, Any]],
    max_positions: int = 15,
    pullback_threshold: float = PULLBACK_SCORE_THRESHOLD,
    momentum_threshold: float = MOMENTUM_SCORE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Select top eligible signals, preserving module and rank."""
    selected = []
    for s in signals:
        module = s["module"]
        score = s["score"]
        diag = s.get("diag", {})
        if module == "momentum":
            if score < momentum_threshold or not diag.get("entry_trigger", False):
                continue
        else:
            if score < pullback_threshold:
                continue
        selected.append(s)
        if len(selected) >= max_positions:
            break
    return selected


if __name__ == "__main__":
    # Sanity check over 2yr daily bars
    bars = json.load(open("/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json"))
    qqq = bars["QQQ"]
    universe = {s: {"closes": d["closes"], "volumes": d["volumes"]}
                for s, d in bars.items() if s not in ("SPY", "QQQ")}

    qqq_5d = (qqq["closes"][-1] - qqq["closes"][-6]) / qqq["closes"][-6]
    results = []
    for sym, data in universe.items():
        score, blocked, module, diag = score_symbol("RISK_ON", data["closes"], data["volumes"], qqq_5d)
        if not np.isnan(score):
            results.append({
                "symbol": sym,
                "module": module,
                "score": round(score, 4),
                "blocked": blocked,
                "eligible": entry_eligible(module, score, diag),
                **{k: round(v, 4) if isinstance(v, (int, float)) else v for k, v in diag.items()},
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    print("Top 10 momentum candidates:")
    for r in results[:10]:
        print(f"  {r}")
