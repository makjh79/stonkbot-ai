#!/usr/bin/env python3
"""
STONK.AI Market Indices Fetcher
Fetches S&P 500, Dow Jones, and NASDAQ for The Race comparison
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Market indices to track
INDICES = {
    '^GSPC': {'name': 'S&P 500'},
    '^DJI': {'name': 'Dow Jones'},
    '^IXIC': {'name': 'NASDAQ'}
}

EXPERIMENT_START_VALUE = 100000  # $100K starting value
START_PRICES_FILE = Path('/opt/stonk-ai/market_start_prices.json')

def load_start_prices():
    """Load saved start prices from June 4, 2026"""
    if START_PRICES_FILE.exists():
        with open(START_PRICES_FILE) as f:
            return json.load(f)
    return {}

def save_start_prices(prices):
    """Save start prices for persistence"""
    with open(START_PRICES_FILE, 'w') as f:
        json.dump(prices, f, indent=2)

def fetch_market_data():
    """Fetch market indices from Yahoo Finance"""
    start_prices = load_start_prices()
    data = {
        'timestamp': datetime.now().isoformat(),
        'indices': {}
    }
    
    for symbol, info in INDICES.items():
        try:
            # Yahoo Finance API - get 10 days of data to find June 4
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=10d"
            resp = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if resp.status_code != 200:
                logger.error(f"Failed to fetch {symbol}: {resp.status_code}")
                continue
            
            chart_data = resp.json()
            
            if 'chart' not in chart_data or not chart_data['chart']['result']:
                logger.error(f"Invalid data for {symbol}")
                continue
            
            result = chart_data['chart']['result'][0]
            meta = result.get('meta', {})
            timestamps = result.get('timestamp', [])
            
            # Get current price
            current_price = meta.get('regularMarketPrice', 0)
            if not current_price and 'indicators' in result:
                closes = result['indicators']['quote'][0].get('close', [])
                if closes and closes[-1]:
                    current_price = closes[-1]
            
            if not current_price:
                logger.error(f"No current price for {symbol}")
                continue
            
            # Get start price - try to find June 4, 2026 or use oldest available
            if symbol in start_prices:
                # Use cached start price
                start_price = start_prices[symbol]
            else:
                # Use the oldest close price from the 10-day range (around June 3-4)
                closes = result['indicators']['quote'][0].get('close', [])
                valid_closes = [c for c in closes if c]
                if valid_closes:
                    start_price = valid_closes[0]  # Oldest price
                    start_prices[symbol] = start_price
                    save_start_prices(start_prices)
                    logger.info(f"Set {info['name']} start price: ${start_price:,.2f}")
                else:
                    logger.error(f"No historical data for {symbol}")
                    continue
            
            # Calculate return from start
            return_pct = ((current_price - start_price) / start_price) * 100
            
            # Calculate equivalent portfolio value
            current_value = EXPERIMENT_START_VALUE * (1 + return_pct / 100)
            
            data['indices'][info['name']] = {
                'symbol': symbol,
                'current_price': round(current_price, 2),
                'start_price': round(start_price, 2),
                'return_pct': round(return_pct, 2),
                'current_value': round(current_value, 2),
                'last_updated': datetime.now().isoformat()
            }
            
            logger.info(f"{info['name']}: ${current_price:,.2f} ({return_pct:+.2f}%) → ${current_value:,.2f}")
            
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            continue
    
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
    logger.info(f"Tracking: {', '.join(INDICES.keys())}")
    
    while True:
        data = fetch_market_data()
        if data and data.get('indices'):
            save_market_data(data)
        else:
            logger.warning("Failed to fetch market indices")
        
        time.sleep(30)  # Refresh every 30 seconds

if __name__ == "__main__":
    main()
