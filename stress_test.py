"""
STONK.AI Stress Testing Framework v1.0

Portfolio-level risk analytics:
  - Correlation matrix of held positions
  - Value at Risk (VaR) parametric + historical
  - Scenario simulation (market crash, sector rotation, single-stock collapse)
  - Concentration risk report

Inputs:
  /opt/stonk-ai/portfolio_data.json
  /opt/stonk-ai/signals.json
  Alpaca daily bars via alpaca_data.py

Outputs:
  /opt/stonk-ai/stress_test_report.json
"""

import argparse
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

BASE = Path(__file__).resolve().parent


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}")
        return default


class StressTest:
    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days
        self.portfolio_data: Dict = {}
        self.position_symbols: List[str] = []
        self.positions: List[Dict] = []
        self.historical_returns: Optional[np.ndarray] = None
        self.weights: Optional[np.ndarray] = None

    def load(self):
        self.portfolio_data = load_json(BASE / "portfolio_data.json", {})
        self.positions = self.portfolio_data.get("positions", [])
        self.position_symbols = [p["symbol"] for p in self.positions]
        self.pv = self.portfolio_data.get("account", {}).get("portfolio_value", 0)

    def fetch_historical_returns(self):
        """Fetch daily returns for each held symbol over lookback window."""
        if not self.position_symbols:
            return
        try:
            from alpaca_data import get_data_hub
            hub = get_data_hub()
            data = hub.get_daily_bars(self.position_symbols, days=self.lookback_days)
        except Exception as e:
            logger.error(f"Failed to fetch historical bars: {e}")
            return

        returns = {}
        valid_symbols = []
        for sym, bars in data.items():
            closes = bars.get("closes", [])
            if len(closes) < 30:
                continue
            rets = np.diff(closes) / closes[:-1]
            if len(rets) > 0:
                returns[sym] = rets
                valid_symbols.append(sym)

        if not valid_symbols:
            return

        # Align lengths (trim to minimum)
        min_len = min(len(returns[s]) for s in valid_symbols)
        self.historical_returns = np.vstack([returns[s][-min_len:] for s in valid_symbols]).T
        self.position_symbols = valid_symbols

        # Compute portfolio weights
        total_equity = sum(p.get("market_value", 0) for p in self.positions if p["symbol"] in valid_symbols)
        self.weights = np.array([
            next((p.get("market_value", 0) / total_equity for p in self.positions if p["symbol"] == sym), 0.0)
            for sym in valid_symbols
        ])

    # ------------------------------------------------------------------
    # Correlation matrix
    # ------------------------------------------------------------------

    def correlation_matrix(self) -> Dict:
        if self.historical_returns is None or len(self.position_symbols) < 2:
            return {}
        corr = np.corrcoef(self.historical_returns, rowvar=False)
        result = {}
        for i, sym in enumerate(self.position_symbols):
            result[sym] = {self.position_symbols[j]: float(corr[i, j]) for j in range(len(self.position_symbols))}
        return result

    # ------------------------------------------------------------------
    # VaR
    # ------------------------------------------------------------------

    def var(self) -> Dict:
        if self.historical_returns is None or self.weights is None:
            return {}

        # Portfolio returns
        portfolio_rets = self.historical_returns @ self.weights

        # Parametric VaR (assuming normal distribution)
        mean = portfolio_rets.mean()
        std = portfolio_rets.std()
        var_95_param = -(mean - 1.645 * std) * self.pv
        var_99_param = -(mean - 2.326 * std) * self.pv

        # Historical VaR
        var_95_hist = -np.percentile(portfolio_rets, 5) * self.pv
        var_99_hist = -np.percentile(portfolio_rets, 1) * self.pv

        return {
            "parametric_95": float(var_95_param),
            "parametric_99": float(var_99_param),
            "historical_95": float(var_95_hist),
            "historical_99": float(var_99_hist),
            "daily_volatility": float(std),
            "portfolio_value": self.pv,
        }

    # ------------------------------------------------------------------
    # Scenario simulation
    # ------------------------------------------------------------------

    def scenario_simulation(self) -> Dict:
        """Simulate P&L impact of several stress scenarios."""
        if self.pv <= 0 or not self.positions:
            return {}

        scenarios = {}

        # 1. Broad market -5%
        scenarios["market_down_5pct"] = self._simulate_market_shock(-0.05)

        # 2. Sector rotation: tech/growth down -8%, defensives up +2%
        scenarios["tech_rotation"] = self._simulate_sector_shock(
            sectors=["AI/Growth", "Semiconductors", "Cloud/Data"],
            shock=-0.08,
            offset_sectors=["Retail/Lifestyle"],
            offset_shock=0.02,
        )

        # 3. Single largest position drops -25%
        largest = max(self.positions, key=lambda p: p.get("market_value", 0), default=None)
        if largest:
            loss = largest.get("market_value", 0) * 0.25
            scenarios["largest_position_down_25pct"] = {
                "symbol": largest["symbol"],
                "position_value": largest.get("market_value", 0),
                "estimated_loss": float(loss),
                "portfolio_impact_pct": float(loss / self.pv),
            }

        # 4. Portfolio correlation stress: all correlations -> 1, -5% market
        scenarios["correlation_spike"] = self._simulate_correlation_spike(-0.05)

        return scenarios

    def _position_weight(self, symbol: str) -> float:
        mv = next((p.get("market_value", 0) for p in self.positions if p["symbol"] == symbol), 0)
        return mv / self.pv if self.pv > 0 else 0

    def _simulate_market_shock(self, shock: float) -> Dict:
        beta = 1.3  # assume portfolio is slightly more volatile than SPY
        estimated_impact = shock * beta
        loss = self.pv * estimated_impact
        return {
            "shock": shock,
            "assumed_beta": beta,
            "estimated_impact_pct": float(estimated_impact),
            "estimated_loss": float(-loss),
            "new_portfolio_value": float(self.pv + loss),
        }

    def _simulate_sector_shock(self, sectors: List[str], shock: float, offset_sectors: List[str], offset_shock: float) -> Dict:
        sector_map = {
            "AI/Growth": ["PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "PATH", "PANW", "APP", "GTLB", "ELF", "DUOL", "ESTC", "CFLT", "S"],
            "Semiconductors": ["AMD", "NVDA", "AVGO", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON"],
            "Cloud/Data": ["SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW"],
            "Retail/Lifestyle": ["LULU", "NKE", "COST", "WMT", "HD", "ELF"],
        }
        affected = set()
        for s in sectors:
            affected.update(sector_map.get(s, []))
        offset = set()
        for s in offset_sectors:
            offset.update(sector_map.get(s, []))

        impact = 0.0
        for p in self.positions:
            sym = p["symbol"]
            w = self._position_weight(sym)
            if sym in affected:
                impact += w * shock
            elif sym in offset:
                impact += w * offset_shock
        loss = self.pv * impact
        return {
            "affected_sectors": sectors,
            "shock": shock,
            "offset_shock": offset_shock,
            "estimated_impact_pct": float(impact),
            "estimated_loss": float(-loss),
            "new_portfolio_value": float(self.pv + loss),
        }

    def _simulate_correlation_spike(self, market_shock: float) -> Dict:
        beta = 1.3
        impact = market_shock * beta
        loss = self.pv * impact
        return {
            "assumption": "all correlations -> 1",
            "market_shock": market_shock,
            "estimated_impact_pct": float(impact),
            "estimated_loss": float(-loss),
            "new_portfolio_value": float(self.pv + loss),
        }

    # ------------------------------------------------------------------
    # Concentration risk
    # ------------------------------------------------------------------

    def concentration_risk(self) -> Dict:
        if not self.positions:
            return {}
        total = sum(p.get("market_value", 0) for p in self.positions)
        max_pos = max(self.positions, key=lambda p: p.get("market_value", 0), default={})
        sectors = defaultdict(float)
        for p in self.positions:
            sectors[p.get("sector", "Other")] += p.get("market_value", 0)
        max_sector = max(sectors.items(), key=lambda x: x[1], default=("None", 0))
        return {
            "position_count": len(self.positions),
            "total_equity": float(total),
            "largest_position": {
                "symbol": max_pos.get("symbol"),
                "market_value": max_pos.get("market_value", 0),
                "pct_of_portfolio": float(max_pos.get("market_value", 0) / self.pv) if self.pv > 0 else 0,
            },
            "largest_sector": {
                "sector": max_sector[0],
                "market_value": float(max_sector[1]),
                "pct_of_portfolio": float(max_sector[1] / self.pv) if self.pv > 0 else 0,
            },
            "sector_breakdown": {k: float(v / self.pv) for k, v in sectors.items()},
        }

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        self.load()
        self.fetch_historical_returns()

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "portfolio_value": self.pv,
            "lookback_days": self.lookback_days,
            "correlation_matrix": self.correlation_matrix(),
            "value_at_risk": self.var(),
            "scenarios": self.scenario_simulation(),
            "concentration_risk": self.concentration_risk(),
        }

        out_path = BASE / "stress_test_report.json"
        out_path.write_text(json.dumps(report, indent=2, default=str))
        logger.info(f"Stress test report saved to {out_path}")
        return report


def main():
    parser = argparse.ArgumentParser(description="STONK.AI Stress Test")
    parser.add_argument("--lookback", type=int, default=252)
    args = parser.parse_args()

    st = StressTest(lookback_days=args.lookback)
    report = st.run()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
