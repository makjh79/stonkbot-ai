#!/usr/bin/env python3
"""Sync Bot state from real Alpaca paper account to dm_paper/ files.

Overwrites sleeve_state.json and appends to sleeve_equity.csv so the website
shows actual Bot performance, not theoretical Yahoo-based simulation.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

if os.geteuid() == 0:
    print("ERROR: sync_bot_state.py must not run as root.", file=sys.stderr)
    sys.exit(1)

BASE = Path("/opt/stonk-ai/dm_paper")
BASE.mkdir(parents=True, exist_ok=True)
WEB = Path("/var/www/hedge-fund-website/dm_paper")
WEB.mkdir(parents=True, exist_ok=True)

ALPACA_CFG_PATHS = [
    Path("/opt/stonk-ai/alpaca_config.json"),
    Path("/var/www/hedge-fund-website/alpaca_config.json"),
]


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

    def get_clock(self) -> Dict:
        try:
            r = self.session.get(f"{self.base_url}/v2/clock", timeout=20)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"Warning: clock check failed: {e}", file=sys.stderr)
        return {}


def atomic_write(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.rename(path)


def copy_to_web_root(src_state: Path, src_hist: Path, dst_state: Path, dst_hist: Path, src_exec: Path | None = None, dst_exec: Path | None = None):
    """Copy files to web root using normal permissions."""
    shutil.copy2(src_state, dst_state)
    shutil.copy2(src_hist, dst_hist)
    os.chmod(dst_state, 0o644)
    os.chmod(dst_hist, 0o644)
    if src_exec and dst_exec and src_exec.exists():
        shutil.copy2(src_exec, dst_exec)
        os.chmod(dst_exec, 0o644)


def main():
    cfg = load_alpaca_config()
    client = AlpacaClient(cfg)

    acct = client.get_account()
    equity = float(acct.get("equity", 0))
    cash = float(acct.get("cash", 0))
    positions = client.get_positions()

    holdings: Dict[str, float] = {}
    for p in positions:
        sym = p.get("symbol")
        mv = float(p.get("market_value", 0))
        if sym and mv > 0:
            holdings[sym] = mv
    # defensive: cash is the remainder if any
    invested = sum(holdings.values())
    cash_remaining = max(0.0, equity - invested)
    if cash_remaining > 1:
        holdings["CASH"] = cash_remaining

    state_path = BASE / "sleeve_state.json"
    exec_log_path = BASE / "rebalance_executions.json"
    prev_state = {}
    if state_path.exists():
        try:
            prev_state = json.loads(state_path.read_text())
        except Exception:
            pass

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Determine last executed rebalance from log if available.
    last_rebalance_at = prev_state.get("last_rebalance_at")
    if exec_log_path.exists():
        try:
            exec_log = json.loads(exec_log_path.read_text())
            executed = [e for e in exec_log if e.get("executed") and not e.get("dry_run")]
            if executed:
                last_rebalance_at = executed[-1].get("timestamp", last_rebalance_at)
        except Exception:
            pass

    state = {
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "holdings": {k: round(v, 2) for k, v in holdings.items()},
        "inception": prev_state.get("inception", "2026-08-24"),
        "era_start": prev_state.get("era_start", "2026-09-29"),
        "era_baseline": prev_state.get("era_baseline", 87708.12),
        "last_date": today,
        "last_signal_month": prev_state.get("last_signal_month"),
        "last_rebalance_at": last_rebalance_at,
        "gate": prev_state.get("gate", "QQQ"),
        "mode": "paper",
        "source": "alpaca",
    }
    atomic_write(state_path, json.dumps(state, indent=2) + "\n")

    # Append equity history
    hist_path = BASE / "sleeve_equity.csv"
    summary = "|".join(f"{s}:{v:.2f}" for s, v in sorted(holdings.items(), key=lambda x: -x[1])[:5])
    line = f"{today},{equity:.2f},{summary}\n"
    if hist_path.exists():
        existing = hist_path.read_text()
        if not existing.endswith("\n"):
            existing += "\n"
        # avoid duplicate date
        if f"{today}," not in existing:
            atomic_write(hist_path, existing + line)
        else:
            # replace last line for today
            lines = existing.strip().split("\n")
            lines = [l for l in lines if not l.startswith(today + ",")]
            lines.append(line.strip())
            atomic_write(hist_path, "\n".join(lines) + "\n")
    else:
        atomic_write(hist_path, "date,equity,summary\n" + line)

    # Copy to web root
    try:
        copy_to_web_root(
            state_path, hist_path, WEB / "sleeve_state.json", WEB / "sleeve_equity.csv",
            src_exec=exec_log_path, dst_exec=WEB / "rebalance_executions.json",
        )
    except Exception as e:
        print(f"Warning: could not copy to web root: {e}", file=sys.stderr)

    # Also publish legacy portfolio_data.json (hero/race-card fallback path) so it
    # never goes stale while the intraday bot is retired. Same canonical Alpaca data.
    try:
        last_equity = float(acct.get("last_equity", 0) or 0)
        buying_power = float(acct.get("buying_power", 0) or 0)
        legacy_positions = []
        for p in positions:
            sym = p.get("symbol")
            if not sym:
                continue
            legacy_positions.append({
                "symbol": sym,
                "qty": p.get("qty"),
                "avg_entry": float(p.get("avg_entry_price", 0) or 0),
                "current": float(p.get("current_price", 0) or 0),
                "market_value": float(p.get("market_value", 0) or 0),
                "cost_basis": float(p.get("cost_basis", 0) or 0),
                "unrealized_pl": float(p.get("unrealized_pl", 0) or 0),
                "unrealized_plpc": float(p.get("unrealized_plpc", 0) or 0),
            })
        open_pl = round(sum(x["unrealized_pl"] for x in legacy_positions), 2)
        portfolio_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "ok",
            "portfolio_value": round(equity, 2),
            "cash": round(cash, 2),
            "account": {
                "portfolio_value": round(equity, 2),
                "cash": round(cash, 2),
                "equity": round(equity, 2),
                "buying_power": round(buying_power, 2),
                "last_equity": round(last_equity, 2),
            },
            "positions": legacy_positions,
            "total_pl": round(equity - 87708.12, 2),
            "total_pl_pct": round((equity - 87708.12) / 87708.12 * 100, 2),
            "open_total_pl": open_pl,
            "open_total_pl_pct": round(open_pl / max(1.0, equity - open_pl - cash) * 100, 2) if legacy_positions else 0.0,
            "day_change": round((equity - last_equity) / last_equity * 100, 2) if last_equity else 0.0,
        }
        atomic_write(Path("/var/www/hedge-fund-website/portfolio_data.json"), json.dumps(portfolio_payload, indent=2) + "\n")
    except Exception as e:
        print(f"Warning: could not write portfolio_data.json: {e}", file=sys.stderr)

    clock = client.get_clock()
    print(f"Synced Bot state: equity=${equity:,.2f} cash=${cash:,.2f} positions={len(positions)} market_open={clock.get('is_open')}")
    for sym, mv in sorted(holdings.items(), key=lambda x: -x[1]):
        print(f"  {sym}: ${mv:,.2f}")


if __name__ == "__main__":
    main()
