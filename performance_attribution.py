"""
STONK.AI Performance Attribution v1.0

Analyzes live trades and signals to answer:
  - Are we beating the benchmark?
  - Which factors (confirmations) predict winners?
  - What does the per-trade journal show?

Inputs:
  /opt/stonk-ai/trades_log.json
  /opt/stonk-ai/signals.json
  /opt/stonk-ai/portfolio_history.json

Outputs:
  /opt/stonk-ai/performance_attribution.json
  /opt/stonk-ai/performance_attribution.csv
"""

import json
import logging
import math
from collections import defaultdict
from datetime import datetime
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


class PerformanceAttribution:
    def __init__(self):
        self.trades = []
        self.signals = []
        self.portfolio_history = []
        self.signal_map: Dict[str, List[Dict]] = defaultdict(list)

    def load(self):
        trades_data = load_json(BASE / "trades_log.json", {"trades": []})
        self.trades = trades_data.get("trades", [])

        signals_data = load_json(BASE / "signals.json", {"signals": []})
        self.signals = signals_data.get("signals", [])

        ph = load_json(BASE / "portfolio_history.json", {})
        if isinstance(ph, dict):
            self.portfolio_history = ph.get("checks", [])
        else:
            self.portfolio_history = ph

        # Build signal map by date + symbol for easy lookup
        # If signals don't have generated_at, also index by symbol only
        has_dates = any(s.get("generated_at") for s in self.signals)
        for s in self.signals:
            sym = s.get("symbol")
            if not sym:
                continue
            generated = (s.get("generated_at") or "")[:10]
            self.signal_map[(sym, generated)].append(s)
            if not has_dates:
                # No date info — index by symbol only as fallback
                self.signal_map[(sym, "")].append(s)

    # ------------------------------------------------------------------
    # Portfolio metrics
    # ------------------------------------------------------------------

    def portfolio_metrics(self) -> Dict:
        if not self.portfolio_history or len(self.portfolio_history) < 2:
            return {}

        values = np.array([float(p.get("portfolio_value", 0)) for p in self.portfolio_history if p.get("portfolio_value")])
        if len(values) < 2:
            return {}

        returns = np.diff(values) / values[:-1]

        # SPY benchmark history may not be in portfolio_history; assume SPY returns from data if available
        bm_returns = self._benchmark_returns()

        sharpe = 0.0
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * math.sqrt(252)

        peak = np.maximum.accumulate(values)
        max_dd = ((values - peak) / peak).min()

        alpha, beta = 0.0, 0.0
        if len(bm_returns) >= len(returns) and len(returns) > 1:
            n = len(returns)
            b = bm_returns[-n:]
            cov = np.cov(returns, b)[0, 1]
            var_b = np.var(b)
            beta = cov / var_b if var_b > 0 else 0.0
            alpha = returns.mean() - beta * b.mean()

        return {
            "periods": len(values),
            "start_value": float(values[0]),
            "end_value": float(values[-1]),
            "total_return": float((values[-1] - values[0]) / values[0]),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(max_dd),
            "alpha": float(alpha),
            "beta": float(beta),
            "annualized_volatility": float(returns.std() * math.sqrt(252)),
        }

    def _benchmark_returns(self) -> np.ndarray:
        """Try to load SPY history from market_indices.json or derive from portfolio history."""
        # First try portfolio_history benchmark values
        if self.portfolio_history:
            bm_values = [float(p.get("benchmark_value", 0)) for p in self.portfolio_history if p.get("benchmark_value")]
            if len(bm_values) >= 2:
                return np.diff(np.array(bm_values)) / np.array(bm_values)[:-1]
        # Fallback to market_indices.json
        mi = load_json(BASE / "market_indices.json", {})
        if mi and isinstance(mi, dict) and "spy_history" in mi:
            hist = mi["spy_history"]
            if len(hist) >= 2:
                prices = np.array([float(h["close"]) for h in hist])
                return np.diff(prices) / prices[:-1]
        return np.array([])

    # ------------------------------------------------------------------
    # Factor decomposition
    # ------------------------------------------------------------------

    def factor_decomposition(self) -> Dict:
        """For each closed trade, find the signal at entry and score confirmations."""
        if not self.trades:
            return {}

        # Group trades into round trips (simple FIFO per symbol)
        positions = defaultdict(list)  # symbol -> list of buy trades
        closed_trades = []

        for t in sorted(self.trades, key=lambda x: x.get("timestamp", "")):
            action = t.get("action", "").upper()
            sym = t.get("symbol")
            if action == "BUY":
                positions[sym].append(t)
            elif action == "SELL" and positions[sym]:
                buy = positions[sym].pop(0)
                qty = min(buy.get("qty", 0), t.get("qty", 0))
                if qty > 0:
                    buy_price = buy.get("price", 0)
                    sell_price = t.get("price", 0)
                    pnl_pct = (sell_price - buy_price) / buy_price if buy_price > 0 else 0
                    closed_trades.append({
                        "symbol": sym,
                        "buy_date": buy.get("timestamp", "")[:10],
                        "sell_date": t.get("timestamp", "")[:10],
                        "qty": qty,
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                        "pnl_pct": pnl_pct,
                    })

        if not closed_trades:
            return {"closed_trades": 0, "win_rate": 0.0}

        # Correlate entry signals with outcomes
        factor_scores = defaultdict(list)  # factor -> list of (score, pnl)
        for ct in closed_trades:
            sigs = self.signal_map.get((ct["symbol"], ct["buy_date"]), [])
            if not sigs:
                # Try previous day
                sigs = self.signal_map.get((ct["symbol"], self._prev_day(ct["buy_date"])), [])
            if not sigs:
                # Fallback: match by symbol only (current signals as proxy)
                sigs = self.signal_map.get((ct["symbol"], ""), [])
            sig = sigs[0] if sigs else {}
            conf = sig.get("confirmations", {})

            factor_scores["readiness_score"].append((sig.get("readiness_score", 0), ct["pnl_pct"]))
            factor_scores["confirmation_count"].append((sig.get("confirmation_count", 0), ct["pnl_pct"]))
            factor_scores["volume_confirmed"].append((1 if conf.get("volume_confirmed") else 0, ct["pnl_pct"]))
            factor_scores["macd_turning"].append((1 if conf.get("macd_turning") else 0, ct["pnl_pct"]))
            factor_scores["above_ema"].append((1 if conf.get("above_ema") else 0, ct["pnl_pct"]))
            factor_scores["sector_strong"].append((1 if conf.get("sector_strong") else 0, ct["pnl_pct"]))
            factor_scores["rsi_neutral_not_overbought"].append((1 if conf.get("rsi_signal") != "overbought" else 0, ct["pnl_pct"]))

        factor_stats = {}
        for factor, pairs in factor_scores.items():
            if not pairs:
                continue
            xs = np.array([p[0] for p in pairs])
            ys = np.array([p[1] for p in pairs])
            if len(xs) < 2 or xs.std() == 0:
                continue
            corr = np.corrcoef(xs, ys)[0, 1] if xs.std() > 0 and ys.std() > 0 else 0.0
            factor_stats[factor] = {
                "count": len(pairs),
                "correlation_with_pnl": float(corr),
                "avg_pnl_when_true": float(ys[xs > 0].mean()) if (xs > 0).any() else None,
                "avg_pnl_when_false": float(ys[xs == 0].mean()) if (xs == 0).any() else None,
            }

        winners = [ct for ct in closed_trades if ct["pnl_pct"] > 0]
        losers = [ct for ct in closed_trades if ct["pnl_pct"] <= 0]

        return {
            "closed_trades": len(closed_trades),
            "win_rate": len(winners) / len(closed_trades),
            "avg_winner": float(np.mean([w["pnl_pct"] for w in winners])) if winners else 0.0,
            "avg_loser": float(np.mean([l["pnl_pct"] for l in losers])) if losers else 0.0,
            "factor_correlations": factor_stats,
            "top_winners": sorted(closed_trades, key=lambda x: x["pnl_pct"], reverse=True)[:5],
            "top_losers": sorted(closed_trades, key=lambda x: x["pnl_pct"])[:5],
        }

    @staticmethod
    def _prev_day(date_str: str) -> str:
        try:
            from datetime import timedelta
            d = datetime.strptime(date_str, "%Y-%m-%d")
            return (d - timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            return date_str

    # ------------------------------------------------------------------
    # Trade journal
    # ------------------------------------------------------------------

    def trade_journal(self) -> List[Dict]:
        """Build a journal entry for each closed round trip."""
        positions = defaultdict(list)
        journal = []
        for t in sorted(self.trades, key=lambda x: x.get("timestamp", "")):
            action = t.get("action", "").upper()
            sym = t.get("symbol")
            if action == "BUY":
                positions[sym].append(t)
            elif action == "SELL" and positions[sym]:
                buy = positions[sym].pop(0)
                qty = min(buy.get("qty", 0), t.get("qty", 0))
                if qty > 0:
                    pnl = (t.get("price", 0) - buy.get("price", 0)) * qty
                    pnl_pct = (t.get("price", 0) - buy.get("price", 0)) / buy.get("price", 0) if buy.get("price", 0) > 0 else 0
                    sigs = self.signal_map.get((sym, buy.get("timestamp", "")[:10]), [])
                    if not sigs:
                        sigs = self.signal_map.get((sym, ""), [])
                    sig = sigs[0] if sigs else {}
                    journal.append({
                        "symbol": sym,
                        "entry_date": buy.get("timestamp", ""),
                        "exit_date": t.get("timestamp", ""),
                        "qty": qty,
                        "entry_price": buy.get("price", 0),
                        "exit_price": t.get("price", 0),
                        "pnl_usd": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 4),
                        "entry_readiness": sig.get("readiness_score"),
                        "entry_confirmations": sig.get("confirmation_count"),
                        "strategy_type": sig.get("strategy_type", "unknown"),
                        "rationale": buy.get("rationale", ""),
                        "result": "win" if pnl_pct > 0 else "loss",
                        "lesson": self._lesson(pnl_pct, sig),
                    })
        return journal

    @staticmethod
    def _lesson(pnl_pct: float, sig: Dict) -> str:
        if pnl_pct > 0.10:
            return "Strong winner — factor alignment worked."
        elif pnl_pct > 0:
            return "Modest winner — held to target."
        elif pnl_pct > -0.05:
            return "Small loss — likely noise or stop too tight."
        else:
            return "Significant loss — review entry timing and sector exposure."

    # ------------------------------------------------------------------
    # Run + output
    # ------------------------------------------------------------------

    def run(self) -> Dict:
        self.load()
        metrics = self.portfolio_metrics()
        factors = self.factor_decomposition()
        journal = self.trade_journal()

        report = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "portfolio_metrics": metrics,
            "factor_decomposition": factors,
            "trade_journal": journal[:50],  # keep first 50
        }

        out_json = BASE / "performance_attribution.json"
        out_json.write_text(json.dumps(report, indent=2, default=str))
        logger.info(f"Performance attribution saved to {out_json}")

        # CSV export for journal
        if journal:
            import csv
            out_csv = BASE / "performance_attribution.csv"
            with open(out_csv, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=journal[0].keys())
                writer.writeheader()
                writer.writerows(journal)
            logger.info(f"Trade journal CSV saved to {out_csv}")

        return report


def main():
    attr = PerformanceAttribution()
    report = attr.run()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
