#!/usr/bin/env python3
"""Live quotes poller — tier-2 real-time layer for the public site.

Every POLL_SEC during US market hours (09:30-16:00 ET, Mon-Fri, ex-holidays):
  1. Reads canonical positions + cash from the bot-written portfolio_data.json
     (read-only — the bot stays the single writer of canonical state).
  2. Batch-fetches SIP snapshots for held symbols + SPY via the Alpaca hub
     (one HTTP request per cycle).
  3. Computes live portfolio value, day change, and per-position unrealized P&L.
  4. Atomically writes live_quotes.json to the web root.

The site polls that file every 10s and only uses it when <60s old, so any
failure here silently falls back to the standard 5-minute pipeline.

Added 2026-07-22. Run manually with --once to print a single payload.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from alpaca_data import get_data_hub
from fetch_data_simple import is_market_open
from stonk_utils import atomic_write_json

PORTFOLIO_FILE = Path('/var/www/hedge-fund-website/portfolio_data.json')
OUT_FILE = Path('/var/www/hedge-fund-website/live_quotes.json')
LOG_FILE = Path('/opt/stonk-ai/logs/live_quotes.log')

SPY_RESET_PRICE = 747.71  # Jul 7, 2026 baseline — matches fetch_market_indices RESET_PRICES
EXPERIMENT_BASELINE = 100000.0
POLL_SEC = 15
IDLE_SEC = 300

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)
logger = logging.getLogger('live_quotes')


def build_payload(hub) -> dict:
    """One poll cycle: positions + cash -> snapshots -> live payload."""
    pdata = json.loads(PORTFOLIO_FILE.read_text())
    positions = pdata.get('positions', []) or []
    cash = float(pdata.get('account', {}).get('cash', 0) or 0)

    symbols = [p['symbol'] for p in positions if p.get('symbol')]
    snaps = hub.get_snapshots(symbols + ['SPY'])

    live_positions = {}
    market_value = 0.0
    prev_market_value = 0.0
    missing = []
    for p in positions:
        sym = p.get('symbol')
        if not sym:
            continue
        qty = float(p.get('qty', 0) or 0)
        avg_entry = float(p.get('avg_entry_price') or p.get('avg_entry') or 0)
        snap = snaps.get(sym) or {}
        price = snap.get('price') or snap.get('daily_close')
        if not price:
            missing.append(sym)
            continue
        prev_close = snap.get('prev_close')
        live_positions[sym] = {
            'price': round(price, 4),
            'prev_close': prev_close,
            'day_change_pct': round((price / prev_close - 1) * 100, 2) if prev_close else None,
            'qty': qty,
            'market_value': round(qty * price, 2),
            'unrealized_pl': round(qty * (price - avg_entry), 2) if avg_entry else None,
            'unrealized_plpc': round((price / avg_entry - 1) * 100, 2) if avg_entry else None,
        }
        market_value += qty * price
        if prev_close:
            prev_market_value += qty * prev_close

    pv = cash + market_value
    prev_pv = cash + prev_market_value if prev_market_value else None

    spy = snaps.get('SPY') or {}
    spy_price = spy.get('price') or spy.get('daily_close')

    return {
        'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'market_open': True,
        'source': 'alpaca-sip',
        'portfolio_value': round(pv, 2),
        'cash': round(cash, 2),
        'total_pl': round(pv - EXPERIMENT_BASELINE, 2),
        'total_return_pct': round((pv - EXPERIMENT_BASELINE) / EXPERIMENT_BASELINE * 100, 2),
        'day_change_pct': round((pv / prev_pv - 1) * 100, 2) if prev_pv else None,
        'spy': {
            'price': spy_price,
            'value': round(spy_price / SPY_RESET_PRICE * 100000, 2) if spy_price else None,
            'return_pct': round((spy_price / SPY_RESET_PRICE - 1) * 100, 2) if spy_price else None,
        },
        'positions': live_positions,
        'missing_symbols': missing,
    }


def run_once(hub) -> dict:
    payload = build_payload(hub)
    atomic_write_json(OUT_FILE, payload)
    return payload


def main() -> None:
    logger.info('live quotes poller starting (15s during market hours)')
    hub = get_data_hub()

    if '--once' in sys.argv:
        payload = run_once(hub)
        print(json.dumps(payload, indent=2))
        return

    while True:
        try:
            if is_market_open():
                run_once(hub)
                time.sleep(POLL_SEC)
            else:
                logger.debug('market closed - idle')
                time.sleep(IDLE_SEC)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f'cycle error: {e}')
            time.sleep(30)


if __name__ == '__main__':
    main()
