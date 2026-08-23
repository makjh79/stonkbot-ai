#!/usr/bin/env python3
"""
STONK.AI v3 Adaptive Regime Detector

Clean, testable module that classifies market regime from a set of ETF and
index prices.  Uses SPY 50/200 EMA slopes, VIXY absolute level, credit-spread
ratio relative to a rolling baseline, and a hysteresis state machine so that
regime flips require 2-3 consecutive days.

Regimes: RISK_ON, RISK_OFF, CAUTION, CRISIS
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


REGIMES = ["RISK_ON", "RISK_OFF", "CAUTION", "CRISIS"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False).mean()


def _ema_slope(values: pd.Series, period: int) -> pd.Series:
    """Slope of an EMA over the next `period` days, as daily percentage."""
    ema = _ema(values, period)
    return ema.pct_change() * 100.0


def _credit_zscore(lqd: pd.Series, hyg: pd.Series, window: int = 60) -> pd.Series:
    """Rolling z-score of the LQD/HYG credit spread ratio."""
    ratio = lqd / hyg
    rolling_mean = ratio.rolling(window=window, min_periods=window).mean()
    rolling_std = ratio.rolling(window=window, min_periods=window).std()
    z = (ratio - rolling_mean) / rolling_std.replace(0, np.nan)
    return z


def classify_regime(
    date: Any,
    spy: pd.Series,
    vixy: pd.Series,
    lqd: pd.Series,
    hyg: pd.Series,
    shy: Optional[pd.Series] = None,
    tlt: Optional[pd.Series] = None,
    *,
    vixy_crisis_level: float = 80.0,
    vixy_risk_off_level: float = 55.0,
    credit_z_risk_off: float = 1.0,
    credit_z_crisis: float = 2.5,
    spy_ema_fast: int = 50,
    spy_ema_slow: int = 200,
    slope_lookback: int = 5,
    flip_hysteresis: int = 2,
    prior_regime: Optional[str] = None,
    consecutive_days_in_prior: int = 0,
) -> Tuple[str, Dict]:
    """
    Classify the regime for a single date using SPY, VIXY, LQD, HYG data.

    Returns
    -------
    (regime, metadata)
        regime : one of RISK_ON, RISK_OFF, CAUTION, CRISIS
        metadata : dict with diagnostics (ema values, slopes, z-scores, triggers)
    """
    d = pd.to_datetime(date)
    if d not in spy.index:
        raise KeyError(f"Date {d} not found in SPY series")

    # EMAs
    spy_ema50 = _ema(spy, spy_ema_fast)
    spy_ema200 = _ema(spy, spy_ema_slow)

    spy_price = float(spy.loc[d])
    ema50_val = float(spy_ema50.loc[d])
    ema200_val = float(spy_ema200.loc[d])

    # EMA slopes: daily % change of EMA over lookback days
    ema50_slope = float(spy_ema50.pct_change(slope_lookback).loc[d] * 100.0)
    ema200_slope = float(spy_ema200.pct_change(slope_lookback).loc[d] * 100.0)

    above_50 = spy_price >= ema50_val
    above_200 = spy_price >= ema200_val
    rising_50 = ema50_slope > 0
    rising_200 = ema200_slope > 0

    # Credit spread z-score
    credit_z = float(_credit_zscore(lqd, hyg, window=60).loc[d])

    # VIXY level (raw, absolute) — note VIXY is reverse-split adjusted, so the
    # configured thresholds should be chosen with the dataset's adjustment in mind.
    vixy_level = float(vixy.loc[d])

    # Yield curve signal
    yield_signal = "normal"
    if shy is not None and tlt is not None:
        ratio = shy / tlt
        baseline = ratio.shift(20)
        if pd.notna(ratio.loc[d]) and pd.notna(baseline.loc[d]):
            if ratio.loc[d] > baseline.loc[d]:
                yield_signal = "steepening"

    # -----------------------------------------------------------------------
    # Raw classification (before hysteresis)
    # -----------------------------------------------------------------------
    raw = "RISK_ON"
    triggers: List[str] = []

    # Crisis conditions
    if vixy_level > vixy_crisis_level:
        raw = "CRISIS"
        triggers.append(f"VIXY level {vixy_level:.1f} > {vixy_crisis_level}")
    if credit_z > credit_z_crisis:
        raw = "CRISIS"
        triggers.append(f"Credit z-score {credit_z:.2f} > {credit_z_crisis}")
    if not above_200 and not above_50 and credit_z > credit_z_risk_off:
        raw = "CRISIS"
        triggers.append("SPY below EMA200 and EMA50 while credit stress")

    if raw != "CRISIS":
        # Risk-off conditions
        if vixy_level > vixy_risk_off_level:
            raw = "RISK_OFF"
            triggers.append(f"VIXY level {vixy_level:.1f} > {vixy_risk_off_level}")
        if not above_200:
            raw = "RISK_OFF"
            triggers.append("SPY below EMA200")
        if not above_50 and credit_z > credit_z_risk_off:
            raw = "RISK_OFF"
            triggers.append(f"SPY below EMA50 and credit z-score {credit_z:.2f} > {credit_z_risk_off}")
        if yield_signal == "steepening" and credit_z > credit_z_risk_off:
            raw = "RISK_OFF"
            triggers.append("Yield curve steepening + credit stress")

    # Recovery/caution: below long-term trend but short-term improving
    if raw == "RISK_OFF" and not above_200 and above_50 and rising_50:
        raw = "CAUTION"
        triggers.append("SPY below EMA200 but above rising EMA50 -> CAUTION")

    # -----------------------------------------------------------------------
    # Hysteresis state machine
    # -----------------------------------------------------------------------
    if prior_regime is None or prior_regime == raw:
        regime = raw
        consecutive = consecutive_days_in_prior + 1
    else:
        # Need flip_hysteresis consecutive days in the new raw regime before switching
        if consecutive_days_in_prior >= flip_hysteresis:
            regime = raw
            consecutive = 1
        else:
            regime = prior_regime
            consecutive = consecutive_days_in_prior + 1

    metadata = {
        "raw_regime": raw,
        "spy_price": spy_price,
        "spy_ema50": ema50_val,
        "spy_ema200": ema200_val,
        "spy_above_50": above_50,
        "spy_above_200": above_200,
        "ema50_slope_pct": ema50_slope,
        "ema200_slope_pct": ema200_slope,
        "vixy_level": vixy_level,
        "credit_z": credit_z,
        "yield_signal": yield_signal,
        "triggers": triggers,
        "prior_regime": prior_regime,
        "consecutive_days": consecutive,
    }
    return regime, metadata


def build_regime_series_adaptive(
    bars: Dict[str, Dict[str, List]],
    etfs: Dict[str, pd.Series],
    *,
    flip_hysteresis: int = 2,
    vixy_crisis_level: float = 80.0,
    vixy_risk_off_level: float = 55.0,
    credit_z_risk_off: float = 1.0,
    credit_z_crisis: float = 2.5,
    normalize_vixy_to_window: bool = False,
    vixy_scale_reference: Optional[float] = None,
) -> pd.DataFrame:
    """
    Build a daily regime DataFrame from QQQ-indexed bars and ETF price series.
    `bars` is keyed by symbol -> {"timestamps": [...], "closes": [...], ...}
    `etfs` is keyed by symbol -> pd.Series indexed by UTC timestamps.

    If `normalize_vixy_to_window` is True, the VIXY thresholds are re-scaled to the
    empirical distribution of VIXY in the supplied window so that level-based
    rules are not dominated by absolute share-price differences across history.
    Pass `vixy_scale_reference` (e.g. a real VIX value) to override the percentile
    reference used for scaling; default uses the 80th percentile mapped to 28.
    If `normalize_vixy_to_window` is False and `vixy_scale_reference` is provided,
    the thresholds are scaled directly so that `vixy_risk_off_level` maps to that
    reference value.
    """
    qqq_dates = [pd.to_datetime(d, utc=True) for d in bars["QQQ"]["timestamps"]]
    spy_closes = pd.Series(bars["SPY"]["closes"], index=qqq_dates)

    def align(s: pd.Series) -> pd.Series:
        df = pd.DataFrame({"price": s})
        df = df.reindex(qqq_dates, method="ffill")
        return df["price"]

    vixy = align(etfs.get("VIXY"))
    lqd = align(etfs.get("LQD"))
    hyg = align(etfs.get("HYG"))
    shy = align(etfs.get("SHY")) if "SHY" in etfs else None
    tlt = align(etfs.get("TLT")) if "TLT" in etfs else None

    if normalize_vixy_to_window:
        # VIXY is reverse-split adjusted, so absolute levels differ wildly across
        # history.  Normalize by scaling the configured thresholds so that the
        # window's 80th percentile maps to the real-VIX "risk-off" reference of 28.
        # This preserves relative levels within a window while making cross-window
        # comparisons meaningful.
        ref_high = vixy_scale_reference if vixy_scale_reference is not None else 28.0
        vixy_high = float(vixy.quantile(0.80))
        if vixy_high and not np.isnan(vixy_high) and vixy_high > 0:
            scale = ref_high / vixy_high
            vixy_crisis_level = vixy_crisis_level * scale
            vixy_risk_off_level = vixy_risk_off_level * scale
    elif vixy_scale_reference is not None and vixy_scale_reference > 0:
        # Per-window absolute scale: map configured risk_off level to the provided
        # VIXY value (e.g. the empirical 80th percentile of that window).
        scale = vixy_scale_reference / vixy_risk_off_level
        vixy_crisis_level = vixy_crisis_level * scale
        vixy_risk_off_level = vixy_risk_off_level * scale

    rows = []
    prior_regime = None
    consecutive = 0
    for d in qqq_dates:
        regime, meta = classify_regime(
            d,
            spy=spy_closes,
            vixy=vixy,
            lqd=lqd,
            hyg=hyg,
            shy=shy,
            tlt=tlt,
            flip_hysteresis=flip_hysteresis,
            vixy_crisis_level=vixy_crisis_level,
            vixy_risk_off_level=vixy_risk_off_level,
            credit_z_risk_off=credit_z_risk_off,
            credit_z_crisis=credit_z_crisis,
            prior_regime=prior_regime,
            consecutive_days_in_prior=consecutive,
        )
        prior_regime = regime
        consecutive = meta["consecutive_days"]
        # store date in the same ISO-8601-with-Z format used by the bars files
        meta["date"] = d.strftime("%Y-%m-%dT%H:%M:%SZ")
        meta["regime"] = regime
        meta["vixy_crisis_level_used"] = vixy_crisis_level
        meta["vixy_risk_off_level_used"] = vixy_risk_off_level
        rows.append(meta)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df.set_index("date")


# ---------------------------------------------------------------------------
# Stand-alone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    from pathlib import Path

    DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
    BARS_FILE = DATA_DIR / "daily_bars_2yr.json"
    REGIME_CACHE = DATA_DIR / "regime_etfs_yf.json"

    with open(BARS_FILE) as f:
        bars = json.load(f)
    with open(REGIME_CACHE) as f:
        etf_cache = json.load(f)

    etfs = {
        sym: pd.Series(v["prices"], index=pd.to_datetime(v["dates"], utc=True))
        for sym, v in etf_cache.items()
    }

    df = build_regime_series_adaptive(bars, etfs, flip_hysteresis=2)
    print(df["regime"].value_counts())
    print(df.tail(20)[["regime", "raw_regime", "spy_price", "spy_ema50", "spy_ema200", "vixy_level", "credit_z"]])
