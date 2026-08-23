#!/usr/bin/env python3
"""
STONK.AI v3 HYBRID Engine — Regime-Aware Momentum + Pullback Backtest
=====================================================================

Combines a breakout/momentum module with the existing trend-pullback module,
with regime-aware switching.  Designed for autonomous iteration over the
lever space defined in the subagent task.

Data / execution / costs are identical to proper_backtest_deployed.py:
- daily_bars_2yr.json + features_2yr.json + Yahoo Finance regime ETFs
- walk-forward, t signal -> t+1 close execution
- 0.1% cost per side

Configurable levers
-------------------
- Momentum trend filter: EMA20/EMA50, EMA20/EMA200 (computed on the fly),
  or price vs 52-week high.
- Momentum entry timing: pullback to 5-day EMA, 10-day low, 20-day low,
  or breakout (no pullback).
- Momentum base / STRONG_NOW position sizing.
- Momentum profit-taking: full trailing only, 1/4 at +1 ATR, or 1/3 at
  +0.5/+1 ATR.
- Regime usage: momentum only in RISK_ON, or also in CAUTION.
- Momentum RSI band.
- Minimum 20-day return threshold for momentum candidates.
- Max momentum positions.

The pullback module keeps the existing v3 signal scoring and the original
risk constraints can be loosened/tightened via config.

Outputs per variant
-------------------
- /opt/stonk-ai/reports/v3_hybrid_vNN_backtest_YYYYMMDD.json
- /opt/stonk-ai/reports/v3_hybrid_vNN_equity_YYYYMMDD.csv
- /opt/stonk-ai/reports/v3_hybrid_vNN_equity_YYYYMMDD.png
- /opt/stonk-ai/reports/hybrid_iteration_log.csv (append)

Author: OpenClaw subagent
Date: 2026-08-23
"""

from __future__ import annotations

import csv
import inspect
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path("/opt/stonk-ai/v3_rebuild/data")
REPORT_DIR = Path("/opt/stonk-ai/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

BARS_FILE = DATA_DIR / "daily_bars_2yr.json"
FEATURES_FILE = DATA_DIR / "features_2yr.json"
REGIME_CACHE = DATA_DIR / "regime_etfs_yf.json"

START_DATE = "2024-08-14"
END_DATE = "2026-08-21"

START_VALUE = 100_000.0
COST_PER_SIDE = 0.001

QQQ_TOTAL_RETURN = 0.5555652610661019  # known from prior runs

# ---------------------------------------------------------------------------
# Default config (will be overridden per variant)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    # Momentum module
    "mom_trend_filter": "ema20_ema50",       # ema20_ema50 | ema20_ema200 | price_52w_high
    "mom_entry_timing": "pullback_5ema",     # breakout | pullback_5ema | pullback_10d_low | pullback_20d_low
    "mom_base_pct": 0.03,
    "mom_strong_cap_pct": 0.12,
    "mom_profit_take": "scaleout_1_3",       # trailing_only | scaleout_1_4 | scaleout_1_3
    "mom_regimes": ["RISK_ON"],                # list including RISK_ON and optionally CAUTION
    "mom_rsi_low": 55,
    "mom_rsi_high": 80,
    "mom_min_ret20d": 0.05,
    "mom_max_positions": 15,
    "mom_use_rank": True,

    # Pullback module (existing v3)
    "pb_threshold": 0.5,
    "pb_max_positions": 15,
    "pb_base_pct": 0.03,
    "pb_strong_cap_pct": 0.12,
    "pb_regimes": ["RISK_ON"],                 # pullback entries in these regimes
    "pb_rsi_max": 75,
    "pb_dist_ema200_min": -0.15,
    "pb_use_rank": True,

    # Shared risk
    "cash_floor_pct": 0.05,
    "entry_buffer_pct": 0.06,
    "sector_cap_pct": 0.25,
    "drawdown_halt_pct": 0.10,

    # Stops / targets
    "hard_stop_atr_mult": 1.5,
    "hard_stop_min_pct": 0.05,
    "hard_stop_max_pct": 0.11,
    "trailing_stop_atr_mult": 2.0,
    "trailing_stop_min_pct": 0.05,
    "trailing_stop_max_pct": 0.14,
    "scaleout_t1_atr": 0.5,
    "scaleout_t2_atr": 1.0,
    "scaleout_frac": 1 / 3.0,
    "full_exit_profit_pct": 0.30,
}

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


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(-period, 0)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(-period, 0)]
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _atr_pct(closes: List[float], highs: List[float], lows: List[float], idx: int, period: int = 14) -> float:
    if idx < period:
        return 0.05
    trs = []
    for j in range(idx - period + 1, idx + 1):
        high = highs[j]
        low = lows[j]
        prev_close = closes[j - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return (sum(trs) / len(trs)) / closes[idx]


def load_bars() -> Dict[str, Dict[str, List]]:
    with open(BARS_FILE) as f:
        return json.load(f)


def load_features() -> Dict[Tuple[str, str], Dict]:
    with open(FEATURES_FILE) as f:
        rows = json.load(f)
    return {(r["symbol"], r["date"]): r for r in rows}


def fetch_or_load_regime_etfs() -> Dict[str, pd.Series]:
    if REGIME_CACHE.exists():
        with open(REGIME_CACHE) as f:
            data = json.load(f)
        return {sym: pd.Series(v["prices"], index=pd.to_datetime(v["dates"], utc=True)) for sym, v in data.items()}

    symbols = ["VIXY", "LQD", "HYG", "TLT", "SHY"]
    series: Dict[str, pd.Series] = {}
    for sym in symbols:
        print(f"Fetching {sym} from Yahoo Finance...")
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="2y", auto_adjust=True)
        hist.index = hist.index.tz_convert("UTC")
        series[sym] = hist["Close"]

    cache = {}
    for sym, s in series.items():
        cache[sym] = {
            "dates": [d.isoformat() for d in s.index],
            "prices": s.astype(float).tolist(),
        }
    with open(REGIME_CACHE, "w") as f:
        json.dump(cache, f)
    return series


