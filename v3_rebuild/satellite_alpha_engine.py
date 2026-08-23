"""
satellite_alpha_engine.py
StonkBOT.AI v3 Rebuild — Satellite Alpha Engine v0

A simple monthly-rebalanced stock picker that runs only when the macro
allocator's equity exposure is > 30%.

Selection:
- Universe: individual stocks with >= 252 trading days of history.
- Exclude ETFs used by the macro allocator.
- Composite score = 0.5 * 12-month momentum + 0.3 * 3-month momentum +
                    0.2 * relative strength vs SPY.

Sizing:
- Equal-weight within the satellite sleeve by default.
- Per-stock cap at max_position_pct.
- Sector data unavailable; sector_cap_pct is used as a warning/limitation
  only (capped at the individual stock level).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


ALLOCATOR_ETFS: Tuple[str, ...] = ("SPY", "QQQ", "VIXY", "LQD", "HYG", "TLT", "SHY", "GLD")

DEFAULT_MOMENTUM_WEIGHTS: Dict[str, float] = {
    "mom_12m": 0.5,
    "mom_3m": 0.3,
    "rs_spy": 0.2,
}


@dataclass
class StockSignal:
    symbol: str
    date: datetime
    mom_12m: float
    mom_3m: float
    rs_spy: float
    composite_score: float
    close: float


class SatelliteAlphaEngine:
    """
    Momentum + relative-strength satellite stock picker.

    Parameters:
        max_positions: number of stocks to hold in the satellite sleeve.
        max_position_pct: maximum weight of any single stock (0..1).
        sector_cap_pct: intended sector cap; not enforced due to missing sector data.
        weights: dict mapping "mom_12m", "mom_3m", "rs_spy" to weights summing to 1.
        min_history_days: minimum trading days required to score a stock.
        exclude_symbols: symbols to exclude from selection (default: allocator ETFs).
    """

    def __init__(
        self,
        max_positions: int = 10,
        max_position_pct: float = 0.15,
        sector_cap_pct: float = 0.25,
        weights: Optional[Dict[str, float]] = None,
        min_history_days: int = 252,
        exclude_symbols: Optional[Sequence[str]] = None,
    ):
        self.max_positions = max(1, int(max_positions))
        self.max_position_pct = max(0.0, min(1.0, float(max_position_pct)))
        self.sector_cap_pct = max(0.0, min(1.0, float(sector_cap_pct)))
        self.weights = dict(weights or DEFAULT_MOMENTUM_WEIGHTS)
        total_weight = sum(self.weights.values())
        if total_weight <= 0:
            self.weights = DEFAULT_MOMENTUM_WEIGHTS
        else:
            self.weights = {k: v / total_weight for k, v in self.weights.items()}
        self.min_history_days = max(1, int(min_history_days))
        self.exclude_symbols = set(exclude_symbols or ALLOCATOR_ETFS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def select_stocks(
        self,
        date: datetime,
        daily_bars: Dict[str, Dict[str, Any]],
        eligible_universe: Optional[Sequence[str]] = None,
        max_positions: Optional[int] = None,
        spy_bars: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Select top stocks by composite momentum + relative strength score.

        Args:
            date: rebalancing date; index is found by exact match on timestamp.
            daily_bars: dict[symbol -> {"timestamps": [...], "closes": [...], ...}].
            eligible_universe: optional list of symbols to consider.
            max_positions: override default number of positions.
            spy_bars: optional SPY bars used for relative strength calculation.
                      If not supplied, the engine tries to use daily_bars["SPY"].

        Returns:
            List of dicts (top N), each with symbol, scores, close, composite_score.
        """
        n = max_positions if max_positions is not None else self.max_positions
        spy = spy_bars or daily_bars.get("SPY")
        spy_index = self._find_index_for_date(spy, date)
        # 12-month SPY return is required for a genuine relative-strength reading.
        # Do not fall back to shorter windows for the RS component; instead use
        # None when unavailable and the per-stock logic will zero out RS.
        spy_return = self._total_return_at_index(spy, spy_index, 252)

        universe = self._build_universe(daily_bars, eligible_universe)
        signals: List[StockSignal] = []

        for symbol in universe:
            bars = daily_bars[symbol]
            idx = self._find_index_for_date(bars, date)
            if idx is None or idx < self.min_history_days:
                continue
            closes = bars["closes"]
            if len(closes) < max(252, 63):
                continue

            mom_12m = self._total_return(closes, idx, 252)
            mom_3m = self._total_return(closes, idx, 63)
            # Relative strength must be computed over the same window as the
            # 12-month momentum term. If 12-month history is not available yet
            # (e.g., early in a short window), do not fabricate a relative-
            # strength reading from a shorter window; set it to zero so the
            # score is driven by the available momentum terms only.
            if mom_12m is not None and spy_return is not None:
                rs_spy = mom_12m - spy_return
            else:
                rs_spy = 0.0
            composite = (
                self.weights["mom_12m"] * (mom_12m if mom_12m is not None else 0.0)
                + self.weights["mom_3m"] * (mom_3m if mom_3m is not None else 0.0)
                + self.weights["rs_spy"] * rs_spy
            )

            signals.append(
                StockSignal(
                    symbol=symbol,
                    date=date,
                    mom_12m=mom_12m if mom_12m is not None else 0.0,
                    mom_3m=mom_3m if mom_3m is not None else 0.0,
                    rs_spy=rs_spy,
                    composite_score=composite,
                    close=float(closes[idx]),
                )
            )

        signals.sort(key=lambda s: s.composite_score, reverse=True)
        selected = signals[:n]
        return [self._signal_to_dict(s) for s in selected]

    def size_positions(
        self,
        signals: List[Dict[str, Any]],
        capital: float,
        max_positions: Optional[int] = None,
        sector_cap_pct: Optional[float] = None,
        equal_weight: bool = True,
    ) -> Dict[str, float]:
        """
        Convert selected signals into target notionals for the satellite sleeve.

        Args:
            signals: output from select_stocks.
            capital: capital assigned to the satellite sleeve.
            max_positions: number of positions (used to cap target weight).
            sector_cap_pct: ignored; documented limitation (sector data unavailable).
            equal_weight: if True, equal-weight; else score-weighted.

        Returns:
            Dict mapping symbol -> target notional.
        """
        n = max_positions if max_positions is not None else self.max_positions
        cap = self.max_position_pct
        if not signals or capital <= 0:
            return {}

        selected = signals[:n]
        if equal_weight:
            target_weight = min(1.0 / len(selected), cap)
            weights = {s["symbol"]: target_weight for s in selected}
            # Distribute leftover cash among positions not already at cap.
            residual = 1.0 - sum(weights.values())
            if residual > 1e-9:
                room = [
                    s["symbol"] for s in selected if weights[s["symbol"]] < cap - 1e-9
                ]
                if room:
                    add = residual / len(room)
                    for sym in room:
                        weights[sym] = min(cap, weights[sym] + add)
            # Renormalize in case rounding/capping left us off; keep capped.
            weights = self._normalize_capped(weights, cap)
        else:
            scores = [max(1e-9, s["composite_score"]) for s in selected]
            total = sum(scores)
            weights = {s["symbol"]: (scores[i] / total) for i, s in enumerate(selected)}
            weights = self._normalize_capped(weights, cap)

        return {sym: capital * w for sym, w in weights.items()}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_universe(
        self,
        daily_bars: Dict[str, Dict[str, Any]],
        eligible_universe: Optional[Sequence[str]],
    ) -> List[str]:
        if eligible_universe:
            candidates = [s for s in eligible_universe if s in daily_bars]
        else:
            candidates = list(daily_bars.keys())
        return [
            s
            for s in candidates
            if s not in self.exclude_symbols
            and len(daily_bars[s].get("closes", [])) >= self.min_history_days
        ]

    def _find_index_for_date(
        self, bars: Optional[Dict[str, Any]], date: datetime
    ) -> Optional[int]:
        if bars is None or "timestamps" not in bars:
            return None
        target = date.date()
        for i, ts in enumerate(bars["timestamps"]):
            d = ts.date() if isinstance(ts, datetime) else datetime.fromisoformat(ts).date()
            if d == target:
                return i
        return None

    def _total_return_at_index(
        self, bars: Optional[Dict[str, Any]], idx: Optional[int], window: int
    ) -> Optional[float]:
        if bars is None or idx is None or "closes" not in bars:
            return None
        closes = bars["closes"]
        return self._total_return(closes, idx, window)

    @staticmethod
    def _total_return(closes: Sequence[float], idx: int, window: int) -> Optional[float]:
        if idx < window:
            return None
        prev = float(closes[idx - window])
        cur = float(closes[idx])
        if prev <= 0:
            return None
        return (cur - prev) / prev

    def _normalize_capped(
        self, weights: Dict[str, float], cap: float
    ) -> Dict[str, float]:
        """Iteratively cap and renormalize until stable."""
        for _ in range(100):
            capped = {k: min(cap, v) for k, v in weights.items()}
            total = sum(capped.values())
            if total <= 0:
                return {k: 0.0 for k in capped}
            if abs(total - 1.0) < 1e-9 and all(capped[k] == weights[k] for k in capped):
                return capped
            weights = {k: v / total for k, v in capped.items()}
        return {k: min(cap, v) for k, v in weights.items()}

    def _signal_to_dict(self, signal: StockSignal) -> Dict[str, Any]:
        return {
            "symbol": signal.symbol,
            "date": signal.date.isoformat(),
            "mom_12m": float(signal.mom_12m),
            "mom_3m": float(signal.mom_3m),
            "rs_spy": float(signal.rs_spy),
            "composite_score": float(signal.composite_score),
            "close": float(signal.close),
        }


