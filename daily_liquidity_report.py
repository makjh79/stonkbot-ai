"""
daily_liquidity_report.py — Daily slippage and liquidity report for watchlist + holdings.

Run via cron pre-market or every 4 hours during market hours.
Flags symbols where expected spread cost exceeds 20 bps (liquidity warning).
Outputs JSON to /opt/stonk-ai/liquidity_report.json and logs to Telegram if alerts configured.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import execution_analytics

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SPREAD_WARNING_BPS = 20.0
SPREAD_CRITICAL_BPS = 50.0


def _load_json(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load {path}: {e}")
        return {}


def get_target_symbols() -> List[str]:
    symbols = set()

    watchlist = _load_json("/var/www/hedge-fund-website/ai_watchlist_live.json")
    for item in watchlist.get("watchlist", []):
        sym = item.get("symbol")
        if sym:
            symbols.add(sym)
    for sym in watchlist.get("prices", {}):
        symbols.add(sym)

    portfolio = _load_json("/var/www/hedge-fund-website/portfolio_data.json")
    for pos in portfolio.get("positions", []):
        sym = pos.get("symbol")
        if sym:
            symbols.add(sym)

    return sorted(symbols)


def main():
    symbols = get_target_symbols()
    if not symbols:
        logger.warning("No symbols found; exiting.")
        return

    logger.info(f"Running liquidity report for {len(symbols)} symbols...")
    report = {
        "generated_at": datetime.now().isoformat(),
        "symbol_count": len(symbols),
        "warning_threshold_bps": SPREAD_WARNING_BPS,
        "critical_threshold_bps": SPREAD_CRITICAL_BPS,
        "symbols": {},
        "warnings": [],
        "critical": [],
    }

    for sym in symbols:
        try:
            est = execution_analytics.estimate_slippage(sym, 100, 100.0)
            if not est:
                continue
            report["symbols"][sym] = {
                "half_spread_bps": est["half_spread_bps"],
                "adv": est["adv"],
                "total_bps": est["total_bps"],
            }
            spread = est["half_spread_bps"]
            if spread >= SPREAD_CRITICAL_BPS:
                report["critical"].append({"symbol": sym, "spread_bps": spread})
            elif spread >= SPREAD_WARNING_BPS:
                report["warnings"].append({"symbol": sym, "spread_bps": spread})
        except Exception as e:
            logger.warning(f"Failed liquidity check for {sym}: {e}")

    out_path = Path("/opt/stonk-ai/liquidity_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"Wrote {out_path}")
    logger.info(f"Warnings ({len(report['warnings'])}): {report['warnings']}")
    logger.info(f"Critical ({len(report['critical'])}): {report['critical']}")


def _record_heartbeat():
    try:
        import subprocess
        subprocess.run(
            ["/usr/bin/python3", "/opt/stonk-ai/heartbeat_tracker.py", "daily_liquidity_report_am"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
    _record_heartbeat()
