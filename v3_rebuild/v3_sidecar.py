"""
STONK.AI v3 Sidecar — Trend Pullback Signal Logger

Runs independently of trading_bot.py to compute and log v3 trend-pullback
scores every cycle. Safe to run alongside the live bot because it makes no
trades and modifies no live state.

Logs to: /opt/stonk-ai/v3_rebuild/logs/v3_sidecar.log
Outputs: /opt/stonk-ai/v3_rebuild/sidecar_output/v3_signals_latest.json
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, '/opt/stonk-ai')
from v3_rebuild.v3_signal_engine import score_universe

UNIVERSE_PATH = '/opt/stonk-ai/v3_rebuild/data/universe.json'
LOG_DIR = '/opt/stonk-ai/v3_rebuild/logs'
OUTPUT_DIR = '/opt/stonk-ai/v3_rebuild/sidecar_output'
OUTPUT_PATH = os.path.join(OUTPUT_DIR, 'v3_signals_latest.json')
HISTORY_PATH = os.path.join(OUTPUT_DIR, 'v3_signals_history.jsonl')

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'v3_sidecar.log')),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger('v3_sidecar')


def main():
    logger.info('v3 sidecar starting')
    try:
        universe = json.load(open(UNIVERSE_PATH))
    except Exception as e:
        logger.error(f'Failed to load universe: {e}')
        return

    # Use cached 2-year bars for sufficient history (200-day EMA needs ~300+ trading days)
    try:
        bars = json.load(open('/opt/stonk-ai/v3_rebuild/data/daily_bars_2yr.json'))
    except Exception as e:
        logger.error(f'Failed to load cached 2yr bars: {e}')
        return

    if 'QQQ' not in bars:
        logger.error('QQQ bars missing')
        return

    qqq_closes = bars['QQQ']['closes']

    symbol_bars = {}
    for sym in universe:
        if sym not in bars:
            continue
        d = bars[sym]
        if 'closes' not in d or 'volumes' not in d:
            continue
        symbol_bars[sym] = {'closes': d['closes'], 'volumes': d['volumes']}

    signals = score_universe(symbol_bars, qqq_closes)

    now = datetime.now(timezone.utc).isoformat()
    output = {
        'generated_at': now,
        'universe_size': len(symbol_bars),
        'qqq_5d_return': (qqq_closes[-1] - qqq_closes[-6]) / qqq_closes[-6] if len(qqq_closes) >= 6 else None,
        'top_signals': signals[:30],
    }

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)

    with open(HISTORY_PATH, 'a') as f:
        f.write(json.dumps({'timestamp': now, 'top5': [s['symbol'] for s in signals[:5]], 'scores': [s['v3_score'] for s in signals[:5]], 'eligible_top5': [s['v3_entry_eligible'] for s in signals[:5]]}) + '\n')

    if signals:
        logger.info(f'Generated {len(signals)} v3 signals; top: {signals[0]["symbol"]}={signals[0]["v3_score"]:.2f}')
    else:
        logger.warning('Generated 0 v3 signals')


if __name__ == '__main__':
    main()
