"""
sector_rotation_engine.py
StonkBOT.AI v3 Rebuild — Sector Rotation Momentum Engine

A simple, explainable monthly sector-rotation alpha layer.
Picks the strongest sector/factor ETFs by 3-month + 6-month relative
strength versus SPY, filtered by credit-spread and VIXY regime conditions.

This is intentionally a *different* alpha source from the stock-picking
satellite: it bets on broad sector themes rather than individual names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class SectorScore:
    symbol: str
    mom_3m: float
    mom_6m: float
    rel_3m: float
    rel_6m: float
    score: float
    excluded: bool
    exclusion_reason: str


class SectorRotationEngine:
    """
    Rule-based sector rotation engine.

    Selection logic (monthly, rebalanced at month-end):
      1. Compute 3-month and 6-month total returns for every candidate ETF.
      2. Compute the same for SPY; relative strength = ETF return - SPY return.
      3. Baseline score = 0.5 * rel_3m + 0.5 * rel_6m.
      4. Regime penalty if credit stress (LQD/HYG z-score <= -1) or VIXY
         elevated (VIXY z-score >= +1) is present.
      5. Absolute filter: exclude any ETF whose absolute 3-month momentum is
         negative (mom_3m < 0).
      6. Pick the top `top_n` ETFs by adjusted score.

    Sizing logic:
      - Equal weight among selected ETFs.
      - Each position capped at `max_sector_pct` of total capital.
      - If the macro allocator's equity exposure is provided, the sector book
        is scaled by it (macro acts as the risk on/off switch).
    """

    # Lookback windows in trading days
    MOM_3M_DAYS: int = 63
    MOM_6M_DAYS: int = 126
    VOL_20D_DAYS: int = 20

    # Regime thresholds
    CREDIT_STRESS_Z: float = -1.0
    VIXY_ELEVATED_Z: float = +1.0

    # Score weights
    REL_3M_WEIGHT: float = 0.5
    REL_6M_WEIGHT: float = 0.5

    # Penalty applied per active stress flag
    REGIME_PENALTY: float = 0.05

    def __init__(
        self,
        candidate_etfs: Sequence[str],
        top_n: int = 3,
        max_sector_pct: float = 0.33,
        min_3m_momentum: float = 0.0,
        macro_equity_min: float = 0.30,
    ):
        self.candidate_etfs = list(candidate_etfs)
        self.top_n = max(1, int(top_n))
        self.max_sector_pct = max(0.0, min(max_sector_pct, 1.0))
        self.min_3m_momentum = min_3m_momentum
        self.macro_equity_min = macro_equity_min

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def select_sectors(
        self,
        date: datetime,
        daily_bars: Dict[str, Dict[str, Sequence]],
        macro_features: Optional[Dict[str, float]] = None,
        top_n: Optional[int] = None,
    ) -> Tuple[List[str], List[SectorScore]]:
        """
        Select sector ETFs for the upcoming month.

        Args:
            date: current rebalancing date (used for logging/diagnostics).
            daily_bars: dict keyed by symbol -> {"closes": [...], "timestamps": [...]}.
            macro_features: optional dict with credit spread and VIXY z-scores.
            top_n: override the default top_n.

        Returns:
            (selected_symbols, full_scorecard)
        """
        top_n = top_n or self.top_n
        spy_bars = daily_bars.get("SPY")
        if spy_bars is None:
            return [], []

        spy_closes = np.asarray(spy_bars["closes"], dtype=float)

        scores: List[SectorScore] = []
        for symbol in self.candidate_etfs:
            bars = daily_bars.get(symbol)
            if bars is None or len(bars.get("closes", [])) < self.MOM_6M_DAYS + 1:
                continue

            closes = np.asarray(bars["closes"], dtype=float)
            mom_3m = self._total_return(closes, self.MOM_3M_DAYS)
            mom_6m = self._total_return(closes, self.MOM_6M_DAYS)
            rel_3m = mom_3m - self._total_return(spy_closes, self.MOM_3M_DAYS)
            rel_6m = mom_6m - self._total_return(spy_closes, self.MOM_6M_DAYS)

            score = self.REL_3M_WEIGHT * rel_3m + self.REL_6M_WEIGHT * rel_6m

            excluded = False
            reasons: List[str] = []

            if mom_3m < self.min_3m_momentum:
                excluded = True
                reasons.append(f"3m_mom={mom_3m:.2%} < 0")

            # Regime filter: penalize, but still allow selection if score remains high
            penalty = 0.0
            if macro_features is not None:
                credit_z = macro_features.get("lqd_hyg_ratio_z60", 0.0)
                vixy_z = macro_features.get("vixy_level_z60", 0.0)
                if credit_z <= self.CREDIT_STRESS_Z:
                    penalty += self.REGIME_PENALTY
                    reasons.append("credit_stress")
                if vixy_z >= self.VIXY_ELEVATED_Z:
                    penalty += self.REGIME_PENALTY
                    reasons.append("vixy_elevated")

            score -= penalty

            scores.append(
                SectorScore(
                    symbol=symbol,
                    mom_3m=float(mom_3m),
                    mom_6m=float(mom_6m),
                    rel_3m=float(rel_3m),
                    rel_6m=float(rel_6m),
                    score=float(score),
                    excluded=excluded,
                    exclusion_reason=", ".join(reasons) if reasons else "",
                )
            )

        eligible = [s for s in scores if not s.excluded]
        eligible.sort(key=lambda s: s.score, reverse=True)
        selected = [s.symbol for s in eligible[:top_n]]
        return selected, scores

    def size_positions(
        self,
        symbols: Sequence[str],
        capital: float,
        macro_exposure: Optional[float] = None,
        max_sector_pct: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Size sector positions.

        The macro allocator acts as a risk on/off switch. When
        `macro_exposure` is provided and is below `macro_equity_min`, the
        engine returns no positions (flat). Otherwise the full `capital` is
        deployed equally across the selected ETFs, subject to
        `max_sector_pct` per symbol.

        Args:
            symbols: selected ETF symbols.
            capital: total capital to allocate (e.g., 1.0 for NAV).
            macro_exposure: macro allocator's equity exposure (0..1). If None,
                treated as fully risk-on.
            max_sector_pct: max allocation per symbol as a fraction of total
                capital. Defaults to the engine parameter.

        Returns:
            dict symbol -> target notional as a fraction of total capital.
        """
        if not symbols:
            return {}

        if macro_exposure is not None and macro_exposure <= self.macro_equity_min:
            return {}

        max_pct = max_sector_pct if max_sector_pct is not None else self.max_sector_pct
        max_pct = max(0.0, min(max_pct, 1.0))

        equal_weight = capital / len(symbols)

        positions: Dict[str, float] = {}
        for symbol in symbols:
            positions[symbol] = min(equal_weight, max_pct * capital)

        return positions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _total_return(self, closes: np.ndarray, days: int) -> float:
        if len(closes) < days + 1:
            return 0.0
        return float(closes[-1] / closes[-1 - days] - 1.0)


# ----------------------------------------------------------------------
# Utility helpers used by the backtest
# ----------------------------------------------------------------------
def compute_volatility(closes: Sequence[float], days: int = 20) -> float:
    """Annualized daily return volatility over the trailing `days`."""
    arr = np.asarray(closes, dtype=float)
    if len(arr) < days + 1:
        return 0.0
    recent = arr[-days - 1 :]
    rets = np.diff(np.log(recent))
    if len(rets) < 2:
        return 0.0
    return float(np.std(rets, ddof=1) * np.sqrt(252))


def month_end_indices(dates: List[datetime]) -> List[int]:
    """Return indices of the last trading day of each calendar month."""
    if not dates:
        return []
    idxs: List[int] = []
    last_month = (dates[0].year, dates[0].month)
    for i, d in enumerate(dates):
        this_month = (d.year, d.month)
        if this_month != last_month:
            idxs.append(i - 1)
            last_month = this_month
    idxs.append(len(dates) - 1)
    return idxs
