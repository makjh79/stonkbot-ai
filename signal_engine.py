"""
STONK.AI Signal Engine v2.1

Generates daily quality-momentum scores for a liquid US stock universe.
Scores combine momentum, quality, risk, and macro-regime factors.
The trading bot consumes `signals.json` as the single source of truth.

v2.1: Adds readiness_score, confirmations, entry_eligible — the new
      primary drivers for tier assignment and entry decisions.
"""

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import options_iv_analytics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from readiness_score import compute_readiness, ReadinessResult, compute_confirmation_count
from stonk_utils import atomic_write_json
from stonkbot_db import save_signals as db_save_signals, heartbeat, export_json_mirrors
from mean_reversion_signal import compute_mean_reversion
# PEAD dropped — zero external dependencies
from alpaca_data import get_data_hub

# Intraday data cache (populated during generate_signals)
_intraday_cache: Dict = {}
_snapshot_cache: Dict = {}

logger = logging.getLogger(__name__)

# Liquid US growth/momentum universe. ~60 names, no ETFs, no micro-caps.
DEFAULT_UNIVERSE = [
    # Tech Giants
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "NFLX",
    # Semiconductors / Hardware
    "AMD", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON",
    # Cybersecurity / Enterprise Software
    "CRWD", "PANW", "ZS", "NET", "DDOG", "OKTA", "FTNT", "CYBR", "S", "PATH", "PLTR",
    # Cloud / Data / SaaS
    "SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW",
    # Fintech
    "HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY",
    # Consumer / Platform / E-commerce
    "UBER", "DKNG", "SHOP", "TTD", "ROKU", "PINS", "SNAP", "ABNB", "EXPE", "SPOT",
    # Retail / Lifestyle / Growth
    "ELF", "APP", "DUOL", "CHWY", "ETSY", "LULU", "NKE", "COST", "WMT", "HD",
    # EV / Mobility
    "TSLA", "RIVN", "LCID", "NIO", "XPEV",
    # Healthcare / Biotech
    "UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "VRTX", "BMY", "REGN",
    "GILD", "ISRG", "ZBH", "ILMN", "SGEN",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY",
    # Industrials
    "GE", "CAT", "UNP", "HON", "UPS", "RTX", "LMT", "DE",
    # Financials / Banks
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "V",
    # Communications / Media
    "DIS", "CMCSA", "TMUS", "CHTR", "WBD", "PARA",
    # Tech Expansion
    "AVGO", "TXN", "IBM", "INTC", "CRM", "ORCL", "ADBE", "INTU", "PYPL", "FIS",
]

COMPANY_NAMES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "NVDA": "NVIDIA Corp.",
    "NFLX": "Netflix Inc.",
    "AMD": "Advanced Micro Devices",
    "MU": "Micron Technology Inc.",
    "LRCX": "Lam Research Corp.",
    "AMAT": "Applied Materials Inc.",
    "KLAC": "KLA Corp.",
    "SNPS": "Synopsys Inc.",
    "CDNS": "Cadence Design Systems",
    "MRVL": "Marvell Technology Inc.",
    "NXPI": "NXP Semiconductors",
    "QCOM": "Qualcomm Inc.",
    "SWKS": "Skyworks Solutions Inc.",
    "TER": "Teradyne Inc.",
    "ON": "ON Semiconductor Corp.",
    "CRWD": "CrowdStrike Holdings",
    "PANW": "Palo Alto Networks Inc.",
    "ZS": "Zscaler Inc.",
    "NET": "Cloudflare Inc.",
    "DDOG": "Datadog Inc.",
    "OKTA": "Okta Inc.",
    "FTNT": "Fortinet Inc.",
    "CYBR": "CyberArk Software Ltd.",
    "S": "SentinelOne Inc.",
    "PATH": "UiPath Inc.",
    "PLTR": "Palantir Technologies",
    "SNOW": "Snowflake Inc.",
    "MDB": "MongoDB Inc.",
    "GTLB": "GitLab Inc.",
    "CFLT": "Confluent Inc.",
    "ESTC": "Elastic N.V.",
    "PSTG": "Pure Storage Inc.",
    "DOCN": "DigitalOcean Holdings",
    "VEEV": "Veeva Systems Inc.",
    "TEAM": "Atlassian Corp.",
    "NOW": "ServiceNow Inc.",
    "HOOD": "Robinhood Markets Inc.",
    "COIN": "Coinbase Global Inc.",
    "SQ": "Block Inc.",
    "UPST": "Upstart Holdings Inc.",
    "AFRM": "Affirm Holdings Inc.",
    "SOFI": "SoFi Technologies Inc.",
    "PAYO": "Payoneer Global Inc.",
    "LMND": "Lemonade Inc.",
    "RELY": "Remitly Global Inc.",
    "UBER": "Uber Technologies Inc.",
    "DKNG": "DraftKings Inc.",
    "SHOP": "Shopify Inc.",
    "TTD": "The Trade Desk Inc.",
    "ROKU": "Roku Inc.",
    "PINS": "Pinterest Inc.",
    "SNAP": "Snap Inc.",
    "ABNB": "Airbnb Inc.",
    "EXPE": "Expedia Group Inc.",
    "SPOT": "Spotify Technology S.A.",
    "ELF": "e.l.f. Beauty Inc.",
    "APP": "AppLovin Corp.",
    "DUOL": "Duolingo Inc.",
    "CHWY": "Chewy Inc.",
    "ETSY": "Etsy Inc.",
    "LULU": "Lululemon Athletica Inc.",
    "NKE": "Nike Inc.",
    "COST": "Costco Wholesale Corp.",
    "WMT": "Walmart Inc.",
    "HD": "Home Depot Inc.",
    "TSLA": "Tesla Inc.",
    "RIVN": "Rivian Automotive Inc.",
    "LCID": "Lucid Group Inc.",
    "NIO": "NIO Inc.",
    "XPEV": "XPeng Inc.",
    # Healthcare
    "UNH": "UnitedHealth Group", "LLY": "Eli Lilly & Co.", "JNJ": "Johnson & Johnson",
    "PFE": "Pfizer Inc.", "ABBV": "AbbVie Inc.", "MRK": "Merck & Co.",
    "TMO": "Thermo Fisher Scientific", "VRTX": "Vertex Pharmaceuticals",
    "BMY": "Bristol-Myers Squibb", "REGN": "Regeneron Pharmaceuticals",
    "GILD": "Gilead Sciences", "ISRG": "Intuitive Surgical Inc.",
    "ZBH": "Zimmer Biomet Holdings", "ILMN": "Illumina Inc.",
    "SGEN": "Seagen Inc.",
    # Energy
    "XOM": "ExxonMobil Corp.", "CVX": "Chevron Corp.", "COP": "ConocoPhillips",
    "SLB": "Schlumberger N.V.", "EOG": "EOG Resources Inc.",
    "PSX": "Phillips 66", "MPC": "Marathon Petroleum", "OXY": "Occidental Petroleum",
    # Industrials
    "GE": "General Electric Co.", "CAT": "Caterpillar Inc.",
    "UNP": "Union Pacific Corp.", "HON": "Honeywell International",
    "UPS": "United Parcel Service", "RTX": "RTX Corp.",
    "LMT": "Lockheed Martin Corp.", "DE": "Deere & Co.",
    # Financials
    "JPM": "JPMorgan Chase & Co.", "BAC": "Bank of America Corp.",
    "WFC": "Wells Fargo & Co.", "GS": "Goldman Sachs Group",
    "MS": "Morgan Stanley", "BLK": "BlackRock Inc.",
    "SCHW": "Charles Schwab Corp.", "V": "Visa Inc.",
    # Communications
    "DIS": "Walt Disney Co.", "CMCSA": "Comcast Corp.",
    "TMUS": "T-Mobile US Inc.", "CHTR": "Charter Communications",
    "WBD": "Warner Bros Discovery", "PARA": "Paramount Global",
    # Tech Expansion
    "AVGO": "Broadcom Inc.", "TXN": "Texas Instruments Inc.",
    "IBM": "International Business Machines", "INTC": "Intel Corp.",
    "CRM": "Salesforce Inc.", "ORCL": "Oracle Corp.",
    "ADBE": "Adobe Inc.", "INTU": "Intuit Inc.",
    "PYPL": "PayPal Holdings", "FIS": "Fidelity National Info",
}

