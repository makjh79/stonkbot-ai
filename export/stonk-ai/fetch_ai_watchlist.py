#!/usr/bin/env python3
"""
STONK.AI AI Watchlist Live Price Fetcher
Fetches real-time prices for AI watchlist stocks
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import requests

# Yahoo Finance for RSI (free alternative to paid Alpaca data)
YAHOO_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

# Polygon.io API - Primary RSI source
# Free tier: 5 API calls/minute, no daily limit
POLYGON_API_KEY = "ZzgS2QyoeY2aDdvz8Z0Ww66G0kJgLWxZ"
POLYGON_BASE_URL = "https://api.polygon.io"

# Symbols that work better on Yahoo than Polygon free tier
YAHOO_PREFERRED = {'SQ', 'UPST'}  # Polygon free tier doesn't have these

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default watchlist - will be overridden by dynamic loading
DEFAULT_WATCHLIST = [
    'AMZN', 'COIN', 'DKNG', 'NET', 'NFLX', 'PATH',
    'SHOP', 'SQ', 'SQQQ', 'TQQQ', 'UPST', 'XLE'
]

def get_watchlist_symbols():
    """Dynamically load watchlist symbols from watchlist_changes.json or use default"""
    try:
        # First check for dynamic watchlist changes (updated by manager)
        changes_path = Path("/var/www/hedge-fund-website/watchlist_changes.json")
        if changes_path.exists():
            with open(changes_path, 'r') as f:
                data = json.load(f)
                new_watchlist = data.get('new_watchlist', [])
                if new_watchlist:
                    logger.info(f"Loaded {len(new_watchlist)} symbols from dynamic manager")
                    return new_watchlist
    except Exception as e:
        logger.warning(f"Could not load dynamic watchlist changes: {e}")
    
    # Fallback to existing watchlist
    try:
        watchlist_path = Path(__file__).parent / "ai_watchlist_live.json"
        if watchlist_path.exists():
            with open(watchlist_path, 'r') as f:
                data = json.load(f)
                symbols = list(data.get('prices', {}).keys())
                if symbols:
                    logger.info(f"Loaded {len(symbols)} symbols from existing watchlist")
                    return symbols
    except Exception as e:
        logger.warning(f"Could not load existing watchlist: {e}")
    
    logger.info(f"Using default watchlist: {DEFAULT_WATCHLIST}")
    return DEFAULT_WATCHLIST

# Legacy constant for backward compatibility - use get_watchlist_symbols() instead
AI_WATCHLIST_SYMBOLS = DEFAULT_WATCHLIST

# Load Alpaca config
def load_config():
    config_path = Path(__file__).parent / "alpaca_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def calculate_rsi(prices, period=14):
    """Calculate RSI for a price series"""
    if len(prices) < period + 1:
        return None
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    
    # Use last 'period' values
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 1)


# Yahoo Finance session with cookies for better rate limit handling
_yahoo_session = None
_yahoo_last_request = 0
_YAHOO_MIN_DELAY = 1.0  # Minimum 1 second between requests

def get_yahoo_session():
    """Get or create Yahoo session with proper headers"""
    global _yahoo_session
    if _yahoo_session is None:
        _yahoo_session = requests.Session()
        _yahoo_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://finance.yahoo.com/',
        })
    return _yahoo_session


def fetch_yahoo_history(symbol, days=30):
    """Fetch historical price data from Yahoo Finance for RSI calculation"""
    global _yahoo_last_request
    
    try:
        # Enforce rate limit
        now = time.time()
        time_since_last = now - _yahoo_last_request
        if time_since_last < _YAHOO_MIN_DELAY:
            sleep_time = _YAHOO_MIN_DELAY - time_since_last
            logger.debug(f"Rate limit: sleeping {sleep_time:.1f}s before {symbol}")
            time.sleep(sleep_time)
        
        # Calculate date range
        end = int(time.time())
        start = end - (days * 24 * 60 * 60)
        
        url = f"{YAHOO_BASE_URL}/{symbol}"
        params = {
            'period1': start,
            'period2': end,
            'interval': '1d',
            'events': 'history'
        }
        
        session = get_yahoo_session()
        resp = session.get(url, params=params, timeout=10)
        _yahoo_last_request = time.time()
        
        if resp.status_code == 200:
            data = resp.json()
            result = data.get('chart', {}).get('result', [{}])[0]
            timestamps = result.get('timestamp', [])
            closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
            
            if len(closes) >= 15:
                # Filter out None values
                valid_closes = [c for c in closes if c is not None]
                if len(valid_closes) >= 15:
                    logger.debug(f"Fetched {len(valid_closes)} bars for {symbol}")
                    return valid_closes
            return None
        elif resp.status_code == 429:
            logger.warning(f"Yahoo rate limit hit for {symbol}, waiting longer...")
            time.sleep(5)  # Extra wait on rate limit
            return None
        else:
            logger.debug(f"Yahoo error {resp.status_code} for {symbol}")
            return None
    except Exception as e:
        logger.debug(f"Yahoo fetch failed for {symbol}: {e}")
        return None


def get_rsi_from_yahoo(symbol):
    """Get RSI using Yahoo Finance historical data"""
    prices = fetch_yahoo_history(symbol, days=30)
    if prices and len(prices) >= 15:
        rsi = calculate_rsi(prices)
        logger.info(f"Yahoo RSI for {symbol}: {rsi}")
        return rsi
    return None


# RSI cache file for persistence across restarts
RSI_CACHE_FILE = Path('/opt/stonk-ai/rsi_cache.json')

def load_rsi_cache():
    """Load cached RSI values from file"""
    if RSI_CACHE_FILE.exists():
        try:
            with open(RSI_CACHE_FILE) as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_rsi_cache(cache):
    """Save RSI cache to file"""
    try:
        with open(RSI_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.debug(f"Failed to save RSI cache: {e}")


def get_rsi_from_polygon(symbol):
    """Get RSI from Polygon.io using historical data
    
    Polygon free tier: 5 calls/minute with your API key
    """
    try:
        # Get historical data from Polygon
        end = int(time.time())
        start = end - (30 * 24 * 60 * 60)  # 30 days
        
        url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
        params = {
            'apiKey': POLYGON_API_KEY,
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 30
        }
        
        resp = requests.get(url, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('results', [])
            
            if len(results) >= 15:
                # Extract closing prices
                closes = [bar['c'] for bar in results]
                
                # Calculate RSI
                gains = []
                losses = []
                
                for i in range(1, len(closes)):
                    change = closes[i] - closes[i-1]
                    if change > 0:
                        gains.append(change)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(change))
                
                # Use last 14 periods
                avg_gain = sum(gains[-14:]) / 14
                avg_loss = sum(losses[-14:]) / 14
                
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                
                rsi = round(rsi, 1)
                logger.info(f"Polygon RSI for {symbol}: {rsi}")
                return rsi
            else:
                logger.debug(f"Polygon: insufficient data for {symbol} ({len(results)} bars)")
        elif resp.status_code == 429:
            logger.warning(f"Polygon rate limit for {symbol}")
        else:
            logger.debug(f"Polygon error {resp.status_code} for {symbol}: {resp.text[:100]}")
        
        return None
    except Exception as e:
        logger.debug(f"Polygon failed for {symbol}: {e}")
        return None


def get_rsi_with_fallback(symbol):
    """Get RSI with Polygon primary, Yahoo fallback, cached fallback
    
    Priority:
    1. Polygon.io (your API key - reliable) - for most symbols
    2. Yahoo Finance (free, rate limited) - for SQ, UPST, etc.
    3. Cached value (up to 24h old)
    """
    # Some symbols work better on Yahoo
    if symbol in YAHOO_PREFERRED:
        # Try Yahoo first for these
        rsi = get_rsi_from_yahoo(symbol)
        if rsi:
            return rsi, 'Yahoo'
        # Then Polygon as fallback
        logger.info(f"Yahoo failed for {symbol}, trying Polygon...")
        rsi = get_rsi_from_polygon(symbol)
        if rsi:
            return rsi, 'Polygon'
    else:
        # Try Polygon first for most symbols
        rsi = get_rsi_from_polygon(symbol)
        if rsi:
            return rsi, 'Polygon'
        # Yahoo as fallback
        logger.info(f"Polygon failed for {symbol}, trying Yahoo...")
        rsi = get_rsi_from_yahoo(symbol)
        if rsi:
            return rsi, 'Yahoo'
    
    # Check cache as last resort
    cache = load_rsi_cache()
    if symbol in cache:
        cached = cache[symbol]
        age_hours = (time.time() - cached.get('timestamp', 0)) / 3600
        if age_hours < 24:  # Cache valid for 24 hours
            logger.info(f"Using cached RSI for {symbol}: {cached['rsi']} ({age_hours:.1f}h old)")
            return cached['rsi'], 'Cached'
    
    logger.warning(f"Could not get RSI for {symbol} - all sources failed")
    return None, None


def fetch_watchlist_prices():
    """Fetch live prices for AI watchlist stocks with change % and RSI"""
    config = load_config()
    api_key = config.get('api_key', '')
    api_secret = config.get('api_secret', '')
    
    if not api_key or not api_secret:
        logger.error("No Alpaca API credentials found")
        return None
    
    prices = {}
    
    # Get dynamic watchlist symbols
    watchlist_symbols = get_watchlist_symbols()
    
    try:
        # Use REST API directly
        base = "https://data.alpaca.markets"
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret
        }
        
        symbols_str = ",".join(watchlist_symbols)
        
        # Get latest TRADES for actual last traded price (more accurate than quotes on weekends)
        trades_resp = requests.get(
            f"{base}/v2/stocks/trades/latest?symbols={symbols_str}",
            headers=headers, timeout=30
        )
        
        # Get latest quotes for bid/ask spread
        quotes_resp = requests.get(
            f"{base}/v2/stocks/quotes/latest?symbols={symbols_str}",
            headers=headers, timeout=30
        )
        
        # Get historical bars for change % and RSI
        bars_resp = requests.get(
            f"{base}/v2/stocks/bars?symbols={symbols_str}&timeframe=1Day&limit=20",
            headers=headers, timeout=30
        )
        
        bars_data = {}
        if bars_resp.status_code == 200:
            bars_data = bars_resp.json().get('bars', {})
            logger.info(f"Fetched bars for {len(bars_data)} symbols")
        else:
            logger.error(f"Failed to fetch bars: {bars_resp.status_code}")
        
        # Parse trades data
        trades_data = {}
        if trades_resp.status_code == 200:
            trades_data = trades_resp.json().get('trades', {})
            logger.info(f"Fetched trades for {len(trades_data)} symbols")
        else:
            logger.error(f"Failed to fetch trades: {trades_resp.status_code}")
        
        # Parse quotes data
        quotes_data = {}
        if quotes_resp.status_code == 200:
            quotes_data = quotes_resp.json().get('quotes', {})
            logger.info(f"Fetched quotes for {len(quotes_data)} symbols")
        
        if trades_data or quotes_data:
            for symbol in watchlist_symbols:
                # Use trade price first (more accurate), fallback to quote midpoint
                current_price = 0
                bid = 0
                ask = 0
                
                if symbol in trades_data:
                    current_price = float(trades_data[symbol].get('p', 0))
                    trade_time = trades_data[symbol].get('t', '')
                    logger.info(f"{symbol}: Using trade price ${current_price:.2f} from {trade_time}")
                
                if symbol in quotes_data:
                    quote_data = quotes_data[symbol]
                    bid = float(quote_data.get('bp', 0))
                    ask = float(quote_data.get('ap', 0))
                    # If no trade price, use quote midpoint
                    if current_price == 0 and bid > 0 and ask > 0:
                        current_price = (bid + ask) / 2
                        logger.info(f"{symbol}: Using quote midpoint ${current_price:.2f}")
                    elif current_price == 0:
                        current_price = bid or ask
                        logger.info(f"{symbol}: Using quote price ${current_price:.2f}")
                    
                    # Calculate change % from previous close
                    change_pct = 0.0
                    change_amount = 0.0
                    prev_close = current_price
                    rsi = None
                    
                    if symbol in bars_data:
                        symbol_bars = bars_data[symbol]
                        if len(symbol_bars) >= 2:
                            prev_close = symbol_bars[-2]['c']
                            change_pct = ((current_price - prev_close) / prev_close) * 100
                            change_amount = current_price - prev_close
                    
                    # VALIDATION: Ensure price is reasonable (not 0 or extreme outlier)
                    if current_price <= 0:
                        logger.error(f"{symbol}: Invalid price ${current_price} - skipping")
                        continue
                    
                    # Check if price is within 20% of previous close (sanity check)
                    if prev_close > 0:
                        price_diff_pct = abs(current_price - prev_close) / prev_close * 100
                        if price_diff_pct > 20:
                            logger.warning(f"{symbol}: Large price jump {price_diff_pct:.1f}% (${prev_close:.2f} -> ${current_price:.2f})")
                    
                    # Check trade timestamp is recent (within last 24 hours)
                    if symbol in trades_data:
                        from datetime import datetime
                        trade_ts = trades_data[symbol].get('t', '')
                        if trade_ts:
                            try:
                                trade_time = datetime.fromisoformat(trade_ts.replace('Z', '+00:00'))
                                age_hours = (datetime.now(trade_time.tzinfo) - trade_time).total_seconds() / 3600
                                if age_hours > 24:
                                    logger.warning(f"{symbol}: Stale trade data ({age_hours:.1f}h old)")
                            except:
                                pass
                    
                    # Calculate RSI from Alpaca bars data (if available)
                    if symbol in bars_data:
                        symbol_bars = bars_data[symbol]
                        if len(symbol_bars) >= 15:
                            price_history = [bar['c'] for bar in symbol_bars]
                            rsi = calculate_rsi(price_history)
                    
                    # RSI will be fetched separately from Polygon/Yahoo to avoid rate limits
                    # For now, leave as None - main() will populate from cache or fresh fetch
                    
                    # Calculate DYNAMIC AI Score (0-100) based on technicals
                    # Higher = more bullish, Lower = more bearish
                    ai_score = 50  # Neutral base
                    
                    # RSI factor (30-70 scale) - PRIMARY SIGNAL
                    if rsi:
                        if rsi < 30:  # Oversold - bullish
                            ai_score += 25
                        elif rsi < 40:  # Getting oversold
                            ai_score += 15
                        elif rsi > 70:  # Overbought - bearish
                            ai_score -= 25
                        elif rsi > 60:  # Getting overbought
                            ai_score -= 15
                        # Fine-tune based on RSI distance from 50
                        elif rsi < 45:  # Slightly oversold
                            ai_score += 5
                        elif rsi > 55:  # Slightly overbought
                            ai_score -= 5
                    
                    # Price change factor (daily)
                    if change_pct < -10:  # Big drop - buying opportunity
                        ai_score += 15
                    elif change_pct < -5:  # Moderate drop
                        ai_score += 8
                    elif change_pct > 10:  # Big run - caution
                        ai_score -= 15
                    elif change_pct > 5:  # Moderate run
                        ai_score -= 8
                    
                    # Multi-day momentum factor (5-day trend)
                    if symbol in bars_data and len(bars_data[symbol]) >= 5:
                        week_bars = bars_data[symbol][-5:]
                        week_start = week_bars[0]['c']
                        week_change = ((current_price - week_start) / week_start) * 100
                        
                        if week_change < -15:  # Strong weekly decline - contrarian bullish
                            ai_score += 12
                        elif week_change < -8:  # Moderate weekly decline
                            ai_score += 6
                        elif week_change > 15:  # Strong weekly run - contrarian bearish
                            ai_score -= 12
                        elif week_change > 8:  # Moderate weekly run
                            ai_score -= 6
                    
                    # Calculate buy targets for distance analysis
                    conservative_target = round(current_price * 0.88, 2)
                    distance_to_target = ((current_price - conservative_target) / conservative_target) * 100
                    
                    # Distance to buy zone factor
                    if distance_to_target < 5:  # Very close to buy zone - bullish setup
                        ai_score += 10
                    elif distance_to_target < 10:  # Approaching buy zone
                        ai_score += 5
                    elif distance_to_target > 25:  # Far from buy zone - overextended
                        ai_score -= 8
                    
                    # Category/sector factor (growth vs hedge)
                    growth_stocks = {'UPST', 'SHOP', 'SQ', 'NET', 'SNOW', 'ROKU', 'PATH', 'DKNG'}
                    crypto_stocks = {'COIN'}
                    hedge_etfs = {'SQQQ', 'TQQQ'}
                    
                    # Adjust based on market conditions (RSI proxy for market)
                    market_rsi = rsi if rsi else 50
                    
                    if symbol in growth_stocks:
                        if market_rsi < 40:  # Growth stocks attractive when market oversold
                            ai_score += 5
                        elif market_rsi > 65:  # Growth stocks risky when market overbought
                            ai_score -= 5
                    elif symbol in crypto_stocks:
                        if market_rsi < 35:  # Crypto oversold = buying opportunity
                            ai_score += 8
                    elif symbol in hedge_etfs:
                        if market_rsi > 60:  # Hedges attractive when market extended
                            ai_score += 10
                        elif market_rsi < 40:  # Hedges less attractive when market oversold
                            ai_score -= 10
                    
                    # Clamp to 0-100
                    ai_score = max(0, min(100, int(ai_score)))
                    
                    # Calculate DYNAMIC Sentiment based on AI score
                    if ai_score >= 70:
                        sentiment = 80  # Strong bullish
                        sentiment_label = "Strong Bullish"
                    elif ai_score >= 60:
                        sentiment = 65  # Bullish
                        sentiment_label = "Bullish"
                    elif ai_score >= 45:
                        sentiment = 50  # Neutral
                        sentiment_label = "Neutral"
                    elif ai_score >= 30:
                        sentiment = 35  # Bearish
                        sentiment_label = "Bearish"
                    else:
                        sentiment = 20  # Strong bearish
                        sentiment_label = "Strong Bearish"
                    
                    # Calculate Council target prices (The Council's Strategy)
                    targets = {
                        'conservative_target': round(current_price * 0.88, 2),  # Buy at -12% dip
                        'aggressive_target': round(current_price * 0.82, 2),    # Buy at -18% dip
                        'stop_loss': round(current_price * 0.85, 2),          # Stop loss at -15%
                        'profit_25': round(current_price * 1.25, 2),          # Trim at +25%
                        'profit_50': round(current_price * 1.50, 2),          # Exit at +50%
                        'signal': 'WAIT',
                        'council_note': 'Monitor for dip'
                    }
                    
                    # Determine signal based on MULTIPLE factors (not just daily change)
                    # Factor 1: Daily change
                    # Factor 2: RSI (oversold < 35, overbought > 70)
                    # Factor 3: AI score (0-100)
                    # Factor 4: Distance to conservative target
                    
                    price_to_target = (current_price - targets['conservative_target']) / targets['conservative_target'] * 100
                    rsi_val = rsi if rsi is not None else 50  # Default to neutral if no RSI
                    
                    # STRONG BUY: Deep dip OR oversold RSI OR near target with high AI
                    if change_pct < -15 or rsi_val < 35 or (price_to_target < 10 and ai_score >= 60):
                        targets['signal'] = 'STRONG_BUY'
                        if rsi_val < 35:
                            targets['council_note'] = f'Oversold (RSI {rsi_val:.0f}) - Paulson buying'
                        elif price_to_target < 10:
                            targets['council_note'] = f'Near buy zone (+{price_to_target:.0f}%) - Entry soon'
                        else:
                            targets['council_note'] = 'Deep oversold - Paulson likes this'
                    
                    # BUY: Good dip OR low RSI OR approaching target
                    elif change_pct < -10 or rsi_val < 45 or (price_to_target < 15 and ai_score >= 50):
                        targets['signal'] = 'BUY'
                        if rsi_val < 45:
                            targets['council_note'] = f'Weakness (RSI {rsi_val:.0f}) - Wood accumulating'
                        elif price_to_target < 15:
                            targets['council_note'] = f'Approaching target (+{price_to_target:.0f}%) - Set alerts'
                        else:
                            targets['council_note'] = 'Good entry zone - Wood approves'
                    
                    # WATCH: Moderate dip OR neutral RSI with decent AI
                    elif change_pct < -5 or rsi_val < 55 or (ai_score >= 60 and rsi_val < 65):
                        targets['signal'] = 'WATCH'
                        if rsi_val < 55:
                            targets['council_note'] = f'Cooling off (RSI {rsi_val:.0f}) - Jones watching'
                        elif ai_score >= 60:
                            targets['council_note'] = f'Strong AI ({ai_score}) - Monitor for dip'
                        else:
                            targets['council_note'] = 'Getting interesting - Jones watching'
                    
                    # AVOID: Big run up OR overbought
                    elif change_pct > 10 or rsi_val > 75:
                        targets['signal'] = 'AVOID'
                        if rsi_val > 75:
                            targets['council_note'] = f'Overbought (RSI {rsi_val:.0f}) - Wait for cool down'
                        else:
                            targets['council_note'] = 'Too extended - wait for pullback'
                    
                    # ACCUMULATE: Good AI + reasonable RSI
                    elif ai_score >= 60 and rsi_val < 60:
                        targets['signal'] = 'ACCUMULATE'
                        targets['council_note'] = f'Quality setup (AI {ai_score}) - Buy on dips'
                    
                    # HOLD: Good AI score but elevated RSI
                    elif ai_score >= 60:
                        targets['signal'] = 'HOLD'
                        targets['council_note'] = f'Quality setup (AI {ai_score}) - Hold position'
                    
                    # WAIT: Default - not compelling
                    else:
                        targets['signal'] = 'WAIT'
                        if ai_score < 40:
                            targets['council_note'] = f'Weak setup (AI {ai_score}) - Skip for now'
                        else:
                            targets['council_note'] = 'Monitor for dip'
                    
                    # Special rules for hedges
                    if symbol in ['SQQQ', 'TQQQ']:
                        targets['conservative_target'] = round(current_price * 0.95, 2)
                        targets['aggressive_target'] = round(current_price * 0.90, 2)
                        targets['council_note'] = 'Hedge/momentum tool - use for timing'
                    
                    prices[symbol] = {
                        'price': round(current_price, 2),
                        'change_pct': round(change_pct, 2),
                        'change_amount': round(change_amount, 2),
                        'rsi': rsi,
                        'bid': round(float(quote_data.get('bp', 0)), 2) if quote_data.get('bp') else None,
                        'ask': round(float(quote_data.get('ap', 0)), 2) if quote_data.get('ap') else None,
                        'targets': targets,
                        'ai_score': ai_score,
                        'sentiment': sentiment,
                        'sentiment_label': sentiment_label,
                        'timestamp': datetime.now().isoformat()
                    }
                else:
                    logger.warning(f"No quote data for {symbol}")
        else:
            logger.error(f"Failed to fetch quotes: {resp.status_code}")
            return None
                
    except Exception as e:
        logger.error(f"Error fetching watchlist prices: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
    
    return prices


def council_autonomous_watchlist_adjustment(prices):
    """
    THE COUNCIL'S AUTONOMOUS WATCHLIST MANAGEMENT
    
    Paul Tudor Jones: Cut losers, focus on quality
    George Soros: Add momentum/reflexivity plays when trend strong
    John Paulson: Add hedges when portfolio overextended
    Cathie Wood: Add innovation names on dips
    """
    
    # Get current dynamic watchlist
    dynamic_symbols = get_watchlist_symbols()
    
    if not prices:
        return dynamic_symbols
    
    current_symbols = set(dynamic_symbols)
    
    # Analyze current watchlist performance
    avg_change = sum(p.get('change_pct', 0) for p in prices.values()) / len(prices)
    
    # Paulson: If everything down >3%, market stressed - add hedges
    if avg_change < -3.0:
        if 'SQQQ' not in current_symbols:
            logger.info("COUNCIL: Adding SQQQ hedge (market stress detected)")
            current_symbols.add('SQQQ')
        if 'GLD' not in current_symbols:
            logger.info("COUNCIL: Adding GLD gold hedge")
            current_symbols.add('GLD')
    
    # Soros: If momentum strong, add leveraged plays
    momentum_stocks = [s for s, p in prices.items() if p.get('change_pct', 0) > 5]
    if len(momentum_stocks) >= 3:
        if 'TQQQ' not in current_symbols:
            logger.info("COUNCIL: Adding TQQQ momentum play")
            current_symbols.add('TQQQ')
        if 'SOXL' not in current_symbols:
            logger.info("COUNCIL: Adding SOXL semiconductor leverage")
            current_symbols.add('SOXL')
    
    # Wood: Innovation names on deep dips
    oversold = [s for s, p in prices.items() if p.get('rsi') and p['rsi'] < 25]
    for symbol in oversold:
        if symbol == 'PLTR' and 'PLTR' not in current_symbols:
            logger.info("COUNCIL: Adding PLTR on deep oversold")
            current_symbols.add('PLTR')
        if symbol == 'CRWD' and 'CRWD' not in current_symbols:
            logger.info("COUNCIL: Adding CRWD on cybersecurity dip")
            current_symbols.add('CRWD')
    
    # Jones: Remove chronic underperformers after 30 days
    # (This would require tracking history - simplified here)
    
    return sorted(list(current_symbols))


def recalculate_ai_scores(prices):
    """Recalculate AI scores and sentiment AFTER RSI is populated"""
    for symbol, p in prices.items():
        rsi = p.get('rsi')
        change_pct = p.get('change_pct', 0)
        
        # Calculate DYNAMIC AI Score (0-100) based on technicals
        ai_score = 50  # Neutral base
        
        # RSI factor (30-70 scale)
        if rsi:
            if rsi < 30:  # Oversold - bullish
                ai_score += 20
            elif rsi < 40:  # Getting oversold
                ai_score += 10
            elif rsi > 70:  # Overbought - bearish
                ai_score -= 20
            elif rsi > 60:  # Getting overbought
                ai_score -= 10
        
        # Price change factor
        if change_pct < -10:  # Big drop - buying opportunity
            ai_score += 15
        elif change_pct < -5:  # Moderate drop
            ai_score += 8
        elif change_pct > 10:  # Big run - caution
            ai_score -= 15
        elif change_pct > 5:  # Moderate run
            ai_score -= 8
        
        # Clamp to 0-100
        ai_score = max(0, min(100, int(ai_score)))
        
        # Calculate DYNAMIC Sentiment based on AI score
        if ai_score >= 70:
            sentiment = 80
            sentiment_label = "Strong Bullish"
        elif ai_score >= 60:
            sentiment = 65
            sentiment_label = "Bullish"
        elif ai_score >= 45:
            sentiment = 50
            sentiment_label = "Neutral"
        elif ai_score >= 30:
            sentiment = 35
            sentiment_label = "Bearish"
        else:
            sentiment = 20
            sentiment_label = "Strong Bearish"
        
        p['ai_score'] = ai_score
        p['sentiment'] = sentiment
        p['sentiment_label'] = sentiment_label


def save_watchlist_data(prices):
    """Save watchlist data for website"""
    if not prices:
        return False
    
    # Recalculate AI scores with actual RSI data
    recalculate_ai_scores(prices)
    
    # Let Council autonomously adjust watchlist
    dynamic_symbols = council_autonomous_watchlist_adjustment(prices)
    
    # Check if any RSI data is available
    has_rsi = any(p.get('rsi') is not None for p in prices.values())
    
    data = {
        "timestamp": datetime.now().isoformat(),
        "status": "live",
        "prices": prices,
        "symbols": dynamic_symbols,
        "council_note": "Autonomous management active - symbols adjust based on market conditions",
        "data_source_note": "RSI via Polygon.io" if has_rsi else "RSI unavailable"
    }
    
    # Save to opt directory
    opt_file = Path('/opt/stonk-ai/ai_watchlist_live.json')
    try:
        with open(opt_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved to {opt_file}")
    except Exception as e:
        logger.error(f"Failed to save to opt: {e}")
    
    # Save to website directory
    web_file = Path('/var/www/hedge-fund-website/ai_watchlist_live.json')
    try:
        web_file.parent.mkdir(parents=True, exist_ok=True)
        with open(web_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(prices)} watchlist prices to website")
        return True
    except Exception as e:
        logger.error(f"Failed to save to web: {e}")
        return False


def main():
    """Main loop - fetch prices every 30s, RSI every 5 minutes"""
    logger.info("AI Watchlist Price Fetcher Starting")
    
    # Get dynamic watchlist
    watchlist_symbols = get_watchlist_symbols()
    logger.info(f"Monitoring: {', '.join(watchlist_symbols)}")
    
    # Cache for RSI to avoid rate limits
    rsi_cache = {}
    last_rsi_fetch = 0
    RSI_FETCH_INTERVAL = 300  # 5 minutes
    
    # Track current watchlist to detect changes
    current_watchlist = set(watchlist_symbols)
    
    while True:
        # Refresh watchlist dynamically each iteration
        new_watchlist_symbols = get_watchlist_symbols()
        new_watchlist_set = set(new_watchlist_symbols)
        
        # Check if watchlist changed
        if new_watchlist_set != current_watchlist:
            removed = current_watchlist - new_watchlist_set
            added = new_watchlist_set - current_watchlist
            if removed or added:
                logger.info(f"🔄 Watchlist changed! Removed: {removed}, Added: {added}")
            current_watchlist = new_watchlist_set
            # Clear caches for clean slate
            rsi_cache.clear()
        
        watchlist_symbols = new_watchlist_symbols
        
        # Fetch prices from Alpaca (only for current watchlist)
        prices = fetch_watchlist_prices()
        
        # Filter prices to ONLY include current watchlist symbols
        if prices:
            prices = {k: v for k, v in prices.items() if k in current_watchlist}
        
        if prices:
            # Check if we need to refresh RSI
            now = time.time()
            if now - last_rsi_fetch > RSI_FETCH_INTERVAL:
                logger.info("Fetching RSI (Polygon primary, Yahoo fallback)...")
                # Load existing cache
                file_cache = load_rsi_cache()
                
                for symbol in watchlist_symbols:
                    if symbol in prices:
                        # Use fallback chain: Polygon -> Yahoo -> Cache
                        rsi, source = get_rsi_with_fallback(symbol)
                        if rsi:
                            rsi_cache[symbol] = rsi
                            file_cache[symbol] = {'rsi': rsi, 'timestamp': now, 'source': source}
                            prices[symbol]['rsi'] = rsi
                            logger.info(f"  {symbol}: RSI={rsi} (via {source})")
                        else:
                            logger.warning(f"  {symbol}: Could not fetch RSI")
                
                # Save cache to file
                save_rsi_cache(file_cache)
                last_rsi_fetch = now
            else:
                # Use cached RSI
                file_cache = load_rsi_cache()
                for symbol in prices:
                    if symbol in rsi_cache:
                        prices[symbol]['rsi'] = rsi_cache[symbol]
                    elif symbol in file_cache:
                        prices[symbol]['rsi'] = file_cache[symbol]['rsi']
            
            save_watchlist_data(prices)
            # Log sample data
            for symbol in list(prices.keys())[:3]:
                p = prices[symbol]
                rsi_str = f"RSI: {p['rsi']:.1f}" if p['rsi'] else "RSI: N/A"
                logger.info(f"{symbol}: ${p['price']:.2f} ({p['change_pct']:+.2f}%) {rsi_str}")
        else:
            logger.warning("Failed to fetch watchlist prices")
        
        time.sleep(30)  # Refresh prices every 30 seconds


if __name__ == "__main__":
    main()