# ---------------------------------------------------------------------------
# Regime replication (identical to deployed harness)
# ---------------------------------------------------------------------------

CREDIT_SPREAD_RISK_OFF = 1.45
CREDIT_SPREAD_CRISIS = 1.60
VIXY_CHANGE_RISK_OFF = 5.0
VIXY_CHANGE_CRISIS = 15.0
SPY_EMA_PERIOD = 50


def build_regime_series(bars: Dict[str, Dict[str, List]], etfs: Dict[str, pd.Series]) -> pd.DataFrame:
    qqq_dates = [pd.to_datetime(d, utc=True) for d in bars["QQQ"]["timestamps"]]
    spy_closes = pd.Series(bars["SPY"]["closes"], index=qqq_dates)
    qqq_closes = pd.Series(bars["QQQ"]["closes"], index=qqq_dates)

    def align_to_dates(s: pd.Series) -> pd.Series:
        df = pd.DataFrame({"price": s})
        df = df.reindex(qqq_dates, method="ffill")
        return df["price"]

    vixy = align_to_dates(etfs["VIXY"])
    lqd = align_to_dates(etfs["LQD"])
    hyg = align_to_dates(etfs["HYG"])
    tlt = align_to_dates(etfs["TLT"])
    shy = align_to_dates(etfs["SHY"])

    spy_ema50 = spy_closes.ewm(span=SPY_EMA_PERIOD, adjust=False).mean()
    spy_above_ema = spy_closes >= spy_ema50

    vixy_change = vixy.pct_change() * 100.0
    credit_ratio = lqd / hyg
    credit_baseline = credit_ratio.shift(20)
    credit_widening = credit_ratio > credit_baseline
    yield_ratio = shy / tlt
    yield_baseline = yield_ratio.shift(20)
    yield_steepening = yield_ratio > yield_baseline
    qqq_5d = qqq_closes.pct_change(5)

    regime = []
    for d in qqq_dates:
        triggers = []
        banner = "RISK_ON"
        cs = credit_ratio.loc[d]
        vix = vixy_change.loc[d]
        spy_above = spy_above_ema.loc[d]
        credit_wide = credit_widening.loc[d]
        yield_steep = yield_steepening.loc[d]

        if not pd.isna(vix) and vix > VIXY_CHANGE_CRISIS:
            banner = "CRISIS"
            triggers.append(f"VIXY change {vix:.1f}% > {VIXY_CHANGE_CRISIS}%")
        if not pd.isna(cs) and cs > CREDIT_SPREAD_CRISIS:
            banner = "CRISIS"
            triggers.append(f"Credit spread {cs:.2f} > {CREDIT_SPREAD_CRISIS}")
        if not pd.isna(spy_above) and not spy_above and credit_wide:
            banner = "CRISIS"
            triggers.append("SPY below EMA50 AND credit spreads widening")

        if banner != "CRISIS":
            if not pd.isna(cs) and cs > CREDIT_SPREAD_RISK_OFF:
                banner = "RISK_OFF"
                triggers.append(f"Credit spread {cs:.2f} > {CREDIT_SPREAD_RISK_OFF}")
            if not pd.isna(spy_above) and not spy_above:
                banner = "RISK_OFF"
                triggers.append("SPY below 50-day EMA")
            if not pd.isna(vix) and vix > VIXY_CHANGE_RISK_OFF:
                banner = "RISK_OFF"
                triggers.append(f"VIXY change {vix:.1f}% > {VIXY_CHANGE_RISK_OFF}%")
            if yield_steep and credit_wide:
                banner = "RISK_OFF"
                triggers.append("Yield curve steepening AND credit spreads widening")

        regime.append({
            "date": d,
            "regime": banner,
            "spy_above_ema50": bool(spy_above) if not pd.isna(spy_above) else None,
            "credit_spread": float(cs) if not pd.isna(cs) else None,
            "vixy_change": float(vix) if not pd.isna(vix) else None,
            "yield_curve_signal": "steepening" if yield_steep else "normal",
            "triggers": triggers,
            "qqq_5d_return": float(qqq_5d.loc[d]) if not pd.isna(qqq_5d.loc[d]) else None,
        })

    return pd.DataFrame(regime).set_index("date")


