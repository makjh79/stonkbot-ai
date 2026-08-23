#!/usr/bin/env python3
"""
STONK.AI v3 Trend-Following + Tactical Satellite Engine v1
=========================================================

Clean signal engine built from scratch for the new trend architecture.

Core model
----------
- Market regime driven by SPY/QQQ 200-day EMA slope + 50/200 EMA cross.
- RISK_ON : price > 200EMA and 50EMA > 200EMA.
- RISK_OFF: price < 200EMA.
- RECOVERY: price > 50EMA but < 200EMA.

Long equity selection
---------------------
- Top N names from the 63-symbol universe by combined:
  12-month momentum + 3-month momentum + volatility-adjusted score.

Short / hedge leg
-----------------
- In RISK_OFF, allocate 0-50% to an inverse-QQQ proxy.

Tactical satellite
------------------
- Limited pullback entries only when core trend is RECOVERY or RISK_ON and
  the name is already in the top momentum bucket.

Position sizing
---------------
- Base size configurable (default 5%), max position 15%.
- Max total gross exposure 150%.
- Max net exposure 100% long / 50% short.

Risk management
---------------
- -15% drawdown halt.
- Max sector concentration 25%.

Author: OpenClaw subagent
Date: 2026-08-23
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")

COST_PER_SIDE = 0.001

SECTOR_PEERS = {
    "AI/Growth": ["PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "PANW", "APP", "GTLB", "ELF", "DUOL", "ESTC", "CFLT", "S"],
    "Semiconductors": ["AMD", "NVDA", "AVGO", "MU", "LRCX", "AMAT", "KLAC", "MRVL", "QCOM"],
    "Tech Giants": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "NOW", "TEAM", "VEEV"],
    "Fintech": ["HOOD", "COIN", "SQ", "UPST", "SOFI", "PAYO"],
    "Consumer/Platform": ["UBER", "DKNG", "SHOP", "ROKU", "TTD", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "CHWY", "ETSY"],
    "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
    "Retail/Lifestyle": ["LULU", "NKE", "COST", "WMT", "HD", "ELF"],
    "Cloud/Data": ["SNOW", "MDB", "GTLB", "CFLT", "ESTC", "TEAM", "NOW"],
}
SYMBOL_TO_SECTOR: Dict[str, str] = {}
for sector, syms in SECTOR_PEERS.items():
    for s in syms:
        SYMBOL_TO_SECTOR[s] = sector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    mult = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = (v - e) * mult + e
    return e


def _realized_volatility(closes: List[float], period: int = 20) -> float:
    if len(closes) < period + 1:
        return 0.02
    arr = np.array(closes[-(period + 1):])
    rets = np.diff(arr) / arr[:-1]
    return float(np.std(rets) * math.sqrt(252))


def _atr_pct(closes: List[float], highs: List[float], lows: List[float], idx: int, period: int = 14) -> float:
    if idx < period:
        return 0.02
    trs = []
    for j in range(idx - period + 1, idx + 1):
        tr = max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
        trs.append(tr)
    return (sum(trs) / len(trs)) / closes[idx]


def load_bars(path: Path) -> Dict[str, Dict[str, List]]:
    with open(path) as f:
        return json.load(f)


def load_cached_regime_etfs(path: Path) -> Dict[str, pd.Series]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return {sym: pd.Series(v["prices"], index=pd.to_datetime(v["dates"], utc=True)) for sym, v in data.items()}


# ---------------------------------------------------------------------------
# Core trend model
# ---------------------------------------------------------------------------

class TrendModel:
    """
    Compute market regime from SPY/QQQ closes.

    RISK_ON  : price > 200EMA and 50EMA > 200EMA
    RISK_OFF : price < 200EMA
    RECOVERY : price > 50EMA but < 200EMA
    """

    def __init__(self, benchmark: str = "SPY", ema_fast: int = 50, ema_slow: int = 200):
        self.benchmark = benchmark
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def compute_from_series(self, spy_series: pd.Series, qqq_series: pd.Series, dates: List[str]) -> pd.DataFrame:
        """Compute regime for the requested window dates using continuous benchmark series."""
        dt_index = pd.to_datetime(dates, utc=True)
        spy_aligned = spy_series.reindex(dt_index, method="ffill")
        qqq_aligned = qqq_series.reindex(dt_index, method="ffill")

        ema50 = spy_series.ewm(span=self.ema_fast, adjust=False).mean().reindex(dt_index, method="ffill")
        ema200 = spy_series.ewm(span=self.ema_slow, adjust=False).mean().reindex(dt_index, method="ffill")
        ema200_slope = ema200.diff()

        regimes = []
        for d in dt_index:
            price = spy_aligned.loc[d]
            e50 = ema50.loc[d]
            e200 = ema200.loc[d]
            slope200 = ema200_slope.loc[d]
            qqq_price = qqq_aligned.loc[d]

            if pd.isna(e200) or pd.isna(e50):
                regime = "RISK_OFF"
            elif price < e200:
                regime = "RISK_OFF"
            elif price > e200 and e50 > e200:
                regime = "RISK_ON"
            elif price > e50:
                regime = "RECOVERY"
            else:
                regime = "RISK_OFF"

            regimes.append({
                "date": d,
                "regime": regime,
                "spy_close": float(price) if not pd.isna(price) else None,
                "spy_ema50": float(e50) if not pd.isna(e50) else None,
                "spy_ema200": float(e200) if not pd.isna(e200) else None,
                "spy_ema200_slope": float(slope200) if not pd.isna(slope200) else None,
                "qqq_close": float(qqq_price) if not pd.isna(qqq_price) else None,
            })

        return pd.DataFrame(regimes).set_index("date")

    def compute(self, bars: Dict[str, Dict[str, List]], dates: List[str]) -> pd.DataFrame:
        spy_closes = bars[self.benchmark]["closes"]
        qqq_closes = bars["QQQ"]["closes"]
        dt_index = pd.to_datetime(dates, utc=True)

        spy_series = pd.Series(spy_closes, index=dt_index)
        qqq_series = pd.Series(qqq_closes, index=dt_index)

        return self.compute_from_series(spy_series, qqq_series, dates)


# ---------------------------------------------------------------------------
# Signal engine
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    symbol: str
    score: float
    regime: str
    regime_allowed: bool
    rank: int = 0
    selected: bool = False
    entry_price: float = 0.0
    side: str = "long"
    source: str = "momentum"
    meta: Dict[str, Any] = field(default_factory=dict)


class TrendSignalEngine:
    """
    Generate daily signals for the trend engine.

    Configurable keys:
      - top_n
      - trend_ema_slow / fast
      - lookback_mom12 / mom3
      - tactical_weight_pct
    """

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.trend = TrendModel(benchmark=cfg.get("benchmark", "SPY"),
                                 ema_fast=cfg.get("trend_ema_fast", 50),
                                 ema_slow=cfg.get("trend_ema_slow", 200))
        self.regime_df: Optional[pd.DataFrame] = None

    def _score_equity(self, sym: str, bars: Dict[str, Dict[str, List]], i: int, dt) -> Optional[Dict[str, Any]]:
        sym_bars = bars[sym]
        if i >= len(sym_bars["timestamps"]):
            return None
        close = sym_bars["closes"][i]
        if close <= 0:
            return None

        past = sym_bars["closes"][:i + 1]
        lb12 = self.cfg.get("lookback_mom12", 252)
        lb3 = self.cfg.get("lookback_mom3", 63)

        mom12 = (close / past[-min(lb12, len(past))] - 1.0) if len(past) > 1 else 0.0
        mom3 = (close / past[-min(lb3, len(past))] - 1.0) if len(past) > 1 else 0.0
        vol = _realized_volatility(past, 20)
        vol_adj = mom12 / max(vol, 0.05) if vol > 0 else 0.0

        ema50 = _ema(past, self.cfg.get("trend_ema_fast", 50))
        ema200 = _ema(past, self.cfg.get("trend_ema_slow", 200))

        score = 0.5 * mom12 + 0.35 * mom3 + 0.15 * vol_adj

        return {
            "symbol": sym,
            "score": score,
            "mom12": mom12,
            "mom3": mom3,
            "vol": vol,
            "vol_adj": vol_adj,
            "close": close,
            "ema50": ema50,
            "ema200": ema200,
            "timestamp": sym_bars["timestamps"][i],
        }

    def generate(self, bars: Dict[str, Dict[str, List]], dates: List[str], i: int) -> Tuple[str, List[Signal]]:
        dt = pd.to_datetime(dates[i], utc=True)
        if self.regime_df is not None:
            regime = self.regime_df.loc[dt, "regime"]
        else:
            regime_df = self.trend.compute(bars, dates)
            regime_row = regime_df.loc[dt]
            regime = regime_row["regime"]

        universe = sorted([s for s in bars if s not in ("SPY", "QQQ")])

        scored = []
        for sym in universe:
            info = self._score_equity(sym, bars, i, dt)
            if info is None or info["score"] <= 0:
                continue
            scored.append(info)

        scored.sort(key=lambda x: -x["score"])
        top_n = self.cfg.get("top_n", 10)
        top_symbols = {x["symbol"] for x in scored[:top_n]}

        signals: List[Signal] = []
        for rank, info in enumerate(scored, 1):
            sym = info["symbol"]
            in_top = sym in top_symbols

            if regime == "RISK_ON":
                allowed = in_top
                source = "momentum"
                side = "long"
            elif regime == "RECOVERY":
                # tactical satellite: only top names, on a pullback to ~50EMA
                ema50 = info.get("ema50")
                pullback_ok = (ema50 is not None and info["close"] <= ema50 * 1.02)
                allowed = in_top and pullback_ok
                source = "tactical"
                side = "long"
            else:  # RISK_OFF
                allowed = False
                source = "none"
                side = "flat"

            sig = Signal(
                symbol=sym,
                score=info["score"],
                regime=regime,
                regime_allowed=allowed,
                rank=rank,
                selected=allowed,
                entry_price=info["close"],
                side=side,
                source=source,
                meta={"mom12": info["mom12"], "mom3": info["mom3"], "vol": info["vol"],
                      "ema50": info["ema50"], "ema200": info["ema200"]},
            )
            signals.append(sig)

        return regime, signals


# ---------------------------------------------------------------------------
# Short / hedge leg model
# ---------------------------------------------------------------------------

class HedgeLeg:
    """
    Simple inverse-QQQ proxy using SQQQ close data when available,
    otherwise model a synthetic short of QQQ.
    """

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def get_hedge_instrument(self, bars: Dict[str, Dict[str, List]]) -> str:
        if "SQQQ" in bars:
            return "SQQQ"
        return "QQQ"

    def expected_return(self, bars: Dict[str, Dict[str, List]], i: int, prev_i: int) -> float:
        instr = self.get_hedge_instrument(bars)
        if instr not in bars:
            return 0.0
        closes = bars[instr]["closes"]
        if i >= len(closes) or prev_i < 0:
            return 0.0
        if instr == "SQQQ":
            return closes[i] / closes[prev_i] - 1.0
        else:
            qqq_ret = closes[i] / closes[prev_i] - 1.0
            borrow = self.cfg.get("borrow_cost_annual", 0.02) / 252
            return -qqq_ret - borrow

    def value_change(self, notional: float, bars: Dict[str, Dict[str, List]], i: int, prev_i: int) -> float:
        return notional * self.expected_return(bars, i, prev_i)


# ---------------------------------------------------------------------------
# Portfolio sizing helper
# ---------------------------------------------------------------------------

def size_target_positions(signals: List[Signal], mv: float, cash: float, cfg: Dict[str, Any],
                          positions: Dict[str, Any], sector_exposure: Dict[str, float]) -> List[Dict[str, Any]]:
    """
    Given selected long signals, return target orders respecting max position,
    max gross/net exposure, and sector concentration.
    """
    base = cfg.get("base_size_pct", 0.05)
    max_pos = cfg.get("max_position_pct", 0.15)
    max_gross = cfg.get("max_gross_exposure_pct", 1.50)
    max_net_long = cfg.get("max_net_long_pct", 1.00)
    max_sector = cfg.get("max_sector_pct", 0.25)

    current_long = sum(p["mv"] for p in positions.values() if p["side"] == "long")
    current_short = sum(p["mv"] for p in positions.values() if p["side"] == "short")
    current_gross = current_long + current_short
    current_net = current_long - current_short

    long_budget = min(mv * max_pos, mv * max_gross - current_gross, mv * max_net_long - current_net)
    long_budget = min(long_budget, cash)

    orders = []
    for sig in signals:
        if not sig.selected or sig.side != "long":
            continue
        sector = SYMBOL_TO_SECTOR.get(sig.symbol, "Other")
        sec_used = sector_exposure.get(sector, 0.0)
        sec_room = max(0.0, mv * max_sector - sec_used)
        if sec_room <= 0:
            continue

        target = min(mv * base, long_budget, sec_room)
        if target < 100:
            continue

        shares = target / sig.entry_price
        cost = shares * sig.entry_price * (1 + COST_PER_SIDE)
        if cost > cash or cost > long_budget:
            shares = min(cash, long_budget) / (sig.entry_price * (1 + COST_PER_SIDE))
            cost = shares * sig.entry_price * (1 + COST_PER_SIDE)
        if shares <= 0 or cost <= 0:
            continue

        orders.append({
            "symbol": sig.symbol,
            "side": "long",
            "shares": float(shares),
            "entry_price": float(sig.entry_price),
            "cost": float(cost),
            "mv": float(shares * sig.entry_price),
            "sector": sector,
            "source": sig.source,
        })
        long_budget -= cost
        cash -= cost
        current_long += shares * sig.entry_price
        current_gross += shares * sig.entry_price
        current_net += shares * sig.entry_price
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + shares * sig.entry_price

    return orders


if __name__ == "__main__":
    cfg = {
        "benchmark": "SPY",
        "trend_ema_fast": 50,
        "trend_ema_slow": 200,
        "top_n": 10,
        "base_size_pct": 0.05,
        "max_position_pct": 0.15,
        "max_gross_exposure_pct": 1.50,
        "max_net_long_pct": 1.00,
        "max_net_short_pct": 0.50,
        "max_sector_pct": 0.25,
        "drawdown_halt_pct": 0.15,
        "short_alloc_pct": 0.25,
        "tactical_weight_pct": 0.20,
        "lookback_mom12": 252,
        "lookback_mom3": 63,
        "borrow_cost_annual": 0.02,
    }
    engine = TrendSignalEngine(cfg)
    bars = load_bars(DATA_DIR / "daily_bars_2yr.json")
    dates = bars["QQQ"]["timestamps"]
    for i in [200, 300, 400]:
        regime, signals = engine.generate(bars, dates, i)
        selected = [s for s in signals if s.selected][:5]
        print(f"{dates[i]} regime={regime} selected={[(s.symbol, round(s.score, 3), s.source) for s in selected]}")