# Minimum liquidity threshold: average daily volume > 50k shares on SIP consolidated feed.
# Real volume will be much higher; this just filters out dead names on the free tier.
MIN_AVG_VOLUME = 50_000

# Regime inputs: broad-market proxies used to scale exposure
REGIME_SYMBOLS = ["SPY", "QQQ", "VIXY", "SHY", "TLT", "LQD", "HYG"]

# Score weights
MOMENTUM_WEIGHT = 0.40
QUALITY_WEIGHT = 0.25
RISK_WEIGHT = 0.20
REGIME_WEIGHT = 0.15


@dataclass
class Signal:
    symbol: str
    momentum_score: float
    quality_score: float
    risk_score: float
    regime_score: float
    total_score: float
    rank: int
    price: float
    atr14: float
    rsi14: float
    momentum_20d: float
    momentum_50d: float
    volatility_20d: float
    avg_volume: int
    spy_corr_20d: float
    ai_score: Optional[float] = None
    sector: str = "Other"
    company: str = ""
    thesis: str = ""
    drivers: List[str] = None
    earnings: Optional[Dict] = None
    recommendation: Optional[Dict] = None
    news: Optional[Dict] = None
    updated_at: Optional[str] = None
    # --- v2.1 readiness fields ---
    readiness_score: float = 0.0
    tier: str = "MONITOR"
    confirmations: Dict = None
    confirmation_count: int = 0
    entry_eligible: bool = False
    tier_reason: str = ""
    relative_strength_20d: float = 0.0
    macd_hist: float = 0.0
    volume_ratio: float = 0.0
    above_ema20: bool = False
    sector_strong: bool = False
    intraday_vwap: Optional[float] = None
    intraday_vol_ratio: Optional[float] = None
    daily_vwap: Optional[float] = None
    prev_close: Optional[float] = None
    options_implied_vol: Optional[float] = None
    options_volume: Optional[int] = None
    strategy_type: str = "momentum"
    factor_breakdown: Optional[Dict] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        if d.get("drivers") is None:
            d["drivers"] = []
        if d.get("confirmations") is None:
            d["confirmations"] = {}
        return d


