"""
macro_allocator.py
StonkBOT.AI v3 Rebuild — Macro State Risk-Budget Allocator

A simple, explainable, regime-aware monthly equity exposure allocator.
Uses only macro/ETF features derived from available daily bar data.

Design principles:
- Monthly rebalancing only.
- No intra-month timing.
- Exposure ∈ {0.0, 0.25, 0.50, 0.75, 1.0} (long equity) optionally mixed with a small
  short-equity sleeve via SH/SQQQ (not used by default in this prototype).
- Maximum drawdown target ≤ -20% in any window.
- Parameters chosen by reasoning and frozen; not overfitted to the recent window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class MacroFeatures:
    """Container for the macro/ETF features used by the allocator."""

    date: datetime
    spy_close: float
    spy_ema200: float
    spy_ema50: float
    spy_ema50_slope_20d: float  # 20-day slope of 50-day EMA, annualized-ish
    lqd_hyg_ratio: float
    lqd_hyg_ratio_z60: float  # z-score of LQD/HYG ratio vs 60-day baseline
    vixy_close: float
    vixy_level_z60: float  # z-score of VIXY level vs 60-day baseline
    tlt_close: float
    tlt_ema50_slope_20d: float  # slope of TLT 50-day EMA
    shy_close: float
    spy_ret_60d: float  # 60-day total return used as additional context
    qqq_ret_60d: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "spy_close": self.spy_close,
            "spy_ema200": self.spy_ema200,
            "spy_ema50": self.spy_ema50,
            "spy_ema50_slope_20d": self.spy_ema50_slope_20d,
            "lqd_hyg_ratio": self.lqd_hyg_ratio,
            "lqd_hyg_ratio_z60": self.lqd_hyg_ratio_z60,
            "vixy_close": self.vixy_close,
            "vixy_level_z60": self.vixy_level_z60,
            "tlt_close": self.tlt_close,
            "tlt_ema50_slope_20d": self.tlt_ema50_slope_20d,
            "shy_close": self.shy_close,
            "spy_ret_60d": self.spy_ret_60d,
            "qqq_ret_60d": self.qqq_ret_60d,
        }


class MacroAllocator:
    """
    Rule-based macro state allocator.

    The allocator inspects the following macro axes each month-end:

    1. EQUITY TREND (SPY)
       - Price vs 200-day EMA (bull/bear filter).
       - 50-day EMA 20-day slope (momentum confirmation).

    2. CREDIT SPREAD (LQD / HYG ratio)
       - A falling LQD/HYG ratio indicates credit stress (high-yield underperforming).
       - Z-score vs 60-day baseline makes the signal adaptive per window.

    3. RISK/VOLATILITY (VIXY)
       - Elevated VIXY relative to its 60-day baseline is a risk-off flag.

    4. RATES/TREASURIES (TLT trend)
       - Rising TLT = yields falling = equity tailwind.
       - Falling TLT = yields rising = macro headwind.

    5. ABSOLUTE PROTECTION RULES
       - If SPY is below its 200-day EMA AND credit stress is present,
         equity exposure is capped at 25% (can go to 0% if VIXY also elevated).
       - Maximum drawdown safety cap: if 60-day SPY return is worse than -12%,
         reduce exposure by one notch (at least 25% -> 0%).

    Output is a single equity exposure between 0.0 and 1.0.
    Short-equity sleeve is intentionally set to 0 in this prototype to keep
    the first version simple and interpretable; the class structure accepts it.
    """

    # Exposure grid. The allocator always returns one of these values.
    EXPOSURE_GRID: Tuple[float, ...] = (0.0, 0.25, 0.50, 0.75, 1.0)

    # --- Frozen parameters (chosen by reasoning, not optimized on recent window) ---
    # Trend / regime
    BEAR_TREND_THRESHOLD: float = 0.0  # SPY below 200d EMA => price/ema200 - 1 < 0
    MOMENTUM_SLOPE_THRESHOLD: float = 0.0  # 50d EMA slope positive = bullish
    # Credit
    CREDIT_STRESS_Z: float = -1.0  # LQD/HYG ratio one std below baseline
    CREDIT_EASY_Z: float = +0.3  # LQD/HYG ratio modestly above baseline
    # Volatility
    VIXY_ELEVATED_Z: float = +1.0  # VIXY one std above its 60d baseline
    VIXY_CALM_Z: float = -0.3  # VIXY modestly below baseline
    # Rates
    TLT_RISING_SLOPE: float = +0.0003  # TLT 50d EMA rising
    TLT_FALLING_SLOPE: float = -0.0003  # TLT 50d EMA falling
    # Drawdown safety
    DRAWDOWN_SPY_60D_LIMIT: float = -0.12  # if SPY -12% over 60d, derisk

    def __init__(self, allow_short_sleeve: bool = False, short_sleeve_max: float = 0.0):
        # Short sleeve disabled by default in the first prototype.
        self.allow_short_sleeve = allow_short_sleeve and short_sleeve_max > 0
        self.short_sleeve_max = max(0.0, min(short_sleeve_max, 0.30))

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------
    def decide_equity_exposure(
        self,
        date: datetime,
        macro_features: Dict[str, Any],
    ) -> float:
        """
        Decide long-equity exposure for the upcoming month.

        Args:
            date: current rebalancing date (usually month-end / first trading day).
            macro_features: dict matching MacroFeatures.to_dict() or raw keys.

        Returns:
            float in {0.0, 0.25, 0.50, 0.75, 1.0}
        """
        f = self._normalize_features(date, macro_features)

        # ---- 1. Trend-first baseline exposure ----
        long_exposure = self._trend_baseline(f)

        # ---- 2. Modifiers from credit, vol, rates ----
        credit_delta = self._credit_delta(f)
        vol_delta = self._volatility_delta(f)
        rates_delta = self._rates_delta(f)

        long_exposure += credit_delta + vol_delta + rates_delta
        long_exposure = self._snap_to_grid(long_exposure)

        # ---- 3. Absolute protection / drawdown safety cap ----
        long_exposure = self._apply_safety_caps(long_exposure, f)

        # Short sleeve intentionally unused in first prototype.
        # We return only long equity exposure (0..1).
        return round(long_exposure, 4)

    def decide_sleeve(
        self,
        date: datetime,
        macro_features: Dict[str, Any],
    ) -> Dict[str, float]:
        """
        Return a full sleeve breakdown if a future caller wants it.
        For this prototype, short sleeve is always 0.
        """
        equity = self.decide_equity_exposure(date, macro_features)
        return {
            "equity_long": equity,
            "equity_short": 0.0,
            "cash": 1.0 - equity,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _normalize_features(
        self, date: datetime, macro_features: Dict[str, Any]
    ) -> MacroFeatures:
        if isinstance(macro_features, MacroFeatures):
            return macro_features  # type: ignore[return-value]

        def parse_date(d: Any) -> datetime:
            if isinstance(d, datetime):
                return d
            if isinstance(d, str):
                # Strip Z / offset to keep pandas/strptime happy
                return datetime.fromisoformat(d.replace("Z", "+00:00"))
            raise ValueError(f"Cannot parse date: {d!r}")

        return MacroFeatures(
            date=parse_date(macro_features.get("date", date)),
            spy_close=float(macro_features["spy_close"]),
            spy_ema200=float(macro_features["spy_ema200"]),
            spy_ema50=float(macro_features["spy_ema50"]),
            spy_ema50_slope_20d=float(macro_features["spy_ema50_slope_20d"]),
            lqd_hyg_ratio=float(macro_features["lqd_hyg_ratio"]),
            lqd_hyg_ratio_z60=float(macro_features["lqd_hyg_ratio_z60"]),
            vixy_close=float(macro_features["vixy_close"]),
            vixy_level_z60=float(macro_features["vixy_level_z60"]),
            tlt_close=float(macro_features["tlt_close"]),
            tlt_ema50_slope_20d=float(macro_features["tlt_ema50_slope_20d"]),
            shy_close=float(macro_features["shy_close"]),
            spy_ret_60d=float(macro_features["spy_ret_60d"]),
            qqq_ret_60d=float(macro_features["qqq_ret_60d"]),
        )

    def _trend_baseline(self, f: MacroFeatures) -> float:
        """
        Trend is the primary macro axis.
        - Above 200d EMA + positive 50d slope => 1.0 (full equity)
        - Above 200d EMA but weak momentum => 0.75
        - Below 200d EMA but positive momentum => 0.25
        - Below 200d EMA + negative momentum => 0.0
        """
        dist_200 = (f.spy_close / f.spy_ema200) - 1.0
        if dist_200 >= self.BEAR_TREND_THRESHOLD:
            if f.spy_ema50_slope_20d >= self.MOMENTUM_SLOPE_THRESHOLD:
                return 1.0
            return 0.75
        else:
            if f.spy_ema50_slope_20d >= self.MOMENTUM_SLOPE_THRESHOLD:
                return 0.25
            return 0.0

    def _credit_delta(self, f: MacroFeatures) -> float:
        """Return a modifier in {-0.25, 0, +0.25}."""
        z = f.lqd_hyg_ratio_z60
        if z <= self.CREDIT_STRESS_Z:
            return -0.25
        if z >= self.CREDIT_EASY_Z:
            return +0.25
        return 0.0

    def _volatility_delta(self, f: MacroFeatures) -> float:
        """Return a modifier in {-0.25, 0, +0.25}."""
        z = f.vixy_level_z60
        if z >= self.VIXY_ELEVATED_Z:
            return -0.25
        if z <= self.VIXY_CALM_Z:
            return +0.25
        return 0.0

    def _rates_delta(self, f: MacroFeatures) -> float:
        """Return a modifier in {-0.25, 0, +0.25}."""
        slope = f.tlt_ema50_slope_20d
        if slope >= self.TLT_RISING_SLOPE:
            return +0.25  # rates falling = equity friendly
        if slope <= self.TLT_FALLING_SLOPE:
            return -0.25  # rates rising = headwind
        return 0.0

    def _snap_to_grid(self, value: float) -> float:
        value = max(0.0, min(1.0, value))
        return min(self.EXPOSURE_GRID, key=lambda x: abs(x - value))

    def _apply_safety_caps(self, exposure: float, f: MacroFeatures) -> float:
        # Hard risk-off if SPY below 200d EMA AND credit stress AND vol elevated
        dist_200 = (f.spy_close / f.spy_ema200) - 1.0
        if dist_200 < 0 and f.lqd_hyg_ratio_z60 <= self.CREDIT_STRESS_Z and f.vixy_level_z60 >= self.VIXY_ELEVATED_Z:
            exposure = min(exposure, 0.0)

        # If below 200d and credit stress, cap at 25%
        if dist_200 < 0 and f.lqd_hyg_ratio_z60 <= self.CREDIT_STRESS_Z:
            exposure = min(exposure, 0.25)

        # If SPY has dropped >12% in 60d, derisk by one notch (but never below 0)
        if f.spy_ret_60d <= self.DRAWDOWN_SPY_60D_LIMIT:
            idx = self.EXPOSURE_GRID.index(exposure)
            exposure = self.EXPOSURE_GRID[max(0, idx - 1)]

        # Final clamp
        return round(max(0.0, min(1.0, exposure)), 4)

    def rule_summary(self) -> str:
        return """
