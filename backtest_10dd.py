"""
STONK.AI Backtesting Framework v1.0

Historical signal replay + trade simulation.
Uses Alpaca paid daily bars via alpaca_data.py (or local JSON cache).

Outputs:
  - Cumulative portfolio value vs SPY buy-and-hold
  - Sharpe ratio, max drawdown, win rate, alpha, beta
  - Per-trade summary and CSV export

Usage:
  python backtest.py --start 2024-01-01 --end 2026-06-27 --cash 100000
"""

import argparse
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Allow importing from /opt/stonk-ai when run on the VPS
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")


def load_alpaca_config():
    paths = [BASE / "alpaca_config.json", Path("/opt/stonk-ai/alpaca_config.json")]
    for p in paths:
        if p.exists():
            return json.loads(p.read_text())
    return {}


class BacktestEngine:
    """Replay the signal engine over historical daily bars and simulate trades."""

    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_cash: float = 100_000.0,
        universe: Optional[List[str]] = None,
        benchmark: str = "SPY",
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, Dict] = {}  # symbol -> {qty, cost_basis}
        self.trades: List[Dict] = []
        self.daily_values: List[Dict] = []
        self.benchmark_series: List[float] = []
        self.portfolio_series: List[float] = []
        self.dates: List[str] = []
        self.benchmark_symbol = benchmark
        self.slippage_bps = 8  # 8 basis points per trade
        self.whipsaw_penalty_bps = 3  # additional penalty for VWAP stop whipsaw
        self.universe = universe
        self.high_water_mark: float = initial_cash  # Track peak portfolio value
        self.drawdown_halt: bool = False  # Halt new entries when DD < -15%
        self._halt_cooldown: int = 0  # Cooldown days after halt triggers

        # Defaults from signal_engine if available
        try:
            from signal_engine import DEFAULT_UNIVERSE
            self.universe = self.universe or DEFAULT_UNIVERSE
        except Exception:
            self.universe = self.universe or []

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def fetch_data(self, symbols: List[str]):
        """Fetch daily bars from Alpaca data hub for the backtest window."""
        try:
            from alpaca_data import get_data_hub
            hub = get_data_hub(load_alpaca_config())
            days = (datetime.strptime(self.end_date, "%Y-%m-%d") - datetime.strptime(self.start_date, "%Y-%m-%d")).days + 1
            data = hub.get_daily_bars(symbols, days=days + 60)
            return data
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            return {}

    @staticmethod
    def _slice_to_date(bars: Dict, date_str: str) -> Optional[Dict]:
        """Return bars up to and including a given date."""
        timestamps = bars.get("timestamps", [])
        if not timestamps:
            return None
        # Find index of latest date <= date_str
        idx = -1
        for i, t in enumerate(timestamps):
            if t[:10] <= date_str:
                idx = i
            else:
                break
        if idx < 0:
            return None
        return {
            "closes": bars["closes"][: idx + 1],
            "highs": bars["highs"][: idx + 1],
            "lows": bars["lows"][: idx + 1],
            "volumes": bars["volumes"][: idx + 1],
            "timestamps": bars["timestamps"][: idx + 1],
            "vwap": bars["vwap"][: idx + 1],
            "opens": bars.get("opens", bars["closes"])[: idx + 1],
        }

    # ------------------------------------------------------------------
    # Signal / readiness replay
    # ------------------------------------------------------------------

    def generate_signal_for_symbol(self, symbol: str, bars: Dict, all_bars: Dict) -> Optional[Dict]:
        """
        Reconstruct a lightweight signal using the same readiness logic.
        Returns a dict compatible with the bot's entry/exit logic.
        """
        from signal_engine import SignalEngine
        from readiness_score import compute_readiness
        from mean_reversion_signal import compute_mean_reversion

        closes = bars["closes"]
        volumes = bars["volumes"]
        if len(closes) < 50 or len(volumes) < 20:
            return None

        price = closes[-1]
        avg_volume = sum(volumes[-20:]) / 20
        if avg_volume < 50_000:
            return None

        try:
            rsi14 = SignalEngine._rsi(closes, 14)
            atr14 = SignalEngine._atr(closes, bars["highs"], bars["lows"], 14)
        except Exception:
            return None

        # Momentum/quality/risk/regime scoring (lightweight)
        momentum_20d = (closes[-1] - closes[-21]) / closes[-21] if len(closes) >= 21 else 0.0
        momentum_50d = (closes[-1] - closes[-51]) / closes[-51] if len(closes) >= 51 else 0.0
        volatility = SignalEngine._volatility(closes, 20)
        spy_corr = SignalEngine._correlation(closes, all_bars.get("SPY", {}).get("closes", []), 20)

        # Approximate total_score (0-100)
        momentum_score = 50 + 25 * math.tanh(momentum_20d * 10) + 15 * math.tanh(momentum_50d * 5) - 10 * abs(spy_corr)
        momentum_score = max(0, min(100, momentum_score))

        ema20 = sum(closes[-20:]) / 20
        ema50 = sum(closes[-50:]) / 50
        quality_score = 80 if price > ema20 > ema50 else 50 if price > ema50 else 20
        risk_score = max(0, min(100, 90 - volatility * 400 - (atr14 / price * 400) - 10 * abs(spy_corr - 0.6)))

        # Regime score
        spy = all_bars.get("SPY", {}).get("closes", [])
        qqq = all_bars.get("QQQ", {}).get("closes", [])
        vixy = all_bars.get("VIXY", {}).get("closes", [])
        regime_score = 50.0
        if len(spy) >= 20:
            regime_score += 25 * math.tanh(((spy[-1] - spy[-20]) / spy[-20]) * 8)
        if len(qqq) >= 20:
            regime_score += 15 * math.tanh(((qqq[-1] - qqq[-20]) / qqq[-20]) * 8)
        if len(vixy) >= 5:
            regime_score -= 25 * math.tanh(((vixy[-1] - vixy[-5]) / vixy[-5]) * 5)
        regime_score = max(0, min(100, regime_score))

        total = 0.4 * momentum_score + 0.25 * quality_score + 0.20 * risk_score + 0.15 * regime_score

        # Determine sector
        sectors = {
            "AI/Growth": ["PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "PATH", "PANW", "APP", "GTLB", "ELF", "DUOL", "ESTC", "CFLT", "S"],
            "Semiconductors": ["AMD", "NVDA", "AVGO", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON"],
            "Tech Giants": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "NOW", "TEAM", "VEEV", "DOCN"],
            "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY"],
            "Consumer/Platform": ["UBER", "DKNG", "SHOP", "ROKU", "TTD", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "CHWY", "ETSY"],
            "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
            "Retail/Lifestyle": ["LULU", "NKE", "COST", "WMT", "HD", "ELF"],
            "Cloud/Data": ["SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW"],
        }
        sector = "Other"
        for s, syms in sectors.items():
            if symbol in syms:
                sector = s
                break

        readiness = compute_readiness(
            symbol=symbol,
            total_score=total,
            rsi14=rsi14,
            closes=closes,
            volumes=volumes,
            price=price,
            sector=sector,
            all_bars=all_bars,
            options_implied_vol=None,
        )

        # Mean reversion check
        mr = compute_mean_reversion(symbol, closes, volumes, price, rsi14)

        signal = {
            "symbol": symbol,
            "price": price,
            "readiness_score": readiness.readiness_score,
            "confirmation_count": readiness.confirmation_count,
            "entry_eligible": readiness.entry_eligible or readiness.confirmation_count >= 2,
            "tier": readiness.tier,
            "atr14": atr14,
            "rsi14": rsi14,
            "sector": sector,
            "strategy_type": "momentum",
            "total_score": total,
        }

        # If mean reversion is stronger, prefer it
        if mr and mr.entry_eligible and (not readiness.entry_eligible or mr.reversion_score > readiness.readiness_score):
            signal.update({
                "readiness_score": mr.readiness_score,
                "confirmation_count": mr.confirmation_count,
                "entry_eligible": mr.entry_eligible,
                "tier": mr.tier,
                "strategy_type": "mean_reversion",
                "total_score": mr.reversion_score,
            })

        return signal

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def _portfolio_value(self, prices: Dict[str, float]) -> float:
        equity = self.cash
        for sym, pos in self.positions.items():
            if sym in prices and prices[sym] > 0:
                equity += pos["qty"] * prices[sym]
        return equity

    def run(self, max_positions: int = 10, verbose: bool = True):
        """Run the backtest with T+1 execution (no lookahead bias).

        Signals are generated from day T's close.
        Orders are executed at day T+1's open price (realistic execution lag).
        Portfolio is marked-to-market at each day's close.
        """
        symbols = [self.benchmark_symbol] + list(self.universe)
        data = self.fetch_data(symbols)
        if not data:
            logger.error("No data fetched.")
            return None

        all_dates = data.get(self.benchmark_symbol, {}).get("timestamps", [])
        if not all_dates:
            logger.error("No benchmark dates.")
            return None

        # Build date list within range
        dates = [d[:10] for d in all_dates if self.start_date <= d[:10] <= self.end_date]
        if not dates:
            logger.error("No dates in range.")
            return None

        first_bm = None
        pending_orders = []  # Orders queued from day T, executed at day T+1

        for i, date_str in enumerate(dates):
            # Slice all data up to this date (for signal generation + mark-to-market)
            sliced = {sym: self._slice_to_date(b, date_str) for sym, b in data.items() if b}
            if not sliced.get(self.benchmark_symbol):
                continue

            # Current prices = today's close (for mark-to-market)
            current_prices = {sym: sliced[sym]["closes"][-1] for sym in sliced if sliced[sym]}

            # Execute pending orders from yesterday's signals at today's open
            if pending_orders:
                for order in pending_orders:
                    sym = order["symbol"]
                    if sym not in current_prices:
                        continue
                    # Use today's open if available, otherwise today's close
                    exec_price = current_prices[sym]  # Fallback to close
                    bars_for_sym = data.get(sym, {})
                    opens = bars_for_sym.get("opens", [])
                    timestamps = bars_for_sym.get("timestamps", [])
                    for j, ts in enumerate(timestamps):
                        if ts[:10] == date_str and j < len(opens):
                            exec_price = opens[j]
                            break

                    if order["action"] == "BUY":
                        # Conviction-based sizing: STRONG_NOW gets 1.5x, NOW gets 1.0x
                        multiplier = order.get("multiplier", 1.0)
                        allocation = order["allocation"] * multiplier
                        qty = int(allocation / exec_price) if exec_price > 0 else 0
                        if qty > 0:
                            # Apply slippage to cost (not price) so it actually impacts returns
                            cost = qty * exec_price * (1 + self.slippage_bps / 10000)
                            self.cash -= cost
                            self.positions[sym] = {"qty": qty, "cost_basis": cost, "entry_date_idx": 0, "entry_price": cost / qty}
                            self.trades.append({
                                "date": date_str,
                                "action": "BUY",
                                "symbol": sym,
                                "qty": qty,
                                "price": exec_price,
                                "execution": "T+1 open",
                                "slippage_cost": (cost - qty * exec_price),
                                "tier": order.get("tier", "NOW"),
                            })
                    elif order["action"] == "SELL":
                        pos = self.positions.pop(sym, None)
                        if pos:
                            proceeds = pos["qty"] * exec_price * (1 - self.slippage_bps / 10000)
                            self.cash += proceeds
                            self.trades.append({
                                "date": date_str,
                                "action": "SELL",
                                "symbol": sym,
                                "qty": pos["qty"],
                                "price": exec_price,
                                "execution": "T+1 open",
                                "slippage_cost": (pos["qty"] * exec_price - proceeds),
                                "reason": order.get("reason", "tier_demotion"),
                            })
                pending_orders = []

            # Mark-to-market at today's close
            bm_price = sliced[self.benchmark_symbol]["closes"][-1]
            if first_bm is None:
                first_bm = bm_price

            # Generate signals from today's close (for execution tomorrow)
            signals = []
            for sym in self.universe:
                if sym not in sliced or not sliced[sym]:
                    continue
                sig = self.generate_signal_for_symbol(sym, sliced[sym], sliced)
                if sig and sig.get("entry_eligible"):
                    signals.append(sig)

            signals.sort(key=lambda s: s["readiness_score"], reverse=True)
            top_signals = signals[:max_positions]
            top_symbols = set(s["symbol"] for s in top_signals)

            # Check stop losses first (-10% hard stop)
            for sym in list(self.positions.keys()):
                pos = self.positions.get(sym, {})
                entry_price = pos.get("entry_price", 0)
                if entry_price > 0 and sym in current_prices:
                    loss_pct = (current_prices[sym] - entry_price) / entry_price
                    if loss_pct <= -0.10:
                        pending_orders.append({"action": "SELL", "symbol": sym, "reason": "stop_loss"})
                        continue

            # Queue sells for tomorrow at T+1 open (tier demotion)
            for sym in list(self.positions.keys()):
                if sym in [o["symbol"] for o in pending_orders if o["action"] == "SELL"]:
                    continue  # Already queued for stop loss
                if sym not in top_symbols:
                    pos = self.positions[sym]
                    days_held = pos.get("entry_date_idx", 0)
                    if days_held < 20:
                        pos["entry_date_idx"] = days_held + 1
                        continue
                    sym_signal = next((s for s in signals if s["symbol"] == sym), None)
                    if sym_signal and sym_signal["readiness_score"] >= 55:
                        pos["entry_date_idx"] = days_held + 1
                        continue
                    # Queue sell for tomorrow
                    pending_orders.append({"action": "SELL", "symbol": sym})

            # --- Drawdown halt check ---
            # Track high water mark and halt new entries if DD > -15%.
            # On halt: reset HWM to current PV and impose 3-day cooldown.
            # After cooldown, resume entries normally (fresh HWM baseline).
            pv_now = self._portfolio_value(current_prices)
            if pv_now > self.high_water_mark:
                self.high_water_mark = pv_now
            dd_pct = (pv_now - self.high_water_mark) / self.high_water_mark if self.high_water_mark > 0 else 0.0
            if dd_pct <= -0.10:
                if not self.drawdown_halt:
                    logger.info(f"⚠️ Drawdown halt triggered: DD={dd_pct:.1%} (HWM=${self.high_water_mark:,.0f})")
                self.drawdown_halt = True
                self._halt_cooldown = 3  # 3-day cooldown
                self.high_water_mark = pv_now  # Reset HWM for fresh baseline
            elif self._halt_cooldown > 0:
                self._halt_cooldown -= 1
                self.drawdown_halt = True  # Still in cooldown
            else:
                if self.drawdown_halt:
                    logger.info(f"✅ Drawdown halt lifted: DD={dd_pct:.1%}")
                self.drawdown_halt = False

            # Queue buys for tomorrow at T+1 open (conviction-based sizing)
            # Skip new entries if drawdown halt is active (only allow exits)
            available_cash = self.cash
            # Only deploy 90% of cash (keep 10% cash floor like live bot)
            deployable_cash = available_cash * 0.90
            target_symbols = [s for s in top_signals if s["symbol"] not in self.positions]
            if target_symbols and deployable_cash > 0 and not self.drawdown_halt:
                base_allocation = deployable_cash / len(target_symbols)
                for sig in top_signals:
                    sym = sig["symbol"]
                    if sym in self.positions or sym not in current_prices:
                        continue
                    multiplier = 1.5 if sig.get("tier") == "STRONG_NOW" else 1.0
                    pending_orders.append({
                        "action": "BUY",
                        "symbol": sym,
                        "allocation": base_allocation,
                        "multiplier": multiplier,
                        "tier": sig.get("tier", "NOW"),
                    })
            elif self.drawdown_halt:
                logger.debug(f"Drawdown halt active (DD={dd_pct:.1%}), skipping new entries")

            # Update entry_date_idx for held positions
            for sym in list(self.positions.keys()):
                self.positions[sym]["entry_date_idx"] = self.positions[sym].get("entry_date_idx", 0) + 1

            pv = self._portfolio_value(current_prices)
            self.daily_values.append({
                "date": date_str,
                "portfolio_value": pv,
                "cash": self.cash,
                "positions": len(self.positions),
            })
            self.portfolio_series.append(pv)
            self.benchmark_series.append(first_bm * (bm_price / first_bm))
            self.dates.append(date_str)

            if verbose and date_str in dates[::30]:
                logger.info(f"{date_str} PV=${pv:,.2f} Pos={len(self.positions)} Cash=${self.cash:,.2f}")

        return self.report()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def report(self) -> Dict:
        if not self.portfolio_series:
            return {}

        pv = np.array(self.portfolio_series)
        bm = np.array(self.benchmark_series)
        returns = np.diff(pv) / pv[:-1]
        bm_returns = np.diff(bm) / bm[:-1]

        # Sharpe ratio (annualized, assuming 252 trading days)
        sharpe = 0.0
        if len(returns) > 1 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * math.sqrt(252)

        # Max drawdown
        peak = np.maximum.accumulate(pv)
        drawdowns = (pv - peak) / peak
        max_dd = drawdowns.min()

        # Win rate (profitable days)
        win_rate = (returns > 0).sum() / max(1, len(returns))

        # Alpha / Beta vs benchmark
        alpha, beta = self._alpha_beta(returns, bm_returns)

        # Total return
        total_return = (pv[-1] - self.initial_cash) / self.initial_cash

        report = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_cash": self.initial_cash,
            "final_value": float(pv[-1]),
            "total_return": float(total_return),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(max_dd),
            "win_rate": float(win_rate),
            "alpha": float(alpha),
            "beta": float(beta),
            "trades": len(self.trades),
            "trades_list": self.trades[:20],  # summary only
        }

        # Save report
        out_path = BASE / "backtest_report.json"
        out_path.write_text(json.dumps(report, indent=2, default=str))
        logger.info(f"Backtest report saved to {out_path}")
        return report

    @staticmethod
    def _alpha_beta(returns: np.ndarray, bm_returns: np.ndarray) -> Tuple[float, float]:
        if len(returns) < 2 or len(bm_returns) < 2:
            return 0.0, 0.0
        # Align lengths
        n = min(len(returns), len(bm_returns))
        r = returns[-n:]
        b = bm_returns[-n:]
        cov = np.cov(r, b)[0, 1]
        var_b = np.var(b)
        beta = cov / var_b if var_b > 0 else 0.0
        alpha = r.mean() - beta * b.mean()
        return alpha, beta


def main():
    parser = argparse.ArgumentParser(description="STONK.AI Backtest Framework")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--benchmark", default="SPY")
    args = parser.parse_args()

    engine = BacktestEngine(
        start_date=args.start,
        end_date=args.end,
        initial_cash=args.cash,
        benchmark=args.benchmark,
    )
    report = engine.run(max_positions=args.max_positions)
    if report:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
