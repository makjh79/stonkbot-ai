#!/usr/bin/env python3
"""Live Alpaca executor for the DM-gated individual-stock momentum sleeve.

- Reads dm_paper/sleeve_state.json to know target holdings.
- Compares against current Alpaca paper positions.
- Rebalances once per day after US close (or on demand).
- Sells losers / trims to target, buys new targets.
- Logs all trades to TRADES_LOG.md and trades_log.json.

This is intended to REPLACE the broken intraday bot with the working individual-stock
momentum sleeve already validated in dm_paper since 2026-08-24.
"""
import json
import logging
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Never run as root
if os.geteuid() == 0:
    print("ERROR: sleeve_trader.py must not run as root.", file=sys.stderr)
    sys.exit(1)

# Monthly Bot strategy now uses rebalance_bot.py as its executor.
# This script is kept for reference but should not be scheduled.
BOT_SENTINEL = Path("/opt/stonk-ai/BOT_STRATEGY_ACTIVE")
if BOT_SENTINEL.exists():
    print(f"INFO: {BOT_SENTINEL.name} is present. Use rebalance_bot.py for monthly Bot execution.", file=sys.stderr)
    sys.exit(0)

BASE = Path("/opt/stonk-ai")
WEB = Path("/var/www/hedge-fund-website")
SLEEVE_STATE = BASE / "dm_paper" / "sleeve_state.json"
SLEEVE_SIGNAL = BASE / "dm_paper" / "sleeve_rebalance_signal.json"
ALPACA_CFG_PATHS = [
    BASE / "alpaca_config.json",
    WEB / "alpaca_config.json",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE / "logs" / "sleeve_trader.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def load_alpaca_config() -> Dict:
    for p in ALPACA_CFG_PATHS:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception as e:
                logger.warning(f"Could not load {p}: {e}")
    return {
        "api_key": os.getenv("ALPACA_API_KEY"),
        "api_secret": os.getenv("ALPACA_SECRET_KEY"),
        "base_url": os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
    }


class AlpacaClient:
    def __init__(self, cfg: Dict):
        import requests
        self.api_key = cfg.get("api_key") or cfg.get("APCA_API_KEY_ID")
        self.api_secret = cfg.get("api_secret") or cfg.get("APCA_API_SECRET_KEY")
        self.base_url = cfg.get("base_url", "https://paper-api.alpaca.markets").rstrip("/")
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API key/secret missing")
        self.session = requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Accept": "application/json",
        })

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
            logger.warning(f"Clock check failed: {e}")
        return False

    def get_latest_quote(self, symbol: str) -> Optional[float]:
        """Best-effort price from quote endpoint; fall back to latest trade / snapshot if quote missing."""
        # 1) Try market API latest quote (works for some endpoints)
        try:
            r = self.session.get(f"{self.base_url}/v2/stocks/{symbol}/quotes/latest", timeout=20)
            if r.status_code == 200:
                q = r.json().get("quote", {})
                bp = q.get("bp")
                ap = q.get("ap")
                if bp and ap and bp > 0:
                    return round((bp + ap) / 2, 2)
        except Exception as e:
            logger.debug(f"Quote endpoint for {symbol}: {e}")
        # 2) Try market API latest trade
        try:
            r = self.session.get(f"{self.base_url}/v2/stocks/{symbol}/trades/latest", timeout=20)
            if r.status_code == 200:
                t = r.json().get("trade", {})
                p = t.get("p")
                if p and p > 0:
                    return round(p, 2)
        except Exception as e:
            logger.debug(f"Trade endpoint for {symbol}: {e}")
        # 3) Fall back to data API snapshot
        try:
            data_url = self._cfg.get("data_url", "https://data.alpaca.markets").rstrip("/")
            r = self.session.get(f"{data_url}/v2/stocks/snapshots?symbols={symbol}&feed=sip", timeout=20)
            if r.status_code == 200:
                data = r.json()
                snap = data.get("snapshots", data).get(symbol, {})
                p = snap.get("latestTrade", {}).get("p") or snap.get("dailyBar", {}).get("c")
                if p and p > 0:
                    return round(p, 2)
        except Exception as e:
            logger.debug(f"Snapshot for {symbol}: {e}")
        return None

    def submit_market_order(self, symbol: str, qty: int, side: str, dry_run: bool = False) -> Optional[str]:
        if dry_run:
            logger.info(f"DRY RUN {side.upper()} {qty} {symbol}")
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
            return r.json().get("id")
        except Exception as e:
            logger.error(f"Failed to {side} {qty} {symbol}: {e}")
            return None


def load_sleeve_state() -> Dict:
    if not SLEEVE_STATE.exists():
        raise FileNotFoundError(f"{SLEEVE_STATE} missing — run dm_paper/dm_tracker.py first")
    return json.loads(SLEEVE_STATE.read_text())


def current_alpaca_positions(client: AlpacaClient) -> Tuple[float, Dict[str, float]]:
    """Return (total equity, {symbol: market_value})."""
    acct = client.get_account()
    equity = float(acct.get("equity", 0))
    cash = float(acct.get("cash", 0))
    positions = client.get_positions()
    holdings: Dict[str, float] = {}
    pos_mv = 0.0
    for p in positions:
        sym = p.get("symbol")
        mv = float(p.get("market_value", 0))
        if sym and mv > 0:
            holdings[sym] = mv
            pos_mv += mv
    # Use equity if available, otherwise cash + position MV
    total = equity if equity > 0 else (cash + pos_mv)
    return total, holdings