def load_daily_bars(path: str) -> Dict[str, Dict[str, Any]]:
    import json

    with open(path) as fh:
        data = json.load(fh)
    # Normalize timestamps to datetime objects
    for sym, bars in data.items():
        if "timestamps" in bars:
            bars["timestamps"] = [
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if isinstance(ts, str)
                else ts
                for ts in bars["timestamps"]
            ]
    return data


def _quick_test() -> None:
    import os

    base_dir = os.path.dirname(__file__)
    bars_path = os.path.join(base_dir, "data", "daily_bars_2yr.json")
    bars = load_daily_bars(bars_path)
    engine = SatelliteAlphaEngine()
    dates = bars["SPY"]["timestamps"]
    sample_date = dates[-1]
    selected = engine.select_stocks(sample_date, bars)
    notionals = engine.size_positions(selected, capital=100_000.0)
    print(f"Date: {sample_date.date()}")
    print(f"Selected {len(selected)} stocks")
    for s in selected[:5]:
        print(f"  {s['symbol']}: score={s['composite_score']:.4f}")
    print("Top notional targets:")
    for sym, notional in sorted(notionals.items(), key=lambda x: -x[1])[:5]:
        print(f"  {sym}: ${notional:,.0f}")


if __name__ == "__main__":
    _quick_test()
