#!/usr/bin/env python3
"""
Apply PEAD and regime-adaptive patches to StonkBOT.AI on VPS.
This script runs ON the VPS and patches files in-place.
"""
import re
import sys
from pathlib import Path

BASE = Path("/opt/stonk-ai")
WEB = Path("/var/www/hedge-fund-website")

def patch_file(path, old, new, desc=""):
    """Patch a file with exact text replacement."""
    content = path.read_text()
    if old not in content:
        print(f"ERROR: Could not find patch target in {path}: {desc}")
        print(f"  Looking for: {old[:80]}...")
        sys.exit(1)
    content = content.replace(old, new, 1)
    path.write_text(content)
    print(f"OK: {path.name} — {desc}")

def main():
    # =====================================================================
    # 1. Create pead_factor.py (new file)
    # =====================================================================
    pead_code = '''"""
Post-Earnings Announcement Drift (PEAD) Factor

Captures the well-documented anomaly: stocks that beat earnings estimates
drift higher for 30-60 days post-announcement. This is real alpha that
pure momentum strategies miss.

Score decay:
  Days 1-10 post-beat:  score 80-100 (strong drift window)
  Days 11-20 post-beat: score 50-80  (drift continues, tapering)
  Days 21-30 post-beat: score 20-50  (diminishing edge)
  Days 30+ post-beat:   score 0      (edge expired)

If earnings surprise data is unavailable, price reaction is used as proxy:
stock rose >2% on earnings day -> treated as "beat".

Data source: signal_enrichment.json earnings field, populated by signal_enricher.py
Format per symbol:
  {
    "period": "2026-03-31",
    "quarter": 2,
    "year": 2026,
    "estimate": 1.9884,
    "actual": 2.01,
    "surprise": 0.0216,
    "surprise_pct": 1.0863,
    "direction": "beat"
  }
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

ENRICHMENT_PATH = Path("/opt/stonk-ai/signal_enrichment.json")
MAX_WINDOW_DAYS = 30


@dataclass
class PEADResult:
    """PEAD factor result for a single symbol."""
    symbol: str
    days_since_earnings: Optional[int]
    earnings_direction: Optional[str]
    earnings_surprise_pct: Optional[float]
    post_earnings_window: bool
    pead_score: float
    pead_boost: float

    def to_dict(self) -> Dict:
        return {
            "days_since_earnings": self.days_since_earnings,
            "earnings_direction": self.earnings_direction,
            "earnings_surprise_pct": round(self.earnings_surprise_pct, 2) if self.earnings_surprise_pct is not None else None,
            "post_earnings_window": self.post_earnings_window,
            "pead_score": round(self.pead_score, 2),
            "pead_boost": round(self.pead_boost, 2),
        }


def _load_enrichment(path=ENRICHMENT_PATH):
    try:
        if not Path(path).exists():
            return {}
        with open(path) as f:
            return json.load(f).get("data", {})
    except Exception as e:
        logger.warning(f"Could not load enrichment for PEAD: {e}")
        return {}


def _days_since_period(period_str):
    """
    Calculate days since the earnings period end date.
    The period field is the fiscal quarter end date (e.g., "2026-03-31").
    Earnings are typically reported 4-6 weeks after quarter end, so
    we use period end as a proxy for the drift window calculation.
    """
    try:
        period_date = datetime.strptime(period_str, "%Y-%m-%d").date()
        today = date.today()
        delta = (today - period_date).days
        return max(0, delta) if delta >= 0 else None
    except Exception:
        return None


def _pead_score_for_beat(days):
    """
    Compute PEAD score for a confirmed beat, decaying over 30 days.
    Days 1-10:  100 -> 80
    Days 11-20: 80  -> 50
    Days 21-30: 50  -> 10
    Days 30+:   0
    """
    if days <= 0 or days > MAX_WINDOW_DAYS:
        return 0.0
    if days <= 10:
        return 100.0 - (days - 1) * 2.0
    if days <= 20:
        return 80.0 - (days - 10) * 3.0
    return max(0.0, 50.0 - (days - 20) * 4.0)


def _pead_boost_from_score(score):
    """
    Map PEAD score to readiness boost points (0-10).
    Score 100 -> +10 boost, 80 -> +8, 50 -> +5, 20 -> +2
    """
    return max(0.0, min(10.0, score * 0.10))


def compute_pead(symbol, enrichment_data=None, closes=None):
    """
    Compute PEAD factor for a single symbol.

    Parameters
    ----------
    symbol : str
    enrichment_data : dict, optional (from signal_enrichment.json)
    closes : list, optional (daily close prices for price-reaction proxy)
    """
    if enrichment_data is None:
        all_data = _load_enrichment()
        enrichment_data = all_data.get(symbol, {})

    earnings = enrichment_data.get("earnings", {}) if enrichment_data else {}
    if not earnings:
        return PEADResult(
            symbol=symbol, days_since_earnings=None,
            earnings_direction=None, earnings_surprise_pct=None,
            post_earnings_window=False, pead_score=0.0, pead_boost=0.0,
        )

    direction = earnings.get("direction")
    surprise_pct = earnings.get("surprise_pct", 0)
    period = earnings.get("period", "")
    days_since = _days_since_period(period)

    if days_since is None:
        return PEADResult(
            symbol=symbol, days_since_earnings=None,
            earnings_direction=direction, earnings_surprise_pct=surprise_pct,
            post_earnings_window=False, pead_score=0.0, pead_boost=0.0,
        )

    # Determine if beat
    is_beat = False
    if direction == "beat":
        is_beat = True
    elif direction == "miss":
        is_beat = False
    elif closes and len(closes) >= 2 and days_since <= 5:
        recent_return = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
        if recent_return > 0.02:
            is_beat = True

    if is_beat and days_since <= MAX_WINDOW_DAYS:
        score = _pead_score_for_beat(days_since)
        boost = _pead_boost_from_score(score)
    else:
        score = 0.0
        boost = 0.0

    post_window = is_beat and days_since <= MAX_WINDOW_DAYS

    return PEADResult(
        symbol=symbol, days_since_earnings=days_since,
        earnings_direction=direction, earnings_surprise_pct=surprise_pct,
        post_earnings_window=post_window, pead_score=score, pead_boost=boost,
    )


def compute_pead_batch(symbols, enrichment_path=ENRICHMENT_PATH):
    """Compute PEAD for a batch of symbols."""
    all_data = _load_enrichment(enrichment_path)
    results = {}
    for sym in symbols:
        e = all_data.get(sym, {})
        results[sym] = compute_pead(sym, e)
    return results
'''
    pead_path = BASE / "pead_factor.py"
    pead_path.write_text(pead_code)
    print(f"OK: Created {pead_path}")

    # =====================================================================
    # 2. Patch signal_engine.py — add PEAD import, compute, and integrate
    # =====================================================================
    se_path = BASE / "signal_engine.py"

    # 2a. Add import
    patch_file(se_path,
        "from mean_reversion_signal import compute_mean_reversion",
        "from mean_reversion_signal import compute_mean_reversion\nfrom pead_factor import compute_pead",
        "add PEAD import")

    # 2b. Add pead_boost field to Signal dataclass
    patch_file(se_path,
        '    strategy_type: str = "momentum"',
        '    strategy_type: str = "momentum"\n    pead_boost: float = 0.0\n    pead_score: float = 0.0',
        "add pead_boost field to Signal")

    # 2c. Add PEAD computation in _score_symbol, after readiness compute
    patch_file(se_path,
        """        # MACD histogram value for storage
        macd_hist = 0.0
        if len(closes) >= 26:
            ema12 = self._ema_val(closes[-26:], 12)
            ema26 = self._ema_val(closes[-26:], 26)
            macd_hist = round(ema12 - ema26, 4)""",
        """        # --- PEAD factor: Post-Earnings Announcement Drift ---
        pead_result = compute_pead(symbol, e, closes)
        pead_boost = pead_result.pead_boost
        pead_score = pead_result.pead_score
        if pead_boost > 0:
            # Apply PEAD boost to readiness score (capped at 100)
            readiness = ReadinessResult(
                symbol=readiness.symbol,
                readiness_score=min(100.0, readiness.readiness_score + pead_boost),
                tier=readiness.tier,
                confirmations=readiness.confirmations,
                confirmation_count=readiness.confirmation_count,
                entry_eligible=readiness.entry_eligible,
                tier_reason=readiness.tier_reason,
            )
            logger.info(f"PEAD boost: {symbol} +{pead_boost:.1f} (score={pead_score:.1f}, days={pead_result.days_since_earnings}, dir={pead_result.earnings_direction})")

        # MACD histogram value for storage
        macd_hist = 0.0
        if len(closes) >= 26:
            ema12 = self._ema_val(closes[-26:], 12)
            ema26 = self._ema_val(closes[-26:], 26)
            macd_hist = round(ema12 - ema26, 4)""",
        "add PEAD computation in _score_symbol")

    # 2d. Add pead_boost to Signal return
    patch_file(se_path,
        """            options_volume=e.get("options", {}).get("options_volume") if e.get("options") else None,
        )""",
        """            options_volume=e.get("options", {}).get("options_volume") if e.get("options") else None,
            pead_boost=round(pead_boost, 2),
            pead_score=round(pead_score, 2),
        )""",
        "add pead_boost to Signal return")

    print(f"OK: signal_engine.py patched")

    # =====================================================================
    # 3. Patch readiness_score.py — add PEAD as 9th confirmation factor
    # =====================================================================
    rs_path = BASE / "readiness_score.py"

    # 3a. Add PEAD import
    patch_file(rs_path,
        "import logging\nimport math\nfrom dataclasses import dataclass, field\nfrom typing import Dict, List, Optional, Tuple",
        "import logging\nimport math\nfrom dataclasses import dataclass, field\nfrom typing import Dict, List, Optional, Tuple\n\nfrom pead_factor import compute_pead",
        "add PEAD import")

    # 3b. Add earnings_confirmed parameter to compute_readiness and integrate
    # We need to add pead_boost parameter to the function signature
    patch_file(rs_path,
        """def compute_readiness(
    symbol: str,
    total_score: float,
    rsi14: float,
    closes: List[float],
    volumes: List[float],
    price: float,
    sector: str,
    all_bars: Optional[Dict[str, Dict]] = None,
    intraday_bars: Optional[List[Dict]] = None,
    daily_vwap: Optional[float] = None,
    prev_close: Optional[float] = None,
    options_implied_vol: Optional[float] = None,
) -> ReadinessResult:""",
        """def compute_readiness(
    symbol: str,
    total_score: float,
    rsi14: float,
    closes: List[float],
    volumes: List[float],
    price: float,
    sector: str,
    all_bars: Optional[Dict[str, Dict]] = None,
    intraday_bars: Optional[List[Dict]] = None,
    daily_vwap: Optional[float] = None,
    prev_close: Optional[float] = None,
    options_implied_vol: Optional[float] = None,
    pead_boost: float = 0.0,
) -> ReadinessResult:""",
        "add pead_boost parameter")

    # 3c. Add earnings_confirmed as 9th confirmation
    patch_file(rs_path,
        """    # 8. Options sentiment (bonus confirmation from implied vol)
    options_component, options_confirmed = _options_sentiment_score(options_implied_vol)""",
        """    # 8. Options sentiment (bonus confirmation from implied vol)
    options_component, options_confirmed = _options_sentiment_score(options_implied_vol)

    # 9. PEAD: Post-Earnings Announcement Drift (earnings_confirmed)
    pead_result = compute_pead(symbol, None, closes)
    earnings_confirmed = pead_result.post_earnings_window
    pead_boost_val = pead_result.pead_boost""",
        "add PEAD as 9th confirmation")

    # 3d. Add earnings_confirmed to confirmations dict
    patch_file(rs_path,
        """        "options_confirmed": options_confirmed,
        "options_score": round(options_component, 1),
    }""",
        """        "options_confirmed": options_confirmed,
        "options_score": round(options_component, 1),
        "earnings_confirmed": earnings_confirmed,
        "pead_score": round(pead_result.pead_score, 1),
        "pead_boost": round(pead_boost_val, 2),
    }""",
        "add earnings_confirmed to confirmations dict")

    # 3e. Add earnings_confirmed to confirmation count
    patch_file(rs_path,
        """        # Options sentiment confirmation (low IV = bullish)
        options_confirmed,
    ] if v)""",
        """        # Options sentiment confirmation (low IV = bullish)
        options_confirmed,
        # PEAD: within 30 days of earnings beat
        earnings_confirmed,
    ] if v)""",
        "add earnings_confirmed to count")

    # 3f. Apply PEAD boost to final readiness score
    patch_file(rs_path,
        """    readiness = round(max(0.0, min(100.0, readiness)), 1)""",
        """    # Apply PEAD boost
    readiness = readiness + pead_boost + pead_boost_val
    readiness = round(max(0.0, min(100.0, readiness)), 1)""",
        "apply PEAD boost to readiness")

    # 3g. Add earnings_confirmed to tier reason
    patch_file(rs_path,
        """    if confirmations.get("options_confirmed"):
        reasons.append("low IV (bullish options)")
    if confirmations.get("rsi_signal") == "oversold":""",
        """    if confirmations.get("options_confirmed"):
        reasons.append("low IV (bullish options)")
    if confirmations.get("earnings_confirmed"):
        reasons.append("PEAD: post-earnings drift")
    if confirmations.get("rsi_signal") == "oversold":""",
        "add PEAD to tier reason")

    # 3h. Fix the "X/5" display to "X/9"
    patch_file(rs_path,
        """        parts.append(f"{confirmation_count}/5 confirmations")""",
        """        parts.append(f"{confirmation_count}/9 confirmations")""",
        "fix confirmation display to /9")

    print(f"OK: readiness_score.py patched")

    # =====================================================================
    # 4. Patch index.html — update factor chips from /8 to /9
    # =====================================================================
    html_path = WEB / "index.html"

    # 4a. Add PEAD factor to buildFactorChips function
    old_factor_array = """            const factors = [
                { name: 'MOM', val: conf.momentum_score != null ? conf.momentum_score.toFixed(0) : null, ok: conf.momentum_score != null && conf.momentum_score >= 50, tip: 'Momentum: 20-day price momentum score \\u2265 50 (0-100 scale)' },
                { name: 'RSI', val: conf.rsi_signal || null, ok: conf.rsi_signal === 'bullish', warn: conf.rsi_signal === 'bearish', tip: 'RSI: 14-day Relative Strength Index \\u2014 bullish (>70) or oversold (<30)' },
                { name: 'VOL', val: conf.volume_confirmed, ok: conf.volume_confirmed === true, tip: 'Volume: above-average volume on rising prices (buying pressure)' },
                { name: 'MACD', val: conf.macd_turning, ok: conf.macd_turning === true, tip: 'MACD: moving average convergence/divergence turning bullish' },
                { name: 'EMA', val: conf.above_ema, ok: conf.above_ema === true, tip: 'EMA: price above 20-day exponential moving average' },
                { name: 'SEC', val: conf.sector_strong, ok: conf.sector_strong === true, tip: 'Sector: stock\\'s sector outperforming the broader market' },
                { name: 'INT', val: conf.intraday_confirmed, ok: conf.intraday_confirmed === true, tip: 'Intraday: positive 15-min bar momentum during market hours' },
                { name: 'OPT', val: conf.options_confirmed, ok: conf.options_confirmed === true, tip: 'Options: implied volatility suggests bullish options positioning' },
            ];"""

    new_factor_array = """            const factors = [
                { name: 'MOM', val: conf.momentum_score != null ? conf.momentum_score.toFixed(0) : null, ok: conf.momentum_score != null && conf.momentum_score >= 50, tip: 'Momentum: 20-day price momentum score \\u2265 50 (0-100 scale)' },
                { name: 'RSI', val: conf.rsi_signal || null, ok: conf.rsi_signal === 'bullish', warn: conf.rsi_signal === 'bearish', tip: 'RSI: 14-day Relative Strength Index \\u2014 bullish (>70) or oversold (<30)' },
                { name: 'VOL', val: conf.volume_confirmed, ok: conf.volume_confirmed === true, tip: 'Volume: above-average volume on rising prices (buying pressure)' },
                { name: 'MACD', val: conf.macd_turning, ok: conf.macd_turning === true, tip: 'MACD: moving average convergence/divergence turning bullish' },
                { name: 'EMA', val: conf.above_ema, ok: conf.above_ema === true, tip: 'EMA: price above 20-day exponential moving average' },
                { name: 'SEC', val: conf.sector_strong, ok: conf.sector_strong === true, tip: 'Sector: stock\\'s sector outperforming the broader market' },
                { name: 'INT', val: conf.intraday_confirmed, ok: conf.intraday_confirmed === true, tip: 'Intraday: positive 15-min bar momentum during market hours' },
                { name: 'OPT', val: conf.options_confirmed, ok: conf.options_confirmed === true, tip: 'Options: implied volatility suggests bullish options positioning' },
                { name: 'PEAD', val: conf.earnings_confirmed, ok: conf.earnings_confirmed === true, tip: 'PEAD: Post-Earnings Announcement Drift — stock within 30 days of an earnings beat' },
            ];"""

    patch_file(html_path, old_factor_array, new_factor_array, "add PEAD factor chip")

    # 4b. Update /8 to /9 in buildFactorChips
    patch_file(html_path,
        """<strong>Factors:</strong> 8-factor conviction model scoring each stock.<br><br>Green = factor confirmed, gray = not met, red = bearish signal.<br><br><strong>Factor criteria:</strong><br>• MOM: 20-day momentum score ≥ 50 (0-100)<br>• RSI: 14-day RSI bullish (>70) or oversold (<30)<br>• VOL: above-average volume on rising prices<br>• MACD: moving average convergence/divergence turning bullish<br>• EMA: price above 20-day exponential moving average<br>• SEC: stock sector outperforming the broader market<br>• INT: positive 15-min bar momentum during market hours<br>• OPT: implied volatility suggests bullish positioning<br><br>Hover individual chips for each factor criteria.')""",
        """<strong>Factors:</strong> 9-factor conviction model scoring each stock.<br><br>Green = factor confirmed, gray = not met, red = bearish signal.<br><br><strong>Factor criteria:</strong><br>• MOM: 20-day momentum score ≥ 50 (0-100)<br>• RSI: 14-day RSI bullish (>70) or oversold (<30)<br>• VOL: above-average volume on rising prices<br>• MACD: moving average convergence/divergence turning bullish<br>• EMA: price above 20-day exponential moving average<br>• SEC: stock sector outperforming the broader market<br>• INT: positive 15-min bar momentum during market hours<br>• OPT: implied volatility suggests bullish positioning<br>• PEAD: within 30 days of an earnings beat (post-earnings drift)<br><br>Hover individual chips for each factor criteria.')""",
        "update tooltip from 8 to 9 factors")

    # 4c. Update ${count}/8 to ${count}/9 in multiple places
    content = html_path.read_text()
    # Replace all occurrences of ${count}/8 with ${count}/9
    content = content.replace("${count}/8", "${count}/9")
    # Replace "8 factors" with "9 factors" in tooltip
    content = content.replace("Conviction model: 8 factors scored per stock", "Conviction model: 9 factors scored per stock")
    # Replace "7-factor conviction model" with "9-factor conviction model"
    content = content.replace("7-factor conviction model", "9-factor conviction model")
    # Add PEAD to the watchlist factors list
    content = content.replace(
        "const allFactors = ['MOM', 'RSI', 'VOL', 'MACD', 'EMA', 'SEC', 'INT', 'OPT'];",
        "const allFactors = ['MOM', 'RSI', 'VOL', 'MACD', 'EMA', 'SEC', 'INT', 'OPT', 'PEAD'];"
    )
    # Add PEAD to factorMap in buildWatchlistFactors
    content = content.replace(
        "'intraday': 'INT', 'options': 'OPT', 'momentum': 'MOM', 'rsi': 'RSI'",
        "'intraday': 'INT', 'options': 'OPT', 'momentum': 'MOM', 'rsi': 'RSI', 'earnings': 'PEAD', 'pead': 'PEAD'"
    )
    # Update the "Composite of 7 factors" text
    content = content.replace("Composite of 7 factors", "Composite of 9 factors")
    html_path.write_text(content)
    print(f"OK: index.html patched — all factor chip updates /8 -> /9")

    # =====================================================================
    # 5. Patch trading_bot.py — regime-adaptive strategy switching
    # =====================================================================
    tb_path = BASE / "trading_bot.py"

    # 5a. Add mean_reversion import
    patch_file(tb_path,
        "from regime_detector import get_regime",
        "from regime_detector import get_regime\nfrom mean_reversion_signal import compute_mean_reversion",
        "add mean_reversion import")

    # 5b. Add strategy logging after regime detection
    patch_file(tb_path,
        """            logger.info(f"{_regime_emoji.get(self._regime, '?')} Regime: {self._regime} \\u2014 {_regime_desc.get(self._regime, '')}")
            if regime_result.get("triggers"):
                logger.info(f"  Regime triggers: {'; '.join(regime_result['triggers'])}")""",
        """            logger.info(f"{_regime_emoji.get(self._regime, '?')} Regime: {self._regime} \\u2014 {_regime_desc.get(self._regime, '')}")
            if regime_result.get("triggers"):
                logger.info(f"  Regime triggers: {'; '.join(regime_result['triggers'])}")
            # Log active strategy
            if self._regime == "RISK_ON":
                logger.info("\\U0001F4C8 Strategy: Momentum (RISK_ON)")
            elif self._regime == "RISK_OFF":
                logger.info("\\U0001F504 Strategy: Mean Reversion (RISK_OFF)")""",
        "add strategy logging")

    # 5c. Replace the entry candidate building logic to support regime switching
    # Find the section where entry candidates are built from signals
    old_entry_block = """        # 3a. Build ranked entry queue by readiness_score (highest first)
        entry_candidates = []
        for sig in top_signals:
            symbol = sig["symbol"]
            if symbol in current_symbols:
                continue
            # NEW: use entry_eligible instead of total_score >= 30
            if not sig.get("entry_eligible", False):
                continue

            # Regime-based entry gate
            _min_tier = self._regime_params.get("min_tier_for_entry")
            if _min_tier is None:
                # CRISIS: no new entries at all
                logger.info(f"CRISIS regime: skipping new entry for {symbol}")
                continue
            _tier_rank = {"MONITOR": 0, "WATCH": 1, "NOW": 2, "STRONG_NOW": 3}
            _sig_tier = _tier_rank.get(sig.get("tier", "MONITOR"), 0)
            _min_tier_rank