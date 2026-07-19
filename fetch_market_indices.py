#!/usr/bin/env python3
"""
STONK.AI Market Indices Fetcher
Fetches S&P 500 (SPY), Dow Jones (DIA), and NASDAQ (QQQ) via Alpaca data hub.
Zero external data dependencies. All indices use Alpaca-tradable ETF proxies.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Alpaca config
ALPACA_CONFIG_FILE = Path(__file__).parent / "alpaca_config.json"

# July 7, 2026 baseline prices (bot reset date — race is measured from the reset)
RESET_PRICES = {
    'SPY': 747.71,       # S&P 500 ETF (Alpaca, Jul 7 close)
    'DIA': 528.45,       # SPDR Dow Jones ETF (Alpaca, Jul 7 close)
    'QQQ': 709.43        # Invesco QQQ NASDAQ ETF (Alpaca, Jul 7 close)
}

EXPERIMENT_START_VALUE = 100000  # $100K starting value

def _get_hub():
    """Return Alpaca data hub, importing lazily to avoid hard dependency at import time."""
    from alpaca_data import get_data_hub
    return get_data_hub()

def fetch_spy_from_alpaca():
    """Fetch SPY price from Alpaca data hub"""
    try:
        hub = _get_hub()
        price = hub.get_latest_price('SPY')
        return float(price) if price else None
    except Exception as e:
        logger.warning(f"Alpaca SPY fetch failed: {e}")
        return None

def fetch_regime_data():
    """Fetch regime indicator data (VIXY, SHY/TLT, LQD/HYG) from Alpaca hub"""
    try:
        hub = _get_hub()
        snaps = hub.get_snapshots(['VIXY', 'SHY', 'TLT', 'LQD', 'HYG'])
        regime = {}
        for sym, snap in snaps.items():
            regime[sym] = {
                'price': snap.get('price'),
                'prev_close': snap.get('prev_close'),
                'change_pct': ((snap.get('price', 0) - snap.get('prev_close', 0)) / snap.get('prev_close', 1) * 100) if snap.get('prev_close') else 0,
            }
        # Yield curve proxy: SHY/TLT ratio
        if 'SHY' in snaps and 'TLT' in snaps:
            shy_price = snaps['SHY'].get('price', 0)
            tlt_price = snaps['TLT'].get('price', 0)
            if tlt_price > 0:
                ratio = shy_price / tlt_price
                regime['yield_curve_ratio'] = round(ratio, 4)
                # yield_curve_signal removed; regime_detector computes from 20d daily bars
        # Credit spread proxy: LQD/HYG ratio
        if 'LQD' in snaps and 'HYG' in snaps:
            lqd_price = snaps['LQD'].get('price', 0)
            hyg_price = snaps['HYG'].get('price', 0)
            if hyg_price > 0:
                ratio = lqd_price / hyg_price
                regime['credit_spread_ratio'] = round(ratio, 4)
                # credit_signal removed; regime_detector computes from 20d daily bars
        return regime
    except Exception as e:
        logger.warning(f"Regime data fetch failed: {e}")
        return {}


def fetch_market_data():
    """Fetch all market indices + regime data"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'indices': {},
        'regime': fetch_regime_data()
    }
    
    # S&P 500 - Alpaca SIP only
    spy_price = fetch_spy_from_alpaca()
    
    if spy_price:
        spy_start = RESET_PRICES['SPY']
        spy_return = ((spy_price - spy_start) / spy_start) * 100
        spy_value = EXPERIMENT_START_VALUE * (1 + spy_return / 100)
        
        data['indices']['S&P 500'] = {
            'symbol': 'SPY',
            'current_price': round(spy_price, 2),
            'start_price': spy_start,
            'return_pct': round(spy_return, 2),
            'current_value': round(spy_value, 2),
            'last_updated': datetime.now().isoformat(),
            'source': 'Alpaca'
        }
        logger.info(f"S&P 500 (SPY): ${spy_price:.2f} ({spy_return:+.2f}%) → ${spy_value:,.2f}")
    
    # Dow Jones - DIA ETF via Alpaca
    dia_price = None
    try:
        hub = _get_hub()
        dia_price = hub.get_latest_price('DIA')
    except Exception as e:
        logger.warning(f"Alpaca DIA fetch failed: {e}")
    if not dia_price:
        try:
            bars = hub.get_daily_bars(['DIA'], days=5)
            closes = bars.get('DIA', {}).get('closes', [])
            if closes:
                dia_price = closes[-1]
        except Exception as e:
            logger.warning(f"DIA bars fallback failed: {e}")
    if dia_price:
        dia_start = RESET_PRICES['DIA']
        dia_return = ((dia_price - dia_start) / dia_start) * 100
        dia_value = EXPERIMENT_START_VALUE * (1 + dia_return / 100)
        
        data['indices']['Dow Jones'] = {
            'symbol': 'DIA',
            'current_price': round(dia_price, 2),
            'start_price': dia_start,
            'return_pct': round(dia_return, 2),
            'current_value': round(dia_value, 2),
            'last_updated': datetime.now().isoformat(),
            'source': 'Alpaca'
        }
        logger.info(f"Dow Jones (DIA):  ({dia_return:+.2f}%) -> ")
    
    # NASDAQ - QQQ ETF via Alpaca
    qqq_price = None
    try:
        hub = _get_hub()
        qqq_price = hub.get_latest_price('QQQ')
    except Exception as e:
        logger.warning(f"Alpaca QQQ fetch failed: {e}")
    if not qqq_price:
        try:
            bars = hub.get_daily_bars(['QQQ'], days=5)
            closes = bars.get('QQQ', {}).get('closes', [])
            if closes:
                qqq_price = closes[-1]
        except Exception as e:
            logger.warning(f"QQQ bars fallback failed: {e}")
    if qqq_price:
        qqq_start = RESET_PRICES['QQQ']
        qqq_return = ((qqq_price - qqq_start) / qqq_start) * 100
        qqq_value = EXPERIMENT_START_VALUE * (1 + qqq_return / 100)
        
        data['indices']['NASDAQ'] = {
            'symbol': 'QQQ',
            'current_price': round(qqq_price, 2),
            'start_price': qqq_start,
            'return_pct': round(qqq_return, 2),
            'current_value': round(qqq_value, 2),
            'last_updated': datetime.now().isoformat(),
            'source': 'Alpaca'
        }
        logger.info(f"NASDAQ (QQQ):  ({qqq_return:+.2f}%) -> ")
    
    return data

def save_market_data(data):
    """Save market data for website"""
    if not data or 'indices' not in data:
        logger.error("No data to save")
        return False
    
    # Save to opt directory
    opt_file = Path('/opt/stonk-ai/market_indices.json')
    try:
        with open(opt_file, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save to opt: {e}")
    
    # Save to website directory
    web_file = Path('/var/www/hedge-fund-website/market_indices.json')
    try:
        web_file.parent.mkdir(parents=True, exist_ok=True)
        with open(web_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(data['indices'])} market indices to website")
        return True
    except Exception as e:
        logger.error(f"Failed to save to web: {e}")
        return False

def main():
    """Main loop - fetch every 30 seconds"""
    logger.info("Market Indices Fetcher Starting")
    logger.info("SPY source: Alpaca")
    logger.info(f"Jul 7 reset baselines: SPY=${RESET_PRICES['SPY']}, DIA=${RESET_PRICES['DIA']}, QQQ=${RESET_PRICES['QQQ']}")
    
    while True:
        data = fetch_market_data()
        if data and data.get('indices'):
            save_market_data(data)
        else:
            logger.warning("Failed to fetch market indices")
        
        time.sleep(30)

if __name__ == "__main__":
    main()