def target_weights_from_state(state: Dict) -> Dict[str, float]:
    equity = float(state.get("equity", 100000))
    holdings = state.get("holdings", {})
    weights = {}
    for sym, val in holdings.items():
        if sym == "CASH":
            continue
        weights[sym] = float(val) / equity if equity > 0 else 0
    return weights


def compute_rebalance_trades(
    total_equity: float,
    current: Dict[str, float],
    target_weights: Dict[str, float],
    prices: Dict[str, float],
    min_trade: float = 250.0,
    buffer_pct: float = 0.005,  # allow 0.5% drift without trading
) -> List[Tuple[str, str, int, float]]:
    """Return list of (symbol, side, qty, notional) trades to hit target weights."""
    all_symbols = set(current) | set(target_weights)
    trades: List[Tuple[str, str, int, float]] = []
    for sym in all_symbols:
        price = prices.get(sym)
        if not price or price <= 0:
            continue
        cur_w = current.get(sym, 0) / total_equity if total_equity > 0 else 0
        tgt_w = target_weights.get(sym, 0)
        delta_w = tgt_w - cur_w
        if abs(delta_w) < buffer_pct:
            continue
        notional = delta_w * total_equity
        if abs(notional) < min_trade:
            continue
        side = "buy" if notional > 0 else "sell"
        qty = int(abs(notional) / price)
        if qty <= 0:
            continue
        trades.append((sym, side, qty, notional))
    return trades


def log_trade(symbol: str, side: str, qty: int, price: float, reason: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "timestamp": now,
        "symbol": symbol,
        "action": side.upper(),
        "qty": qty,
        "price": price,
        "rationale": reason,
    }
    # Append to trades_log.json
    log_path = WEB / "trades_log.json"
    try:
        data = json.loads(log_path.read_text()) if log_path.exists() else []
        if isinstance(data, dict):
            data = data.get("trades", [])
        data.append(entry)
        log_path.write_text(json.dumps(data, indent=1))
    except Exception as e:
        logger.warning(f"Could not update trades_log.json: {e}")


def main(dry_run: bool = False):
    logger.info(f"Starting sleeve_trader dry_run={dry_run}")
    client = AlpacaClient(load_alpaca_config())

    # Read daily signal file produced by dm_tracker.py
    signal_data = {}
    if SLEEVE_SIGNAL.exists():
        try:
            signal_data = json.loads(SLEEVE_SIGNAL.read_text())
            logger.info(f"Signal file: signal={signal_data.get('signal')} — {signal_data.get('reason')}")
        except Exception as e:
            logger.warning(f"Could not read signal file: {e}")

    state = load_sleeve_state()
    targets = target_weights_from_state(state)
    logger.info(f"Sleeve target weights: {targets}")

    total_equity, current = current_alpaca_positions(client)
    logger.info(f"Alpaca equity ${total_equity:.2f}, current positions: {current}")

    # Authoritative check: compare actual Alpaca positions to target weights.
    all_symbols = sorted(set(current) | set(targets))
    needs_trade = False
    drift_reasons = []
    buffer_pct = 0.005
    min_trade_dollar = 250.0
    for sym in all_symbols:
        cur_w = current.get(sym, 0.0) / total_equity if total_equity > 0 else 0.0
        tgt_w = targets.get(sym, 0.0)
        if abs(cur_w - tgt_w) > buffer_pct and abs(cur_w - tgt_w) * total_equity > min_trade_dollar:
            needs_trade = True
            drift_reasons.append(f"{sym}: {cur_w:.2%} vs target {tgt_w:.2%}")

    if not needs_trade:
        logger.info("No rebalance needed — Alpaca positions already match sleeve target within buffer.")
        return

    if signal_data.get("signal") is False:
        logger.info("Signal file says no change, but Alpaca positions drifted; trading anyway to align account.")
    elif signal_data.get("signal") is True:
        logger.info(f"Rebalance signal active: {signal_data.get('reason')}")

    # Fetch prices for all current + target symbols
    price_symbols = sorted(set(current) | set(targets))
    prices: Dict[str, float] = {}
    for sym in price_symbols:
        q = client.get_latest_quote(sym)
        if q:
            prices[sym] = q
        else:
            logger.warning(f"No quote for {sym}; will skip")

    trades = compute_rebalance_trades(total_equity, current, targets, prices)
    if not trades:
        logger.info("No rebalance trades needed.")
        return

    logger.info(f"Rebalance trades to execute: {len(trades)}")
    for sym, side, qty, notional in trades:
        price = prices.get(sym)
        if not price:
            continue
        order_id = client.submit_market_order(sym, qty, side, dry_run=dry_run)
        reason = f"sleeve rebalance to target weight {targets.get(sym, 0):.2%}"
        if signal_data.get("reason"):
            reason += f" (signal: {signal_data['reason']})"
        if order_id:
            log_trade(sym, side, qty, price, reason)
            logger.info(f"Executed {side} {qty} {sym} @ ~${price} (order {order_id})")
        else:
            logger.error(f"Failed to execute {side} {qty} {sym}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
