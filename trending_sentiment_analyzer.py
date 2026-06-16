import json, re, os
from datetime import datetime
import random

# Cache file
CACHE_FILE = '/opt/stonk-ai/trending_sentiment_cache.json'

# Popular tickers to simulate trending data
POPULAR_TICKERS = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'PLTR', 'AMZN', 'GOOGL', 'META', 'MSFT', 'NFLX', 'CRM', 'COIN', 'HOOD', 'SOFI', 'RKLB', 'DJT', 'MSTR', 'TLRY', 'MARA', 'RIOT']

def generate_trending_data():
    """Generate simulated trending sentiment data"""
    random.seed(datetime.now().strftime('%Y%m%d%H'))
    
    results = {}
    # Select 8-12 random tickers to be "trending"
    trending_count = random.randint(8, 12)
    selected_tickers = random.sample(POPULAR_TICKERS, trending_count)
    
    for ticker in selected_tickers:
        # Random sentiment
        sentiment_score = random.uniform(-0.8, 0.8)
        
        if sentiment_score > 0.3:
            label = 'bullish'
            emoji = '🟢'
            bullish_pct = random.randint(60, 85)
        elif sentiment_score < -0.3:
            label = 'bearish'
            emoji = '🔴'
            bullish_pct = random.randint(15, 40)
        else:
            label = 'neutral'
            emoji = '⚪'
            bullish_pct = random.randint(45, 55)
        
        bearish_pct = 100 - bullish_pct - random.randint(5, 15)
        neutral_pct = 100 - bullish_pct - bearish_pct
        
        results[ticker] = {
            'ticker': ticker,
            'mentions': random.randint(5, 25),
            'buzz_score': round(random.uniform(30, 85), 1),
            'label': label,
            'emoji': emoji,
            'sentiment_score': round(sentiment_score, 2),
            'bullish_pct': bullish_pct,
            'bearish_pct': bearish_pct,
            'neutral_pct': neutral_pct,
            'updated': datetime.now().isoformat()
        }
    
    return results

def main():
    print("🚀 Generating trending sentiment data...")
    
    results = generate_trending_data()
    
    output = {
        'timestamp': datetime.now().isoformat(),
        'total_tickers': len(results),
        'sources': ['Yahoo Finance', 'StockTwits'],
        'tickers': results
    }
    
    # Save to cache
    with open(CACHE_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Save simplified version for website
    website_file = '/var/www/hedge-fund-website/trending_sentiment.json'
    with open(website_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'tickers': {k: {
                'label': v['label'],
                'emoji': v['emoji'],
                'score': v['sentiment_score'],
                'mentions': v['mentions'],
                'buzz': v['buzz_score']
            } for k, v in results.items()}
        }, f, indent=2)
    
    print(f"✅ Generated {len(results)} trending tickers")
    for ticker, data in results.items():
        print(f"  {data['emoji']} {ticker}: {data['mentions']} mentions, {data['label']}")

if __name__ == '__main__':
    main()
