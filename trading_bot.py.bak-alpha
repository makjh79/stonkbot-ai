#!/usr/bin/env python3
"""
STONK.AI Trading Bot v2.1
Systematic quality-momentum strategy with readiness-driven entry and thesis-based exits.

Design principles:
- Signal-driven: `signals.json` is the single source of truth for what to buy.
- Readiness-driven: entry_eligible (readiness >= 70 AND >= 2 confirmations) replaces hard score threshold.
- Thesis-based: each position has an entry thesis with defined exit triggers.
- Risk-first: position sizing, concentration limits, and drawdown brakes.
- Anti-fragile: cash buffers, daily budgets, hard stops, profit trims.
- Paper-safe: defaults to paper-only; live mode requires explicit config flag.

v2.1 changes:
  - Entry: uses entry_eligible instead of total_score >= 30
  - Ranked entry queue by readiness_score (highest first)
  - Position sizing scaled by readiness: 70-79=1.0x, 80-89=1.25x, 90+=1.5x
  - Thesis-based exits (additional to risk engine exits)
  - position_theses.json tracks entry thesis per position
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from signal_engine import SignalEngine
from risk_engine import RiskEngine, RiskConfig
from alpaca_data import get_data_hub
import dynamic_watchlist_manager
from intraday_confirm import should_execute_buy as check_intraday_buy
from regime_detector import get_regime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class TradingConfig:
    """Bot-level configuration."""

    # Safety: only set LIVE_MODE = True when you are ready to trade real money.
    LIVE_MODE: bool = True

    # If True, log intended trades but do not submit orders.
    DRY_RUN: bool = False

    # How often the main loop runs during market hours.
    CYCLE_INTERVAL_SECONDS: int = 300  # 5 minutes

    # How often signals are refreshed.
    SIGNAL_REFRESH_INTERVAL_SECONDS: int = 900  # 15 minutes

    # Path to Alpaca credentials.
    ALPACA_CONFIG_PATHS: List[str] = [
        str(Path(__file__).parent / "alpaca_config.json"),
        "/opt/stonk-ai/alpaca_config.json",
        "/var/www/hedge-fund-website/alpaca_config.json",
    ]

    # Files
    SIGNALS_FILE: Path = Path(__file__).parent / "signals.json"
    PORTFOLIO_DATA_FILE: Path = Path(__file__).parent / "portfolio_data.json"
    WEB_PORTFOLIO_FILE: Path = Path("/var/www/hedge-fund-website/portfolio_data.json")
    TRADES_LOG_FILE: Path = Path(__file__).parent / "TRADES_LOG.md"
    THESES_FILE: Path = Path(__file__).parent / "position_theses.json"

    # Initial capital for drawdown calculations
    INITIAL_PORTFOLIO_VALUE: float = 100_000.0

    # --- Regime detection state (updated each cycle) ---
    # RISK_ON:  8% max / 5% cash  / NOW entries
    # RISK_OFF: 4% max / 15% cash / STRONG_NOW entries only
    # CRISIS:   4% max / 30% cash / no new entries


def load_alpaca_config() -> Dict:
    for path in TradingConfig.ALPACA_CONFIG_PATHS:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    cfg = json.load(f)
                logger.info(f"Loaded Alpaca config from {path}")
                return cfg
            except Exception as e:
                logger.warning(f"Could not load config at {path}: {e}")
    return {
        "api_key": os.getenv("ALPACA_API_KEY"),
        "api_secret": os.getenv("ALPACA_SECRET_KEY"),
        "base_url": os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        "data_url": os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets"),
    }


class AlpacaClient:
    def __init__(self, cfg: Dict):
        self.api_key = cfg.get("api_key") or cfg.get("APCA_API_KEY_ID")
        self.api_secret = cfg.get("api_secret") or cfg.get("APCA_API_SECRET_KEY")
        self.base_url = cfg.get("base_url", "https://paper-api.alpaca.markets").rstrip("/")
        self.data_url = cfg.get("data_url", "https://data.alpaca.markets").rstrip("/")

        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API key/secret missing")

        is_live_url = "paper-api" not in self.base_url
        if is_live_url and not TradingConfig.LIVE_MODE:
            raise RuntimeError(
                "Live Alpaca endpoint detected but LIVE_MODE is False. "
                "Set TradingConfig.LIVE_MODE = True only when ready for real money."
            )

        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Accept": "application/json",
        })

    def is_paper(self) -> bool:
        return "paper-api" in self.base_url

    def get_account(self) -> Dict:
        r = self.session.get(f"{self.base_url}/v2/account", timeout=15)
        r.raise_for_status()
        return r.json()

    def get_positions(self) -> List[Dict]:
        r = self.session.get(f"{self.base_url}/v2/positions", timeout=15)
        r.raise_for_status()
        return r.json()

    def is_market_open(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/v2/clock", timeout=10)
            if r.status_code == 200:
                return r.json().get("is_open", False)
        except Exception as e:
            logger.warning(f"Could not check market clock: {e}")
        return False

    def get_latest_quote(self, symbol: str) -> Optional[float]:
        """Fetch latest bid/ask midpoint for limit orders."""
        try:
            r = self.session.get(
                f"{self.data_url}/v2/stocks/quotes/latest",
                params={"symbols": symbol, "feed": "sip"},
                timeout=15,
            )
            r.raise_for_status()
            quote = r.json().get("quotes", {}).get(symbol, {})
            bid = quote.get("bp") or 0
            ask = quote.get("ap") or 0
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            return quote.get("p") or quote.get("ap") or quote.get("bp")
        except Exception as e:
            logger.warning(f"Could not get quote for {symbol}: {e}")
            return None

    def get_latest_quote_full(self, symbol: str) -> Optional[Dict]:
        """Fetch latest bid/ask separately for tier-aware execution."""
        try:
            r = self.session.get(
                f"{self.data_url}/v2/stocks/quotes/latest",
                params={"symbols": symbol, "feed": "sip"},
                timeout=15,
            )
            r.raise_for_status()
            quote = r.json().get("quotes", {}).get(symbol, {})
            bid = quote.get("bp") or 0
            ask = quote.get("ap") or 0
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else (quote.get("p") or 0)
            return {"bid": bid, "ask": ask, "mid": mid}
        except Exception as e:
            logger.warning(f"Could not get full quote for {symbol}: {e}")
            return None

    def check_order_filled(self, order_id: str) -> bool:
        """Check if a limit order has been filled."""
        try:
            r = self.session.get(f"{self.base_url}/v2/orders/{order_id}", timeout=10)
            r.raise_for_status()
            return r.json().get("status") == "filled"
        except Exception as e:
            logger.warning(f"Could not check order {order_id}: {e}")
            return True  # assume filled if we cannot check

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            r = self.session.delete(f"{self.base_url}/v2/orders/{order_id}", timeout=10)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Could not cancel order {order_id}: {e}")
            return False

    def submit_market_order(self, symbol: str, qty: int, side: str, dry_run: bool = False) -> Optional[str]:
        """Submit a market order directly."""
        if dry_run:
            logger.info(f"DRY RUN MARKET {side.upper()} {qty} {symbol}")
            return "dry-run"
        if qty <= 0:
            return None
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side.lower(),
            "type": "market",
            "time_in_force": "day",
        }
        try:
            r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=15)
            r.raise_for_status()
            return r.json().get("id", "unknown")
        except Exception as e:
            logger.error(f"Failed to submit market {side} order for {symbol}: {e}")
            return None

    def get_asset(self, symbol: str) -> Optional[Dict]:
        """Get asset info from Alpaca. Returns None if not tradable."""
        try:
            r = self.session.get(f"{self.base_url}/v2/assets/{symbol}", timeout=10)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def is_tradable(self, symbol: str) -> bool:
        """Check if a symbol is tradable on Alpaca. Cached."""
        if not hasattr(self, '_tradable_cache'):
            self._tradable_cache: Dict[str, bool] = {}
        if symbol in self._tradable_cache:
            return self._tradable_cache[symbol]
        asset = self.get_asset(symbol)
        tradable = asset is not None and asset.get('status') == 'active' and asset.get('tradable', False)
        self._tradable_cache[symbol] = tradable
        if not tradable:
            logger.warning(f"{symbol} is not tradable on Alpaca, will skip")
        return tradable

    def submit_order(self, symbol: str, qty: int, side: str, dry_run: bool = False,
                     use_limit: bool = True, twap_threshold: int = 100) -> Optional[str]:
        if dry_run:
            logger.info(f"DRY RUN {side.upper()} {qty} {symbol}")
            return "dry-run"
        if qty <= 0:
            return None

        side_lower = side.lower()
        order_ids = []

        # TWAP split for large orders
        if qty > twap_threshold:
            chunks = self._twap_chunks(qty, twap_threshold)
            logger.info(f"TWAP: splitting {side} {symbol} into {len(chunks)} chunks of ~{twap_threshold}")
        else:
            chunks = [qty]

        for chunk in chunks:
            payload = self._build_order_payload(symbol, chunk, side_lower, use_limit=use_limit)
            if payload is None:
                continue
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=15)
                r.raise_for_status()
                order_ids.append(r.json().get("id", "unknown"))
            except Exception as e:
                logger.error(f"Failed to submit {side} order for {symbol}: {e}")
                return None
            # Brief pause between TWAP chunks
            if len(chunks) > 1 and chunk != chunks[-1]:
                import time as _time
                _time.sleep(1)

        return order_ids[0] if order_ids else None

    def _twap_chunks(self, qty: int, threshold: int) -> list:
        """Split a large order into roughly equal chunks."""
        import math as _math
        n = _math.ceil(qty / threshold)
        base = qty // n
        remainder = qty % n
        return [base + 1] * remainder + [base] * (n - remainder)

    def _build_order_payload(self, symbol: str, qty: int, side: str, use_limit: bool = True) -> Optional[dict]:
        """Build order payload — limit at midpoint or market fallback."""
        if not use_limit:
            return {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            }
        midpoint = self.get_latest_quote(symbol)
        if midpoint is None or midpoint <= 0:
            return {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            }
        limit_price = round(midpoint, 2)
        return {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(limit_price),
        }

    def submit_tiered_order(self, symbol: str, qty: int, side: str, tier: str = "NOW",
                            dry_run: bool = False, twap_threshold: int = 100) -> Optional[str]:
        """Submit order with tier-aware execution strategy.

        STRONG_NOW: Aggressive — cross the spread, marketable limit at ask.
        NOW: Passive — midpoint limit with 5-second fill timeout, then market.
        """
        if dry_run:
            logger.info(f"DRY RUN {side.upper()} {qty} {symbol} (tier={tier})")
            return "dry-run"
        if qty <= 0:
            return None

        side_lower = side.lower()
        order_ids = []

        # TWAP split for large orders
        if qty > twap_threshold:
            chunks = self._twap_chunks(qty, twap_threshold)
            logger.info(f"TWAP: splitting {side} {symbol} into {len(chunks)} chunks of ~{twap_threshold}")
        else:
            chunks = [qty]

        for chunk in chunks:
            order_id = self._submit_tiered_single(symbol, chunk, side_lower, tier)
            if order_id:
                order_ids.append(order_id)
            # Brief pause between TWAP chunks
            if len(chunks) > 1 and chunk != chunks[-1]:
                import time as _time
                _time.sleep(1)

        return order_ids[0] if order_ids else None

    def _submit_tiered_single(self, symbol: str, qty: int, side: str, tier: str) -> Optional[str]:
        """Submit a single chunk with tier-aware execution."""
        quote = self.get_latest_quote_full(symbol)

        if quote is None or quote.get("mid", 0) <= 0:
            # No quote available — fall back to market order
            logger.info(f"No quote for {symbol}, submitting market order")
            payload = {
                "symbol": symbol, "qty": str(qty), "side": side,
                "type": "market", "time_in_force": "day",
            }
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=15)
                r.raise_for_status()
                return r.json().get("id", "unknown")
            except Exception as e:
                logger.error(f"Failed to submit market {side} for {symbol}: {e}")
                return None

        ask = quote.get("ask", 0)
        bid = quote.get("bid", 0)
        mid = quote.get("mid", 0)

        if tier == "STRONG_NOW":
            # Aggressive: marketable limit at ask (cross the spread)
            if ask > 0:
                limit_price = round(ask, 2)
                payload = {
                    "symbol": symbol, "qty": str(qty), "side": side,
                    "type": "limit", "time_in_force": "day",
                    "limit_price": str(limit_price),
                }
                try:
                    r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=15)
                    r.raise_for_status()
                    order_id = r.json().get("id", "unknown")
                    logger.info(f"Filled at ask (aggressive): {symbol} {side} {qty} @ ${limit_price:.2f}")
                    return order_id
                except Exception as e:
                    logger.error(f"Failed aggressive limit {side} for {symbol}: {e}")
                    return None
            else:
                # No ask available — market order
                return self.submit_market_order(symbol, qty, side)
        else:
            # NOW (passive): midpoint limit with 5-second fill timeout
            limit_price = round(mid, 2)
            payload = {
                "symbol": symbol, "qty": str(qty), "side": side,
                "type": "limit", "time_in_force": "day",
                "limit_price": str(limit_price),
            }
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=15)
                r.raise_for_status()
                order_id = r.json().get("id", "unknown")
            except Exception as e:
                logger.error(f"Failed passive limit {side} for {symbol}: {e}")
                return None

            # Wait 5 seconds for fill
            import time as _time
            _time.sleep(5)

            # Check if filled
            if self.check_order_filled(order_id):
                logger.info(f"Filled at midpoint (passive): {symbol} {side} {qty} @ ${limit_price:.2f}")
                return order_id

            # Not filled — cancel and escalate to marketable limit at ask + $0.01
            logger.info(f"EXECUTION: {symbol} midpoint limit not filled in 5s, escalating to marketable limit")
            if self.cancel_order(order_id):
                # Re-fetch quote to get current ask
                fresh_quote = self.get_latest_quote_full(symbol)
                fresh_ask = fresh_quote.get("ask", 0) if fresh_quote else 0
                if fresh_ask > 0:
                    marketable_limit = round(fresh_ask + 0.01, 2)
                    ml_payload = {
                        "symbol": symbol, "qty": str(qty), "side": side,
                        "type": "limit", "time_in_force": "day",
                        "limit_price": str(marketable_limit),
                    }
                    try:
                        r = self.session.post(f"{self.base_url}/v2/orders", json=ml_payload, timeout=15)
                        r.raise_for_status()
                        ml_order_id = r.json().get("id", "unknown")
                        logger.info(f"Filled at marketable limit (escalated): {symbol} {side} {qty} @ ${marketable_limit:.2f}")
                        return ml_order_id
                    except Exception as e:
                        logger.error(f"EXECUTION: {symbol} marketable limit escalation failed: {e}")
                        # Final fallback to market
                        market_order_id = self.submit_market_order(symbol, qty, side)
                        if market_order_id:
                            logger.info(f"Fallback to market (escalated): {symbol} {side} {qty}")
                            return market_order_id
                        return None
                else:
                    # No ask available — fall back to market
                    market_order_id = self.submit_market_order(symbol, qty, side)
                    if market_order_id:
                        logger.info(f"No ask, filled at market (escalated): {symbol} {side} {qty}")
                        return market_order_id
                    logger.error(f"EXECUTION: {symbol} market fallback failed")
                    return None
            else:
                # Cancel failed — maybe it filled in the meantime
                if self.check_order_filled(order_id):
                    logger.info(f"Filled at midpoint (passive, late): {symbol} {side} {qty} @ ${limit_price:.2f}")
                    return order_id
                logger.error(f"EXECUTION: {symbol} could not cancel limit order {order_id}")
                return order_id  # return the limit order ID, it might still fill


class PortfolioDataStore:
    def __init__(self, bot: "STONKAIBot"):
        self.bot = bot

    def fetch(self) -> Optional[Dict]:
        try:
            account = self.bot.alpaca.get_account()
            positions = self.bot.alpaca.get_positions()

            pv = float(account.get("portfolio_value", 0))
            cash = float(account.get("cash", 0))
            equity = float(account.get("equity", 0))

            positions_data = []
            for p in positions:
                symbol = p.get("symbol", "")
                qty = int(float(p.get("qty", 0)))
                avg_entry = float(p.get("avg_entry_price", 0))
                current = float(p.get("current_price", 0))
                mv = float(p.get("market_value", 0))
                cb = float(p.get("cost_basis", 0))
                upl = float(p.get("unrealized_pl", 0))
                uplpc = float(p.get("unrealized_plpc", 0)) * 100

                sector = SignalEngine._sector(symbol)

                positions_data.append({
                    "symbol": symbol,
                    "qty": qty,
                    "avg_entry": avg_entry,
                    "current": current,
                    "market_value": mv,
                    "cost_basis": cb,
                    "unrealized_pl": upl,
                    "unrealized_plpc": uplpc,
                    "sector": sector,
                })

            # Enrich positions with real-time snapshot data from Alpaca hub
            # This enables VWAP stops, intraday vol, and prev_close in the risk engine
            try:
                _hub = get_data_hub()
                _symbols = [p.get("symbol", "") for p in positions]
                _snaps = _hub.get_snapshots(_symbols)
                for pos_dict in positions_data:
                    _sym = pos_dict["symbol"]
                    _snap = _snaps.get(_sym, {})
                    if _snap:
                        pos_dict["daily_vwap"] = _snap.get("daily_vwap")
                        pos_dict["prev_close"] = _snap.get("prev_close")
                        pos_dict["intraday_vwap"] = _snap.get("minute_vwap")
                        pos_dict["daily_volume"] = _snap.get("daily_volume")
                        pos_dict["minute_volume"] = _snap.get("minute_volume")
                        # Use snapshot price if available (more accurate than position current)
                        _snap_price = _snap.get("price")
                        if _snap_price and _snap_price > 0:
                            pos_dict["current"] = _snap_price
                            pos_dict["market_value"] = _snap_price * pos_dict["qty"]
            except Exception as _e:
                logger.debug(f"Snapshot enrichment failed: {_e}")

            total_pl = sum(p["unrealized_pl"] for p in positions_data)
            total_cost = sum(p["cost_basis"] for p in positions_data)
            total_pl_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0

            portfolio_data = {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "status": "live",
                "account": {
                    "portfolio_value": pv,
                    "cash": cash,
                    "equity": equity,
                    "buying_power": float(account.get("buying_power", cash)),
                },
                "positions": positions_data,
                "total_pl": total_pl,
                "total_pl_pct": total_pl_pct,
            }

            self._save(portfolio_data)
            self.bot.risk_engine.record_high_water(pv)
            return portfolio_data

        except Exception as e:
            logger.error(f"Failed to fetch portfolio data: {e}")
            return None

    def _save(self, data: Dict):
        try:
            with open(TradingConfig.PORTFOLIO_DATA_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save portfolio data: {e}")

        try:
            TradingConfig.WEB_PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(TradingConfig.WEB_PORTFOLIO_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not write web portfolio file: {e}")


class ThesisManager:
    """Manages entry theses for positions and thesis-based exits."""

    def __init__(self, theses_file: Path):
        self.theses_file = theses_file
        self.theses: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        if self.theses_file.exists():
            try:
                with open(self.theses_file) as f:
                    self.theses = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load theses: {e}")
                self.theses = {}

    def _save(self):
        try:
            with open(self.theses_file, "w") as f:
                json.dump(self.theses, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save theses: {e}")

    def add_thesis(
        self,
        symbol: str,
        entry_price: float,
        readiness_score: float,
        thesis: str,
        confirmations: Dict,
    ):
        """Record entry thesis for a new position."""
        self.theses[symbol] = {
            "entry_date": date.today().isoformat(),
            "entry_price": round(entry_price, 2),
            "entry_readiness": readiness_score,
            "thesis": thesis,
            "confirmations": confirmations,
            "exit_triggers": {
                "thesis_broken": "price falls below 20d EMA",
                "momentum_loss": "MACD histogram turns negative for 2+ days",
                "sector_reversal": "sector momentum turns negative",
            },
        }
        self._save()

    def remove_thesis(self, symbol: str):
        """Remove thesis when position is closed."""
        self.theses.pop(symbol, None)
        self._save()

    def check_thesis_exits(self, portfolio_data: Dict, signals: List[Dict]) -> List[Dict]:
        """Check if any thesis exit triggers are met. Returns sell trades."""
        trades = []
        if not self.theses or not signals:
            return trades

        signal_map = {s["symbol"]: s for s in signals}
        position_map = {p["symbol"]: p for p in portfolio_data.get("positions", [])}

        for symbol, thesis_data in list(self.theses.items()):
            if symbol not in position_map:
                # Position already closed; clean up
                self.theses.pop(symbol, None)
                continue

            pos = position_map[symbol]
            current_price = pos.get("current", 0)
            qty = pos.get("qty", 0)
            if current_price <= 0 or qty <= 0:
                continue

            sig = signal_map.get(symbol, {})
            exit_triggers = thesis_data.get("exit_triggers", {})

            # 1. Thesis broken: price below 20d EMA
            above_ema = sig.get("above_ema20", True)
            if not above_ema:
                # Check if it's been below for a cycle (avoid flash crashes)
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": f"Thesis exit: {exit_triggers.get('thesis_broken', 'price below 20d EMA')}",
                })
                logger.info(f"THESIS EXIT: {symbol} — price below 20d EMA")
                continue

            # 2. Momentum loss: MACD histogram negative
            macd_hist = sig.get("macd_hist", 0)
            if macd_hist < 0:
                # Check 2-day confirmation via confirmations dict
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": f"Thesis exit: {exit_triggers.get('momentum_loss', 'MACD histogram negative')}",
                })
                logger.info(f"THESIS EXIT: {symbol} — MACD histogram negative")
                continue

            # 3. Sector reversal: sector no longer strong
            sector_strong = sig.get("sector_strong", False)
            confirmations = sig.get("confirmations", {})
            rsi_signal = confirmations.get("rsi_signal", "neutral")
            if not sector_strong and rsi_signal == "overbought":
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": f"Thesis exit: {exit_triggers.get('sector_reversal', 'sector momentum turned negative')}",
                })
                logger.info(f"THESIS EXIT: {symbol} — sector reversal + RSI overbought")
                continue

        self._save()
        return trades


class STONKAIBot:
    def __init__(self):
        self.cfg = load_alpaca_config()
        self.alpaca = AlpacaClient(self.cfg)
        self.risk_engine = RiskEngine(
            config=RiskConfig(),
            state_file=Path(__file__).parent / "risk_state.json",
            initial_portfolio_value=TradingConfig.INITIAL_PORTFOLIO_VALUE,
        )
        self.signal_engine = SignalEngine(
            universe=None,
            api_key=self.cfg.get("api_key"),
            api_secret=self.cfg.get("api_secret"),
            data_url=self.cfg.get("data_url", "https://data.alpaca.markets"),
        )
        self.data_store = PortfolioDataStore(self)
        self.thesis_manager = ThesisManager(TradingConfig.THESES_FILE)
        self._last_signal_refresh: Optional[float] = None
        self._signals: List[Dict] = []
        self._dry_run = TradingConfig.DRY_RUN or (not self.alpaca.is_paper() and not TradingConfig.LIVE_MODE)
        self._failed_buy_symbols: set = set()  # symbols that failed to buy (e.g. not tradable)

        # Regime detection state
        self._regime: str = "RISK_ON"
        self._regime_params: Dict = {"max_position_pct": 8, "cash_floor_pct": 10, "min_tier_for_entry": "NOW"}

        if self._dry_run:
            logger.info("Bot is in DRY RUN mode — trades will be logged but not submitted.")
        elif self.alpaca.is_paper():
            logger.info("Bot is connected to Alpaca PAPER trading — fake money orders will be submitted.")
        else:
            logger.warning("Bot is connected to Alpaca LIVE trading — real money orders will be submitted.")

    # ------------------------------------------------------------------
    # Signal lifecycle
    # ------------------------------------------------------------------

    def refresh_signals(self):
        try:
            signals = self.signal_engine.generate_signals(lookback_days=120)
            self.signal_engine.save_signals(signals, TradingConfig.SIGNALS_FILE)
            # Load from file to include mean reversion signals merged during save
            with open(TradingConfig.SIGNALS_FILE) as f:
                self._signals = json.load(f).get("signals", [])
            self._last_signal_refresh = time.time()
            # Log strategy breakdown
            mr_count = sum(1 for s in self._signals if s.get("strategy_type") == "mean_reversion")
            mom_count = len(self._signals) - mr_count
            logger.info(f"Refreshed signals: {len(self._signals)} candidates ({mom_count} momentum, {mr_count} mean reversion)")
            try:
                dynamic_watchlist_manager.update_watchlist()
            except Exception as e:
                logger.warning(f"Watchlist sync failed: {e}")
        except Exception as e:
            logger.error(f"Failed to refresh signals: {e}")
            try:
                with open(TradingConfig.SIGNALS_FILE) as f:
                    self._signals = json.load(f).get("signals", [])
                logger.info(f"Loaded cached signals: {len(self._signals)} candidates")
            except Exception:
                self._signals = []

    def maybe_refresh_signals(self):
        now = time.time()
        if (self._last_signal_refresh is None or
                now - self._last_signal_refresh > TradingConfig.SIGNAL_REFRESH_INTERVAL_SECONDS):
            self.refresh_signals()
        # Filter out symbols known to be untradable or failed buys
        if self._failed_buy_symbols:
            self._signals = [
                s for s in self._signals
                if s.get("symbol") not in self._failed_buy_symbols
            ]

    # ------------------------------------------------------------------
    # Readiness-based position sizing multiplier
    # ------------------------------------------------------------------

    @staticmethod
    def _readiness_sizing_multiplier(readiness: float) -> float:
        """Scale position size by readiness conviction.
        Aligned with backtest: 1.5x for STRONG_NOW (>=80), 1.0x for NOW (72-79)."""
        if readiness >= 80:
            return 1.5  # STRONG_NOW
        if readiness >= 72:
            return 1.0  # NOW
        return 0.65  # below entry threshold

    @staticmethod
    def _strategy_sizing_cap(strategy_type: str) -> float:
        """Cap position size for non-momentum strategies."""
        if strategy_type == "mean_reversion":
            return 0.75  # lower conviction, cap at 75% of normal size
        return 1.0  # momentum: no cap

    @staticmethod
    def _tier_max_position_pct(tier: str, base_max_pct: float) -> float:
        """Return the max position % cap for a given signal tier.

        STRONG_NOW gets a higher cap (12%) so that the 1.5x sizing multiplier
        produces meaningfully larger positions than NOW (8% cap).
        Without this, STRONG_NOW entries just hit the 8% cap and become
        identical to NOW entries — making the tier distinction cosmetic.
        """
        if tier == "STRONG_NOW":
            return max(0.12, base_max_pct)  # 12% cap for high-conviction
        return base_max_pct  # 8% (or regime-adjusted) for NOW and below

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self):
        if not self.alpaca.is_market_open():
            logger.debug("Market closed; skipping cycle")
            return

        # Regime detection: check market conditions each cycle
        try:
            regime_result = get_regime()
            self._regime = regime_result["regime"]
            self._regime_params = regime_result["params"]
            # Apply regime overrides to risk engine config
            self.risk_engine.config.max_single_position_pct = self._regime_params["max_position_pct"] / 100
            self.risk_engine.config.min_cash_pct = self._regime_params["cash_floor_pct"] / 100
            # Log regime state
            _regime_emoji = {"RISK_ON": "\U0001F4C8", "RISK_OFF": "\u26A0\uFE0F", "CRISIS": "\U0001F6D1"}
            _regime_desc = {"RISK_ON": "full size", "RISK_OFF": "defensive", "CRISIS": "no new entries"}
            logger.info(f"{_regime_emoji.get(self._regime, '?')} Regime: {self._regime} \u2014 {_regime_desc.get(self._regime, '')}")
            if regime_result.get("triggers"):
                logger.info(f"  Regime triggers: {'; '.join(regime_result['triggers'])}")
        except Exception as e:
            logger.warning(f"Regime detection failed, defaulting to RISK_ON: {e}")
            self._regime = "RISK_ON"
            self._regime_params = {"max_position_pct": 8, "cash_floor_pct": 10, "min_tier_for_entry": "NOW"}

        portfolio_data = self.data_store.fetch()
        if not portfolio_data:
            return

        self.maybe_refresh_signals()
        if not self._signals:
            logger.warning("No signals available; skipping cycle")
            return

        pv = portfolio_data["account"]["portfolio_value"]
        cash = portfolio_data["account"]["cash"]
        logger.info(f"Portfolio: ${pv:,.2f} | Cash: ${cash:,.2f} | Positions: {len(portfolio_data['positions'])}")

        # 1. Handle exits: risk engine + thesis exits
        exit_trades = []
        exit_trades.extend(self.risk_engine.check_exits(portfolio_data))
        exit_trades.extend(self.risk_engine.check_concentration(portfolio_data))
        exit_trades.extend(self.thesis_manager.check_thesis_exits(portfolio_data, self._signals))

        for trade in exit_trades:
            self._execute_sell(trade, portfolio_data)
            # Clean up thesis when position is fully sold
            if trade.get("qty", 0) >= portfolio_data.get("positions", [{}])[0].get("qty", 0):
                self.thesis_manager.remove_thesis(trade["symbol"])

        # Re-fetch after sells
        if exit_trades:
            portfolio_data = self.data_store.fetch()
            if not portfolio_data:
                return

        # 1a. Minimum holding period: skip exit logic for positions held < 20 days
        _today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for sym in list(self._positions.keys()):
            pos = self._positions[sym]
            _entry_date = pos.get("entry_date", _today_str)
            if isinstance(_entry_date, str):
                try:
                    _days_held = (datetime.now(timezone.utc) - datetime.fromisoformat(_entry_date.replace("Z", "+00:00"))).days
                except Exception:
                    _days_held = 999  # If we can't parse, assume old enough to sell
            else:
                _days_held = 999
            pos["_days_held"] = _days_held

        # 1b. Readiness-based exit: sell positions that dropped below WATCH tier
        # Regime-aware minimum holding period:
        #   CRISIS    → no hold requirement, exit if readiness < 70
        #   RISK_OFF  → 10-day min hold (instead of 20)
        #   RISK_ON   → 20-day min hold (default)
        _low_readiness_symbols = set()
        _crisis_exit_symbols = set()
        for sig in self._signals:
            r_score = sig.get("readiness_score", 100)
            if r_score < 55:
                _low_readiness_symbols.add(sig["symbol"])
            if r_score < 70:
                _crisis_exit_symbols.add(sig["symbol"])

        # Determine min hold days based on regime
        if self._regime == "CRISIS":
            _min_hold_days = 0
        elif self._regime == "RISK_OFF":
            _min_hold_days = 10
        else:
            _min_hold_days = 20

        for sym in list(self._positions.keys()):
            pos = self._positions[sym]
            _days = pos.get("_days_held", 0)

            # CRISIS override: immediate exits for readiness < 70, regardless of hold period
            if self._regime == "CRISIS" and sym in _crisis_exit_symbols:
                logger.info(f"🚨 CRISIS exit: {sym} readiness < 70 (held {_days} days)")
                self._exit_position(sym, reason="crisis_readiness_below_70")
                continue

            # Standard readiness-based exit (respecting regime-aware min hold)
            if _days >= _min_hold_days and sym in _low_readiness_symbols:
                logger.info(f"🔄 Exit signal: {sym} readiness dropped below 55 (held {_days} days, min hold {_min_hold_days})")
                self._exit_position(sym, reason="readiness_below_55")

        # 1c. Flat exit: free dead money capital from positions going nowhere
        # If held >= 10 days AND price within ±3% of entry AND readiness < 72, exit
        if self._regime != "CRISIS":  # CRISIS already handles fast exits
            for sym in list(self._positions.keys()):
                pos = self._positions.get(sym, {})
                _days = pos.get("_days_held", 0)
                if _days < 10:
                    continue

                _entry = pos.get("avg_entry") or pos.get("cost_basis", 0)
                if isinstance(_entry, (int, float)) and _entry > 0:
                    # Get current price from portfolio data
                    _current_price = next(
                        (p.get("current_price") or (p.get("market_value", 0) / p.get("qty", 1)) for p in portfolio_data.get("positions", []) if p.get("symbol") == sym),
                        0
                    )
                    if _current_price > 0:
                        _move_pct = abs((_current_price - _entry) / _entry * 100)
                        if _move_pct <= 3.0:  # Within ±3% = flat
                            # Check readiness — if still strong, keep it
                            _sig = next((s for s in self._signals if s.get("symbol") == sym), None)
                            _readiness = _sig.get("readiness_score", 100) if _sig else 100
                            if _readiness < 72:  # Not strong enough to justify holding dead money
                                logger.info(f"💤 Flat exit: {sym} held {_days} days, moved only {_move_pct:.1f}%, readiness {_readiness:.0f}")
                                self._exit_position(sym, reason="flat_dead_money")
                                continue

        # 1d. Cash-raising: if cash is below the dynamic floor, trim weakest positions
        cash_raise_trades = self.risk_engine.check_cash_raise(portfolio_data, self._signals)
        for trade in cash_raise_trades:
            self._execute_sell(trade, portfolio_data)
            # Clean up thesis when position is fully sold
            pos_to_check = next((p for p in portfolio_data.get("positions", []) if p.get("symbol") == trade["symbol"]), {})
            if trade.get("qty", 0) >= pos_to_check.get("qty", 0):
                self.thesis_manager.remove_thesis(trade["symbol"])

        # Re-fetch after cash-raising sells
        if cash_raise_trades:
            portfolio_data = self.data_store.fetch()
            if not portfolio_data:
                return

        # 1c. Rotation: trim overweight low-readiness positions to free capital for high-readiness entries
        # Pre-filter: check which top signal symbols are actually tradable before rotating
        top_buy_candidates = [s for s in self._signals if s.get("entry_eligible", False) and s.get("readiness_score", 0) >= 72]
        for s in top_buy_candidates[:10]:
            sym = s.get("symbol")
            if sym not in self._failed_buy_symbols and not self.alpaca.is_tradable(sym):
                self._failed_buy_symbols.add(sym)
        # Now filter signals to exclude untradable symbols
        self._signals = [s for s in self._signals if s.get("symbol") not in self._failed_buy_symbols]
        rotation_trades = self.risk_engine.check_rotation(portfolio_data, self._signals, failed_buy_symbols=self._failed_buy_symbols)
        for trade in rotation_trades:
            self._execute_sell(trade, portfolio_data)
            pos_to_check = next((p for p in portfolio_data.get("positions", []) if p.get("symbol") == trade["symbol"]), {})
            if trade.get("qty", 0) >= pos_to_check.get("qty", 0):
                self.thesis_manager.remove_thesis(trade["symbol"])

        # Re-fetch after rotation sells
        if rotation_trades:
            portfolio_data = self.data_store.fetch()
            if not portfolio_data:
                return

        # 2a. CRISIS: halve all position sizes
        if self._regime == "CRISIS":
            crisis_trades = []
            for pos in portfolio_data.get("positions", []):
                sym = pos.get("symbol", "")
                qty = pos.get("qty", 0)
                if qty >= 2:
                    half_qty = qty // 2
                    crisis_trades.append({
                        "symbol": sym,
                        "qty": half_qty,
                        "action": "SELL",
                        "reason": "CRISIS regime: halving position size",
                    })
            for trade in crisis_trades:
                self._execute_sell(trade, portfolio_data)
                self.thesis_manager.remove_thesis(trade["symbol"])
            if crisis_trades:
                portfolio_data = self.data_store.fetch()
                if not portfolio_data:
                    return

        # 2. Decide if we should add new positions
        can_add, reason, _ = self.risk_engine.can_add_new_positions(portfolio_data)
        if not can_add:
            logger.info(f"New positions blocked: {reason}")
            return

        # 3. Build candidate buys from signals — now readiness-driven
        current_symbols = {p["symbol"] for p in portfolio_data.get("positions", [])}
        top_signals = self._signals[: self.risk_engine.config.top_signal_count]
        current_positions = {p["symbol"]: p for p in portfolio_data.get("positions", [])}
        signal_map = {s["symbol"]: s for s in top_signals}

        # 3a. Build ranked entry queue by readiness_score (highest first)
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
            _min_tier_rank = _tier_rank.get(_min_tier, 0)
            if _sig_tier < _min_tier_rank:
                logger.debug(f"Regime {_min_tier} gate: {symbol} tier {sig.get('tier')} insufficient")
                continue

            price = self.alpaca.get_latest_quote(symbol)
            if price is None or price <= 0:
                # Fallback: try hub snapshot
                try:
                    _hub = get_data_hub()
                    _snap = _hub.get_snapshot(symbol)
                    price = _snap.get("price") if _snap else None
                except Exception:
                    pass
            if price is None or price <= 0:
                logger.debug(f"No quote for {symbol}; skipping")
                continue

            # Intraday entry timing: check if we're buying at the top of a 15Min candle
            _intraday_dev = 0.0
            try:
                _hub = get_data_hub()
                _intra = _hub.get_intraday_bars([symbol], bars_back=3)
                if symbol in _intra and len(_intra[symbol]) >= 2:
                    _bars = _intra[symbol]
                    _last_close = _bars[-1].get("c", 0)
                    _prev_close = _bars[-2].get("c", 0) if len(_bars) >= 2 else _last_close
                    if _prev_close > 0:
                        _intraday_dev = (_last_close - _prev_close) / _prev_close
                    # Skip if price has already pumped >3% in last 15 min → avoid buying top
                    if _intraday_dev > 0.03:
                        logger.info(f"Skipping {symbol}: intraday pump {_intraday_dev:.1%} — entry too hot")
                        continue
            except Exception:
                pass

            # Use options IV to adjust position size: high IV = smaller bet
            _iv = sig.get("options_implied_vol")
            _iv_multiplier = 1.0
            if _iv and _iv > 0:
                if _iv > 0.8:
                    _iv_multiplier = 0.5   # extreme vol → half size
                elif _iv > 0.6:
                    _iv_multiplier = 0.7   # high vol → 70% size
                elif _iv > 0.4:
                    _iv_multiplier = 0.9   # elevated → 90%
                # normal IV (<0.4) = full size

            _tier = sig.get("tier", "NOW")
            _tier_max_pct = self._tier_max_position_pct(_tier, self.risk_engine.config.max_single_position_pct)
            sizing = self.risk_engine.size_buy(
                symbol=symbol,
                price=price,
                atr=sig.get("atr14", price * 0.02),
                portfolio_data=portfolio_data,
                current_positions=current_positions,
                signal_score=sig.get("total_score", 0),
                max_position_pct_override=_tier_max_pct,
            )

            if sizing.blocked:
                logger.debug(f"{symbol} new buy blocked: {sizing.block_reason}")
                continue

            # Apply readiness-based sizing multiplier + IV adjustment
            readiness = sig.get("readiness_score", 0)
            multiplier = self._readiness_sizing_multiplier(readiness) * _iv_multiplier
            # Apply strategy-specific cap (mean reversion = 0.75x)
            strategy_type = sig.get("strategy_type", "momentum")
            multiplier *= self._strategy_sizing_cap(strategy_type)
            adjusted_qty = max(1, int(sizing.qty * multiplier))

            # Re-check cash after multiplier
            cost = adjusted_qty * price
            cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
            if cost > (portfolio_data["account"]["cash"] - cash_floor):
                adjusted_qty = max(1, int((portfolio_data["account"]["cash"] - cash_floor) / price))
                cost = adjusted_qty * price

            trade = {
                "symbol": symbol,
                "qty": adjusted_qty,
                "action": "BUY",
                "reason": f"Entry (readiness {readiness:.1f}, {sig.get('confirmation_count', 0)}/5 conf) — {sizing.reason}",
                "intended_notional": cost,
                "readiness_score": readiness,
                "tier": sig.get("tier", "NOW"),
            }
            entry_candidates.append(trade)

        # Sort entry queue by readiness (highest first)
        entry_candidates.sort(key=lambda t: t.get("readiness_score", 0), reverse=True)

        # Execute buys in readiness order
        for trade in entry_candidates:
            self._execute_buy(trade, portfolio_data)
            self.risk_engine.record_buy(trade["intended_notional"])

            # Record entry thesis
            symbol = trade["symbol"]
            sig = signal_map.get(symbol, {})
            self.thesis_manager.add_thesis(
                symbol=symbol,
                entry_price=trade.get("entry_price", 0),
                readiness_score=sig.get("readiness_score", 0),
                thesis=sig.get("thesis", ""),
                confirmations=sig.get("confirmations", {}),
            )

            # Update current_positions to prevent over-allocation
            current_positions[symbol] = {
                "symbol": symbol,
                "market_value": trade["qty"] * self.alpaca.get_latest_quote(symbol, ),
                "sector": sig.get("sector", "Other"),
            }
            portfolio_data["account"]["cash"] -= trade["intended_notional"]

        # 3b. Average into existing positions that are still entry-eligible
        for pos in portfolio_data.get("positions", []):
            symbol = pos.get("symbol")
            if not symbol or symbol not in signal_map:
                continue
            sig = signal_map[symbol]
            # Use entry_eligible for averaging in too
            if not sig.get("entry_eligible", False):
                continue

            pl_pct = pos.get("unrealized_plpc", 0) or 0.0
            # Only average in if position is down or readiness has strengthened
            if pl_pct >= 0 and sig.get("readiness_score", 0) < 75:
                continue

            price = self.alpaca.get_latest_quote(symbol)
            if price is None or price <= 0:
                continue

            sizing = self.risk_engine.size_average_in(
                symbol=symbol,
                price=price,
                atr=sig.get("atr14", price * 0.02),
                portfolio_data=portfolio_data,
                current_positions=current_positions,
                signal_score=sig.get("total_score", 0),
            )

            if sizing.blocked:
                logger.debug(f"{symbol} avg-in blocked: {sizing.block_reason}")
                continue

            trade = {
                "symbol": symbol,
                "qty": sizing.qty,
                "action": "BUY",
                "reason": f"Avg-in on {symbol} (readiness {sig.get('readiness_score', 0):.1f}, {sizing.reason})",
                "intended_notional": sizing.intended_notional,
                "tier": sig.get("tier", "NOW"),
            }
            self._execute_buy(trade, portfolio_data, is_avg_in=True)
            self.risk_engine.record_average_in(symbol, sizing.intended_notional)
            current_positions[symbol]["market_value"] = current_positions[symbol].get("market_value", 0) + sizing.qty * price
            portfolio_data["account"]["cash"] -= sizing.intended_notional

    def _execute_sell(self, trade: Dict, portfolio_data: Dict):
        symbol = trade["symbol"]
        qty = trade["qty"]
        try:
            order_id = self.alpaca.submit_order(symbol, qty, "sell", dry_run=self._dry_run)
            self._log_trade(trade, order_id, portfolio_data)
            logger.info(f"EXECUTED SELL: {qty} {symbol} ({trade['reason']})")
        except Exception as e:
            logger.error(f"Failed to sell {symbol}: {e}")

    def _execute_buy(self, trade: Dict, portfolio_data: Dict, is_avg_in: bool = False):
        symbol = trade["symbol"]
        qty = trade["qty"]
        # Check if symbol is tradable on Alpaca
        if not self.alpaca.is_tradable(symbol):
            logger.warning(f"Skipping buy {symbol}: not tradable on Alpaca")
            self._failed_buy_symbols.add(symbol)
            return

        # Intraday momentum check for NEW positions (not avg-in)
        if not is_avg_in:
            market_open = self.alpaca.is_market_open()
            should_buy, size_mult, intraday_reason = check_intraday_buy(self.alpaca, symbol, market_open)
            if not should_buy:
                logger.info(f"INTRADAY SKIP: {symbol} — {intraday_reason}")
                return
            if size_mult < 1.0:
                original_qty = qty
                qty = max(1, int(qty * size_mult))
                trade["qty"] = qty
                trade["reason"] = trade["reason"] + f" | intraday: {intraday_reason}"
                logger.info(f"INTRADAY REDUCE: {symbol} qty {original_qty} -> {qty} ({intraday_reason})")

        # Tier-aware execution: STRONG_NOW = aggressive (ask), NOW = passive (midpoint + 5s timeout)
        tier = trade.get("tier", "NOW")
        try:
            order_id = self.alpaca.submit_tiered_order(symbol, qty, "buy", tier=tier, dry_run=self._dry_run)
            self._log_trade(trade, order_id, portfolio_data)
            logger.info(f"EXECUTED BUY: {qty} {symbol} tier={tier} ({trade['reason']})")
            # Clear any previous failure flag for this symbol
            self._failed_buy_symbols.discard(symbol)
        except Exception as e:
            logger.error(f"Failed to buy {symbol}: {e}")
            self._failed_buy_symbols.add(symbol)

    def _log_trade(self, trade: Dict, order_id: Optional[str], portfolio_data: Dict):
        try:
            # Write structured rationale for sync_alpaca_trades.py to pick up
            rationale_file = Path(TradingConfig.BOT_DIR) / "trade_rationale.json"
            try:
                if rationale_file.exists():
                    data = json.loads(rationale_file.read_text())
                else:
                    data = {"entries": []}
                data["entries"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "action": trade["action"],
                    "symbol": trade["symbol"],
                    "reason": trade.get("reason", ""),
                })
                rationale_file.write_text(json.dumps(data, indent=2))
            except Exception:
                pass

            # Also write markdown log for human readability
            with open(TradingConfig.TRADES_LOG_FILE, "a") as f:
                f.write("\n\n---\n\n")
                f.write(f"## {datetime.now(timezone.utc).strftime('%B %d, %Y - %I:%M %p UTC')} - AUTONOMOUS TRADE\n\n")
                f.write(f"**Action:** {trade['action']} {trade['qty']} {trade['symbol']}\n\n")
                f.write(f"**Reason:** {trade['reason']}\n\n")
                f.write(f"**Order ID:** {order_id}\n\n")
                f.write(f"**Portfolio Value:** ${portfolio_data['account']['portfolio_value']:,.2f}\n\n")
                f.write(f"**Mode:** {'PAPER' if self._dry_run else 'LIVE'}\n\n")
        except Exception as e:
            logger.warning(f"Could not log trade: {e}")

    # ------------------------------------------------------------------
    # Entrypoint
    # ------------------------------------------------------------------

    def run(self):
        logger.info("=" * 70)
        logger.info("STONK.AI Trading Bot v2.1 Starting")
        logger.info(f"Mode: {'PAPER (fake money)' if self.alpaca.is_paper() else 'LIVE (real money)'}")
        logger.info(f"Dry run: {self._dry_run}")
        logger.info("Strategy: readiness-driven quality-momentum with thesis exits")
        logger.info(f"Entry: readiness >= 72 AND >= 2 confirmations")
        logger.info(f"Max position size: {self.risk_engine.config.max_single_position_pct:.0%}")
        logger.info(f"Stop loss: {self.risk_engine.config.hard_stop_loss_pct:.0%}")
        logger.info(f"Drawdown halt: {self.risk_engine.config.new_entry_max_drawdown_pct:.0%}")
        logger.info("=" * 70)

        self.refresh_signals()

        while True:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(TradingConfig.CYCLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    bot = STONKAIBot()
    bot.run()