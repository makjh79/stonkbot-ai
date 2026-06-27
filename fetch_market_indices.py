#!/usr/bin/env python3
"""
STONK.AI Market Indices Fetcher
Fetches S&P 500 (SPY), Dow Jones (DIA), and NASDAQ (QQQ) via Alpaca data hub
No Yahoo Finance dependency. All indices use Alpaca-tradable ETF proxies.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
import requests

try:
        HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Alpaca config
ALPACA_CONFIG_FILE = Path(__file__).parent / "alpaca_config.json"

# June 4, 2026 baseline prices (experiment start date)
JUNE_4_PRICES = {
    'SPY': 757.09,       # S&P 500 ETF
    'DIA': 515.29,       # SPDR Dow Jones ETF (Alpaca, June 4 close)
    'QQQ': 739.8         # Invesco QQQ NASDAQ ETF (Alpaca, June 4 close)
}

EXPERIMENT_START_VALUE = 100000  # $100K starting value

def load_alpaca_config():
    """Load Alpaca API credentials"""
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def fetch_spy_from_alpaca():
    """Fetch SPY price from Alpaca data hub"""
    try:
        from alpaca_data import get_data_hub
        hub = get_data_hub()
        price = hub.get_latest_price('SPY')
        return float(price) if price else None
    except Exception as e:
        logger.warning(f"Alpaca SPY fetch failed: {e}")
        return None

def fetch_regime_data():
    """Fetch regime indicator data (VIXY, SHY/TLT, LQD/HYG) from Alpaca hub"""
    try:
        from alpaca_data import get_data_hub
        hub = get_data_hub()
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
                regime['yield_curve_signal'] = 'steepening' if ratio > 0.3 else 'normal'
        # Credit spread proxy: LQD/HYG ratio
        if 'LQD' in snaps and 'HYG' in snaps:
            lqd_price = snaps['LQD'].get('price', 0)
            hyg_price = snaps['HYG'].get('price', 0)
            if hyg_price > 0:
                ratio = lqd_price / hyg_price
                regime['credit_spread_ratio'] = round(ratio, 4)
                regime['credit_signal'] = 'improving' if ratio > 7.0 else 'widening'
        return regime
    except Exception as e:
        logger.warning(f"Regime data fetch failed: {e}")
        return {}

def fetch_spy_from_yahoo():
    """Fallback: Fetch SPY from Yahoo Finance"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1d"
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        data = resp.json()
        meta = data['chart']['result'][0]['meta']
        return float(meta.get('regularMarketPrice', 0))
    except Exception as e:
        logger.error(f"Yahoo SPY fetch failed: {e}")
        return None

def fetch_index_from_yahoo(symbol):
    """Fetch index data from Yahoo Finance"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        data = resp.json()
        meta = data['chart']['result'][0]['meta']
        return float(meta.get('regularMarketPrice', 0))
    except Exception as e:
        logger.error(f"Yahoo {symbol} fetch failed: {e}")
        return None

def fetch_market_data():
    """Fetch all market indices + regime data"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'indices': {},
        'regime': fetch_regime_data()
    }
    
    # S&P 500 - Try Alpaca first, fall back to Yahoo
    spy_price = fetch_spy_from_alpaca()
    if not spy_price:
        spy_price = fetch_spy_from_yahoo()
    
    if spy_price:
        spy_start = JUNE_4_PRICES['SPY']
        spy_return = ((spy_price - spy_start) / spy_start) * 100
        spy_value = EXPERIMENT_START_VALUE * (1 + spy_return / 100)
        
        data['indices']['S&P 500'] = {
            'symbol': 'SPY',
            'current_price': round(spy_price, 2),
            'start_price': spy_start,
            'return_pct': round(spy_return, 2),
            'current_value': round(spy_value, 2),
            'last_updated': datetime.now().isoformat(),
            'source': 'Alpaca' if HAS_ALPACA else 'Yahoo'
        }
        logger.info(f"S&P 500 (SPY): ${spy_price:.2f} ({spy_return:+.2f}%) → ${spy_value:,.2f}")
    
    # Dow Jones - DIA ETF via Alpaca
    dia_price = None
    try:
        if 'hub' not in dir():
            from alpaca_data import get_data_hub
            hub = get_data_hub()
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
        dia_start = JUNE_4_PRICES['DIA']
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
        if 'hub' not in dir():
            from alpaca_data import get_data_hub
            hub = get_data_hub()
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
        qqq_start = JUNE_4_PRICES['QQQ']
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
    logger.info(f"SPY source: {'Alpaca' if HAS_ALPACA else 'Yahoo Finance'}")
    logger.info(f"June 4 baselines: SPY=${JUNE_4_PRICES['SPY']}, DIA=${JUNE_4_PRICES['DIA']}, QQQ=${JUNE_4_PRICES['QQQ']}")
    
    while True:
        data = fetch_market_data()
        if data and data.get('indices'):
            save_market_data(data)
        else:
            logger.warning("Failed to fetch market indices")
        
        time.sleep(30)

if __name__ == "__main__":
    main()