# ---------------------------------------------------------------------------
# Pullback signal scoring (mirrors v3_signal_engine)
# ---------------------------------------------------------------------------

TREND_PULLBACK_WEIGHTS = {
    "dist_ema200": 1.0,
    "dist_ema50": 1.0,
    "dist_ema20": 0.5,
    "ret_5d": -3.0,
    "rsi14": -0.1,
    "vs_qqq_5d": -1.0,
    "vol_ratio": 0.3,
}


def score_pullback(r: Dict, cfg: Dict) -> Tuple[float, bool]:
    dist_ema200 = r["dist_ema200"]
    dist_ema50 = r["dist_ema50"]
    dist_ema20 = r["dist_ema20"]
    ret_5d = r["ret_5d"]
    rsi14 = r["rsi14"]
    vs_qqq_5d = r["vs_qqq_5d"]
    vol_ratio = r["vol_ratio"]

    hard_blocked = False
    if rsi14 > cfg["pb_rsi_max"]:
        hard_blocked = True
    if dist_ema200 < cfg["pb_dist_ema200_min"]:
        hard_blocked = True

    score = 0.0
    score += max(0.0, TREND_PULLBACK_WEIGHTS["dist_ema200"] * dist_ema200)
    score += max(0.0, TREND_PULLBACK_WEIGHTS["dist_ema50"] * dist_ema50)
    score += max(0.0, TREND_PULLBACK_WEIGHTS["dist_ema20"] * dist_ema20)
    score += max(0.0, -TREND_PULLBACK_WEIGHTS["ret_5d"] * ret_5d)
    if rsi14 < 45:
        score += -TREND_PULLBACK_WEIGHTS["rsi14"] * (45 - rsi14)
    score += max(0.0, -TREND_PULLBACK_WEIGHTS["vs_qqq_5d"] * vs_qqq_5d)
    score += min(TREND_PULLBACK_WEIGHTS["vol_ratio"] * max(0.0, vol_ratio - 1.0), 1.0)
    return score, hard_blocked


# ---------------------------------------------------------------------------
# Momentum signal scoring
# ---------------------------------------------------------------------------

