"""
vol_target_engine.py
STONK.AI v3 Rebuild — Volatility-Targeted Index Engine with Credit-Gated Dip Overlay

Research basis: Moreira & Muir (2017) volatility-managed portfolio sizing.
Exposure = target_vol / realized_vol, continuously adjusted, capped.
A credit-gated dip-buying overlay is added to improve crisis/recovery capture.

This engine is intentionally different from prior regime-gated architectures:
- continuous sizing rather than discrete regime buckets
- volatility targeting rather than trend/credit grid
- overlay is blocked when credit stress is present
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Parameters (frozen ex-ante)
# ---------------------------------------------------------------------------
DIP_TIERS: Tuple[Tuple[float, float], ...] = ((0.10, 0.50), (0.05, 0.25))
CRISIS_BRAKE_SPY_RET: float = -0.15
CRISIS_BRAKE_CAP: float = 0.25
CREDIT_GATE_Z: float = -1.0
VIXY_GATE_Z: float = +2.0
VIXY_GATE_WINDOW: int = 20
CREDIT_Z_WINDOW: int = 60
CRISIS_RET_WINDOW: int = 60
DRAWDOWN_WINDOW: int = 20
TRADE_BAND: float = 0.05
COST_PER_SIDE: float = 0.001
MAX_EXPOSURE: float = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_iso_date(s: str) -> datetime:
    """Parse an ISO date string, normalising timezone handling."""
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _annualized_realized_volatility(prices: Sequence[float], lookback: int) -> List[float]:
    """Annualized std of daily log returns.  Returns a list same length as prices."""
    n = len(prices)
    vols = [np.nan] * n
    log_rets = [0.0] * n
    for i in range(1, n):
        if prices[i - 1] > 0:
            log_rets[i] = math.log(prices[i] / prices[i - 1])
    for i in range(lookback, n):
        sample = log_rets[i - lookback + 1 : i + 1]
        if len(sample) >= 2:
            vols[i] = float(np.std(sample, ddof=1) * math.sqrt(252))
    return vols


def _rolling_z_score(series: Sequence[float], window: int) -> List[float]:
    """Rolling z-score using the last `window` points ending at each index."""
    n = len(series)
    z = [np.nan] * n
    arr = np.asarray(series, dtype=float)
    for i in range(window, n):
        sample = arr[i - window : i]
        mean = float(np.mean(sample))
        std = float(np.std(sample, ddof=1))
        if std > 0:
            z[i] = (arr[i] - mean) / std
    return z


def _rolling_ratio_z(a: Sequence[float], b: Sequence[float], window: int) -> Tuple[List[float], List[float]]:
    """Compute a/b ratio and its rolling z-score."""
    ratio = [a[i] / b[i] if b[i] != 0 else np.nan for i in range(len(a))]
    z = _rolling_z_score(ratio, window)
    return ratio, z


def _rolling_total_return(prices: Sequence[float], window: int) -> List[float]:
    n = len(prices)
    rets = [np.nan] * n
    for i in range(window, n):
        if prices[i - window] != 0:
            rets[i] = prices[i] / prices[i - window] - 1.0
    return rets


def _rolling_drawdown_from_high(prices: Sequence[float], window: int) -> List[float]:
    """Drawdown from the max close over the last `window` days (inclusive)."""
    n = len(prices)
    dd = [np.nan] * n
    arr = np.asarray(prices, dtype=float)
    for i in range(window - 1, n):
        high = float(np.max(arr[i - window + 1 : i + 1]))
        if high > 0:
            dd[i] = arr[i] / high - 1.0
    return dd


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
@dataclass
class VolTargetEngine:
    """
    Volatility-targeted index engine.

    Parameters
    ----------
    target_vol : float
        Annualized volatility target (e.g. 0.10 for 10%).
    vol_lookback : int
        Lookback window in trading days for realized vol (20 or 60).
    max_exposure : float
        Upper cap on base exposure (1.0 in v1; no leverage).
    enable_overlay : bool
        If False, the dip-buying overlay is disabled (ablation mode).
    """

    target_vol: float
    vol_lookback: int
    max_exposure: float = MAX_EXPOSURE
    enable_overlay: bool = True

    def __post_init__(self):
        if self.vol_lookback <= 0:
            raise ValueError("vol_lookback must be positive")
        if self.target_vol <= 0:
            raise ValueError("target_vol must be positive")

    @property
    def required_warmup_days(self) -> int:
        """Days of history required before the first non-flat signal."""
        return max(self.vol_lookback, CREDIT_Z_WINDOW, VIXY_GATE_WINDOW, CRISIS_RET_WINDOW)

    def compute_signals(
        self,
        spy_prices: Sequence[float],
        qqq_prices: Sequence[float],
        lqd_prices: Sequence[float],
        hyg_prices: Sequence[float],
        vixy_prices: Sequence[float],
        shy_prices: Optional[Sequence[float]] = None,
    ) -> Dict[str, List[float]]:
        """
        Compute the raw daily target exposure and all intermediate diagnostics.

        Returns a dict with keys:
          - 'target_exposure': per-day raw target (before trade band / execution lag)
          - 'realized_vol', 'base_exposure', 'drawdown_20d_high', 'overlay',
            'credit_gate_open', 'vixy_gate_open', 'crisis_brake_active',
            'lqd_hyg_ratio_z60', 'vixy_z20', 'spy_ret_60d'
        """
        n = len(spy_prices)
        if not all(len(x) == n for x in [qqq_prices, lqd_prices, hyg_prices, vixy_prices]):
            raise ValueError("All price series must have the same length")
        if shy_prices is not None and len(shy_prices) != n:
            raise ValueError("SHY series length mismatch")

        realized_vol = _annualized_realized_volatility(spy_prices, self.vol_lookback)
        base_exposure = [np.nan] * n
        for i in range(self.vol_lookback, n):
            vol = realized_vol[i]
            if vol and vol > 0:
                base_exposure[i] = min(self.target_vol / vol, self.max_exposure)
            else:
                base_exposure[i] = 0.0

        drawdown = _rolling_drawdown_from_high(spy_prices, DRAWDOWN_WINDOW)

        _, lqd_hyg_z = _rolling_ratio_z(lqd_prices, hyg_prices, CREDIT_Z_WINDOW)
        vixy_z = _rolling_z_score(vixy_prices, VIXY_GATE_WINDOW)
        spy_ret_60d = _rolling_total_return(spy_prices, CRISIS_RET_WINDOW)

        overlay = [0.0] * n
        credit_open = [False] * n
        vixy_open = [False] * n
        crisis_active = [False] * n
        target = [0.0] * n

        for i in range(self.required_warmup_days, n):
            credit_open[i] = bool(lqd_hyg_z[i] > CREDIT_GATE_Z)
            vixy_open[i] = bool(vixy_z[i] < VIXY_GATE_Z)
            crisis_active[i] = bool(spy_ret_60d[i] <= CRISIS_BRAKE_SPY_RET)

            if self.enable_overlay and credit_open[i] and vixy_open[i]:
                dd = drawdown[i]
                tier_overlay = 0.0
                for threshold, bump in DIP_TIERS:
                    if dd is not None and dd <= -threshold:
                        tier_overlay = bump
                        break  # larger tier replaces smaller tier
                overlay[i] = tier_overlay

            raw = base_exposure[i] + overlay[i]
            raw = max(0.0, min(1.0, raw))
            if crisis_active[i]:
                raw = min(raw, CRISIS_BRAKE_CAP)
            target[i] = raw

        return {
            "target_exposure": target,
            "realized_vol": realized_vol,
            "base_exposure": base_exposure,
            "drawdown_20d_high": drawdown,
            "overlay": overlay,
            "credit_gate_open": credit_open,
            "vixy_gate_open": vixy_open,
            "crisis_brake_active": crisis_active,
            "lqd_hyg_ratio_z60": lqd_hyg_z,
            "vixy_z20": vixy_z,
            "spy_ret_60d": spy_ret_60d,
        }

    def decide_exposure(self, diagnostics: Dict[str, float]) -> float:
        """Convenience: compute target for a single day's diagnostics dict."""
        return float(diagnostics.get("target_exposure", 0.0))

    def rule_summary(self) -> str:
        return f"""
VolTargetEngine rule set:

Base sizing (Moreira & Muir 2017):
  realized_vol = annualized std of SPY daily log returns over {self.vol_lookback} days
  base_exposure = clip(target_vol / realized_vol, 0, {self.max_exposure})
  target_vol = {self.target_vol:.0%}

Dip-buying overlay (credit-gated):
  drawdown_20d_high = SPY close / max SPY close of last {DRAWDOWN_WINDOW} days - 1
  overlay = 0 unless credit gate is OPEN
    dd >= -10% => +0.50
    dd >=  -5% => +0.25  (tiers replace, do not stack; larger tier wins)

Credit gate:
  CLOSED (blocks overlay) when LQD/HYG ratio z-score vs {CREDIT_Z_WINDOW}-day baseline <= {CREDIT_GATE_Z:.1f}
  CLOSED (blocks overlay) when VIXY {VIXY_GATE_WINDOW}-day z-score >= +{VIXY_GATE_Z:.1f}

Crisis brake:
  If SPY {CRISIS_RET_WINDOW}-day return <= {CRISIS_BRAKE_SPY_RET:.0%},
  cap total exposure at {CRISIS_BRAKE_CAP:.0%}

Final exposure = clip(base + overlay, 0, 1.0), then crisis cap.

Execution assumptions (handled by backtest):
  - Daily signal, 1-day execution lag (signal at close t, trade at close t+1)
  - 5pp trade band to reduce churn
  - {COST_PER_SIDE:.2%} per side transaction cost
  - Sleeve: exposure * QQQ + (1 - exposure) * SHY (cash if SHY unavailable)
""".strip()


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------
def load_window_data(data_dir: Path, window_name: str) -> Dict[str, Dict[str, List]]:
    """
    Load one cross-market window.
    window_name ∈ {"bear_2022", "oos_2023_2024", "forward_2024_2026"}.
    Returns dict keyed by symbol with aligned 'dates' (datetime.date) and 'prices'.
    """
    bars_path = data_dir / f"{window_name}_bars.json"
    regime_path = data_dir / f"{window_name}_regime_etfs.json"

    if not bars_path.exists():
        raise FileNotFoundError(bars_path)
    if not regime_path.exists():
        raise FileNotFoundError(regime_path)

    with open(bars_path) as fh:
        bars = json.load(fh)
    with open(regime_path) as fh:
        regime = json.load(fh)

    raw: Dict[str, Dict[str, List]] = {}
    for sym in bars:
        raw[sym] = {
            "dates": [_parse_iso_date(s).date() for s in bars[sym]["timestamps"]],
            "prices": [float(p) for p in bars[sym]["closes"]],
        }
    for sym in regime:
        raw[sym] = {
            "dates": [_parse_iso_date(s).date() for s in regime[sym]["dates"]],
            "prices": [float(p) for p in regime[sym]["prices"]],
        }

    return raw


