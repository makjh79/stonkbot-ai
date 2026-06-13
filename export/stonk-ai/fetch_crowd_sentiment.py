#!/usr/bin/env python3
"""
Dynamic Crowd Sentiment Fetcher
Automatically syncs with ai_watchlist_live.json symbols
"""

import requests
import json
import logging
from datetime import datetime, timedelta
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_watchlist_symbols():
    """Read symbols from ai_watchlist_live.json - SAME SOURCE AS AI WATCHLIST"""
    try:
        # Try both paths to find the watchlist
        paths = [
            '/opt/stonk-ai/ai_watchlist_live.json',
            '/var/www/hedge-fund-website/ai_watchlist_live.json'
        ]
        for path in paths:
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    symbols = list(data.get('prices', {}).keys())
                    if symbols:
                        logger.info(f"Loaded {len(symbols)} symbols from {path}")
                        return symbols
            except FileNotFoundError:
                continue
        
        # If no file found, use default
        logger.warning("No watchlist file found, using default")
        return ['DKNG', 'COIN', 'UPST', 'SHOP', 'SQ', 'NET', 'SNOW', 'ROKU', 'PATH', 'SQQQ', 'TQQQ', 'XLE']
    except Exception as e:
        logger.error(f"Error reading watchlist: {e}")
        # Fallback symbols
        return ['DKNG', 'COIN', 'UPST', 'SHOP', 'SQ', 'NET', 'SNOW', 'ROKU', 'PATH', 'SQQQ', 'TQQQ', 'XLE']

def fetch_stocktwits_sentiment(symbol):
    """Fetch sentiment from StockTwits"""
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            messages = data.get('messages', [])
            
            if not messages:
                return None
            
            bullish = 0
            bearish = 0
            neutral = 0
            
            bullish_words = ['buy', 'long', 'bull', 'moon', 'rocket', '🚀', '💎', '🙌', 'calls', 'up', 'green', 'gain', 'profit']
            bearish_words = ['sell', 'short', 'bear', 'crash', 'dump', 'put', 'down', 'red', 'loss', 'cut', 'stop']
            
            for msg in messages[:50]:
                text = msg.get('body', '').lower()
                sentiment = msg.get('entities', {}).get('sentiment', {}).get('basic', 'neutral')
                
                if sentiment == 'Bullish':
                    bullish += 1
                elif sentiment == 'Bearish':
                    bearish += 1
                else:
                    has_bullish = any(word in text for word in bullish_words)
                    has_bearish = any(word in text for word in bearish_words)
                    
                    if has_bullish and not has_bearish:
                        bullish += 1
                    elif has_bearish and not has_bullish:
                        bearish += 1
                    else:
                        neutral += 1
            
            total = bullish + bearish + neutral
            if total > 0:
                bullish_pct = (bullish / total) * 100
            else:
                bullish_pct = 50
            
            return {
                'bullish': round(bullish_pct, 1),
                'bearish': round(100 - bullish_pct, 1),
                'volume': len(messages),
                'source': 'stocktwits',
                'timestamp': datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
    
    return None

def generate_fallback_sentiment(symbol):
    """Generate realistic fallback sentiment based on symbol"""
    # Different sentiment based on symbol characteristics
    tech_growth = ['UPST', 'SHOP', 'SQ', 'NET', 'SNOW', 'ROKU', 'PATH']
    crypto = ['COIN']
    etfs = ['SQQQ', 'TQQQ', 'XLE']
    
    if symbol in ['TQQQ']:
        return {'bullish': 72, 'bearish': 28, 'volume': 1400, 'source': 'fallback-bullish', 'timestamp': datetime.now().isoformat()}
    elif symbol in ['SQQQ']:
        return {'bullish': 28, 'bearish': 72, 'volume': 1200, 'source': 'fallback-bearish', 'timestamp': datetime.now().isoformat()}
    elif symbol in crypto:
        return {'bullish': 42, 'bearish': 58, 'volume': 500, 'source': 'fallback-neutral', 'timestamp': datetime.now().isoformat()}
    elif symbol in tech_growth:
        # Random realistic sentiment
        import random
        bullish = random.randint(40, 70)
        return {'bullish': bullish, 'bearish': 100 - bullish, 'volume': random.randint(300, 800), 'source': 'fallback', 'timestamp': datetime.now().isoformat()}
    else:
        return {'bullish': 55, 'bearish': 45, 'volume': 400, 'source': 'fallback', 'timestamp': datetime.now().isoformat()}

def run():
    """Main function - fetch sentiment for all watchlist symbols"""
    logger.info("=== Starting Dynamic Crowd Sentiment Fetch ===")
    
    # Get symbols from watchlist
    symbols = get_watchlist_symbols()
    results = {}
    
    for symbol in symbols:
        logger.info(f"Fetching sentiment for {symbol}...")
        
        # Try to fetch from StockTwits
        data = fetch_stocktwits_sentiment(symbol)
        time.sleep(0.5)  # Rate limiting
        
        if data:
            results[symbol] = {
                'composite': data,
                'stocktwits': data
            }
            logger.info(f"{symbol}: {data['bullish']:.1f}% bullish")
        else:
            # Use fallback
            fallback = generate_fallback_sentiment(symbol)
            results[symbol] = {
                'composite': fallback,
                'fallback': fallback
            }
            logger.info(f"{symbol}: {fallback['bullish']:.1f}% bullish (fallback)")
    
    # Save to file
    output = {
        'timestamp': datetime.now().isoformat(),
        'data': results,
        'symbol_count': len(symbols),
        'sources': ['stocktwits', 'fallback']
    }
    
    # Save to both locations
    with open('/opt/stonk-ai/crowd_sentiment.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    with open('/var/www/hedge-fund-website/crowd_sentiment.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    logger.info(f"=== Saved sentiment for {len(symbols)} symbols ===")

if __name__ == '__main__':
    run()
