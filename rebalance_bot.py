#!/usr/bin/env python3
"""Rebalance Alpaca paper account to match the Bot target basket.

Reads dm_paper/sleeve_rebalance_signal.json for the Bot target symbols,
compares against current Alpaca paper positions, and rebalances into equal
notional weights using only available cash (no margin). Default mode is DRY-RUN.
Pass --execute to submit real orders. Never runs as root.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

if os.geteuid() == 0:
    print("ERROR: rebalance_bot.py must not run as root.", file=sys.stderr)
    sys.exit(1)

BASE = Path("/opt/stonk-ai")
WEB = Path("/var/www/hedge-fund-website")
DM = BASE / "dm_paper"
EXEC_LOG = DM / "rebalance_executions.json"
SIGNAL_FILE = BASE / "dm_paper" / "sleeve_rebalance_signal.json"
ALPACA_CFG_PATHS = [
    BASE / "alpaca_config.json",
    WEB / "alpaca_config.json",
]

_run_dir = BASE / "run"
_run_dir.mkdir(parents=True, exist_ok=True)
_pid_file = _run_dir / "rebalance_bot.pid"


def _acquire_instance_lock() -> bool:
    import atexit
    try:
        if _pid_file.exists():
            pid_text = _pid_file.read_text().strip()
            try:
                old_pid = int(pid_text)
                os.kill(old_pid, 0)
                print(f"ERROR: rebalance_bot.py already running (pid {old_pid}). Refusing to start.", file=sys.stderr)
                return False
            except (ValueError, OSError, ProcessLookupError):
                pass
        with open(_pid_file, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(lambda: _pid_file.unlink(missing_ok=True))
        return True
    except Exception as e:
        print(f"ERROR: could not acquire PID lock: {e}", file=sys.stderr)
        return False


def load_alpaca_config() -> Dict:
    for p in ALPACA_CFG_PATHS:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception as e:
                print(f"Warning: could not load {p}: {e}", file=sys.stderr)
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
            print(f"Warning: clock check failed: {e}", file=sys.stderr)
        return False

    def submit_order(self, symbol: str, side: str, qty: float = 0, notional: float = 0) -> Dict:
        payload = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        if side.lower() == "buy" and notional > 0:
            payload["notional"] = str(round(notional, 2))
        elif qty > 0:
            payload["qty"] = str(qty)
        else:
            raise ValueError(f"Order for {symbol} missing valid qty/notional")
        r = self.session.post(f"{self.base_url}/v2/orders", json=payload, timeout=45)
        r.raise_for_status()
        return r.json()


def get_account_summary(client: AlpacaClient) -> Tuple[float, float, Dict[str, float], Dict[str, float]]:
    acct = client.get_account()
    equity = float(acct.get("equity", 0))
    cash = float(acct.get("cash", 0))
    positions = client.get_positions()
    holdings: Dict[str, float] = {}
    quantities: Dict[str, float] = {}
    pos_mv = 0.0
    for p in positions:
        sym = p.get("symbol")
        mv = float(p.get("market_value", 0))
        qty = float(p.get("qty", 0))
        if sym and mv > 0:
            holdings[sym] = mv
            quantities[sym] = qty
            pos_mv += mv
    total = equity if equity > 0 else (cash + pos_mv)
    return total, cash, holdings, quantities


def compute_rebalance_orders(
    total_equity: float,
    available_cash: float,
    current_holdings: Dict[str, float],
    current_quantities: Dict[str, float],
    target_basket: Dict[str, float],
    reserve_cash: float = 500.0,
) -> List[Dict]:
    orders = []
    # Sell any current position not in the Bot basket
    sell_proceeds = 0.0
    for sym in sorted(current_holdings):
        if sym not in target_basket:
            qty = current_quantities.get(sym, 0)
            if qty > 0:
                mv = current_holdings[sym]
                orders.append({
                    "side": "sell",
                    "symbol": sym,
                    "qty": qty,
                    "notional": mv,
                    "reason": "not in Bot basket",
                })
                sell_proceeds += mv

    # Buy target basket in equal notional weights using available cash + sell proceeds
    target_names = [s for s in target_basket if s != "CASH"]
    if not target_names:
        return orders

    deployable = max(0, available_cash + sell_proceeds - reserve_cash)
    notional_each = deployable / len(target_names)

    for sym in sorted(target_names):
        if notional_each > 50:
            orders.append({
                "side": "buy",
                "symbol": sym,
                "qty": 0,
                "notional": round(notional_each, 2),
                "reason": f"Bot basket target (${notional_each:,.2f})",
            })
    return orders


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def append_execution_record(
    executed: bool,
    signal_date: str,
    pre_equity: float,
    pre_cash: float,
    pre_holdings: Dict[str, float],
    orders: List[Dict],
    order_results: List[Dict],
    dry_run: bool,
    reason: str,
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signal_date": signal_date,
        "executed": executed,
        "dry_run": dry_run,
        "pre_equity": round(pre_equity, 2),
        "pre_cash": round(pre_cash, 2),
        "pre_holdings": {k: round(v, 2) for k, v in pre_holdings.items()},
        "orders": orders,
        "order_results": order_results,
        "reason": reason,
    }
    existing = []
    if EXEC_LOG.exists():
        existing = json.loads(EXEC_LOG.read_text())
    existing.append(record)
    atomic_write(EXEC_LOG, json.dumps(existing, indent=2) + "\n")


def main():
    if not _acquire_instance_lock():
        return

    parser = argparse.ArgumentParser(description="Rebalance Alpaca paper account to Bot basket")
    parser.add_argument("--execute", action="store_true", help="Submit real orders (default is dry-run)")
    parser.add_argument("--extended-hours", action="store_true", help="Allow order submission outside US market hours")
    parser.add_argument("--reserve", type=float, default=500.0, help="Cash reserve to leave in account")
    parser.add_argument("--skip-log", action="store_true", help="Skip writing execution record")
    args = parser.parse_args()

    cfg = load_alpaca_config()
    client = AlpacaClient(cfg)

    acct = client.get_account()
    total, cash, current_holdings, current_quantities = get_account_summary(client)
    market_open = client.is_market_open()

    # Use the generated monthly signal file as the authoritative target basket,
    # not sleeve_state.json (which is overwritten from Alpaca and only shows
    # current holdings).
    signal = json.loads(SIGNAL_FILE.read_text())
    signal_date = signal.get("date")
    target_symbols = sorted(signal.get("target", []))
    if not target_symbols:
        print("\nABORT: no target symbols in sleeve_rebalance_signal.json.")
        return
    if signal.get("signal") is False:
        print("\nNo rebalance needed: sleeve_rebalance_signal.json says signal=false.")
        return
    target_basket = {s: 1.0 / len(target_symbols) for s in target_symbols}

    print(f"Account: {acct.get('account_number')} ({'paper' if 'paper' in client.base_url else 'LIVE'})")
    print(f"Market open: {market_open}")
    print(f"Total equity: ${total:,.2f}")
    print(f"Available cash: ${cash:,.2f}")
    print(f"Current positions ({len(current_holdings)}):")
    for sym, mv in sorted(current_holdings.items(), key=lambda x: -x[1]):
        print(f"  {sym:6} ${mv:>10,.2f}")
    print(f"\nBot target basket ({len(target_basket)}):")
    for sym, w in sorted(target_basket.items(), key=lambda x: -x[1]):
        print(f"  {sym:6} {w*100:>6.1f}%")

    orders = compute_rebalance_orders(total, cash, current_holdings, current_quantities, target_basket, reserve_cash=args.reserve)

    if not orders:
        print("\nNo rebalance needed. Account already matches Bot basket within tolerance.")
        return

    print(f"\nRebalance plan ({len(orders)} orders):")
    total_sell = 0
    total_buy = 0
    for o in orders:
        print(f"  {o['side'].upper():4} {o['symbol']:6} notional=${o['notional']:,.2f} — {o['reason']}")
        if o["side"] == "sell":
            total_sell += o["notional"]
        else:
            total_buy += o["notional"]

    print(f"\nEstimated proceeds from sales: ${total_sell:,.2f}")
    print(f"Estimated buy deployment:      ${total_buy:,.2f}")
    print(f"Estimated cash after:          ${cash + total_sell - total_buy:,.2f}")

    if not args.skip_log:
        append_execution_record(
            executed=False,
            signal_date=signal_date,
            pre_equity=total,
            pre_cash=cash,
            pre_holdings=current_holdings,
            orders=orders,
            order_results=[],
            dry_run=True,
            reason=signal.get("reason", "dry-run plan"),
        )

    if not args.execute:
        print("\nDRY-RUN: no orders submitted. Pass --execute to trade.")
        return

    if not market_open and not args.extended_hours:
        print("\nABORT: market is closed. Pass --extended-hours to override or wait for US market hours.")
        return

    print("\nSubmitting orders...")
    order_results = []
    for o in orders:
        try:
            if o["side"] == "buy":
                result = client.submit_order(o["symbol"], o["side"], notional=o["notional"])
            else:
                result = client.submit_order(o["symbol"], o["side"], qty=o["qty"])
            order_results.append({"symbol": o["symbol"], "side": o["side"], "status": "submitted", "order_id": result.get("id"), "status": result.get("status")})
            print(f"  Submitted {o['side']} {o['symbol']}: id={result.get('id')} status={result.get('status')}")
        except Exception as e:
            order_results.append({"symbol": o["symbol"], "side": o["side"], "status": "failed", "error": str(e)})
            print(f"  FAILED {o['side']} {o['symbol']}: {e}")

    if not args.skip_log:
        append_execution_record(
            executed=True,
            signal_date=signal_date,
            pre_equity=total,
            pre_cash=cash,
            pre_holdings=current_holdings,
            orders=orders,
            order_results=order_results,
            dry_run=False,
            reason=signal.get("reason", "executed rebalance"),
        )

    print("\nDone. Allow a few minutes for fills and sync before refreshing the site.")


if __name__ == "__main__":
    main()