def score_momentum(sym: str, feat: Dict, bars: Dict[str, Dict], i: int, cfg: Dict) -> Tuple[float, Optional[str]]:
    """
    Return (score, tier) for a momentum candidate.  score <= 0 means not selected.
    tier can be STRONG_NOW / NOW / WATCH or None.
    """
    sym_bars = bars[sym]
    if i >= len(sym_bars["timestamps"]):
        return 0.0, None
    close = sym_bars["closes"][i]
    if close <= 0:
        return 0.0, None

    # 20-day return filter
    ret20 = feat.get("ret_20d", 0.0)
    if ret20 < cfg["mom_min_ret20d"]:
        return 0.0, None

    rsi14 = feat["rsi14"]
    if rsi14 < cfg["mom_rsi_low"] or rsi14 > cfg["mom_rsi_high"]:
        return 0.0, None

    past_closes = sym_bars["closes"][:i + 1]
    ema20 = _ema(past_closes, 20)
    ema50 = _ema(past_closes, 50)
    ema200 = _ema(past_closes, 200)

    trend_ok = False
    if cfg["mom_trend_filter"] == "ema20_ema50":
        trend_ok = (ema20 is not None and ema50 is not None and ema20 >= ema50)
    elif cfg["mom_trend_filter"] == "ema20_ema200":
        trend_ok = (ema20 is not None and ema200 is not None and ema20 >= ema200)
    elif cfg["mom_trend_filter"] == "price_52w_high":
        if len(past_closes) >= 252:
            high52 = max(past_closes[-252:])
        else:
            high52 = max(past_closes)
        trend_ok = close >= high52 * 0.90

    if not trend_ok:
        return 0.0, None

    # Entry timing: require pullback to a reference level
    timing_ok = False
    entry_ref = close
    timing = cfg["mom_entry_timing"]
    if timing == "breakout":
        timing_ok = True
    elif timing == "pullback_5ema":
        if ema20 is not None:
            entry_ref = ema20
            timing_ok = close <= ema20 * 1.02  # within 2% above 5-day EMA proxy (20-day EMA used)
    elif timing == "pullback_10d_low":
        if len(past_closes) >= 10:
            low10 = min(sym_bars["lows"][i - 9:i + 1])
            entry_ref = low10
            timing_ok = close <= low10 * 1.02
    elif timing == "pullback_20d_low":
        if len(past_closes) >= 20:
            low20 = min(sym_bars["lows"][i - 19:i + 1])
            entry_ref = low20
            timing_ok = close <= low20 * 1.02

    if not timing_ok:
        return 0.0, None

    # Score combines 20d return, distance from 52w high, relative strength
    score = ret20
    if cfg["mom_trend_filter"] == "price_52w_high":
        if len(past_closes) >= 252:
            high52 = max(past_closes[-252:])
        else:
            high52 = max(past_closes)
        if high52 > 0:
            score += (close / high52 - 1.0) * 2.0
    score += feat.get("vs_qqq_5d", 0.0)
    score += max(0.0, feat.get("vol_ratio", 1.0) - 1.0) * 0.1

    tier = "NOW"
    if ret20 >= 0.15 and rsi14 >= 60:
        tier = "STRONG_NOW"
    elif ret20 >= 0.10:
        tier = "NOW"
    else:
        tier = "WATCH"

    return max(score, 0.01), tier


# ---------------------------------------------------------------------------
# Backtest state
# ---------------------------------------------------------------------------

@dataclass
class Position:
    symbol: str
    shares: float
    entry_price: float
    entry_cost: float
    entry_date: str
    atr_pct_at_entry: float
    tier: str
    sector: str
    module: str  # "momentum" or "pullback"
    remaining_fraction: float = 1.0
    highest_close: float = 0.0
    scaleouts_hit: List[str] = field(default_factory=list)


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
symbol_to_sector = {}
for sector, syms in SECTOR_PEERS.items():
    for s in syms:
        symbol_to_sector[s] = sector


def _trading_days_between(dates: List[str], start: str, end: str) -> int:
    try:
        return max(0, dates.index(end) - dates.index(start))
    except ValueError:
        return 0


def _cap_for_tier(tier: str, cfg: Dict, module: str) -> float:
    if module == "momentum":
        if tier == "STRONG_NOW":
            return cfg["mom_strong_cap_pct"]
        return cfg["mom_base_pct"]
    else:
        if tier == "STRONG_NOW":
            return cfg["pb_strong_cap_pct"]
        return cfg["pb_base_pct"]


