#!/usr/bin/env python3
"""
STONK.AI Trading Bot v2.5
Systematic quality-momentum strategy with readiness-driven entry and thesis-based exits.

Design principles:
- Signal-driven: `signals.json` is the single source of truth for what to buy.
- Readiness-driven: entry_eligible (STRONG_NOW tier, readiness >= 77, >= 5 confirmations, above_ema) replaces hard score threshold.
- Thesis-based: each position has an entry thesis with defined exit triggers.
- Risk-first: position sizing, concentration limits, and drawdown brakes.
- Anti-fragile: cash buffers, daily budgets, hard stops, profit trims.
- Paper-safe: defaults to paper-only; live mode requires explicit config flag.

v2.5 changes:
  - Entry: only STRONG_NOW tier is tradeable (readiness >= TIER_STRONG_NOW_MIN, gate, >= 5 conf, above_ema)
  - NOW tier is non-trading "building" strength
  - Mean reversion signals are watch-only, never entry triggers
  - Reduced sizing multipliers while live expectancy is negative
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Safety guards: never run as root; enforce single instance
if os.geteuid() == 0:
    print("ERROR: trading_bot.py must not run as root. Use user 'stonkai'.", file=sys.stderr)
    sys.exit(1)

_RUN_DIR = Path("/opt/stonk-ai/run")
_RUN_DIR.mkdir(parents=True, exist_ok=True)
_PID_FILE = _RUN_DIR / "trading_bot.pid"


def _acquire_instance_lock() -> bool:
    import atexit
    try:
        if _PID_FILE.exists():
            pid_text = _PID_FILE.read_text().strip()
            try:
                old_pid = int(pid_text)
                # Check if still alive
                os.kill(old_pid, 0)
                print(f"ERROR: trading_bot.py already running (pid {old_pid}). Refusing to start.", file=sys.stderr)
                return False
            except (ValueError, OSError, ProcessLookupError):
                # Stale PID file
                pass
        with open(_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(lambda: _PID_FILE.unlink(missing_ok=True))
        return True
    except Exception as e:
        print(f"WARNING: could not manage PID lock: {e}", file=sys.stderr)
        return True  # don't block startup on lock file issues


if not _acquire_instance_lock():
    sys.exit(1)

from readiness_score import (
    ENTRY_READINESS_MIN,
    ENTRY_MIN_CONFIRMATIONS,
    ENTRY_MIN_HARD_CONFIRMATIONS,
    TIER_STRONG_NOW_MIN,
)

import requests

from signal_engine import SignalEngine, COMPANY_NAMES, DIP_MAX_DAILY_POSITIONS
from risk_engine import RiskEngine, RiskConfig, load_high_beta_symbols
from alpaca_data import get_data_hub
from stonk_utils import atomic_write_json
import dynamic_watchlist_manager
from circuit_breaker import CircuitBreaker
from intraday_confirm import should_execute_buy as check_intraday_buy
from alert_logger import log_alert
from regime_detector import get_regime
from mean_reversion_signal import compute_mean_reversion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/opt/stonk-ai/logs/trading_bot.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Sector-aware diversification parameters (mirror paper_rebalancer.py)
DIVERSIFICATION_READINESS_MIN = 65.0
DIVERSIFICATION_CONFIRMATIONS_MIN = 2
DIVERSIFICATION_MAX_SECTOR_PCT = 0.30
DIVERSIFICATION_TARGET_PCT = 0.045  # ~4.5% of portfolio per div name


class TradingConfig:
    """Bot-level configuration."""

    # Safety: only set LIVE_MODE = True when you are ready to trade real money.
    LIVE_MODE: bool = True

    # If True, log intended trades but do not submit orders.
    DRY_RUN: bool = False

    # How often the main loop runs during market hours.
    CYCLE_INTERVAL_SECONDS: int = 120  # 2 minutes

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
    BOT_DIR: Path = Path(__file__).parent
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
        # Preventative: circuit breaker may be attached externally by the bot wrapper
        self.circuit_breaker = None  # type: ignore[attr-defined]

    def is_paper(self) -> bool:
        return "paper-api" in self.base_url

    def get_account(self) -> Dict:
        r = self.session.get(f"{self.base_url}/v2/account", timeout=45)
        r.raise_for_status()
        return r.json()

    def get_positions(self) -> List[Dict]:
        r = self.session.get(f"{self.base_url}/v2/positions", timeout=45)
        r.raise_for_status()
        return r.json()

    def is_market_open(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/v2/clock", timeout=20)
            if r.status_code == 200:
                return r.json().get("is_open", False)
        except Exception as e:
            logger.warning(f"Could not check market clock: {e}")
        return False

    def _is_us_market_hours(self) -> bool:
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=13, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=20, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close

    def _is_extended_hours(self) -> bool:
        from datetime import time
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        t = now.time()
        premarket = (t >= time(8, 0) and t < time(13, 30))
        afterhours = (t >= time(20, 0) and t <= time(23, 59, 59))
        return premarket or afterhours

    def get_latest_quote(self, symbol: str) -> Optional[float]:
        """Fetch latest bid/ask midpoint for limit orders."""
        try:
            r = self.session.get(
                f"{self.data_url}/v2/stocks/quotes/latest",
                params={"symbols": symbol, "feed": "sip"},
                timeout=30,
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
                timeout=30,
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
            r = self.session.get(f"{self.base_url}/v2/orders/{order_id}", timeout=20)
            r.raise_for_status()
            return r.json().get("status") == "filled"
        except Exception as e:
            logger.warning(f"Could not check order {order_id}: {e}")
            return True  # assume filled if we cannot check

    def _get_spread_pct(self, symbol: str) -> Optional[float]:
        """Return bid-ask spread as percentage of midpoint, or None if unavailable."""
        try:
            r = self.session.get(
                f"{self.data_url}/v2/stocks/quotes/latest",
                params={"symbols": symbol, "feed": "sip"},
                timeout=30,
            )
            r.raise_for_status()
            quote = r.json().get("quotes", {}).get(symbol, {})
            bid = quote.get("bp") or 0
            ask = quote.get("ap") or 0
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2
                return (ask - bid) / mid
        except Exception as e:
            logger.warning(f"Could not get spread for {symbol}: {e}")
        return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            r = self.session.delete(f"{self.base_url}/v2/orders/{order_id}", timeout=20)
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
            r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=30)
            r.raise_for_status()
            return r.json().get("id", "unknown")
        except Exception as e:
            logger.error(f"Failed to submit market {side} order for {symbol}: {e}")
            return None

    def get_asset(self, symbol: str) -> Optional[Dict]:
        """Get asset info from Alpaca. Returns None if not tradable."""
        try:
            r = self.session.get(f"{self.base_url}/v2/assets/{symbol}", timeout=20)
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
                     use_limit: bool = True, twap_threshold: int = 100,
                     extended_hours: bool = False) -> Optional[str]:
        # CIRCUIT BREAKER GUARD (optional — bot-level check happens before calling)
        if not dry_run and getattr(self, 'circuit_breaker', None) and self.circuit_breaker.is_open():
            reason = self.circuit_breaker.status().get('reason', 'unknown')
            logger.critical(f"CIRCUIT BREAKER OPEN — rejecting {side.upper()} {symbol}: {reason}")
            return None
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
            payload = self._build_order_payload(symbol, chunk, side_lower, use_limit=use_limit, extended_hours=extended_hours)
            if payload is None:
                continue
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=30)
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

    def _build_order_payload(self, symbol: str, qty: int, side: str, use_limit: bool = True, extended_hours: bool = False) -> Optional[dict]:
        """Build order payload — limit at midpoint or market fallback."""
        if not use_limit:
            payload = {
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            }
            if extended_hours:
                payload["extended_hours"] = True
            return payload
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
        payload = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": "limit",
            "time_in_force": "day",
            "limit_price": str(limit_price),
        }
        if extended_hours:
            payload["extended_hours"] = True
        return payload

    def submit_tiered_order(self, symbol: str, qty: int, side: str, tier: str = "NOW",
                            dry_run: bool = False, twap_threshold: int = 100,
                            extended_hours: bool = False) -> Optional[str]:
        """Submit order with tier-aware execution strategy.

        STRONG_NOW: Aggressive — cross the spread, marketable limit at ask.
        NOW: Passive — midpoint limit with 5-second fill timeout, then market.
        """
        if dry_run:
            logger.info(f"DRY RUN {side.upper()} {qty} {symbol} (tier={tier})")
            return "dry-run"
        if qty <= 0:
            return None

        # OPENING BELL GUARD: 9:30-10:00 ET has widest spreads
        # Force aggressive execution to avoid midpoint timeout cascades
        try:
            import pytz
            et = pytz.timezone("America/New_York")
            et_now = datetime.now(timezone.utc).astimezone(et)
            if et_now.weekday() < 5 and 9 <= et_now.hour < 10 and et_now.minute < 30:
                if tier != "STRONG_NOW":
                    logger.info(f"OPENING BELL: forcing aggressive execution for {symbol} (normally {tier})")
                    tier = "STRONG_NOW"
        except Exception:
            pass

        side_lower = side.lower()
        order_ids = []

        # TWAP split for large orders
        if qty > twap_threshold:
            chunks = self._twap_chunks(qty, twap_threshold)
            logger.info(f"TWAP: splitting {side} {symbol} into {len(chunks)} chunks of ~{twap_threshold}")
        else:
            chunks = [qty]

        for chunk in chunks:
            order_id = self._submit_tiered_single(symbol, chunk, side_lower, tier, extended_hours=extended_hours)
            if order_id:
                order_ids.append(order_id)
            # Brief pause between TWAP chunks
            if len(chunks) > 1 and chunk != chunks[-1]:
                import time as _time
                _time.sleep(1)

        return order_ids[0] if order_ids else None

    def _submit_tiered_single(self, symbol: str, qty: int, side: str, tier: str,
                                extended_hours: bool = False) -> Optional[str]:
        """Submit a single chunk with tier-aware execution."""
        quote = self.get_latest_quote_full(symbol)

        if quote is None or quote.get("mid", 0) <= 0:
            # No quote available — fall back to market order
            logger.info(f"No quote for {symbol}, submitting market order")
            payload = {
                "symbol": symbol, "qty": str(qty), "side": side,
                "type": "market", "time_in_force": "day",
            }
            if extended_hours:
                payload["extended_hours"] = True
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=30)
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
                    r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=30)
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
            if extended_hours:
                payload["extended_hours"] = True
            try:
                r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=30)
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

            # Not filled — cancel and escalate to marketable limit at ask + 0.5% max
            logger.info(f"EXECUTION: {symbol} midpoint limit not filled in 5s, escalating to marketable limit")
            if self.cancel_order(order_id):
                # Re-fetch quote to get current ask
                fresh_quote = self.get_latest_quote_full(symbol)
                fresh_ask = fresh_quote.get("ask", 0) if fresh_quote else 0
                if fresh_ask > 0:
                    # Cap escalation at ask + 0.5% to avoid flash crash fills
                    cap_limit = round(fresh_ask * 1.005, 2)
                    marketable_limit = min(round(fresh_ask + 0.01, 2), cap_limit)
                    # Abort if the cap would exceed original midpoint by >2% (flash crash guard)
                    if mid > 0 and marketable_limit > mid * 1.02:
                        logger.warning(f"EXECUTION ABORT: {symbol} ask+gap={marketable_limit} > midpoint+2%={mid*1.02:.2f} (flash crash guard)")
                        return None
                    ml_payload = {
                        "symbol": symbol, "qty": str(qty), "side": side,
                        "type": "limit", "time_in_force": "day",
                        "limit_price": str(marketable_limit),
                    }
                    try:
                        r = self.session.post(f"{self.base_url}/v2/orders", json=ml_payload, timeout=30)
                        r.raise_for_status()
                        ml_order_id = r.json().get("id", "unknown")
                        logger.info(f"Filled at marketable limit (escalated): {symbol} {side} {qty} @ ${marketable_limit:.2f}")
                        return ml_order_id
                    except Exception as e:
                        logger.error(f"EXECUTION: {symbol} marketable limit escalation failed: {e}")
                        # No market fallback — abort to avoid slippage
                        logger.warning(f"EXECUTION ABORT: {symbol} all limit attempts failed, no market fallback (safe mode)")
                        return None
                else:
                    # No ask available — abort (no market fallback)
                    logger.warning(f"EXECUTION ABORT: {symbol} no ask available after midpoint timeout, no market fallback")
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

    @staticmethod
    def _detect_and_fix_splits(positions_data: List[Dict], snaps: Dict[str, Dict]) -> List[Dict]:
        """
        Auto-detect stock splits where Alpaca positions API has stale (pre-split)
        avg_entry_price while snapshot API has post-split prices.
        Fixes qty, avg_entry, cost_basis, unrealized_pl, unrealized_plpc to match reality.
        """
        import math
        for pos in positions_data:
            sym = pos.get("symbol", "")
            snap = snaps.get(sym, {})
            if not snap:
                continue
            snap_price = snap.get("price", 0)
            if snap_price <= 0:
                continue
            avg_entry = pos.get("avg_entry", 0)
            if avg_entry <= 0:
                continue
            # Split ratio = old_avg / snap_price (e.g. 775/193 ≈ 4 for 4:1 split)
            ratio = avg_entry / snap_price
            # Only fix if ratio is close to an integer 2-10 (common split ratios)
            if ratio < 1.5:
                continue
            nearest_int = round(ratio)
            if abs(ratio - nearest_int) > 0.15:
                continue  # not a clean split ratio
            if nearest_int < 2 or nearest_int > 10:
                continue
            # Split detected: avg_entry is ~nearest_int times current price
            old_qty = pos["qty"]
            old_avg = pos["avg_entry"]
            old_cost = pos.get("cost_basis", 0)
            new_qty = old_qty * nearest_int
            new_avg = old_avg / nearest_int
            # Recalculate unrealized P&L based on corrected qty/avg
            current_price = pos.get("current", snap_price)
            new_upl = (current_price - new_avg) * new_qty
            new_uplpc = ((current_price / new_avg) - 1) * 100 if new_avg > 0 else 0
            # Update market_value too
            new_mv = current_price * new_qty
            logger.warning(
                f"SPLIT DETECTED {sym}: {nearest_int}-for-1. "
                f"Old: qty={old_qty} avg=${old_avg:.2f}. "
                f"New: qty={new_qty} avg=${new_avg:.2f}. "
                f"P&L corrected: ${new_upl:.2f} ({new_uplpc:.1f}%)."
            )
            pos["qty"] = new_qty
            pos["avg_entry"] = new_avg
            pos["market_value"] = new_mv
            pos["unrealized_pl"] = new_upl
            pos["unrealized_plpc"] = new_uplpc
            # Reset split-adjusted trailing-stop high-water mark so a 4:1 split
            # doesn't leave a pre-split peak that immediately triggers stops.
            try:
                self.bot.risk_engine.position_high_water_marks[sym] = new_avg
            except Exception:
                pass
            # Also adjust snapshot-derived historical bar data so enrichment doesn't overwrite with pre-split values
            for snap_key in ["prev_close", "daily_vwap", "daily_open", "daily_high", "daily_low", "daily_close"]:
                val = snap.get(snap_key)
                if isinstance(val, (int, float)) and val > 0:
                    snap[snap_key] = val / nearest_int
        return positions_data

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
                company = COMPANY_NAMES.get(symbol, symbol)

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
                    "company": company,
                    "entry_date": self.bot.thesis_manager.theses.get(symbol, {}).get("entry_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                })

            # Enrich positions with real-time snapshot data from Alpaca hub
            # This enables VWAP stops, intraday vol, and prev_close in the risk engine
            try:
                _hub = get_data_hub()
                _symbols = [p.get("symbol", "") for p in positions]
                _snaps = _hub.get_snapshots(_symbols)
                # Auto-fix stock splits before enrichment
                positions_data = self._detect_and_fix_splits(positions_data, _snaps)
                # Fetch extended-hours data for all held positions so popups can show pre/after-market %
                try:
                    _ext_hours = _hub.get_extended_hours_bars(_symbols)
                except Exception as _ext_e:
                    logger.debug(f"Extended hours enrichment failed: {_ext_e}")
                    _ext_hours = {}
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
                    # Attach extended-hours fields from the dedicated feed
                    _ext = _ext_hours.get(_sym, {})
                    if _ext.get("premarket_change_pct") is not None:
                        pos_dict["premarket_change_pct"] = _ext["premarket_change_pct"]
                    if _ext.get("premarket_volume") is not None:
                        pos_dict["premarket_volume"] = _ext["premarket_volume"]
                    if _ext.get("afterhours_change_pct") is not None:
                        pos_dict["afterhours_change_pct"] = _ext["afterhours_change_pct"]
                    if _ext.get("afterhours_volume") is not None:
                        pos_dict["afterhours_volume"] = _ext["afterhours_volume"]
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
            atomic_write_json(TradingConfig.PORTFOLIO_DATA_FILE, data)
        except Exception as e:
            logger.warning(f"Could not save portfolio data: {e}")

        try:
            atomic_write_json(TradingConfig.WEB_PORTFOLIO_FILE, data)
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
            "macd_hist_negative_days": 0,
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

            # Minimum holding period for thesis exits: avoid same-hour churn
            entry_date_str = thesis_data.get("entry_date", date.today().isoformat())
            try:
                entry_dt = datetime.fromisoformat(entry_date_str).replace(tzinfo=timezone.utc)
                hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
            except Exception:
                hours_held = 999
            if hours_held < 24:
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

            # 2. Momentum loss: MACD histogram negative for 2+ days
            macd_hist = sig.get("macd_hist", 0)
            negative_days = thesis_data.get("macd_hist_negative_days", 0)
            if macd_hist < 0:
                negative_days += 1
            else:
                negative_days = 0
            thesis_data["macd_hist_negative_days"] = negative_days
            if negative_days >= 2:
                trades.append({
                    "symbol": symbol,
                    "qty": qty,
                    "action": "SELL",
                    "reason": f"Thesis exit: {exit_triggers.get('momentum_loss', 'MACD histogram negative')}",
                })
                logger.info(f"THESIS EXIT: {symbol} — MACD histogram negative for {negative_days} days")
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
            paper_mode=self.alpaca.is_paper(),
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
        self._positions: Dict = {}  # synced from portfolio_data each cycle for exit logic
        self.circuit_breaker = CircuitBreaker()
        logger.info("Circuit breaker initialized")

        # Regime detection state
        self._regime: str = "RISK_ON"
        self._regime_params: Dict = {"max_position_pct": 8, "cash_floor_pct": 10, "min_tier_for_entry": "NOW"}
        self._dip_buys_today: int = 0
        self._dip_buy_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._ext_hours_buys_today: int = 0
        self._ext_hours_buy_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self._dry_run:
            logger.info("Bot is in DRY RUN mode — trades will be logged but not submitted.")
        elif self.alpaca.is_paper():
            logger.info("Bot is connected to Alpaca PAPER trading — fake money orders will be submitted.")
        else:
            logger.warning("Bot is connected to Alpaca LIVE trading — real money orders will be submitted.")



    def _is_entry_eligible_for_mode(self, sig: dict) -> bool:
        """Entry gate: use signal's entry_eligible flag; fall back only in paper mode.
        All strategies (momentum + mean reversion) compete on the same entry_eligible gate.
        """
        # MR blanket ban removed 2026-07-08 — MR signals now compete on entry_eligible
        # Execution quality guard: skip names with wide bid/ask spread
        if sig.get("wide_spread", False):
            return False

        # Corporate action risk guard: skip names with upcoming dividends/splits/mergers/spinoffs
        if sig.get("corporate_action_risk", False):
            return False

        if sig.get("entry_eligible", False):
            return True
        if not getattr(self.alpaca, "is_paper", lambda: False)():
            return False
        # Paper fallback only: STRONG_NOW tier only, match gate
        readiness = sig.get("readiness_score", 0)
        conf = sig.get("confirmation_count", 0)
        tier = sig.get("tier", "")
        confirmations = sig.get("confirmations", {})
        above_ema = sig.get("above_ema20", False) or confirmations.get("above_ema", False)
        hard_conf = sum(
            1 for k in ("volume_confirmed", "macd_turning", "intraday_confirmed",
                        "options_confirmed", "relvol_confirmed")
            if confirmations.get(k)
        )
        return (tier == "STRONG_NOW" and readiness >= ENTRY_READINESS_MIN
                and conf >= ENTRY_MIN_CONFIRMATIONS
                and hard_conf >= ENTRY_MIN_HARD_CONFIRMATIONS
                and above_ema)


    def _load_watchlist_symbols(self) -> set:
        """Load curated watchlist symbols from ai_watchlist_live.json.
        If stale (>15 min) or empty, fall back to full universe."""
        try:
            watchlist_path = Path("/var/www/hedge-fund-website/ai_watchlist_live.json")
            if not watchlist_path.exists():
                return set()
            with open(watchlist_path) as f:
                data = json.load(f)
            ts_str = data.get("timestamp", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
                if age_min > 15:
                    logger.warning(f"Watchlist stale ({age_min:.0f} min) — using full universe")
                    return set()
            symbols = set(data.get("prices", {}).keys())
            if symbols:
                logger.info(f"🎯 Watchlist aligned: {len(symbols)} symbols")
            return symbols
        except Exception as e:
            logger.warning(f"Watchlist load failed: {e}")
            return set()

    def _high_beta_buy_blocked(self, symbol: str, cost: float, portfolio_data: Dict, high_beta_symbols: set) -> bool:
        """Block a new high-beta buy unless it fits under the cap or qualifies for opportunistic headroom.

        Exceptional PRIME candidates (readiness >= TIER_STRONG_NOW_MIN) may exceed the steady-state cap up to the
        opportunistic cap, matching the watchlist/website logic in dynamic_watchlist_manager.py.
        """
        if not self.risk_engine.config.high_beta_basket_cap_enabled or symbol not in high_beta_symbols:
            return False
        account = portfolio_data.get("account", {})
        pv = account.get("portfolio_value", 0)
        if pv <= 0:
            return False
        current_high_beta_mv = sum(
            p.get("market_value", 0)
            for p in portfolio_data.get("positions", [])
            if p.get("symbol") in high_beta_symbols
        )
        new_high_beta_mv = current_high_beta_mv + cost

        # Look up the candidate signal to decide if it qualifies for opportunistic headroom.
        sig = next((s for s in self._signals if s.get("symbol") == symbol), {})
        tier = sig.get("tier", "")
        readiness = sig.get("readiness_score", 0)
        is_exceptional = tier == "STRONG_NOW" and readiness >= TIER_STRONG_NOW_MIN

        steady_cap = self.risk_engine.config.max_high_beta_deployed_pct
        opportunistic_cap = getattr(dynamic_watchlist_manager, "OPPORTUNISTIC_HIGH_BETA_CAP", 0.40)
        effective_cap = opportunistic_cap if is_exceptional else steady_cap

        if new_high_beta_mv / pv > effective_cap:
            logger.info(
                f"Blocking {symbol} buy: would push high-beta basket to {new_high_beta_mv/pv:.1%} "
                f"(cap {effective_cap:.1%}, {'opportunistic' if is_exceptional else 'steady-state'})"
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Sector helpers for diversification
    # ------------------------------------------------------------------
    @staticmethod
    def _symbol_sector(symbol: str) -> str:
        """Return sector mapping (synced with signal_engine.py / paper_rebalancer.py)."""
        sectors = {
            "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "NFLX", "CRM", "ORCL", "ADBE", "INTU", "IBM", "INTC", "SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW", "NET", "DDOG", "OKTA", "PATH", "PLTR", "UBER", "ABNB", "EXPE", "SPOT", "ROKU", "PINS", "SNAP", "TTD", "SHOP"],
            "Semiconductors": ["AMD", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON", "AVGO", "TXN"],
            "Cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "CYBR", "S"],
            "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY", "PYPL", "FIS", "V", "GS", "MS", "BLK", "SCHW"],
            "Consumer/Platform": ["UBER", "DKNG", "SHOP", "TTD", "ROKU", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "ELF", "APP", "DUOL", "CHWY", "ETSY", "LULU", "NKE", "COST", "WMT", "HD"],
            "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
            "Healthcare": ["UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "VRTX", "BMY", "REGN", "GILD", "ISRG", "ZBH", "ILMN", "SGEN"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY"],
            "Industrials": ["GE", "CAT", "UNP", "HON", "UPS", "RTX", "LMT", "DE"],
            "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "V"],
            "Communications/Media": ["DIS", "CMCSA", "TMUS", "CHTR", "WBD", "PARA"],
        }
        for sector, symbols in sectors.items():
            if symbol in symbols:
                return sector
        return "Other"

    def _sector_exposures(self, portfolio_data: dict) -> dict:
        exposures = {}
        for pos in portfolio_data.get("positions", []):
            sector = self._symbol_sector(pos.get("symbol"))
            exposures[sector] = exposures.get(sector, 0.0) + pos.get("market_value", 0)
        return exposures

    def _add_diversification_entries(
        self,
        entry_candidates: list,
        portfolio_data: dict,
        current_symbols: set,
        high_beta_symbols: set,
    ) -> None:
        """Add near-eligible non-high-beta candidates from underweight sectors.

        This runs after the core entry queue and only deploys if cash is plentiful
        (cash > 40% of portfolio) to avoid crowding out high-conviction momentum entries.
        """
        pv = portfolio_data["account"]["portfolio_value"]
        cash = portfolio_data["account"]["cash"]
        if cash <= pv * 0.40:
            return

        # ALPHA: diversification is a pro-cyclical feature — only in RISK_ON
        if self._regime != "RISK_ON":
            logger.info(f"Diversification skipped: regime={self._regime} (only active in RISK_ON)")
            return

        exposures = self._sector_exposures(portfolio_data)
        pv = portfolio_data["account"]["portfolio_value"]
        existing_symbols = {t["symbol"] for t in entry_candidates} | current_symbols

        div_candidates = []
        for sig in self._signals:
            symbol = sig.get("symbol")
            if symbol in existing_symbols:
                continue
            if sig.get("entry_eligible", False):
                continue
            if symbol in high_beta_symbols:
                continue
            readiness = sig.get("readiness_score", 0)
            conf = sig.get("confirmation_count", 0)
            if readiness < DIVERSIFICATION_READINESS_MIN or conf < DIVERSIFICATION_CONFIRMATIONS_MIN:
                continue
            above_ema = sig.get("above_ema20") or sig.get("confirmations", {}).get("above_ema")
            if not above_ema:
                continue
            price = sig.get("price", 0)
            if price <= 0:
                continue
            sector = self._symbol_sector(symbol)
            if exposures.get(sector, 0) >= pv * DIVERSIFICATION_MAX_SECTOR_PCT:
                continue
            div_candidates.append(sig)

        # Sort by readiness and pick enough to deploy cash down to ~40%
        div_candidates.sort(key=lambda s: s.get("readiness_score", 0), reverse=True)
        deploy_cash = cash - pv * 0.40
        deployed_div = 0.0
        for sig in div_candidates:
            if deployed_div >= deploy_cash:
                break
            symbol = sig.get("symbol")
            sector = self._symbol_sector(symbol)
            if exposures.get(sector, 0) >= pv * DIVERSIFICATION_MAX_SECTOR_PCT:
                continue

            price = sig.get("price", 0)
            if price <= 0:
                continue

            target_value = min(pv * DIVERSIFICATION_TARGET_PCT, deploy_cash - deployed_div)
            # Respect single-stock cap
            max_single_value = pv * self.risk_engine.config.max_single_position_pct
            target_value = min(target_value, max_single_value)

            qty = max(1, int(target_value / price))
            cost = qty * price
            cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
            if cost > (cash - cash_floor - deployed_div):
                qty = max(0, int((cash - cash_floor - deployed_div) / price))
                cost = qty * price
            if qty <= 0 or cost <= 0:
                continue

            if self._high_beta_buy_blocked(symbol, cost, portfolio_data, high_beta_symbols):
                continue

            entry_candidates.append({
                "symbol": symbol,
                "qty": qty,
                "action": "BUY",
                "reason": f"Diversification entry (readiness {sig.get('readiness_score', 0):.1f}, {conf}/10 conf) - sector underweight",
                "intended_notional": cost,
                "readiness_score": sig.get("readiness_score", 0),
                "tier": sig.get("tier", "WATCH"),
                "diversification": True,
            })
            deployed_div += cost
            exposures[sector] = exposures.get(sector, 0.0) + cost
            logger.info(f"DIV ENTRY queued: {symbol} {qty} shares @ ${price:.2f} ({cost:.0f}) - sector {sector}")

    # ------------------------------------------------------------------
    # Signal lifecycle
    # ------------------------------------------------------------------

    def refresh_signals(self):
        try:
            # Temporarily extend universe with held positions so they never drop
            # from signals.json even when borderline — prevents watchlist 0.0 placeholders
            try:
                with open("/opt/stonk-ai/portfolio_data.json") as _pf:
                    _portfolio = json.load(_pf)
                _held = {p["symbol"] for p in _portfolio.get("positions", []) if p.get("symbol")}
                _original_universe = list(self.signal_engine.universe)
                _extra = [s for s in _held if s not in _original_universe]
                if _extra:
                    self.signal_engine.universe = _original_universe + _extra
                    logger.info(f"Held positions added to signal universe: {', '.join(_extra)}")
            except Exception:
                _extra = []
                _original_universe = list(self.signal_engine.universe)

            signals = self.signal_engine.generate_signals(lookback_days=120)

            if _extra:
                self.signal_engine.universe = _original_universe

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

        # Reset daily dip-buy counter at start of each trading cycle
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today_str != self._dip_buy_date:
            self._dip_buy_date = today_str
            self._dip_buys_today = 0
        if today_str != self._ext_hours_buy_date:
            self._ext_hours_buy_date = today_str
            self._ext_hours_buys_today = 0

    # ------------------------------------------------------------------
    # Readiness-based position sizing multiplier
    # ------------------------------------------------------------------

    @staticmethod
    def _readiness_sizing_multiplier(readiness: float) -> float:
        """Scale position size by readiness conviction.
        Reduced from 3.0×/1.5×/0.5× to 2.0×/1.0×/0.5× while live expectancy is negative.
        """
        if readiness >= 80:
            return 2.0   # STRONG_NOW high conviction
        if readiness >= 75:
            return 1.0   # upper NOW
        if readiness >= 72:
            return 0.5   # lower NOW — minimal size
        return 0.0       # below threshold — blocked

    @staticmethod
    def _strategy_sizing_cap(strategy_type: str) -> float:
        """Cap position size for non-momentum strategies."""
        if strategy_type == "mean_reversion":
            return 0.75  # lower conviction, cap at 75% of normal size
        return 1.0  # momentum: no cap

    @staticmethod
    def _tier_max_position_pct(tier: str, base_max_pct: float) -> float:
        """Return the max position % cap for a given signal tier.

        STRONG_NOW: 12% — conviction gets room to run. NOW: 8% hard wall.
        """
        if tier == "STRONG_NOW":
            return 0.12
        return base_max_pct  # 8% for NOW, WATCH, MONITOR

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_cycle(self):
        logger.info("run_cycle() started")
        # CIRCUIT BREAKER CHECK
        if self.circuit_breaker.is_open():
            status = self.circuit_breaker.status()
            logger.critical(f"CIRCUIT BREAKER OPEN — skipping trade cycle: {status.get('reason')}")
            # Optionally still refresh portfolio but skip trades
            return

        # Run during regular hours OR extended hours if enabled
        market_open = self.alpaca.is_market_open()
        ext_hours = (self.risk_engine.config.extended_hours_enabled
                     and self.alpaca._is_extended_hours()
                     and not self.alpaca._is_us_market_hours())
        if not market_open and not ext_hours:
            logger.debug("Market closed and extended hours inactive; skipping cycle")
            # Off-hours risk check: alert on concentration breaches that cannot be trimmed now
            try:
                portfolio_data = self.data_store.fetch()
                if portfolio_data:
                    high_beta_symbols = load_high_beta_symbols()
                    high_beta_trades = self.risk_engine.check_high_beta_basket(portfolio_data, high_beta_symbols)
                    # Always log off-hours high-beta status for visibility
                    positions = portfolio_data.get("positions", [])
                    account = portfolio_data.get("account", {})
                    pv = account.get("portfolio_value", 0)
                    hb_mv = sum(p.get("market_value", 0) for p in positions if p.get("symbol") in high_beta_symbols)
                    logger.info(f"Off-hours high-beta check: {hb_mv / pv:.1%} ({len(high_beta_symbols)} symbols loaded)")
                    if high_beta_trades:
                        total_trim = sum(t.get("qty", 0) for t in high_beta_trades)
                        symbols = ", ".join([t.get("symbol", "?") for t in high_beta_trades])
                        logger.warning(
                            f"OFF-HOURS HIGH-BETA BREACH: {total_trim} shares to trim across {symbols}. "
                            "Trim will execute at next market open."
                        )
            except Exception as e:
                logger.warning(f"Off-hours high-beta check failed: {e}")
            return

        # If cash is negative, force cash raise before any new buys
        try:
            portfolio_data = self.data_store.fetch()
            if portfolio_data:
                cash = portfolio_data.get("account", {}).get("cash", 0)
                if cash < 0:
                    logger.warning(f"Negative cash detected: . Forcing cash raise.")
                    self.risk_engine.check_cash_raise(portfolio_data, self._signals)
        except Exception as e:
            logger.warning(f"Could not pre-check cash for negative balance: {e}")

        # Regime detection: check market conditions each cycle
        try:
            regime_result = get_regime()
            self._regime = regime_result["regime"]
            self._regime_params = regime_result["params"]
            # Apply regime overrides to risk engine config
            if not self.alpaca.is_paper():
                self.risk_engine.config.max_single_position_pct = self._regime_params["max_position_pct"] / 100
            # Paper mode keeps the looser 10% cap set in RiskConfig
            self.risk_engine.config.min_cash_pct = self._regime_params["cash_floor_pct"] / 100
            # Log regime state
            _regime_emoji = {"RISK_ON": "\U0001F4C8", "RISK_OFF": "\u26A0\uFE0F", "CRISIS": "\U0001F6D1"}
            _regime_desc = {"RISK_ON": "full size", "RISK_OFF": "defensive", "CRISIS": "no new entries"}
            logger.info(f"{_regime_emoji.get(self._regime, '?')} Regime: {self._regime} \u2014 {_regime_desc.get(self._regime, '')}")
            if regime_result.get("triggers"):
                logger.info(f"  Regime triggers: {'; '.join(regime_result['triggers'])}")
            # Log active strategy
            if self._regime == "RISK_ON":
                logger.info("\U0001F4C8 Strategy: Momentum (RISK_ON)")
            elif self._regime == "RISK_OFF":
                logger.info("\U0001F504 Strategy: Mean Reversion (RISK_OFF)")
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
        # Sync _positions from portfolio data for exit logic
        self._positions = {
            p["symbol"]: {
                "qty": p.get("qty", 0),
                "avg_entry": p.get("avg_entry", 0),
                "current_price": p.get("current", 0),
                "market_value": p.get("market_value", 0),
                "sector": p.get("sector", "Other"),
                "entry_date": p.get("entry_date") or self.thesis_manager.theses.get(p["symbol"], {}).get("entry_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            }
            for p in portfolio_data.get("positions", [])
            if p.get("symbol")
        }

        # Load macro-correlation high-beta basket for this cycle
        high_beta_symbols = load_high_beta_symbols()
        if high_beta_symbols:
            logger.info(f"High-beta basket loaded: {len(high_beta_symbols)} symbols")

        # 1. Handle exits: risk engine + thesis exits
        exit_trades = []
        exit_trades.extend(self.risk_engine.check_exits(portfolio_data))
        exit_trades.extend(self.risk_engine.check_concentration(portfolio_data))
        # Symmetric high-beta cap enforcement: trim existing high-beta positions
        # when the basket exceeds its cap, then block new buys until compliant.
        exit_trades.extend(self.risk_engine.check_high_beta_basket(portfolio_data, high_beta_symbols))
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
            _entry_date = pos.get("entry_date") or _today_str
            if isinstance(_entry_date, str):
                try:
                    _days_held = (datetime.now(timezone.utc) - datetime.fromisoformat(_entry_date.replace("Z", "+00:00"))).days
                except Exception:
                    _days_held = 0  # Treat unparseable as just-entered, not ancient
            else:
                _days_held = 0
            pos["_days_held"] = _days_held

        # 1b. Readiness-based exit: sell positions that dropped below WATCH tier
        # Regime-aware minimum holding period:
        #   CRISIS    → no hold requirement, exit if readiness < 70
        #   RISK_OFF  → 10-day min hold (instead of 20)
        #   RISK_ON   → 20-day min hold (default)
        _low_readiness_symbols = set()
        _thesis_broken_symbols = set()  # readiness < 40 = thesis dead, exit immediately
        _crisis_exit_symbols = set()
        for sig in self._signals:
            r_score = sig.get("readiness_score", 100)
            if r_score < 55:
                _low_readiness_symbols.add(sig["symbol"])
            if r_score < 40:
                _thesis_broken_symbols.add(sig["symbol"])
            if r_score < 70:
                _crisis_exit_symbols.add(sig["symbol"])

        # Determine min hold days based on regime
        if self._regime == "CRISIS":
            _min_hold_days = 0
        elif self._regime == "RISK_OFF":
            _min_hold_days = 1
        else:
            _min_hold_days = 2  # RISK_ON: 2-day minimum hold to reduce intraday churn

        # Track which symbols have already had an exit attempt this cycle
        # to prevent multiple overlapping exit rules firing on the same position.
        _exited_today = set()

        for sym in list(self._positions.keys()):
            if sym in _exited_today:
                continue
            pos = self._positions[sym]
            _days = pos.get("_days_held", 0)

            # CRISIS override: immediate exits for readiness < 70, regardless of hold period
            if self._regime == "CRISIS" and sym in _crisis_exit_symbols:
                logger.info(f"🚨 CRISIS exit: {sym} readiness < 70 (held {_days} days)")
                self._exit_position(sym, reason="crisis_readiness_below_70")
                _exited_today.add(sym)
                continue

            # Thesis broken: readiness < 40 = exit immediately, no holding period
            if sym in _thesis_broken_symbols:
                logger.info(f"💀 Thesis exit: {sym} readiness below 40 (held {_days} days) — immediate exit")
                self._exit_position(sym, reason="thesis_broken_below_40")
                _exited_today.add(sym)
                continue

            # Standard readiness-based exit (respecting regime-aware min hold)
            if _days >= _min_hold_days and sym in _low_readiness_symbols:
                logger.info(f"🔄 Exit signal: {sym} readiness dropped below 55 (held {_days} days, min hold {_min_hold_days})")
                self._exit_position(sym, reason="readiness_below_55")
                _exited_today.add(sym)

        # 1c. Flat exit: free dead money capital from positions going nowhere
        # If held >= 5 days AND price within ±3% of entry AND readiness < 70, exit
        # ALPHA: flat exit hold period — regime-adaptive to reduce churn
        _flat_exit_min_days = 7 if self._regime == "RISK_ON" else 5
        if self._regime != "CRISIS":  # CRISIS already handles fast exits
            for sym in list(self._positions.keys()):
                if sym in _exited_today:
                    continue
                pos = self._positions.get(sym, {})
                _days = pos.get("_days_held", 0)
                if _days < _flat_exit_min_days:
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
                            if _readiness < 70:  # Not strong enough to justify holding dead money
                                logger.info(f"💤 Flat exit: {sym} held {_days} days, moved only {_move_pct:.1f}%, readiness {_readiness:.0f}")
                                self._exit_position(sym, reason="flat_dead_money")
                                _exited_today.add(sym)

        # Hard cut: anything down -3% gets exited regardless of holding period or flatness
        for sym in list(self._positions.keys()):
            if sym in _exited_today:
                continue
            pos = self._positions.get(sym, {})
            _entry = pos.get("avg_entry") or pos.get("cost_basis", 0)
            _current = pos.get("current_price", 0) or (pos.get("market_value", 0) / pos.get("qty", 1))
            if _entry > 0 and _current > 0:
                _loss_pct = (_current - _entry) / _entry * 100
                if _loss_pct <= -3.0:
                    logger.info(f"🛑 Hard cut: {sym} down {_loss_pct:.1f}% — hitting -3% limit")
                    self._exit_position(sym, reason="hard_stop_3pct")
                    _exited_today.add(sym)

        # 1d. Max-hold exit: prevent long-term bag-holding (14+ days bucket was deeply unprofitable)
        for sym in list(self._positions.keys()):
            if sym in _exited_today:
                continue
            pos = self._positions.get(sym, {})
            _days = pos.get("_days_held", 0)
            if _days >= 14:
                logger.info(f"⏰ Max-hold exit: {sym} held {_days} days — recycle capital")
                self._exit_position(sym, reason="max_hold_14d")
                _exited_today.add(sym)

        # 1e. Cash-raising: if cash is below the dynamic floor, trim weakest positions
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
        top_buy_candidates = [s for s in self._signals if self._is_entry_eligible_for_mode(s)]
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

        # 2. Drawdown trim: if in drawdown halt, trim weakest 25% of positions
        _pv_now = portfolio_data["account"]["portfolio_value"]
        _dd = self.risk_engine._current_drawdown(_pv_now)
        if _dd >= abs(self.risk_engine.config.new_entry_max_drawdown_pct):
            # Sort positions by readiness (lowest = weakest)
            _pos_with_readiness = []
            for p in portfolio_data.get("positions", []):
                _sym = p.get("symbol", "")
                _sig = next((s for s in self._signals if s.get("symbol") == _sym), None)
                _r = _sig.get("readiness_score", 50) if _sig else 50
                _pos_with_readiness.append((_sym, _r, p.get("qty", 0)))
            _pos_with_readiness.sort(key=lambda x: x[1])  # weakest first
            _trim_count = max(1, len(_pos_with_readiness) // 4)  # trim 25%
            _trimmed = 0
            for _sym, _r, _qty in _pos_with_readiness[:_trim_count]:
                if _qty >= 2 and _r < 65:
                    _trim_qty = max(1, _qty // 3)  # trim 1/3 of position
                    logger.info(f"📉 DD trim: {_sym} readiness={_r:.0f} DD={_dd:.1%} — trimming {_trim_qty}/{_qty} shares")
                    self._execute_sell({
                        "symbol": _sym,
                        "qty": _trim_qty,
                        "action": "SELL",
                        "reason": f"DD trim: {self.risk_engine.config.new_entry_max_drawdown_pct:.0%} halt, readiness {_r:.0f}",
                    }, portfolio_data)
                    _trimmed += 1
            if _trimmed > 0:
                logger.info(f"Drawdown halt active: trimmed {_trimmed} positions (DD={_dd:.1%})")
                portfolio_data = self.data_store.fetch()
                if not portfolio_data:
                    return

        # 2b. Decide if we should add new positions
        can_add, reason, _ = self.risk_engine.can_add_new_positions(portfolio_data)
        if not can_add:
            logger.info(f"New positions blocked: {reason}")
            return

        # 3. Build candidate buys from signals — now readiness-driven
        current_symbols = {p["symbol"] for p in portfolio_data.get("positions", [])}

# ALPHA: Hard portfolio position ceiling -- trim weakest when over limit, block new entries at limit
        MAX_POSITIONS = 12
        if len(current_symbols) >= MAX_POSITIONS:
            if len(current_symbols) > MAX_POSITIONS:
                self._trim_weakest_positions(portfolio_data, target=MAX_POSITIONS)
            logger.info(f"🚫 MAX_POSITIONS ceiling ({MAX_POSITIONS}) reached: {len(current_symbols)} held. No new entries until positions exit.")
            return

        top_signals = sorted(self._signals, key=lambda s: s.get("readiness_score", 0), reverse=True)[: self.risk_engine.config.top_signal_count]

        # ALIGN BOT TO WATCHLIST: only buy symbols in the curated watchlist
        watchlist_symbols = self._load_watchlist_symbols()
        if watchlist_symbols:
            _pre = len(top_signals)
            top_signals = [s for s in top_signals if s.get("symbol") in watchlist_symbols]
            logger.info(f"Watchlist align: {len(top_signals)}/{_pre} from watchlist of {len(watchlist_symbols)}")

        current_positions = {p["symbol"]: p for p in portfolio_data.get("positions", [])}
        signal_map = {s["symbol"]: s for s in top_signals}

        # 3a. Build ranked entry queue by readiness_score (highest first)
        # Regime-adaptive strategy switching:
        #   RISK_ON  -> momentum strategy (entry_eligible from momentum signals)
        #   RISK_OFF -> mean reversion strategy (entry_eligible from MR signals + STRONG_NOW momentum)
        #   CRISIS   -> no new entries (min_tier_for_entry = None)
        entry_candidates = []

        if self._regime == "RISK_OFF":
            # ALPHA: RISK_OFF only allows STRONG_NOW momentum with higher bar
            logger.info("Searching for STRONG_NOW momentum entries (RISK_OFF mode)...")
            for sig in top_signals:
                symbol = sig["symbol"]
                if symbol in current_symbols:
                    continue

                # In RISK_OFF, allow:
                #   1. Mean reversion signals with entry_eligible (RSI < 35, volume capitulation)
                #   2. STRONG_NOW momentum signals (high conviction even in defensive mode)
                # ALPHA: RISK_OFF only allows STRONG_NOW momentum
                if sig.get("tier") != "STRONG_NOW":
                    continue
                readiness = sig.get("readiness_score", 0)
                if readiness < _risk_off_min_readiness:
                    continue
                if not self._is_entry_eligible_for_mode(sig) or sig.get("tier") != "STRONG_NOW":
                    continue

                # CRISIS check
                _min_tier = self._regime_params.get("min_tier_for_entry")
                if _min_tier is None:
                    logger.info(f"CRISIS regime: skipping new entry for {symbol}")
                    continue

                price = self.alpaca.get_latest_quote(symbol)
                if price is None or price <= 0:
                    try:
                        _hub = get_data_hub()
                        _snap = _hub.get_snapshot(symbol)
                        price = _snap.get("price") if _snap else None
                    except Exception:
                        pass
                if price is None or price <= 0:
                    logger.debug(f"No quote for {symbol}; skipping")
                    continue

                # Intraday pump check
                try:
                    _hub = get_data_hub()
                    _intra = _hub.get_intraday_bars([symbol], bars_back=3)
                    if symbol in _intra and len(_intra[symbol]) >= 2:
                        _bars = _intra[symbol]
                        _last_close = _bars[-1].get("c", 0)
                        _prev_close = _bars[-2].get("c", 0) if len(_bars) >= 2 else _last_close
                        if _prev_close > 0:
                            _intraday_dev = (_last_close - _prev_close) / _prev_close
                            if _intraday_dev > 0.03:
                                logger.info(f"Skipping {symbol}: intraday pump {_intraday_dev:.1%} - entry too hot")
                                continue
                except Exception:
                    pass

                _iv = _iv_scalar(sig.get("options_implied_vol"))
                _iv_multiplier = 1.0
                if _iv and _iv > 0:
                    if _iv > 0.8:
                        _iv_multiplier = 0.5
                    elif _iv > 0.6:
                        _iv_multiplier = 0.7
                    elif _iv > 0.4:
                        _iv_multiplier = 0.9

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

                readiness = sig.get("readiness_score", 0)
                multiplier = self._readiness_sizing_multiplier(readiness) * _iv_multiplier
                multiplier *= self._strategy_sizing_cap(strategy_type)
                # Scale by hard confirmation count (2026-07-08)
                _confirms = sig.get("confirmations", {})
                _hard = sum(1 for k in ("volume_confirmed", "macd_turning", "intraday_confirmed", "options_confirmed", "relvol_confirmed") if _confirms.get(k))
                if _hard >= 3:
                    _hm = 1.0
                elif _hard == 2:
                    _hm = 0.75
                elif _hard == 1:
                    _hm = 0.5
                else:
                    _hm = 0.33
                multiplier *= _hm
                if multiplier <= 0:
                    continue
                adjusted_qty = max(1, int(sizing.qty * multiplier))

                cost = adjusted_qty * price
                cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
                if cost > (portfolio_data["account"]["cash"] - cash_floor):
                    adjusted_qty = max(0, int((portfolio_data["account"]["cash"] - cash_floor) / price))
                    cost = adjusted_qty * price

                if self._high_beta_buy_blocked(symbol, cost, portfolio_data, high_beta_symbols):
                    logger.info(f"Skipping {symbol}: high-beta basket cap")
                    continue

                trade = {
                    "symbol": symbol,
                    "qty": adjusted_qty,
                    "action": "BUY",
                    "reason": f"Entry ({strategy_type}, readiness {readiness:.1f}, {sig.get('confirmation_count', 0)}/10 conf) - {sizing.reason}",
                    "intended_notional": cost,
                    "readiness_score": readiness,
                    "tier": _tier,
                }
                entry_candidates.append(trade)

        else:
            # RISK_ON: momentum strategy (default)
            for sig in top_signals:
                symbol = sig["symbol"]
                if symbol in current_symbols:
                    continue
                if not self._is_entry_eligible_for_mode(sig) or sig.get("tier") != "STRONG_NOW":
                    continue

                # Regime-based entry gate
                _min_tier = self._regime_params.get("min_tier_for_entry")
                if _min_tier is None:
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
                    try:
                        _hub = get_data_hub()
                        _snap = _hub.get_snapshot(symbol)
                        price = _snap.get("price") if _snap else None
                    except Exception:
                        pass
                if price is None or price <= 0:
                    logger.debug(f"No quote for {symbol}; skipping")
                    continue

                # Intraday entry timing
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
                        if _intraday_dev > 0.03:
                            logger.info(f"Skipping {symbol}: intraday pump {_intraday_dev:.1%} - entry too hot")
                            continue
                except Exception:
                    pass

                _iv = _iv_scalar(sig.get("options_implied_vol"))
                _iv_multiplier = 1.0
                if _iv and _iv > 0:
                    if _iv > 0.8:
                        _iv_multiplier = 0.5
                    elif _iv > 0.6:
                        _iv_multiplier = 0.7
                    elif _iv > 0.4:
                        _iv_multiplier = 0.9

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

                readiness = sig.get("readiness_score", 0)
                multiplier = self._readiness_sizing_multiplier(readiness) * _iv_multiplier
                strategy_type = sig.get("strategy_type", "momentum")
                multiplier *= self._strategy_sizing_cap(strategy_type)
                # Scale by hard confirmation count (2026-07-08)
                _confirms = sig.get("confirmations", {})
                _hard = sum(1 for k in ("volume_confirmed", "macd_turning", "intraday_confirmed", "options_confirmed", "relvol_confirmed") if _confirms.get(k))
                if _hard >= 3:
                    _hm = 1.0
                elif _hard == 2:
                    _hm = 0.75
                elif _hard == 1:
                    _hm = 0.5
                else:
                    _hm = 0.33
                multiplier *= _hm
                if multiplier <= 0:
                    continue
                adjusted_qty = max(1, int(sizing.qty * multiplier))

                cost = adjusted_qty * price
                cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
                if cost > (portfolio_data["account"]["cash"] - cash_floor):
                    adjusted_qty = max(0, int((portfolio_data["account"]["cash"] - cash_floor) / price))
                    cost = adjusted_qty * price

                if self._high_beta_buy_blocked(symbol, cost, portfolio_data, high_beta_symbols):
                    logger.info(f"Skipping {symbol}: high-beta basket cap")
                    continue

                trade = {
                    "symbol": symbol,
                    "qty": adjusted_qty,
                    "action": "BUY",
                    "reason": f"Entry (readiness {readiness:.1f}, {sig.get('confirmation_count', 0)}/10 conf) - {sizing.reason}",
                    "intended_notional": cost,
                    "readiness_score": readiness,
                    "tier": sig.get("tier", "NOW"),
                }
                entry_candidates.append(trade)

        # Sort entry queue by readiness (highest first)
        # Hard cash gate: if cash is zero or negative, block ALL new entries
        if cash <= 0:
            logger.warning(f"CASH GATE: Cash is zero or negative — blocking all new entries until cash is raised")
            return

        # Hard position cap: only top 12 high-conviction ideas
        entry_candidates = entry_candidates[:12]
        # DIP BUYING OPPORTUNITY: broad market pullback + strong name down with us
        # Only active in RISK_ON regime, capped at 1 per session, half normal size.
        if self._regime == "RISK_ON" and self._dip_buys_today < DIP_MAX_DAILY_POSITIONS:
            for sig in top_signals:
                if not sig.get("dip_opportunity", False):
                    continue
                symbol = sig["symbol"]
                if symbol in current_symbols:
                    continue
                if sig.get("tier") != "STRONG_NOW":
                    continue
                price = self.alpaca.get_latest_quote(symbol)
                if not price or price <= 0:
                    continue
                _tier_max_pct = self._tier_max_position_pct("STRONG_NOW", self.risk_engine.config.max_single_position_pct)
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
                    continue
                adjusted_qty = max(1, int(sizing.qty * 0.5))
                cost = adjusted_qty * price
                cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
                if cost > (portfolio_data["account"]["cash"] - cash_floor):
                    adjusted_qty = max(0, int((portfolio_data["account"]["cash"] - cash_floor) / price))
                    cost = adjusted_qty * price
                if adjusted_qty <= 0:
                    continue
                if self._high_beta_buy_blocked(symbol, cost, portfolio_data, high_beta_symbols):
                    continue
                readiness_score = sig.get("readiness_score", 0)
                reason_text = "Dip buy (SPY pullback, readiness " + str(round(readiness_score, 1)) + ") - " + sizing.reason
                trade = {
                    "symbol": symbol,
                    "qty": adjusted_qty,
                    "action": "BUY",
                    "reason": reason_text,
                    "intended_notional": cost,
                    "readiness_score": readiness_score,
                    "tier": "STRONG_NOW",
                    "is_dip_buy": True,
                }
                entry_candidates.append(trade)
                self._dip_buys_today += 1
                logger.info(f"DIP BUY candidate {symbol}: {adjusted_qty} shares @ ${price:.2f}")
                break

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

            # Hard cash gate: if cash is zero or negative, block ALL avg-in
            if portfolio_data["account"]["cash"] <= 0:
                logger.warning(f"CASH GATE: Cash is zero or negative — blocking all averaging in until cash is raised")
                return

        # 3b. Average into existing positions that are still entry-eligible
        for pos in portfolio_data.get("positions", []):
            symbol = pos.get("symbol")
            if not symbol or symbol not in signal_map:
                continue
            sig = signal_map[symbol]
            # Use mode-aware entry eligibility for averaging in too
            if not self._is_entry_eligible_for_mode(sig) or sig.get("tier") != "STRONG_NOW":
                continue

            pl_pct = pos.get("unrealized_plpc", 0) or 0.0
            # Only average in if position is down or readiness has strengthened
            min_readiness_for_avg_in = 70.0 if self.alpaca.is_paper() else 75.0
            if pl_pct >= 0 and sig.get("readiness_score", 0) < min_readiness_for_avg_in:
                continue

            price = self.alpaca.get_latest_quote(symbol)
            if price is None or price <= 0:
                continue

            _tier = sig.get("tier", "NOW")
            _tier_max_pct = self._tier_max_position_pct(_tier, self.risk_engine.config.max_single_position_pct)
            avg_in_cap = _tier_max_pct
            sizing = self.risk_engine.size_average_in(
                symbol=symbol,
                price=price,
                atr=sig.get("atr14", price * 0.02),
                portfolio_data=portfolio_data,
                current_positions=current_positions,
                signal_score=sig.get("total_score", 0),
                max_position_pct_override=avg_in_cap,
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
        requested_qty = trade["qty"]

        # Hard guard: never short-sell. Only sell what we actually own long.
        long_qty = 0
        positions = portfolio_data.get("positions", []) if portfolio_data else []
        for pos in positions:
            if pos.get("symbol") == symbol:
                q = pos.get("qty", 0)
                if isinstance(q, (int, float)) and q > 0:
                    long_qty = int(q)
                break
        # Fallback to internal _positions if portfolio_data was a stub
        if long_qty <= 0 and hasattr(self, "_positions"):
            pos = self._positions.get(symbol, {})
            q = pos.get("qty", 0)
            if isinstance(q, (int, float)) and q > 0:
                long_qty = int(q)
        if long_qty <= 0:
            logger.warning(f"BLOCKED SELL: no long position in {symbol}; refusing to short")
            return
        qty = min(requested_qty, long_qty)
        if qty <= 0:
            logger.warning(f"BLOCKED SELL: requested {requested_qty} {symbol} but only {long_qty} long available")
            return
        if qty != requested_qty:
            logger.warning(f"TRIMMED SELL: requested {requested_qty} {symbol}, selling only {qty}")

        # Dynamic TWAP threshold for sells too
        twap_threshold = 100
        sig = next((s for s in self._signals if s.get("symbol") == symbol), None)
        if sig and sig.get("avg_volume", 0) > 0:
            twap_threshold = max(100, int(sig["avg_volume"] * 0.001))
        # Belt-and-suspenders: if any open sell order exists, skip to avoid 403 dup
        if not self._dry_run:
            try:
                r = self.alpaca.session.get(
                    f"{self.alpaca.base_url}/v2/orders",
                    params={"status": "open", "symbols": symbol},
                    timeout=20
                )
                r.raise_for_status()
                for o in r.json():
                    if o.get("side", "").lower() == "sell":
                        logger.warning(f"BELT-AND-SUSPENDERS: Blocked duplicate sell for {symbol}: open order {o.get('id', '?')} exists")
                        return
            except Exception as e:
                logger.warning(f"BELT-AND-SUSPENDERS: Could not verify open orders for {symbol}: {e}")
        try:
            order_id = self.alpaca.submit_order(symbol, qty, "sell", dry_run=self._dry_run, twap_threshold=twap_threshold)
            self._log_trade(trade, order_id, portfolio_data)
            log_alert(
                subtype="exit",
                title=f"Sold {symbol}",
                description=f"{qty} shares — {trade.get('reason', '')}",
                symbol=symbol,
                severity="warning",
                rationale=trade.get('reason', ''),
                bot_response="Position closed as planned by risk rules."
            )
            logger.info(f"EXECUTED SELL: {qty} {symbol} ({trade['reason']})")
        except Exception as e:
            logger.error(f"Failed to sell {symbol}: {e}", exc_info=True)

    def _exit_position(self, symbol: str, reason: str = ""):
        """Sell an entire position (readiness-based exit)."""
        pos = self._positions.get(symbol)
        if not pos or pos.get("qty", 0) <= 0:
            return
        trade = {
            "symbol": symbol,
            "qty": pos["qty"],
            "action": "SELL",
            "reason": reason or "readiness_exit",
        }
        self._execute_sell(trade, {"account": {"portfolio_value": 0}})
        self.thesis_manager.remove_thesis(symbol)


    def _trim_weakest_positions(self, portfolio_data: Dict, target: int = 12, max_per_cycle: int = 3):
        """Auto-trim weakest positions when portfolio exceeds target ceiling.
        Priority: off-watchlist first, then lowest readiness, then worst P&L."""
        positions = portfolio_data.get("positions", [])
        total = len(positions)
        if total <= target:
            return
        trim = min(total - target, max_per_cycle)
        
        watchlist = self._load_watchlist_symbols()
        signal_map = {s.get("symbol"): s for s in self._signals}
        
        scored = []
        for p in positions:
            sym = p["symbol"]
            off_wl = sym not in watchlist
            sig = signal_map.get(sym, {})
            readiness = sig.get("readiness_score", 0)
            plpc = p.get("unrealized_plpc", 0)
            scored.append((off_wl, readiness, plpc, sym))
        
        # Sort: off-watchlist first, then readiness asc, then P&L asc
        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        
        for i in range(trim):
            off_wl, readiness, plpc, sym = scored[i]
            reason = f"MAX_POSITIONS auto-trim (#{i+1}/{trim})"
            logger.info(f"🪓 Auto-trimming {sym} — off_watchlist={off_wl}, readiness={readiness:.0f}, P&L={plpc:.1f}%")
            self._exit_position(sym, reason=reason)

    def _execute_buy(self, trade: Dict, portfolio_data: Dict, is_avg_in: bool = False):
        symbol = trade["symbol"]
        qty = trade["qty"]
        price = self.alpaca.get_latest_quote(symbol)
        if price is None or price <= 0:
            logger.warning(f"Skipping buy {symbol}: no usable quote")
            self._failed_buy_symbols.add(symbol)
            return

        # Margin guard: cash-only unless explicitly allowed; use REAL account cash
        if not self.risk_engine.config.allow_margin:
            # Always fetch current account cash from Alpaca so sequential orders within one cycle don't over-commit
            try:
                acc = self.alpaca.get_account()
                current_cash = float(acc.get("cash", portfolio_data.get("account", {}).get("cash", 0)))
            except Exception as e:
                logger.warning(f"Could not fetch live account cash for {symbol}: {e}; using portfolio_data cash")
                current_cash = portfolio_data.get("account", {}).get("cash", 0)
            notional = qty * price
            if notional > current_cash:
                max_qty = int(current_cash / price)
                if max_qty < 1:
                    logger.warning(f"CASH-ONLY BLOCK: {symbol} buy {qty} @ ${price:.2f} = ${notional:,.2f} exceeds cash ${current_cash:,.2f}")
                    self._failed_buy_symbols.add(symbol)
                    return
                logger.warning(f"CASH-ONLY REDUCE: {symbol} qty {qty} -> {max_qty} to stay within cash ${current_cash:,.2f}")
                qty = max_qty
                trade["qty"] = qty
            # Debit the tracked cash immediately so subsequent orders in the same cycle see it
            portfolio_data["account"]["cash"] = max(0, current_cash - (qty * price))

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
        # Dynamic TWAP threshold: 0.1% of ADV (e.g. 500k ADV = 500 shares)
        # Falls back to 100 if no volume data
        twap_threshold = 100
        sig = next((s for s in self._signals if s.get("symbol") == symbol), None)
        if sig and sig.get("avg_volume", 0) > 0:
            twap_threshold = max(100, int(sig["avg_volume"] * 0.001))
        # Extended-hours entries: smaller size, liquidity/spread checks, explicit flag
        is_ext_hours = False
        if self.risk_engine.config.extended_hours_enabled and self.alpaca._is_extended_hours() and not self.alpaca._is_us_market_hours():
            if sig and sig.get("avg_volume", 0) >= self.risk_engine.config.extended_hours_min_avg_volume:
                spread = self.alpaca._get_spread_pct(symbol)
                if spread <= self.risk_engine.config.extended_hours_max_spread_pct:
                    is_ext_hours = True
                    qty = max(1, int(qty * 0.5))  # half size for extended hours
                    trade["qty"] = qty
                    trade["reason"] = trade.get("reason", "") + " | extended-hours"
                    logger.info(f"EXTENDED HOURS entry {symbol}: half size {qty}, spread {spread:.2%}")
                else:
                    logger.info(f"EXTENDED HOURS SKIP {symbol}: spread {spread:.2%} too wide")
                    return
            else:
                logger.info(f"EXTENDED HOURS SKIP {symbol}: avg volume {sig.get('avg_volume', 0)} below threshold")
                return
        try:
            order_id = self.alpaca.submit_tiered_order(symbol, qty, "buy", tier=tier, dry_run=self._dry_run, twap_threshold=twap_threshold, extended_hours=is_ext_hours)
            self._log_trade(trade, order_id, portfolio_data)
            log_alert(
                subtype="entry",
                title=f"Bought {symbol}",
                description=f"{qty} shares @ ${price:.2f} — {trade.get('reason', '')}",
                symbol=symbol,
                value=price,
                value_label="Entry price",
                severity="info",
                rationale=trade.get('reason', ''),
                bot_response=f"Position opened. Target: trim at +{self.risk_engine.config.trim_profit_pct*100:.0f}%, full exit at +{self.risk_engine.config.full_exit_profit_pct*100:.0f}%."
            )
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
                    "readiness_score": trade.get("readiness_score"),
                    "tier": trade.get("tier"),
                    "confirmation_count": trade.get("confirmation_count"),
                    "total_score": trade.get("total_score"),
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
        logger.info("STONK.AI Trading Bot v2.5 Starting")
        logger.info(f"Mode: {'PAPER (fake money)' if self.alpaca.is_paper() else 'LIVE (real money)'}")
        logger.info(f"Dry run: {self._dry_run}")
        logger.info("Strategy: readiness-driven quality-momentum with thesis exits")
        logger.info(f"Entry gate: readiness >= 77 AND >= 5 confirmations AND above_ema")
        logger.info(f"Position caps: 12% STRONG_NOW / 8% other tiers; 25% sector cap")
        logger.info(f"Exits: -3% hard cut + ATR trailing stops + readiness < 40 (2-day min hold in RISK_ON)")
        logger.info(f"Drawdown halt: {self.risk_engine.config.new_entry_max_drawdown_pct:.0%}")
        logger.info("=" * 70)

        self.refresh_signals()

        while True:
            try:
                self.maybe_refresh_signals()
                self.run_cycle()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(TradingConfig.CYCLE_INTERVAL_SECONDS)




# --- 403 GUARD v2 (fixed 2026-06-29) ---
# Uses raw session.get because AlpacaClient has no list_orders wrapper.
import logging as _guard_logging
_original_submit_order = AlpacaClient.submit_order

def _guarded_submit_order_v2(self, symbol, qty, side, dry_run=False, use_limit=True, twap_threshold=100, extended_hours=False):
    if side.lower() == 'sell' and not dry_run:
        try:
            r = self.session.get(
                f"{self.base_url}/v2/orders",
                params={"status": "open", "symbols": symbol},
                timeout=20
            )
            r.raise_for_status()
            open_orders = r.json()
            for o in open_orders:
                if o.get("side", "").lower() == "sell":
                    _guard_logging.getLogger(__name__).warning(
                        f"Blocked duplicate sell for {symbol}: open order {o.get('id', '?')} exists"
                    )
                    blocked = type("BlockedOrder", (), {
                        "id": f"blocked_dup_{o.get('id', '?')}",
                        "status": "blocked",
                        "symbol": symbol,
                    })()
                    return blocked
        except Exception as e:
            _guard_logging.getLogger(__name__).error(f"Error checking open orders for {symbol}: {e}")
            # FAIL CLOSED: if we can't verify no open sell exists, block it
            _guard_logging.getLogger(__name__).warning(f"Blocked sell for {symbol}: cannot verify open orders (safe mode)")
            blocked = type("BlockedOrder", (), {
                "id": f"blocked_safe_{symbol}",
                "status": "blocked",
                "symbol": symbol,
            })()
            return blocked
    return _original_submit_order(self, symbol, qty, side, dry_run=dry_run, use_limit=use_limit, twap_threshold=twap_threshold, extended_hours=extended_hours)

AlpacaClient.submit_order = _guarded_submit_order_v2
# --- END 403 GUARD ---


# --- Market-order sell wrapper (re-applied) ---
_original_build_payload = AlpacaClient._build_order_payload

def _market_on_sell_payload(self, symbol, qty, side, use_limit=True, extended_hours=False):
    # Force market orders for all sells (stops/exits must execute; limit orders can go stale above market)
    if side.lower() == 'sell':
        return _original_build_payload(self, symbol, qty, side, use_limit=False, extended_hours=extended_hours)
    return _original_build_payload(self, symbol, qty, side, use_limit=use_limit, extended_hours=extended_hours)

AlpacaClient._build_order_payload = _market_on_sell_payload


def _iv_scalar(iv):
    """Extract scalar 30d IV from either legacy float or new IV summary dict."""
    if iv is None:
        return None
    if isinstance(iv, dict):
        return iv.get("iv_30d") or iv.get("options_implied_vol") or None
    try:
        return float(iv)
    except (TypeError, ValueError):
        return None

if __name__ == "__main__":
    bot = STONKAIBot()
    bot.run()