MacroAllocator rule set:

Trend-first baseline (primary axis):
1. SPY trend:
   - Price vs 200-day EMA: above = bullish, below = bearish.
   - 50-day EMA 20-day slope: positive = bullish, negative = bearish.
   Baseline exposure:
     above 200d + positive 50d slope => 100%
     above 200d + weak momentum       => 75%
     below 200d + positive momentum   => 25%
     below 200d + negative momentum   => 0%

Modifiers (each +/- 25%):
2. Credit spread (LQD/HYG ratio z-score vs 60-day baseline):
   - z <= -1.0 => credit stress      => -25%
   - z >= +0.3 => credit easy        => +25%
3. VIXY level z-score vs 60-day baseline:
   - z >= +1.0 => elevated risk        => -25%
   - z <= -0.3 => calm               => +25%
4. TLT trend (50-day EMA 20-day slope):
   - slope >= +0.0003 (rising TLT / falling yields) => +25%
   - slope <= -0.0003 (falling TLT / rising yields) => -25%

Snap to {0, 25, 50, 75, 100}% after applying modifiers.

Safety caps (after snapping):
- If SPY below 200d EMA AND credit stress AND VIXY elevated => 0% equity.
- If SPY below 200d EMA AND credit stress => max 25% equity.
- If SPY 60-day return <= -12% => derisk one notch.