def run_backtest(cfg: Dict, variant: str = "v01") -> Dict:
    bars = load_bars()
    features = load_features()
    etfs = fetch_or_load_regime_etfs()
    regime_df = build_regime_series(bars, etfs)

    dates = bars["QQQ"]["timestamps"]
    qqq_closes = bars["QQQ"]["closes"]

    universe = sorted([s for s in bars if s not in ("SPY", "QQQ")])

    cash = START_VALUE
    equity_peak = START_VALUE
    positions: List[Position] = []
    trades: List[Dict] = []
    equity_curve = []
    daily_log = []
    halted = False
    drawdown_halt_date: Optional[str] = None

    for i, d in enumerate(dates):
        dt = pd.to_datetime(d, utc=True)
        qqq_price = qqq_closes[i]

        # Mark-to-market
        def mark_portfolio(positions_list: List[Position], cash_value: float, day_idx: int, day_date: str) -> float:
            mv = cash_value
            for p in positions_list:
                sym_dates = bars[p.symbol]["timestamps"]
                if day_idx < len(sym_dates) and sym_dates[day_idx] == day_date:
                    mv += p.shares * p.remaining_fraction * bars[p.symbol]["closes"][day_idx]
                else:
                    mv += p.shares * p.remaining_fraction * p.entry_price
            return mv

        mv = mark_portfolio(positions, cash, i, d)

        if mv > equity_peak:
            equity_peak = mv
        dd = (equity_peak - mv) / equity_peak

        regime_row = regime_df.loc[dt]
        regime = regime_row["regime"]
        qqq_5d = regime_row["qqq_5d_return"]
        halted_today = False

        if dd >= cfg["drawdown_halt_pct"]:
            if not halted:
                halted = True
                drawdown_halt_date = d
                halted_today = True
        else:
            halted = False

        # ----- Exit logic -----
        exits_today: List[Tuple[int, str, float, float]] = []
        for pi, p in enumerate(positions):
            sym_data = bars[p.symbol]
            if i >= len(sym_data["timestamps"]) or sym_data["timestamps"][i] != d:
                continue
            close = sym_data["closes"][i]
            p.highest_close = max(p.highest_close, close)
            atr_pct = p.atr_pct_at_entry
            entry_price = p.entry_price
            profit_pct = (close - entry_price) / entry_price

            profit_take = cfg["mom_profit_take"] if p.module == "momentum" else "scaleout_1_3"
            if profit_take == "scaleout_1_3":
                t1_frac = cfg["scaleout_frac"]
                t2_frac = cfg["scaleout_frac"]
                if "T1" not in p.scaleouts_hit and profit_pct >= cfg["scaleout_t1_atr"] * atr_pct:
                    exits_today.append((pi, "scaleout_t1", t1_frac, close))
                if "T2" not in p.scaleouts_hit and profit_pct >= cfg["scaleout_t2_atr"] * atr_pct:
                    exits_today.append((pi, "scaleout_t2", t2_frac, close))
            elif profit_take == "scaleout_1_4":
                if "T1" not in p.scaleouts_hit and profit_pct >= 1.0 * atr_pct:
                    exits_today.append((pi, "scaleout_t1", 0.25, close))
            # trailing_only: no scaleouts

            if profit_pct >= cfg["full_exit_profit_pct"]:
                exits_today.append((pi, "full_exit", p.remaining_fraction, close))
                continue

            hard_stop_pct = -max(min(cfg["hard_stop_atr_mult"] * atr_pct, cfg["hard_stop_max_pct"]), cfg["hard_stop_min_pct"])
            if (close - entry_price) / entry_price <= hard_stop_pct:
                exits_today.append((pi, "hard_stop", p.remaining_fraction, close))
                continue

            trail_stop_pct = -max(min(cfg["trailing_stop_atr_mult"] * atr_pct, cfg["trailing_stop_max_pct"]), cfg["trailing_stop_min_pct"])
            if (close - p.highest_close) / p.highest_close <= trail_stop_pct and close < p.highest_close:
                exits_today.append((pi, "trailing_stop", p.remaining_fraction, close))

        for pi, reason, frac, exit_price in sorted(exits_today, key=lambda x: -x[0]):
            p = positions[pi]
            if frac > p.remaining_fraction:
                frac = p.remaining_fraction
            gross = p.shares * frac * exit_price
            proceeds = gross * (1 - COST_PER_SIDE)
            cash += proceeds
            cost_basis = p.entry_cost * frac
            pnl = proceeds - cost_basis
            pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0
            trades.append({
                "symbol": p.symbol,
                "entry_date": p.entry_date,
                "exit_date": d,
                "reason": reason,
                "entry_price": p.entry_price,
                "exit_price": exit_price,
                "shares": p.shares * frac,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "hold_days": _trading_days_between(dates, p.entry_date, d),
                "module": p.module,
            })
            if reason.startswith("scaleout"):
                p.scaleouts_hit.append(reason.replace("scaleout_", "").upper())
                p.remaining_fraction -= frac
            else:
                p.remaining_fraction = 0.0

        positions = [p for p in positions if p.remaining_fraction > 1e-9]

        # ----- Entry logic -----
        if halted or halted_today:
            pass
        else:
            cash_floor = mv * cfg["cash_floor_pct"]
            entry_buffer = mv * cfg["entry_buffer_pct"]
            cash_for_entries = max(0.0, cash - cash_floor - entry_buffer)

            sector_exposure: Dict[str, float] = defaultdict(float)
            for p in positions:
                sec = symbol_to_sector.get(p.symbol, "Other")
                sym_ts = bars[p.symbol]["timestamps"]
                price = bars[p.symbol]["closes"][i] if i < len(sym_ts) and sym_ts[i] == d else p.entry_price
                sector_exposure[sec] += p.shares * p.remaining_fraction * price / mv

            existing_symbols = {p.symbol for p in positions}

            # Momentum entries
            if regime in cfg["mom_regimes"] and qqq_5d is not None and qqq_5d > -0.08:
                mom_slots = cfg["mom_max_positions"] - len([p for p in positions if p.module == "momentum"])
                mom_candidates = []
                for sym in universe:
                    if sym in existing_symbols:
                        continue
                    feat = features.get((sym, d))
                    if feat is None:
                        continue
                    score, tier = score_momentum(sym, feat, bars, i, cfg)
                    if score <= 0:
                        continue
                    mom_candidates.append((score, sym, feat, tier))

                if cfg.get("mom_use_rank", True):
                    mom_candidates.sort(key=lambda x: -x[0])

                selected = 0
                for score, sym, feat, tier in mom_candidates:
                    if selected >= mom_slots or cash_for_entries <= 0:
                        break
                    sec = symbol_to_sector.get(sym, "Other")
                    if sector_exposure[sec] >= cfg["sector_cap_pct"]:
                        continue

                    cap = _cap_for_tier(tier, cfg, "momentum")
                    target_value = min(mv * cfg["mom_base_pct"], mv * cap, cash_for_entries)
                    if target_value < 100:
                        continue

                    entry_price = feat["price"]
                    if entry_price <= 0:
                        continue
                    shares = target_value / entry_price
                    entry_cost = shares * entry_price * (1 + COST_PER_SIDE)
                    if entry_cost > cash_for_entries:
                        shares = cash_for_entries / (entry_price * (1 + COST_PER_SIDE))
                        entry_cost = shares * entry_price * (1 + COST_PER_SIDE)
                    if entry_cost > cash_for_entries or shares <= 0:
                        continue

                    sym_bars = bars[sym]
                    atr_pct = _atr_pct(sym_bars["closes"], sym_bars["highs"], sym_bars["lows"], i)

                    positions.append(Position(
                        symbol=sym,
                        shares=float(shares),
                        entry_price=float(entry_price),
                        entry_cost=float(entry_cost),
                        entry_date=d,
                        atr_pct_at_entry=float(atr_pct),
                        tier=tier,
                        sector=sec,
                        module="momentum",
                        highest_close=float(entry_price),
                    ))
                    cash -= entry_cost
                    cash_for_entries -= entry_cost
                    sector_exposure[sec] += shares * entry_price / mv
                    selected += 1

            # Pullback entries
            if regime in cfg["pb_regimes"] and qqq_5d is not None and qqq_5d > -0.08:
                pb_slots = cfg["pb_max_positions"] - len([p for p in positions if p.module == "pullback"])
                pb_candidates = []
                for sym in universe:
                    if sym in existing_symbols:
                        continue
                    feat = features.get((sym, d))
                    if feat is None:
                        continue
                    score, blocked = score_pullback(feat, cfg)
                    if blocked or math.isnan(score) or score < cfg["pb_threshold"]:
                        continue
                    pb_candidates.append((score, sym, feat))

                pb_candidates.sort(key=lambda x: -x[0])
                if not pb_candidates:
                    pass
                else:
                    n = len(pb_candidates)
                    ranked = []
                    for rank, (score, sym, feat) in enumerate(pb_candidates, 1):
                        if rank <= max(1, n // 3):
                            tier = "STRONG_NOW"
                        elif rank <= max(1, 2 * n // 3):
                            tier = "NOW"
                        else:
                            tier = "WATCH"
                        ranked.append((score, sym, feat, tier))

                    selected = 0
                    for score, sym, feat, tier in ranked:
                        if selected >= pb_slots or cash_for_entries <= 0:
                            break
                        if sym in existing_symbols:
                            continue
                        sec = symbol_to_sector.get(sym, "Other")
                        if sector_exposure[sec] >= cfg["sector_cap_pct"]:
                            continue

                        cap = _cap_for_tier(tier, cfg, "pullback")
                        target_value = min(mv * cfg["pb_base_pct"], mv * cap, cash_for_entries)
                        if target_value < 100:
                            continue

                        entry_price = feat["price"]
                        if entry_price <= 0:
                            continue
                        shares = target_value / entry_price
                        entry_cost = shares * entry_price * (1 + COST_PER_SIDE)
                        if entry_cost > cash_for_entries:
                            shares = cash_for_entries / (entry_price * (1 + COST_PER_SIDE))
                            entry_cost = shares * entry_price * (1 + COST_PER_SIDE)
                        if entry_cost > cash_for_entries or shares <= 0:
                            continue

                        sym_bars = bars[sym]
                        atr_pct = _atr_pct(sym_bars["closes"], sym_bars["highs"], sym_bars["lows"], i)

                        positions.append(Position(
                            symbol=sym,
                            shares=float(shares),
                            entry_price=float(entry_price),
                            entry_cost=float(entry_cost),
                            entry_date=d,
                            atr_pct_at_entry=float(atr_pct),
                            tier=tier,
                            sector=sec,
                            module="pullback",
                            highest_close=float(entry_price),
                        ))
                        cash -= entry_cost
                        cash_for_entries -= entry_cost
                        sector_exposure[sec] += shares * entry_price / mv
                        selected += 1

        # End-of-day mark-to-market
        mv = mark_portfolio(positions, cash, i, d)

        equity_curve.append({
            "date": d,
            "equity": float(mv),
            "cash": float(cash),
            "regime": regime,
            "n_positions": len(positions),
            "drawdown": float(dd),
            "qqq_close": float(qqq_price),
        })
        daily_log.append({
            "date": d,
            "equity": float(mv),
            "cash": float(cash),
            "regime": regime,
            "qqq_close": float(qqq_price),
            "n_positions": len(positions),
            "drawdown": float(dd),
            "halted": halted or halted_today,
        })

    # Final liquidation
    final_i = len(dates) - 1
    final_date = dates[-1]
    final_qqq = qqq_closes[-1]
    for p in positions:
        sym_data = bars[p.symbol]
        if final_i < len(sym_data["timestamps"]) and sym_data["timestamps"][final_i] == final_date:
            exit_price = sym_data["closes"][final_i]
        else:
            exit_price = p.entry_price
        gross = p.shares * p.remaining_fraction * exit_price
        proceeds = gross * (1 - COST_PER_SIDE)
        cash += proceeds
        cost_basis = p.entry_cost * p.remaining_fraction
        pnl = proceeds - cost_basis
        pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0
        trades.append({
            "symbol": p.symbol,
            "entry_date": p.entry_date,
            "exit_date": final_date,
            "reason": "final_liquidation",
            "entry_price": p.entry_price,
            "exit_price": exit_price,
            "shares": p.shares * p.remaining_fraction,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "hold_days": _trading_days_between(dates, p.entry_date, final_date),
            "module": p.module,
        })

    final_equity = cash

    # QQQ benchmark
    qqq_start = qqq_closes[0]
    qqq_final = qqq_closes[-1]
    qqq_return = qqq_final / qqq_start - 1.0
    qqq_shares = START_VALUE / qqq_start * (1 - COST_PER_SIDE)
    qqq_final_value = qqq_shares * qqq_final * (1 - COST_PER_SIDE)

    eq_vals = np.array([e["equity"] for e in equity_curve])
    rets = np.diff(eq_vals) / eq_vals[:-1]
    ann_factor = 252
    total_ret = final_equity / START_VALUE - 1.0
    ann_ret = (1 + total_ret) ** (ann_factor / len(eq_vals)) - 1.0 if len(eq_vals) > 1 else 0.0
    vol = float(np.std(rets) * math.sqrt(ann_factor))
    sharpe = float(ann_ret / vol) if vol > 0 else 0.0

    running_peak = np.maximum.accumulate(eq_vals)
    max_dd = float(np.max((running_peak - eq_vals) / running_peak))

    closed_trades = [t for t in trades if t["reason"] != "final_liquidation"]
    winners = [t for t in closed_trades if t["pnl"] > 0]
    losers = [t for t in closed_trades if t["pnl"] <= 0]
    win_rate = len(winners) / len(closed_trades) if closed_trades else 0.0
    avg_win = float(np.mean([t["pnl_pct"] for t in winners])) if winners else 0.0
    avg_loss = float(np.mean([t["pnl_pct"] for t in losers])) if losers else 0.0
    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_hold = float(np.mean([t["hold_days"] for t in closed_trades])) if closed_trades else 0.0

    qqq_rets = np.diff(qqq_closes) / qqq_closes[:-1]
    qqq_ann_ret = (1 + qqq_return) ** (ann_factor / len(qqq_closes)) - 1.0
    qqq_vol = float(np.std(qqq_rets) * math.sqrt(ann_factor))
    qqq_sharpe = qqq_ann_ret / qqq_vol if qqq_vol > 0 else 0.0

    # Average invested %
    invested = []
    for row in equity_curve:
        e = row["equity"]
        c = row["cash"]
        if e > 0:
            invested.append((e - c) / e)
    avg_invested = float(np.mean(invested)) if invested else 0.0

    mom_trades = [t for t in closed_trades if t.get("module") == "momentum"]
    pb_trades = [t for t in closed_trades if t.get("module") == "pullback"]

    result = {
        "variant": variant,
        "config": cfg,
        "total_return": float(total_ret),
        "annualized_return": float(ann_ret),
        "volatility": vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_winner": avg_win,
        "avg_loser": avg_loss,
        "number_of_trades": len(closed_trades),
        "momentum_trades": len(mom_trades),
        "pullback_trades": len(pb_trades),
        "avg_holding_days": avg_hold,
        "qqq_total_return": float(qqq_return),
        "qqq_sharpe_ratio": qqq_sharpe,
        "final_equity": float(final_equity),
        "final_qqq_equity": float(qqq_final_value),
        "start_date": dates[0],
        "end_date": dates[-1],
        "start_value": START_VALUE,
        "avg_invested_pct": avg_invested,
        "regime_counts": regime_df["regime"].value_counts().to_dict(),
        "drawdown_halt_date": drawdown_halt_date,
        "methodology": {
            "signal_engine": "hybrid: momentum breakout + v3 trend_pullback_score",
            "execution": "daily close, t signal -> t+1 execution, 0.1% cost per side",
            "regime": "replicated from regime_detector.py",
        },
    }

    date_tag = datetime.now().strftime("%Y%m%d")
    report_path = REPORT_DIR / f"v3_hybrid_{variant}_backtest_{date_tag}.json"
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2)

    equity_csv_path = REPORT_DIR / f"v3_hybrid_{variant}_equity_{date_tag}.csv"
    pd.DataFrame(equity_curve).to_csv(equity_csv_path, index=False)

    chart_path = REPORT_DIR / f"v3_hybrid_{variant}_equity_{date_tag}.png"
    make_chart(equity_curve, qqq_final_value, str(chart_path), variant)

    return {
        "result": result,
        "equity_curve": equity_curve,
        "trades": trades,
        "report_path": str(report_path),
        "equity_csv_path": str(equity_csv_path),
        "chart_path": str(chart_path),
        "qqq_final_value": qqq_final_value,
    }


def make_chart(equity_curve: List[Dict], qqq_final_value: float, output_path: str, variant: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])

    start_value = df["equity"].iloc[0]
    df["strategy"] = df["equity"] / start_value
    qqq_start = df["qqq_close"].iloc[0]
    df["qqq"] = df["qqq_close"] / qqq_start

    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax1.plot(df["date"], df["strategy"], label="Strategy", linewidth=2)
    ax1.plot(df["date"], df["qqq"], label="QQQ buy-and-hold", linewidth=2, linestyle="--")
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Normalized Equity")
    ax1.set_title(f"STONK.AI v3 HYBRID {variant} vs QQQ Buy-and-Hold")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)

    regime_colors = {"RISK_ON": "#d4edda", "RISK_OFF": "#fff3cd", "CRISIS": "#f8d7da"}
    current_regime = df["regime"].iloc[0]
    start_idx = 0
    for i in range(1, len(df)):
        if df["regime"].iloc[i] != current_regime:
            ax1.axvspan(df["date"].iloc[start_idx], df["date"].iloc[i], color=regime_colors.get(current_regime, "white"), alpha=0.2)
            current_regime = df["regime"].iloc[i]
            start_idx = i
    ax1.axvspan(df["date"].iloc[start_idx], df["date"].iloc[-1], color=regime_colors.get(current_regime, "white"), alpha=0.2)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def log_to_csv(result: Dict, notes: str = ""):
    csv_path = REPORT_DIR / "hybrid_iteration_log.csv"
    fieldnames = ["variant", "return", "sharpe", "max_dd", "trades", "vs_qqq", "notes"]
    row = {
        "variant": result["variant"],
        "return": f"{result['total_return']:.4%}",
        "sharpe": f"{result['sharpe_ratio']:.3f}",
        "max_dd": f"{-result['max_drawdown']:.2%}",
        "trades": result["number_of_trades"],
        "vs_qqq": f"{result['total_return'] - result['qqq_total_return']:.2%}",
        "notes": notes,
    }
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerow(row)