class SignalEngine:
    def __init__(
        self,
        universe: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        data_url: str = "https://data.alpaca.markets",
        min_avg_volume: int = MIN_AVG_VOLUME,
    ):
        self.universe = universe or DEFAULT_UNIVERSE
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_SECRET_KEY")
        self.data_url = data_url
        self.min_avg_volume = min_avg_volume

        if not self.api_key or not self.api_secret:
            config = self._load_alpaca_config()
            self.api_key = self.api_key or config.get("api_key") or config.get("APCA_API_KEY_ID")
            self.api_secret = self.api_secret or config.get("api_secret") or config.get("APCA_API_SECRET_KEY")
            self.data_url = config.get("data_url", self.data_url)

        # Initialize unified Alpaca data hub
        self._hub = get_data_hub()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_signals(self, lookback_days: int = 120, enrichment: Optional[Dict[str, Dict]] = None) -> List[Signal]:
        """Generate scored signals for the universe."""
        logger.info(f"Generating signals for {len(self.universe)} symbols...")

        # Load enrichment cache if not provided
        if enrichment is None:
            enrichment = self._load_enrichment()

        # Fetch options sentiment from Alpaca (implied vol, options volume)
        try:
            options_data = self._fetch_options_enrichment(self.universe[:30])
            for sym, opts in options_data.items():
                if sym not in enrichment:
                    enrichment[sym] = {}
                enrichment[sym]["options"] = opts
            if options_data:
                logger.info(f"Loaded options sentiment for {len(options_data)} symbols")
        except Exception as e:
            logger.debug(f"Options enrichment skipped: {e}")

        # Fetch all market data in one composite call via Alpaca data hub
        all_symbols = list(set(self.universe + list(REGIME_SYMBOLS)))
        market_data = self._hub.get_market_data(all_symbols, lookback_days)
        raw_data = market_data["daily"]
        _snapshot_cache.clear()
        _snapshot_cache.update(market_data["snapshots"])
        _intraday_cache.clear()
        _intraday_cache.update(market_data["intraday"])

        if not raw_data:
            raise RuntimeError("No price data retrieved from Alpaca; cannot generate signals.")

        # Regime data already included in composite fetch
        regime_data = {k: v for k, v in raw_data.items() if k in REGIME_SYMBOLS}
        if not regime_data:
            regime_data = self._hub.get_daily_bars(list(REGIME_SYMBOLS), lookback_days)
        if not regime_data:
            logger.warning("No regime data; using neutral regime scores.")
            regime_data = {}

        # Merge regime data into all_bars for sector relative strength
        all_bars = dict(raw_data)
        all_bars.update(regime_data)

        signals: List[Signal] = []
        for symbol in self.universe:
            bars = raw_data.get(symbol)
            if not bars:
                continue
            try:
                signal = self._score_symbol(symbol, bars, regime_data, all_bars, enrichment)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.warning(f"Could not score {symbol}: {e}")

        # Rank by readiness_score (new primary), with total_score as tiebreaker
        signals.sort(key=lambda s: (s.readiness_score, s.total_score), reverse=True)
        for i, s in enumerate(signals, start=1):
            s.rank = i
            s.updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        logger.info(f"Generated {len(signals)} signals. Top: {signals[0].symbol if signals else 'none'} (readiness={signals[0].readiness_score if signals else 0:.1f})")
        return signals

    def save_signals(self, signals: List[Signal], path: Optional[Path] = None) -> Path:
        if path is None:
            path = Path(__file__).parent / "signals.json"

        # Merge mean reversion signals
        mr_signals = []
        for s in signals:
            sym = s.symbol
            raw = self._hub.get_daily_bars([sym], 120)
            bars = raw.get(sym)
            if not bars:
                continue
            mr = compute_mean_reversion(sym, bars["closes"], bars["volumes"], s.price, s.rsi14)
            if mr:
                mr_signals.append(mr.to_dict())

        # Add strategy_type to momentum signals
        momentum_dicts = []
        for s in signals:
            d = s.to_dict()
            d["strategy_type"] = "momentum"
            momentum_dicts.append(d)

        # Deduplicate: if a symbol has both momentum and mean reversion signals,
        # keep the one with higher readiness_score and tag it appropriately
        by_symbol = {}
        for d in momentum_dicts:
            by_symbol[d["symbol"]] = d
        for d in mr_signals:
            sym = d["symbol"]
            if sym in by_symbol:
                # Merge: keep higher readiness, but note both strategies exist
                existing = by_symbol[sym]
                if d.get("readiness_score", 0) > existing.get("readiness_score", 0):
                    # Mean reversion wins — merge MR fields into existing momentum dict
                    # (preserves avg_volume, sector, earnings, news, etc from momentum signal)
                    # NOTE: keep momentum entry_eligible; MR is watch-only, not an entry trigger.
                    merged = dict(existing)
                    merged.update({
                        "strategy_type": "mean_reversion",
                        "has_momentum_signal": True,
                        "readiness_score": d.get("readiness_score"),
                        "total_score": d.get("total_score"),
                        "tier": d.get("tier"),
                        "confirmations": d.get("confirmations", {}),
                        "confirmation_count": d.get("confirmation_count", 0),
                        "tier_reason": d.get("tier_reason", ""),
                        "reversion_score": d.get("reversion_score"),
                        "ema_distance_pct": d.get("ema_distance_pct"),
                        "entry_eligible_mr": d.get("entry_eligible_mr", False),
                        "has_mean_reversion_signal": True,
                    })
                    # Preserve momentum entry eligibility (single source of truth)
                    # merged["entry_eligible"] stays as existing's value
                    by_symbol[sym] = merged
                else:
                    # Momentum wins — note mean reversion was also present
                    existing["has_mean_reversion_signal"] = True
            else:
                by_symbol[sym] = d

        all_signals = list(by_symbol.values())
        deduped_count = len(momentum_dicts) + len(mr_signals) - len(all_signals)
        logger.info(f"Signal merge: {len(momentum_dicts)} momentum + {len(mr_signals)} mean reversion = {len(all_signals)} total (removed {deduped_count} duplicates)")

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "count": len(all_signals),
            "signals": all_signals,
        }

        # PHASE 1+: Write to SQLite + JSON mirror
        try:
            db_save_signals(all_signals, run_id=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
            heartbeat("signal_engine", status="ok")
            export_json_mirrors()
            logger.info(f"Saved {len(all_signals)} signals to DB + web mirror")
        except Exception as e:
            logger.warning(f"DB write failed, falling back to JSON: {e}")
            # Fallback to legacy JSON write
            atomic_write_json(path, payload)
            logger.info(f"Saved {len(all_signals)} signals to {path} (fallback)")

        # Legacy mirror for safety (Phase 2: remove)
        web_signals_path = Path("/var/www/hedge-fund-website/signals.json")
        try:
            atomic_write_json(web_signals_path, payload)
        except Exception as e:
            logger.warning(f"Could not mirror signals to web root: {e}")
        return path

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_symbol(
        self,
        symbol: str,
        bars: Dict,
        regime_data: Dict[str, Dict],
        all_bars: Dict[str, Dict],
        enrichment: Optional[Dict[str, Dict]] = None,
    ) -> Optional[Signal]:
        closes = bars["closes"]
        volumes = bars["volumes"]
        highs = bars["highs"]
        lows = bars["lows"]
        if len(closes) < 20 or len(volumes) < 15:
            return None

        avg_volume = int(sum(volumes[-20:]) / 20)
        if avg_volume < self.min_avg_volume:
            return None

        price = closes[-1]
        if price <= 0:
            return None

        momentum_20d = self._roc(closes, 20)
        momentum_50d = self._roc(closes, 50)
        volatility_20d = self._volatility(closes, 20)
        atr14 = self._atr(closes, highs, lows, 14)
        rsi14 = self._rsi(closes, 14)
        spy_corr_20d = self._correlation(
            closes, all_bars.get("SPY", {}).get("closes", []), 20
        )

        momentum_score = self._momentum_score(momentum_20d, momentum_50d, spy_corr_20d)
        quality_score = self._quality_score(price, closes, volumes)
        risk_score = self._risk_score(volatility_20d, atr14, price, spy_corr_20d)
        regime_score = self._regime_score(closes, regime_data)

        total = (
            MOMENTUM_WEIGHT * momentum_score
            + QUALITY_WEIGHT * quality_score
            + RISK_WEIGHT * risk_score
            + REGIME_WEIGHT * regime_score
        )

        e = enrichment.get(symbol, {}) if enrichment else {}
        thesis, drivers = self._generate_thesis(
            symbol, price, closes, volumes, momentum_20d, momentum_50d,
            volatility_20d, atr14, rsi14, spy_corr_20d,
            momentum_score, quality_score, risk_score, regime_score,
            regime_data, enrichment,
        )

        sector = self._sector(symbol)

        # Pre-compute stock vs SPY relative strength for readiness
        spy_closes = all_bars.get("SPY", {}).get("closes", [])
        if len(closes) >= 21 and len(spy_closes) >= 21:
            stock_roc = (closes[-1] - closes[-21]) / closes[-21]
            spy_roc = (spy_closes[-1] - spy_closes[-21]) / spy_closes[-21]
            relative_strength_20d = stock_roc - spy_roc
        else:
            relative_strength_20d = 0.0

        # --- Compute readiness score (v2.1) --
        # Get intraday data for readiness computation
        _intraday = _intraday_cache.get(symbol, [])
        _snap = _snapshot_cache.get(symbol, {})
        _daily_vwap = _snap.get("daily_vwap")
        _prev_close = _snap.get("prev_close")

        _opts_iv = e.get("options", {}).get("avg_implied_vol")

        readiness = compute_readiness(
            symbol=symbol,
            total_score=total,
            rsi14=rsi14,
            closes=closes,
            volumes=volumes,
            price=price,
            sector=sector,
            all_bars=all_bars,
            intraday_bars=_intraday,
            daily_vwap=_daily_vwap,
            prev_close=_prev_close,
            options_implied_vol=_opts_iv,
        )

        # MACD histogram value for storage
        macd_hist = 0.0
        if len(closes) >= 26:
            ema12 = self._ema_val(closes[-26:], 12)
            ema26 = self._ema_val(closes[-26:], 26)
            macd_hist = round(ema12 - ema26, 4)

        # Volume ratio
        if len(volumes) >= 20:
            recent_vol = sum(volumes[-5:]) / 5
            avg_vol_20 = sum(volumes[-20:]) / 20
            vol_ratio = round(recent_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0, 2)
        else:
            vol_ratio = 1.0

        # Above EMA20
        ema20 = self._ema_val(closes[-20:], 20) if len(closes) >= 20 else price
        above_ema20 = price > ema20

        # Enrich with intraday data from snapshot cache
        snap = _snapshot_cache.get(symbol, {})
        intraday_bars = _intraday_cache.get(symbol, [])
        intraday_vwap = snap.get("daily_vwap")
        prev_close = snap.get("prev_close")
        intraday_vol_ratio = None
        if intraday_bars and len(intraday_bars) >= 2:
            recent_intraday_vol = sum(b.get("v", 0) for b in intraday_bars[-3:])
            avg_intraday_vol = sum(b.get("v", 0) for b in intraday_bars) / len(intraday_bars) if intraday_bars else 0
            if avg_intraday_vol > 0:
                intraday_vol_ratio = round(recent_intraday_vol / avg_intraday_vol, 2)

        return Signal(
            symbol=symbol,
            momentum_score=round(momentum_score, 2),
            quality_score=round(quality_score, 2),
            risk_score=round(risk_score, 2),
            regime_score=round(regime_score, 2),
            total_score=round(total, 2),
            rank=0,
            price=round(price, 2),
            atr14=round(atr14, 2),
            rsi14=round(rsi14, 2),
            momentum_20d=round(momentum_20d, 4),
            momentum_50d=round(momentum_50d, 4),
            volatility_20d=round(volatility_20d, 4),
            avg_volume=avg_volume,
            spy_corr_20d=round(spy_corr_20d, 3),
            ai_score=None,
            sector=sector,
            company=COMPANY_NAMES.get(symbol, symbol),
            thesis=thesis,
            drivers=drivers,
            earnings=e.get("earnings"),
            recommendation=e.get("recommendation"),
            news=e.get("news"),
            readiness_score=readiness.readiness_score,
            tier=readiness.tier,
            confirmations=readiness.confirmations,
            confirmation_count=compute_confirmation_count(readiness.confirmations),
            entry_eligible=readiness.entry_eligible,
            tier_reason=readiness.tier_reason,
            factor_breakdown=readiness.factor_breakdown,
            relative_strength_20d=round(relative_strength_20d, 4),
            macd_hist=macd_hist,
            volume_ratio=vol_ratio,
            above_ema20=above_ema20,
            sector_strong=readiness.confirmations.get("sector_strong", False),
            intraday_vwap=round(intraday_vwap, 2) if intraday_vwap else None,
            intraday_vol_ratio=intraday_vol_ratio,
            daily_vwap=round(snap.get("daily_vwap", 0) or 0, 2) if snap.get("daily_vwap") else None,
            prev_close=round(prev_close, 2) if prev_close else None,
            options_implied_vol=e.get("options", {}),
            options_volume=e.get("options", {}).get("options_volume") if e.get("options") else None,
        )

    def _momentum_score(self, roc20: float, roc50: float, spy_corr: float) -> float:
        score = 50.0
        score += 25 * math.tanh(roc20 * 10)
        score += 15 * math.tanh(roc50 * 5)
        score -= 10 * abs(spy_corr)
        return max(0.0, min(100.0, score))

    def _quality_score(self, price: float, closes: List[float], volumes: List[float]) -> float:
        if len(closes) < 20 or len(volumes) < 15:
            return 50.0
        ema20 = sum(closes[-20:]) / 20
        ema50 = sum(closes[-50:]) / 50
        trend_score = 50 if price > ema20 > ema50 else 30 if price > ema50 else 10

        avg_vol = sum(volumes[-20:]) / 20
        recent_vol = sum(volumes[-5:]) / 5
        liquidity_score = 30 if recent_vol >= avg_vol else 20

        penalty = 0
        if price < ema50 * 0.90:
            penalty = 15

        return max(0.0, min(100.0, trend_score + liquidity_score - penalty))

    def _risk_score(self, vol: float, atr: float, price: float, spy_corr: float) -> float:
        if vol <= 0 or price <= 0:
            return 50.0
        vol_penalty = min(40, vol * 400)
        atr_penalty = min(20, (atr / price) * 400)
        corr_penalty = 10 * abs(spy_corr - 0.6)
        return max(0.0, min(100.0, 90 - vol_penalty - atr_penalty - corr_penalty))

    def _generate_thesis(
        self,
        symbol: str,
        price: float,
        closes: List[float],
        volumes: List[float],
        momentum_20d: float,
        momentum_50d: float,
        volatility_20d: float,
        atr14: float,
        rsi14: float,
        spy_corr_20d: float,
        momentum_score: float,
        quality_score: float,
        risk_score: float,
        regime_score: float,
        regime_data: Dict[str, Dict],
        enrichment: Optional[Dict[str, Dict]] = None,
    ) -> Tuple[str, List[str]]:
        """Build a human-readable, quantitative + qualitative thesis using enrichment data."""
        enrichment = enrichment or {}
        e = enrichment.get(symbol, {})
        sector = self._sector(symbol)

        ema20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else price
        ema50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else price
        atr_pct = (atr14 / price * 100) if price > 0 else 0.0
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
        week_52_high = e.get("metrics", {}).get("week_52_high")
        week_52_low = e.get("metrics", {}).get("week_52_low")
        high_52_pct = ((week_52_high - price) / price * 100) if week_52_high and price > 0 else None
        low_52_pct = ((price - week_52_low) / week_52_low * 100) if week_52_low and week_52_low > 0 else None

        # --- Drivers: short, factual bullets ---
        drivers = []
        drivers.append(f"Momentum (40%): 20d return {momentum_20d*100:.1f}%, 50d return {momentum_50d*100:.1f}%, score {momentum_score:.0f}/100")
        drivers.append(f"Quality (25%): price vs 20d/50d EMAs, volume support; score {quality_score:.0f}/100")
        drivers.append(f"Risk (20%): vol {volatility_20d*100:.1f}% annual, ATR {atr_pct:.1f}%, RSI {rsi14:.1f}; score {risk_score:.0f}/100")
        drivers.append(f"Macro (15%): 20d SPY correlation {spy_corr_20d:.2f}, regime score {regime_score:.0f}/100")
        if recent_vol > avg_vol * 1.2:
            drivers.append(f"Volume: recent avg {recent_vol/1e6:.2f}M vs 20d avg {avg_vol/1e6:.2f}M (elevated)")
        else:
            drivers.append(f"Volume: recent avg {recent_vol/1e6:.2f}M vs 20d avg {avg_vol/1e6:.2f}M")

        # Earnings driver
        earnings = e.get("earnings")
        if earnings:
            spct = earnings.get("surprise_pct", 0)
            drivers.append(f"Latest earnings Q{earnings.get('quarter')} {earnings.get('year')}: {earnings.get('direction')} by {abs(spct):.1f}% (${earnings.get('actual', 0):.2f} vs ${earnings.get('estimate', 0):.2f} est)")

        # Analyst driver
        rec = e.get("recommendation")
        if rec:
            drivers.append(f"Analysts: {rec.get('bullish_pct', 0):.0f}% bullish ({rec.get('buy', 0)} buy, {rec.get('hold', 0)} hold, {rec.get('sell', 0)} sell)")

        # News driver
        news = e.get("news")
        if news and news.get("sample_headline"):
            drivers.append(f"News sentiment: {news.get('sentiment_label')} ({news.get('sentiment_score')}/100)")

        # --- Qualitative story construction ---
        trend_word = "neutral"
        if price > ema20 > ema50:
            trend_word = "in an uptrend"
        elif price < ema20 < ema50:
            trend_word = "in a downtrend"
        elif price > ema50:
            trend_word = "in recovery"
        else:
            trend_word = "in a weak setup"

        momentum_word = "mixed"
        if momentum_20d > 0.20:
            momentum_word = "very strong"
        elif momentum_20d > 0.08:
            momentum_word = "strong"
        elif momentum_20d > 0.0:
            momentum_word = "modest"
        elif momentum_20d > -0.08:
            momentum_word = "soft"
        else:
            momentum_word = "negative"

        # Market regime context
        spy = regime_data.get("SPY", {}).get("closes", [])
        qqq = regime_data.get("QQQ", {}).get("closes", [])
        vixy = regime_data.get("VIXY", {}).get("closes", [])
        spy_roc20 = (spy[-1] - spy[-20]) / spy[-20] if len(spy) >= 20 else 0.0
        qqq_roc20 = (qqq[-1] - qqq[-20]) / qqq[-20] if len(qqq) >= 20 else 0.0
        vixy_roc5 = (vixy[-1] - vixy[-5]) / vixy[-5] if len(vixy) >= 5 else 0.0

        if spy_roc20 > 0.03 and qqq_roc20 > 0.03 and vixy_roc5 < 0.05:
            macro_phrase = "in a favorable risk-on macro backdrop"
        elif spy_roc20 < -0.03 or qqq_roc20 < -0.05 or vixy_roc5 > 0.10:
            macro_phrase = "against a cautious macro backdrop"
        else:
            macro_phrase = "in a neutral macro backdrop"

        # Sector-specific narrative templates
        sector_narratives = {
            "Semiconductors": "semiconductor equipment / chip-cycle play",
            "AI/Growth": "AI / high-growth software play",
            "Tech Giants": "mega-cap tech compounder",
            "Fintech": "fintech / digital payments play",
            "Consumer/Platform": "consumer / platform growth play",
            "Cloud/Data": "cloud / data infrastructure play",
            "EV/Mobility": "EV / mobility transition play",
            "Retail/Lifestyle": "consumer retail / lifestyle brand",
        }
        sector_phrase = sector_narratives.get(sector, f"{sector.lower()} play")

        # Build qualitative evidence sentence
        evidence_parts = []
        if earnings:
            spct = earnings.get("surprise_pct", 0)
            direction = earnings.get("direction", "beat")
            evidence_parts.append(f"latest earnings {direction} by {abs(spct):.1f}%")
        if rec and rec.get("bullish_pct", 0) >= 60:
            evidence_parts.append(f"{rec.get('bullish_pct', 0):.0f}% of analysts are bullish")
        if news and news.get("sentiment_label") in ("bullish", "bearish"):
            evidence_parts.append(f"recent news reads {news.get('sentiment_label')}")
        if high_52_pct is not None and high_52_pct < 5:
            evidence_parts.append("trading near 52-week highs")
        elif low_52_pct is not None and low_52_pct < 15:
            evidence_parts.append("still close to 52-week lows")

        evidence_sentence = ""
        if evidence_parts:
            evidence_sentence = "Evidence: " + ", ".join(evidence_parts) + "."

        # Risk phrasing
        if risk_score < 30:
            risk_sentence = f"Risk is elevated ({volatility_20d*100:.1f}% vol, {atr_pct:.1f}% ATR); position is sized with volatility-aware stops."
        elif risk_score > 70:
            risk_sentence = f"Risk looks favorable ({volatility_20d*100:.1f}% vol, {atr_pct:.1f}% ATR)."
        else:
            risk_sentence = f"Risk is manageable ({volatility_20d*100:.1f}% vol, {atr_pct:.1f}% ATR)."

        # RSI qualifier
        rsi_phrase = ""
        if rsi14 < 35:
            rsi_phrase = " RSI near oversold adds short-term bounce potential."
        elif rsi14 > 75:
            rsi_phrase = " RSI is stretched; watch for a pullback."

        thesis = (
            f"{symbol} is a {sector_phrase} with {momentum_word} 20-day momentum, scoring {momentum_score*0.4 + quality_score*0.25 + risk_score*0.2 + regime_score*0.15:.0f}/100 "
            f"on the quality-momentum model. The setup is {trend_word} {macro_phrase}. "
            f"{evidence_sentence} {risk_sentence}{rsi_phrase}"
        )

        return thesis, drivers

    def _regime_score(self, closes: List[float], regime_data: Dict[str, Dict]) -> float:
        spy = regime_data.get("SPY", {}).get("closes", [])
        qqq = regime_data.get("QQQ", {}).get("closes", [])
        vixy = regime_data.get("VIXY", {}).get("closes", [])
        shy = regime_data.get("SHY", {}).get("closes", [])
        tlt = regime_data.get("TLT", {}).get("closes", [])
        lqd = regime_data.get("LQD", {}).get("closes", [])
        hyg = regime_data.get("HYG", {}).get("closes", [])

        score = 50.0

        # Equity trend (SPY/QQQ) — 32 points max
        if len(spy) >= 20:
            spy_roc20 = (spy[-1] - spy[-20]) / spy[-20]
            score += 20 * math.tanh(spy_roc20 * 8)
        if len(qqq) >= 20:
            qqq_roc20 = (qqq[-1] - qqq[-20]) / qqq[-20]
            score += 12 * math.tanh(qqq_roc20 * 8)

        # Volatility (VIXY) — 18 points max
        if len(vixy) >= 5:
            vixy_roc5 = (vixy[-1] - vixy[-5]) / vixy[-5]
            score -= 18 * math.tanh(vixy_roc5 * 5)

        # Yield curve proxy: SHY / TLT ratio (steepening = risk-on)
        if len(shy) >= 20 and len(tlt) >= 20:
            ratio_now = shy[-1] / tlt[-1]
            ratio_prev = shy[-20] / tlt[-20]
            if ratio_now > ratio_prev:
                score += 5  # curve steepening / risk-on
            else:
                score -= 5  # flattening / risk-off

        # Credit spread proxy: LQD / HYG (investment grade vs high yield)
        if len(lqd) >= 20 and len(hyg) >= 20:
            ratio_now = lqd[-1] / hyg[-1]
            ratio_prev = lqd[-20] / hyg[-20]
            if ratio_now > ratio_prev:
                score += 5  # credit improving
            else:
                score -= 5  # credit worsening

        # Market breadth: SPY volume rising with price
        spy_vols = regime_data.get("SPY", {}).get("volumes", [])
        if len(spy_vols) >= 20 and len(spy) >= 20:
            recent_vol = sum(spy_vols[-5:]) / 5
            avg_vol = sum(spy_vols[-20:]) / 20
            if recent_vol > avg_vol * 1.1 and spy[-1] > spy[-20]:
                score += 5  # rising volume on rally = healthy breadth
            elif recent_vol < avg_vol * 0.9 and spy[-1] < spy[-20]:
                score -= 5  # falling volume on decline

        # Symbol vs 20d EMA
        if len(closes) >= 20:
            ema20 = sum(closes[-20:]) / 20
            if closes[-1] > ema20:
                score += 5
            else:
                score -= 5

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # Alpaca data fetching
    # ------------------------------------------------------------------

    def _load_alpaca_config(self) -> Dict:
        paths = [
            Path(__file__).parent / "alpaca_config.json",
            Path("/opt/stonk-ai/alpaca_config.json"),
            Path("/var/www/hedge-fund-website/alpaca_config.json"),
        ]
        for p in paths:
            if p.exists():
                try:
                    with open(p) as f:
                        return json.load(f)
                except Exception:
                    continue
        return {}

    def _load_enrichment(self) -> Dict[str, Dict]:
        """Load qualitative enrichment cache if available."""
        path = Path(__file__).parent / "signal_enrichment.json"
        if not path.exists():
            path = Path("/opt/stonk-ai/signal_enrichment.json")
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                data = json.load(f)
            return data.get("data", {})
        except Exception as e:
            logger.warning(f"Could not load enrichment: {e}")
            return {}

    def _fetch_options_enrichment(self, symbols: List[str]) -> Dict[str, Dict]:
        """Fetch options sentiment data (IV term structure / rank / skew) from Alpaca."""
        result = {}
        # Load pre-computed summaries from cron if available
        try:
            import json
            from pathlib import Path
            summaries_path = Path("/opt/stonk-ai/iv_summaries.json")
            if summaries_path.exists():
                with open(summaries_path) as f:
                    cached = json.load(f)
                for symbol in symbols:
                    if symbol in cached:
                        result[symbol] = cached[symbol]
        except Exception as e:
            logger.debug(f"Options summaries load error: {e}")

        # Fallback to live fetch for missing symbols (uses internal TTL cache)
        try:
            for symbol in symbols:
                if symbol in result:
                    continue
                summary = options_iv_analytics.iv_summary(symbol)
                if summary and summary.get("iv_30d") is not None:
                    result[symbol] = summary
        except Exception as e:
            logger.debug(f"Options enrichment error: {e}")
        return result

    def _fetch_bars(self, symbols: str, days: int) -> Dict[str, Dict]:
        """Fetch daily bars via Alpaca data hub. No more Yahoo/synthetic fallbacks."""
        symbol_list = symbols.split(",")
        return self._hub.get_daily_bars(symbol_list, days)

    def _fetch_alpaca_bars(self, symbols: str, days: int) -> Dict[str, Dict]:
        try:
            import requests
            end = datetime.now(timezone.utc) - timedelta(hours=1)
            start = end - timedelta(days=days + 7)
            url = f"{self.data_url}/v2/stocks/bars"
            headers = {
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
                "Accept": "application/json",
            }
            symbol_list = symbols.split(",")
            BATCH_SIZE = 8  # 8 symbols x ~127 bars = ~1016, fits in 1000 limit
            result = {}
            for i in range(0, len(symbol_list), BATCH_SIZE):
                batch = symbol_list[i:i+BATCH_SIZE]
                params = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "start": start.strftime("%Y-%m-%d"),
                    "end": end.strftime("%Y-%m-%d"),
                    "limit": 1000,
                    "feed": "sip",
                    "adjustment": "all",
                }
                resp = requests.get(url, params=params, headers=headers, timeout=30)
                if resp.status_code != 200:
                    logger.warning(f"Alpaca bars error {resp.status_code}: {resp.text[:200]}")
                    continue
                data = resp.json()
                for symbol, bars in data.get("bars", {}).items():
                    clean = [b for b in bars if all(b.get(k) is not None for k in ("c", "h", "l", "v"))]
                    if clean:
                        result[symbol] = {
                            "closes": [b["c"] for b in clean],
                            "highs": [b["h"] for b in clean],
                            "lows": [b["l"] for b in clean],
                            "volumes": [b["v"] for b in clean],
                        }
            return result
        except Exception as e:
            logger.warning(f"Failed to fetch Alpaca bars: {e}")
            return {}


    @staticmethod
    def _roc(series: List[float], window: int) -> float:
        if len(series) < window + 1:
            return 0.0
        return (series[-1] - series[-window - 1]) / series[-window - 1]

    @staticmethod
    def _volatility(series: List[float], window: int) -> float:
        if len(series) < window + 1:
            return 0.0
        log_returns = [
            math.log(series[i] / series[i - 1])
            for i in range(-window, 0)
            if series[i - 1] > 0
        ]
        if not log_returns:
            return 0.0
        mean = sum(log_returns) / len(log_returns)
        variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
        return math.sqrt(variance) * math.sqrt(252)

    @staticmethod
    def _rsi(series: List[float], period: int = 14) -> float:
        if len(series) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(series)):
            change = series[i] - series[i - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(closes: List[float], highs: List[float], lows: List[float], period: int = 14) -> float:
        if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
            return 0.0
        trs = []
        for i in range(-period, 0):
            idx = len(closes) + i
            if idx <= 0:
                continue
            prev_close = closes[idx - 1]
            tr1 = highs[idx] - lows[idx]
            tr2 = abs(highs[idx] - prev_close)
            tr3 = abs(lows[idx] - prev_close)
            trs.append(max(tr1, tr2, tr3))
        return sum(trs) / len(trs) if trs else 0.0

    @staticmethod
    def _correlation(a: List[float], b: List[float], window: int) -> float:
        if len(a) < window or len(b) < window:
            return 0.0
        a = a[-window:]
        b = b[-window:]
        n = window
        mean_a = sum(a) / n
        mean_b = sum(b) / n
        num = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
        den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
        den_b = math.sqrt(sum((x - mean_b) ** 2 for x in b))
        if den_a == 0 or den_b == 0:
            return 0.0
        return num / (den_a * den_b)

    @staticmethod
    def _ema_val(values: List[float], period: int) -> float:
        """Compute EMA for a list of values."""
        if not values:
            return 0.0
        if len(values) < period:
            return sum(values) / len(values)
        multiplier = 2.0 / (period + 1)
        ema = sum(values[:period]) / period
        for val in values[period:]:
            ema = (val - ema) * multiplier + ema
        return ema

    @staticmethod
    def _sector(symbol: str) -> str:
        sectors = {
            "AI/Growth": ["PLTR", "CRWD", "NET", "DDOG", "SNOW", "MDB", "ZS", "PATH", "PANW", "APP", "GTLB", "ELF", "DUOL", "ESTC", "CFLT", "S"],
            "Semiconductors": ["AMD", "NVDA", "AVGO", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON"],
            "Tech Giants": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "NOW", "TEAM", "VEEV", "DOCN"],
            "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY"],
            "Payments": ["PYPL", "FIS"],
            "Consumer/Platform": ["NFLX", "UBER", "DKNG", "SHOP", "ROKU", "TTD", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "CHWY", "ETSY"],
            "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
            "Retail/Lifestyle": ["LULU", "NKE", "COST", "WMT", "HD", "CROX", "DECK", "ELF"],
            "Cloud/Data": ["SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW"],
            "Healthcare": ["UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "VRTX", "BMY", "REGN", "GILD", "ISRG", "ZBH", "ILMN", "SGEN"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY"],
            "Industrials": ["GE", "CAT", "UNP", "HON", "UPS", "RTX", "LMT", "DE"],
            "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "V"],
            "Communications": ["DIS", "CMCSA", "TMUS", "CHTR", "WBD", "PARA"],
            "Tech Expansion": ["TXN", "IBM", "INTC", "CRM", "ORCL", "ADBE", "INTU", "FIS"],
        }
        seen = set()
        for sector, symbols in sectors.items():
            for s in symbols:
                if s == symbol:
                    return sector
                if s in seen:
                    continue
                seen.add(s)
        return "Other"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = SignalEngine()
    signals = engine.generate_signals()
    engine.save_signals(signals)
    for s in signals[:10]:
        print(
            f"#{s.rank:2d} {s.symbol:5s} readiness={s.readiness_score:.1f} tier={s.tier:7s} "
            f"score={s.total_score:.1f} conf={s.confirmation_count}/10 "
            f"entry={'YES' if s.entry_eligible else 'NO '}"
        )