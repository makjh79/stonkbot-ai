#!/usr/bin/env python3
"""
STONK.AI v3 Deployed Strategy — Cash-Diagnostics Variant
========================================================

Runs the EXACT same entry/exit/sizing/risk logic as
proper_backtest_deployed.py (commit e645b41), but records every
day why the strategy did *not* add new positions.

Reason categories per day:
- risk_off_or_crisis  : regime was not RISK_ON
- score_threshold     : no symbol passed score >= threshold (after vetoes/meltdown)
- cash_floor          : cash below 10% floor
- drawdown_halt       : portfolio drawdown <= -10%
- max_positions       : already at 15 positions
- other               : none of the above / not applicable

Output JSON:
  /opt/stonk-ai/reports/v3_proper_backtest_cash_diag.json
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

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

V3_SCORE_THRESHOLD = 0.5
V3_MELTDOWN_QQQ_5D_MAX = -0.08
V3_POSITION_PCT = 0.03
V3_MAX_POSITIONS = 15
V3_CASH_FLOOR_PCT = 0.10
V3_ENTRY_CASH_BUFFER_PCT = 0.12
V3_SECTOR_CAP_PCT = 0.25
V3_DRAWDOWN_HALT_PCT = -0.10

TIER_CAP = {
    "STRONG_NOW": 0.12,
    "NOW": 0.08,
    "WATCH": 0.08,
    "MONITOR": 0.08,
}

HARD_STOP_ATR_MULT = 1.5
HARD_STOP_MIN_PCT = 0.05
HARD_STOP_MAX_PCT = 0.11
TRAILING_STOP_ATR_MULT = 2.0
TRAILING_STOP_MIN_PCT = 0.05
TRAILING_STOP_MAX_PCT = 0.14
SCALEOUT_T1_ATR = 0.5
SCALEOUT_T2_ATR = 1.0
SCALEOUT_FRAC = 1 / 3.0
FULL_EXIT_PROFIT_PCT = 0.30

CREDIT_SPREAD_RISK_OFF = 1.45
CREDIT_SPREAD_CRISIS = 1.60
VIXY_CHANGE_RISK_OFF = 5.0
VIXY_CHANGE_CRISIS = 15.0
SPY_EMA_PERIOD = 50


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


TREND_PULLBACK_WEIGHTS = {
    "dist_ema200": 1.0,
    "dist_ema50": 1.0,
    "dist_ema20": 0.5,
    "ret_5d": -3.0,
    "rsi14": -0.1,
    "vs_qqq_5d": -1.0,
    "vol_ratio": 0.3,
}
HARD_RSI_MAX = 75
HARD_DIST_EMA200_MIN = -0.15


def score_row(r: Dict) -> Tuple[float, bool]:
    dist_ema200 = r["dist_ema200"]
    dist_ema50 = r["dist_ema50"]
    dist_ema20 = r["dist_ema20"]
    ret_5d = r["ret_5d"]
    rsi14 = r["rsi14"]
    vs_qqq_5d = r["vs_qqq_5d"]
    vol_ratio = r["vol_ratio"]

    hard_blocked = False
    if rsi14 > HARD_RSI_MAX:
        hard_blocked = True
    if dist_ema200 < HARD_DIST_EMA200_MIN:
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
    remaining_fraction: float = 1.0
    highest_close: float = 0.0
    scaleouts_hit: List[str] = field(default_factory=list)


def backtest_cash_diag() -> Dict:
    bars = load_bars()
    features = load_features()
    etfs = fetch_or_load_regime_etfs()
    regime_df = build_regime_series(bars, etfs)

    dates = bars["QQQ"]["timestamps"]
    qqq_closes = bars["QQQ"]["closes"]
    spy_closes = bars["SPY"]["closes"]

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

    universe = sorted([s for s in bars if s not in ("SPY", "QQQ")])

    cash = START_VALUE
    equity_peak = START_VALUE
    positions: List[Position] = []
    trades: List[Dict] = []
    equity_curve = []
    daily_cash_reasons = []
    daily_series = []
    halted = False
    drawdown_halt_date: Optional[str] = None

    for i, d in enumerate(dates):
        dt = pd.to_datetime(d, utc=True)
        qqq_price = qqq_closes[i]

        mv = cash
        for p in positions:
            sym_dates = bars[p.symbol]["timestamps"]
            if i < len(sym_dates) and sym_dates[i] == d:
                mv += p.shares * p.remaining_fraction * bars[p.symbol]["closes"][i]
            else:
                mv += p.shares * p.remaining_fraction * p.entry_price

        if mv > equity_peak:
            equity_peak = mv
        dd = (equity_peak - mv) / equity_peak

        regime_row = regime_df.loc[dt]
        regime = regime_row["regime"]
        qqq_5d = regime_row["qqq_5d_return"]
        halted_today = False

        if dd >= 0.10:
            if not halted:
                halted = True
                drawdown_halt_date = d
                halted_today = True
        else:
            halted = False

        # Exits
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
            if "T1" not in p.scaleouts_hit and profit_pct >= SCALEOUT_T1_ATR * atr_pct:
                exits_today.append((pi, "scaleout_t1", SCALEOUT_FRAC, close))
            if "T2" not in p.scaleouts_hit and profit_pct >= SCALEOUT_T2_ATR * atr_pct:
                exits_today.append((pi, "scaleout_t2", SCALEOUT_FRAC, close))
            if profit_pct >= FULL_EXIT_PROFIT_PCT:
                exits_today.append((pi, "full_exit", p.remaining_fraction, close))
                continue

            hard_stop_pct = -max(min(HARD_STOP_ATR_MULT * atr_pct, HARD_STOP_MAX_PCT), HARD_STOP_MIN_PCT)
            if (close - entry_price) / entry_price <= hard_stop_pct:
                exits_today.append((pi, "hard_stop", p.remaining_fraction, close))
                continue

            trail_stop_pct = -max(min(TRAILING_STOP_ATR_MULT * atr_pct, TRAILING_STOP_MAX_PCT), TRAILING_STOP_MIN_PCT)
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
            })
            if reason.startswith("scaleout"):
                p.scaleouts_hit.append(reason.replace("scaleout_", "").upper())
                p.remaining_fraction -= frac
            else:
                p.remaining_fraction = 0.0

        positions = [p for p in positions if p.remaining_fraction > 1e-9]

        # Entry and cash-diagnostic logic
        cash_floor = mv * V3_CASH_FLOOR_PCT
        entry_buffer = mv * V3_ENTRY_CASH_BUFFER_PCT
        cash_for_entries = max(0.0, cash - cash_floor - entry_buffer)
        invested_pct = 100.0 * (mv - cash) / mv if mv > 0 else 0.0

        reason = "other"
        detail = ""

        # Determine the *single* primary reason no new positions were added today.
        # Entry days are labelled "entered_positions" and excluded from the
        # requested reason counts.
        if halted or halted_today:
            reason = "drawdown_halt"
            detail = f"drawdown {dd:.2%} >= 10%"
        elif regime != "RISK_ON":
            reason = "risk_off_or_crisis"
            detail = f"regime={regime}"
        elif qqq_5d is None or qqq_5d <= V3_MELTDOWN_QQQ_5D_MAX:
            reason = "risk_off_or_crisis"
            detail = f"meltdown qqq_5d={qqq_5d}"
        elif len(positions) >= V3_MAX_POSITIONS:
            reason = "max_positions"
            detail = f"positions={len(positions)}"
        elif cash < cash_floor:
            reason = "cash_floor"
            detail = f"cash {cash:.0f} < floor {cash_floor:.0f}"
        else:
            # Cash/buffer still leaves no entry money
            if cash_for_entries < 100:
                reason = "cash_floor"
                detail = f"cash_for_entries {cash_for_entries:.0f} after buffer"
            else:
                # Evaluate candidate scores
                day_scores = []
                for sym in universe:
                    feat = features.get((sym, d))
                    if feat is None:
                        continue
                    score, blocked = score_row(feat)
                    if blocked or math.isnan(score):
                        continue
                    if score < V3_SCORE_THRESHOLD:
                        continue
                    day_scores.append((score, sym, feat))

                day_scores.sort(key=lambda x: -x[0])
                if not day_scores:
                    reason = "score_threshold"
                    detail = "no candidate scored >= threshold"
                else:
                    # Simulate the selection loop to see if it actually filled slots
                    n = len(day_scores)
                    ranked = []
                    for rank, (score, sym, feat) in enumerate(day_scores, 1):
                        if rank <= max(1, n // 3):
                            tier = "STRONG_NOW"
                        elif rank <= max(1, 2 * n // 3):
                            tier = "NOW"
                        else:
                            tier = "WATCH"
                        ranked.append((score, sym, feat, tier))

                    open_slots = V3_MAX_POSITIONS - len(positions)
                    existing_symbols = {p.symbol for p in positions}
                    sector_exposure: Dict[str, float] = defaultdict(float)
                    for p in positions:
                        sec = symbol_to_sector.get(p.symbol, "Other")
                        sym_ts = bars[p.symbol]["timestamps"]
                        price = bars[p.symbol]["closes"][i] if i < len(sym_ts) and sym_ts[i] == d else p.entry_price
                        sector_exposure[sec] += p.shares * p.remaining_fraction * price / mv

                    would_select = 0
                    for score, sym, feat, tier in ranked:
                        if would_select >= open_slots:
                            break
                        if sym in existing_symbols:
                            continue
                        sec = symbol_to_sector.get(sym, "Other")
                        if sector_exposure[sec] >= V3_SECTOR_CAP_PCT:
                            continue
                        cap = TIER_CAP[tier]
                        target_value = min(mv * V3_POSITION_PCT, mv * cap, cash_for_entries)
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
                        would_select += 1
                        sector_exposure[sec] += shares * entry_price / mv

                    if would_select == 0:
                        reason = "score_threshold"
                        detail = "candidates existed but could not be selected (tiers/sector/cash too small)"
                    else:
                        # Actually entered positions today — this is an entry day
                        reason = "entry_day"
                        detail = f"entered {would_select} positions"

        # Actually run the real entry code (same as base harness) so the simulation
        # state remains identical to proper_backtest_deployed.py.
        can_enter = (
            (not halted)
            and (not halted_today)
            and regime == "RISK_ON"
            and qqq_5d is not None
            and qqq_5d > V3_MELTDOWN_QQQ_5D_MAX
        )

        if can_enter:
            day_scores = []
            for sym in universe:
                feat = features.get((sym, d))
                if feat is None:
                    continue
                score, blocked = score_row(feat)
                if blocked or math.isnan(score):
                    continue
                if score < V3_SCORE_THRESHOLD:
                    continue
                day_scores.append((score, sym, feat))

            day_scores.sort(key=lambda x: -x[0])
            if day_scores:
                n = len(day_scores)
                ranked = []
                for rank, (score, sym, feat) in enumerate(day_scores, 1):
                    if rank <= max(1, n // 3):
                        tier = "STRONG_NOW"
                    elif rank <= max(1, 2 * n // 3):
                        tier = "NOW"
                    else:
                        tier = "WATCH"
                    ranked.append((score, sym, feat, tier))

                cash_floor = mv * V3_CASH_FLOOR_PCT
                entry_buffer = mv * V3_ENTRY_CASH_BUFFER_PCT
                cash_for_entries = max(0.0, cash - cash_floor - entry_buffer)

                open_slots = V3_MAX_POSITIONS - len(positions)
                if open_slots > 0 and cash_for_entries > 0:
                    existing_symbols = {p.symbol for p in positions}
                    sector_exposure: Dict[str, float] = defaultdict(float)
                    for p in positions:
                        sec = symbol_to_sector.get(p.symbol, "Other")
                        sym_ts = bars[p.symbol]["timestamps"]
                        price = bars[p.symbol]["closes"][i] if i < len(sym_ts) and sym_ts[i] == d else p.entry_price
                        sector_exposure[sec] += p.shares * p.remaining_fraction * price / mv

                    selected = 0
                    for score, sym, feat, tier in ranked:
                        if selected >= open_slots:
                            break
                        if sym in existing_symbols:
                            continue

                        sec = symbol_to_sector.get(sym, "Other")
                        if sector_exposure[sec] >= V3_SECTOR_CAP_PCT:
                            continue

                        cap = TIER_CAP[tier]
                        target_value = min(mv * V3_POSITION_PCT, mv * cap, cash_for_entries)
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
                            highest_close=float(entry_price),
                        ))
                        cash -= entry_cost
                        cash_for_entries -= entry_cost
                        sector_exposure[sec] += shares * entry_price / mv
                        selected += 1

        # End-of-day mark-to-market
        mv = cash
        for p in positions:
            sym_data = bars[p.symbol]
            if i < len(sym_data["timestamps"]) and sym_data["timestamps"][i] == d:
                mv += p.shares * p.remaining_fraction * sym_data["closes"][i]
            else:
                mv += p.shares * p.remaining_fraction * p.entry_price

        invested_pct = 100.0 * (mv - cash) / mv if mv > 0 else 0.0

        equity_curve.append({
            "date": d,
            "equity": float(mv),
            "cash": float(cash),
            "regime": regime,
            "n_positions": len(positions),
            "drawdown": float(dd),
            "qqq_close": float(qqq_price),
        })
        daily_cash_reasons.append({
            "date": d,
            "reason": reason,
            "detail": detail,
            "regime": regime,
            "n_positions": len(positions),
            "equity": float(mv),
            "cash": float(cash),
            "invested_pct": float(invested_pct),
            "drawdown": float(dd),
            "halted": halted or halted_today,
        })
        daily_series.append({
            "date": d,
            "invested_pct": float(invested_pct),
            "num_positions": len(positions),
            "regime": regime,
            "equity": float(mv),
            "cash": float(cash),
            "drawdown": float(dd),
        })

    # Force-liquidate remaining positions at final close
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
        })

    final_equity = cash

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

    # Reason counts: only count days when no new positions were added.
    reason_counts = defaultdict(int)
    for row in daily_cash_reasons:
        if row["reason"] != "entry_day":
            reason_counts[row["reason"]] += 1
    # Ensure all requested categories appear, even if zero.
    for cat in ["risk_off_or_crisis", "score_threshold", "cash_floor", "drawdown_halt", "max_positions", "other"]:
        reason_counts.setdefault(cat, 0)

    invested_pcts = [r["invested_pct"] for r in daily_series]
    invested_summary = {
        "min": float(np.min(invested_pcts)),
        "max": float(np.max(invested_pcts)),
        "mean": float(np.mean(invested_pcts)),
        "median": float(np.median(invested_pcts)),
    }

    result = {
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
        "avg_holding_days": avg_hold,
        "qqq_total_return": float(qqq_return),
        "qqq_sharpe_ratio": qqq_sharpe,
        "final_equity": float(final_equity),
        "final_qqq_equity": float(qqq_final_value),
        "start_date": dates[0],
        "end_date": dates[-1],
        "start_value": START_VALUE,
        "regime_counts": regime_df["regime"].value_counts().to_dict(),
        "drawdown_halt_date": drawdown_halt_date,
        "cash_reason_counts": dict(reason_counts),
        "invested_pct_summary": invested_summary,
        "daily_reasons": daily_cash_reasons,
        "daily_series": daily_series,
        "methodology": {
            "signal_engine": "v3_signal_engine.compute_trend_pullback_score (replicated)",
            "execution": "daily close, t signal -> t+1 execution, 0.1% cost per side",
            "regime": "replicated from regime_detector.py using SPY/QQQ/VIXY/LQD/HYG/TLT/SHY daily bars; VIXY/LQD/HYG/TLT/SHY fetched from Yahoo Finance",
            "missing_inputs": [
                "Intraday VWAP confirmation (live v3 requires vwap_confirmed)",
                "Options-flow / IV confirmation",
                "Earnings blackout gating",
                "Live news / sentiment overlays",
                "Intraday stop triggers; stops are evaluated at daily close",
            ],
            "diag_note": "This is the deployed strategy with added cash-floor diagnostic logging; portfolio mechanics are unchanged.",
        },
    }

    report_path = REPORT_DIR / "v3_proper_backtest_cash_diag.json"
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2)

    equity_csv_path = REPORT_DIR / "v3_proper_backtest_cash_diag_equity.csv"
    pd.DataFrame(equity_curve).to_csv(equity_csv_path, index=False)

    return {
        "result": result,
        "equity_curve": equity_curve,
        "trades": trades,
        "report_path": str(report_path),
        "equity_csv_path": str(equity_csv_path),
        "qqq_final_value": qqq_final_value,
    }


def _trading_days_between(dates: List[str], start: str, end: str) -> int:
    try:
        return max(0, dates.index(end) - dates.index(start))
    except ValueError:
        return 0


def main():
    print("Running deployed v3 strategy with cash diagnostics...")
    out = backtest_cash_diag()
    result = out["result"]
    print("\n=== Results ===")
    print(json.dumps({k: v for k, v in result.items() if k not in ("daily_reasons", "daily_series")}, indent=2))
    print(f"\nReport: {out['report_path']}")
    print(f"Equity CSV: {out['equity_csv_path']}")


if __name__ == "__main__":
    main()