def meets_threshold(result: Dict) -> Tuple[bool, str]:
    ret = result["total_return"]
    sharpe = result["sharpe_ratio"]
    dd = result["max_drawdown"]
    vs_qqq = ret - result["qqq_total_return"]

    if ret >= 0.40 and dd <= 0.12:
        return True, "threshold_1"
    if sharpe >= 1.10 and ret >= 0.30 and dd <= 0.12:
        return True, "threshold_2"
    if vs_qqq >= -0.15 and sharpe >= 0.90 and dd <= 0.12:
        return True, "threshold_3"
    return False, ""


def run_variant(cfg: Dict, variant: str, notes: str = "") -> Dict:
    print(f"\n=== Running variant {variant} ===")
    out = run_backtest(cfg, variant=variant)
    result = out["result"]
    log_to_csv(result, notes=notes)

    print(json.dumps({k: result[k] for k in [
        "variant", "total_return", "sharpe_ratio", "max_drawdown",
        "win_rate", "profit_factor", "number_of_trades", "avg_invested_pct",
        "momentum_trades", "pullback_trades"
    ]}, indent=2))

    return out


if __name__ == "__main__":
    out = run_variant(DEFAULT_CONFIG, "v01", notes="baseline hybrid: mom ema20/ema50 pullback_5ema 3%/12% scaleout_1_3 RISK_ON rsi55-80 ret20>=5% max15 + pb RISK_ON")
    print(f"Report: {out['report_path']}")
    print(f"Chart: {out['chart_path']}")