Output:
- Long equity exposure only (short sleeve = 0 in this prototype).
- Monthly rebalancing; no intra-month timing.
- Transaction cost assumption handled by backtest, not allocator.
""".strip()


# ----------------------------------------------------------------------
# Feature engineering helpers (used by backtest / notebooks)
# ----------------------------------------------------------------------
def compute_ema(prices: Sequence[float], span: int) -> List[float]:
    """Exponential moving average with pandas-style span."""
    if not prices or span <= 0:
        return list(prices)
    alpha = 2.0 / (span + 1.0)
    ema: List[float] = []
    for i, p in enumerate(prices):
        if i == 0:
            ema.append(p)
        else:
            ema.append(alpha * p + (1 - alpha) * ema[-1])
    return ema


def compute_ema_slope(prices: Sequence[float], ema_span: int, slope_window: int) -> List[float]:
    """Slope of EMA over slope_window days (per-day change)."""
    ema = compute_ema(prices, ema_span)
    slopes: List[float] = [0.0] * len(ema)
    for i in range(slope_window, len(ema)):
        prev = ema[i - slope_window]
        if prev != 0:
            slopes[i] = (ema[i] - prev) / prev / slope_window
        else:
            slopes[i] = 0.0
    return slopes


def compute_total_return(prices: Sequence[float], window: int) -> List[float]:
    rets = [0.0] * len(prices)
    for i in range(window, len(prices)):
        prev = prices[i - window]
        if prev != 0:
            rets[i] = (prices[i] - prev) / prev
    return rets


def compute_z_score(series: Sequence[float], window: int) -> List[float]:
    """Rolling z-score using the last `window` points ending at each index."""
    z = [0.0] * len(series)
    for i in range(window, len(series)):
        sample = series[i - window : i]
        mean = sum(sample) / len(sample)
        variance = sum((x - mean) ** 2 for x in sample) / len(sample)
        std = variance ** 0.5
        if std != 0:
            z[i] = (series[i] - mean) / std
    return z


def compute_ratio_z(a: Sequence[float], b: Sequence[float], window: int) -> Tuple[List[float], List[float]]:
    """Compute a/b ratio and its rolling z-score."""
    ratio = [a[i] / b[i] if b[i] != 0 else 1.0 for i in range(len(a))]
    z = compute_z_score(ratio, window)
    return ratio, z


def build_macro_features(
    spy_closes: Sequence[float],
    qqq_closes: Sequence[float],
    lqd_closes: Sequence[float],
    hyg_closes: Sequence[float],
    vixy_closes: Sequence[float],
    tlt_closes: Sequence[float],
    shy_closes: Sequence[float],
    dates: Sequence[datetime],
) -> List[MacroFeatures]:
    """Build a list of MacroFeatures for each day with enough history."""
    n = len(spy_closes)
    spy_ema200 = compute_ema(spy_closes, 200)
    spy_ema50 = compute_ema(spy_closes, 50)
    spy_ema50_slope = compute_ema_slope(spy_closes, 50, 20)
    tlt_ema50_slope = compute_ema_slope(tlt_closes, 50, 20)
    lqd_hyg_ratio, lqd_hyg_z = compute_ratio_z(lqd_closes, hyg_closes, 60)
    vixy_z = compute_z_score(vixy_closes, 60)
    spy_ret_60d = compute_total_return(spy_closes, 60)
    qqq_ret_60d = compute_total_return(qqq_closes, 60)

    features: List[MacroFeatures] = []
    # 200-day EMA warm-up is the longest lookback. We start at index 120
    # (roughly 6 months) to capture more of each short window while keeping
    # EMA initialization bias modest. This is documented as a prototype
    # limitation/feature; in production a longer warm-up would be used.
    for i in range(120, n):
        features.append(
            MacroFeatures(
                date=dates[i],
                spy_close=spy_closes[i],
                spy_ema200=spy_ema200[i],
                spy_ema50=spy_ema50[i],
                spy_ema50_slope_20d=spy_ema50_slope[i],
                lqd_hyg_ratio=lqd_hyg_ratio[i],
                lqd_hyg_ratio_z60=lqd_hyg_z[i],
                vixy_close=vixy_closes[i],
                vixy_level_z60=vixy_z[i],
                tlt_close=tlt_closes[i],
                tlt_ema50_slope_20d=tlt_ema50_slope[i],
                shy_close=shy_closes[i],
                spy_ret_60d=spy_ret_60d[i],
                qqq_ret_60d=qqq_ret_60d[i],
            )
        )
    return features


def load_window_data(data_dir: str, window_name: str) -> Dict[str, Any]:
    """
    Load one of the three cross-market windows.
    window_name ∈ {"bear_2022", "oos_2023_2024", "forward_2024_2026"}.
    Returns dict with raw arrays keyed by symbol.
    """
    import os

    bars_path = os.path.join(data_dir, f"{window_name}_bars.json")
    regime_path = os.path.join(data_dir, f"{window_name}_regime_etfs.json")

    with open(bars_path) as fh:
        bars = json.load(fh)
    with open(regime_path) as fh:
        regime = json.load(fh)

    def parse_dates(raw: List[str]) -> List[datetime]:
        out: List[datetime] = []
        for s in raw:
            s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out.append(dt)
        return out

    result: Dict[str, Any] = {}
    for sym in bars:
        result[sym] = {
            "closes": bars[sym]["closes"],
            "timestamps": parse_dates(bars[sym]["timestamps"]),
        }
    for sym in regime:
        result[sym] = {
            "closes": regime[sym]["prices"],
            "timestamps": parse_dates(regime[sym]["dates"]),
        }
    return result


def _main() -> None:
    import os

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    window = "bear_2022"
    data = load_window_data(data_dir, window)
    feats = build_macro_features(
        spy_closes=data["SPY"]["closes"],
        qqq_closes=data["QQQ"]["closes"],
        lqd_closes=data["LQD"]["closes"],
        hyg_closes=data["HYG"]["closes"],
        vixy_closes=data["VIXY"]["closes"],
        tlt_closes=data["TLT"]["closes"],
        shy_closes=data["SHY"]["closes"],
        dates=data["SPY"]["timestamps"],
    )
    alloc = MacroAllocator()
    print(alloc.rule_summary())
    print("\nSample decisions for", window)
    for f in feats[::max(1, len(feats) // 12)]:
        exp = alloc.decide_equity_exposure(f.date, f.to_dict())
        print(f.date.date(), f"exposure={exp:.2%}")


if __name__ == "__main__":
    _main()
