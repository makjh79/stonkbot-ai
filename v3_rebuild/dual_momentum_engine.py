"""
dual_momentum_engine.py
StonkBOT.AI v3 Rebuild — Dual-Momentum Global Asset Rotation (GEM-style)

Monthly rotation across QQQ (risk), GLD (alternative), TLT (defensive), SHY (cash proxy).
Rules (ex-ante, Antonacci GEM):
  1. At month-end, compute lookback total returns for QQQ, GLD, TLT, SHY.
  2. Compare QQQ and GLD; pick the higher-returning risk asset.
  3. Apply absolute momentum filter: hold it only if its return exceeds SHY's return.
  4. If neither QQQ nor GLD beats SHY, hold TLT if TLT beats SHY, otherwise SHY.
Signals are produced at month-end close and executed at the next trading day's close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence


@dataclass
class DualMomentumSignal:
    signal_date: datetime          # month-end close used for signal
    execution_date: datetime       # next trading day close when trade executes
    lookback_months: int
    returns: Dict[str, float]      # total returns by ticker over lookback
    selected: str                  # ticker held after execution
    reason: str


class DualMomentumEngine:
    """
    Dual-momentum asset allocator.
    """

    UNIVERSE = ("QQQ", "GLD", "TLT", "SHY")
    RISK_ASSETS = ("QQQ", "GLD")
    DEFENSIVE_ASSET = "TLT"
    CASH_ASSET = "SHY"

    def __init__(self, lookback_months: int = 12):
        if lookback_months not in (6, 12):
            raise ValueError("lookback_months must be 6 or 12 for this prototype")
        self.lookback_months = lookback_months

    def _trading_days_ago(self, dates: Sequence[datetime], idx: int, months: int) -> int:
        """Find the index approximately `months` calendar months before dates[idx]."""
        target = dates[idx]
        year, month = target.year, target.month
        month -= months
        while month <= 0:
            year -= 1
            month += 12
        target_day = min(target.day, 28)
        from datetime import date
        target_date = date(year, month, target_day)
        best_i = None
        for i in range(idx, -1, -1):
            if dates[i].date() <= target_date:
                best_i = i
                break
        return best_i

    def compute_signals(
        self,
        prices: Dict[str, List[float]],
        dates: List[datetime],
    ) -> List[DualMomentumSignal]:
        """
        Generate month-end signals with next-day execution.
        Returns one signal per month-end where enough history exists.
        """
        signals: List[DualMomentumSignal] = []
        n = len(dates)
        month_ends = []
        last_month = (dates[0].year, dates[0].month)
        for i, d in enumerate(dates):
            this_month = (d.year, d.month)
            if this_month != last_month:
                month_ends.append(i - 1)
                last_month = this_month
        month_ends.append(n - 1)

        lb_label = f"{self.lookback_months}m"
        for i in month_ends:
            start_i = self._trading_days_ago(dates, i, self.lookback_months)
            if start_i is None or start_i < 0:
                continue

            rets = {}
            valid = True
            for ticker in self.UNIVERSE:
                if ticker not in prices:
                    valid = False
                    break
                start_p = prices[ticker][start_i]
                end_p = prices[ticker][i]
                if start_p == 0 or start_p is None:
                    valid = False
                    break
                rets[ticker] = end_p / start_p - 1.0
            if not valid:
                continue

            best_risk = max(self.RISK_ASSETS, key=lambda t: rets[t])
            selected = self.CASH_ASSET
            reason = f"SHY highest {lb_label} return"
            if rets[best_risk] > rets[self.CASH_ASSET]:
                selected = best_risk
                reason = f"{best_risk} {lb_label} return > SHY"
            elif rets[self.DEFENSIVE_ASSET] > rets[self.CASH_ASSET]:
                selected = self.DEFENSIVE_ASSET
                reason = f"TLT {lb_label} return > SHY (risk assets below SHY)"

            execution_idx = min(i + 1, n - 1)
            signals.append(DualMomentumSignal(
                signal_date=dates[i],
                execution_date=dates[execution_idx],
                lookback_months=self.lookback_months,
                returns=rets,
                selected=selected,
                reason=reason,
            ))

        return signals

    def rule_summary(self) -> str:
        lb = self.lookback_months
        return f"""
DualMomentumEngine ({lb}-month lookback):

Universe: QQQ (risk), GLD (alternative), TLT (defensive), SHY (cash proxy)
Rebalance: monthly at month-end
Execution: next trading day close (1-day lag)

Rules:
1. Compute {lb}-month total returns for QQQ, GLD, TLT, SHY.
2. Pick the higher-returning risk asset (QQQ vs GLD).
3. Absolute momentum filter: hold it only if its return exceeds SHY's return.
4. If neither risk asset beats SHY, hold TLT if TLT beats SHY; otherwise hold SHY.
""".strip()


if __name__ == "__main__":
    print(DualMomentumEngine(12).rule_summary())