def align_window_series(raw: Dict[str, Dict[str, List]], required_syms: Sequence[str]) -> Dict[str, np.ndarray]:
    """
    Align all required symbols to the common date intersection.
    Returns arrays keyed by symbol and a 'dates' array of datetime.date.
    """
    # Start with the symbol with the most dates to use as the master intersection base
    sym_dates = {sym: set(raw[sym]["dates"]) for sym in required_syms}
    common = set.intersection(*sym_dates.values())
    if not common:
        raise ValueError(f"No common dates across required symbols: {required_syms}")

    sorted_dates = sorted(common)
    date_to_idx = {d: i for i, d in enumerate(sorted_dates)}

    aligned: Dict[str, np.ndarray] = {"dates": np.array(sorted_dates)}
    for sym in required_syms:
        arr = np.zeros(len(sorted_dates), dtype=float)
        lookup = {d: p for d, p in zip(raw[sym]["dates"], raw[sym]["prices"])}
        for i, d in enumerate(sorted_dates):
            arr[i] = lookup[d]
        aligned[sym] = arr
    return aligned


def load_daily_bars_2yr(data_dir: Path) -> Dict[str, Dict[str, List]]:
    """
    Load daily_bars_2yr.json and regime_etfs_yf.json and align to their common dates.
    NOTE: as of 2026-08-23 this file only spans 2024-08-14 to 2026-08-21, so it
    cannot cover the 2022 bear or 2023-Aug 2024 windows by itself.  Per-window
    files are used for backtesting; this loader is exposed for completeness.
    """
    bars_path = data_dir / "daily_bars_2yr.json"
    regime_path = data_dir / "regime_etfs_yf.json"

    with open(bars_path) as fh:
        bars = json.load(fh)
    with open(regime_path) as fh:
        regime = json.load(fh)

    raw: Dict[str, Dict[str, List]] = {}
    for sym in bars:
        raw[sym] = {
            "dates": [_parse_iso_date(s).date() for s in bars[sym]["timestamps"]],
            "prices": [float(p) for p in bars[sym]["closes"]],
        }
    for sym in regime:
        raw[sym] = {
            "dates": [_parse_iso_date(s).date() for s in regime[sym]["dates"]],
            "prices": [float(p) for p in regime[sym]["prices"]],
        }
    return raw
