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
from alpaca_data import get_data_hub
from readiness_score import compute_confirmation_count
from signal_engine import SignalEngine, DEFAULT_UNIVERSE, COMPANY_NAMES


# Yahoo Finance for RSI (free alternative to paid Alpaca data)

# Polygon.io API - Primary RSI source
# Free tier: 5 API calls/minute, no daily limit
POLYGON_API_KEY = "ZzgS2QyoeY2aDdvz8Z0Ww66G0kJgLWxZ"

# Symbols that work better on Yahoo than Polygon free tier
YAHOO_PREFERRED = {'SQ', 'UPST'}  # Polygon free tier doesn't have these

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Company name mappings for display
OMPANY_NAMES = {
    'AMAT': 'Applied Materials Inc.',
    'AFRM': 'Affirm Holdings Inc.',
    'AMD': 'Advanced Micro Devices',
    'ABNB': 'Airbnb Inc.',
    'CDNS': 'Cadence Design Systems',
    'AAPL': 'Apple Inc.',
    'COST': 'Costco Wholesale Corp.',
    'APP': 'AppLovin Corp.',
    'AMZN': 'Amazon.com Inc.',
    'CHWY': 'Chewy Inc.',
    'COIN': 'Coinbase Global Inc.',
    'MSFT': 'Microsoft Corp.',
    'GOOGL': 'Alphabet Inc.',
    'META': 'Meta Platforms Inc.',
    'NVDA': 'NVIDIA Corp.',
    'SOXL': 'Direxion Daily Semiconductor Bull 3X',
    'TQQQ': 'ProShares UltraPro QQQ',
}

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
            f"{base}/v2/stocks/trades/latest?symbols={symbols_str}&feed=sip",
            headers=headers, timeout=30
        )
        
        # Get latest quotes for bid/ask spread
        quotes_resp = requests.get(
            f"{base}/v2/stocks/quotes/latest?symbols={symbols_str}&feed=sip",
            headers=headers, timeout=30
        )
        
        # Get historical bars for RSI calculation
        bars_resp = requests.get(
            f"{base}/v2/stocks/bars?symbols={symbols_str}&timeframe=1Day&limit=20&feed=sip&adjustment=all",
            headers=headers, timeout=30
        )
        
        # Get SNAPSHOTS for pre-calculated daily change % (more reliable than bars)
        snapshots_resp = requests.get(
            f"{base}/v2/stocks/snapshots?symbols={symbols_str}&feed=sip",
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
                    
                    # Get change % from SNAPSHOTS (most reliable) or calculate from bars
                    change_pct = 0.0
                    change_amount = 0.0
                    prev_close = current_price
                    rsi = None
                    
                    # Try snapshots first (pre-calculated daily change)
                    daily_high = daily_low = daily_vwap = None
                    if snapshots_resp.status_code == 200:
                        snapshots_data = snapshots_resp.json()
                        if symbol in snapshots_data:
                            snap = snapshots_data[symbol]
                            # Get prevDailyBar close as yesterday's close
                            prev_daily = snap.get('prevDailyBar', {})
                            if prev_daily and 'c' in prev_daily:
                                prev_close = float(prev_daily['c'])
                                if prev_close > 0:
                                    change_pct = ((current_price - prev_close) / prev_close) * 100
                                    change_amount = current_price - prev_close
                                    logger.info(f"{symbol}: Using snapshot change {change_pct:.2f}% (${prev_close:.2f} -> ${current_price:.2f})")
                            # Grab today's high/low/vwap from daily bar
                            dbar = snap.get('dailyBar', {})
                            if dbar:
                                daily_high = float(dbar.get('h', 0)) if dbar.get('h') else None
                                daily_low  = float(dbar.get('l', 0)) if dbar.get('l') else None
                                daily_vwap = float(dbar.get('vw', 0)) if dbar.get('vw') else None
                            # Today open from dailyBar
                            daily_open = float(dbar.get('o', 0)) if dbar.get('o') else None
                    
                    # Fallback to bars if snapshots didn't work
                    if change_pct == 0.0 and symbol in bars_data:
                        symbol_bars = bars_data[symbol]
                        if len(symbol_bars) >= 2:
                            prev_close = symbol_bars[-2]['c']
                            change_pct = ((current_price - prev_close) / prev_close) * 100
                            change_amount = current_price - prev_close
                            logger.info(f"{symbol}: Using bars change {change_pct:.2f}%")
                    
                    # VALIDATION: Ensure price is reasonable (not 0 or extreme outlier)
                    if current_price <= 0:
                        # Fall back to prev_close when market is closed (no live price)
                        if prev_close > 0:
                            current_price = prev_close
                            logger.info(f"{symbol}: No live price, using prev_close ${current_price:.2f}")
                        else:
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
                    # Extract volume data from bars
                    current_volume = None
                    avg_volume = None
                    if symbol in bars_data:
                        symbol_bars = bars_data[symbol]
                        logger.info(f"{symbol}: Got {len(symbol_bars)} bars, keys={list(symbol_bars[0].keys()) if symbol_bars else 'N/A'}")
                        if len(symbol_bars) >= 15:
                            price_history = [bar['c'] for bar in symbol_bars]
                            rsi = calculate_rsi(price_history)
                        # Extract volume even from single bar
                        if len(symbol_bars) >= 1:
                            sample_bar = symbol_bars[-1]
                            current_volume = sample_bar.get('v', 0)  # Latest bar volume
                            # Calculate average volume over available bars (up to 20 days)
                            if len(symbol_bars) >= 2:
                                avg_volume = sum(bar.get('v', 0) for bar in symbol_bars) / len(symbol_bars)
                            else:
                                avg_volume = current_volume  # If only 1 bar, use same for avg
                            logger.info(f"{symbol}: Volume extracted - current={current_volume:,.0f}, avg={avg_volume:,.0f}")

                    # RSI will be fetched separately from Polygon/Yahoo to avoid rate limits
                    # For now, leave as None - main() will populate from cache or fresh fetch

                    # Load canonical signal data from signal engine
                    try:
                        import json as _json
                        with open('/opt/stonk-ai/signals.json') as _f:
                            _sigs = {s['symbol']: s for s in _json.load(_f).get('signals', [])}
                        sig_data = _sigs.get(symbol, {})
                    except Exception:
                        sig_data = {}
                    
                    # Use signal engine's total_score as canonical AI score
                    ai_score = int(round(sig_data.get('total_score', 50)))
                    ai_score = max(30, min(100, ai_score))
                    
                    # Derive sentiment from signal tier (same logic the bot sees)
                    _tier = sig_data.get('tier', 'MONITOR')
                    if _tier in ('STRONG_NOW', 'NOW'):
                        sentiment = 80
                        sentiment_label = "Bullish"
                    elif _tier == 'WATCH':
                        sentiment = 60
                        sentiment_label = "Neutral"
                    else:
                        sentiment = 40
                        sentiment_label = "Bearish"


                    # Council target prices derived from live price
                    targets = {
                        'conservative_target': round(current_price * 0.88, 2),
                        'aggressive_target': round(current_price * 0.82, 2),
                        'stop_loss': round(current_price * 0.85, 2),
                        'profit_25': round(current_price * 1.25, 2),
                        'profit_50': round(current_price * 1.50, 2),
                        'signal': 'WAIT',
                        'council_note': 'Monitor for dip'
                    }

                    # Determine council signal from canonical signal engine data
                    _entry = sig_data.get('entry_eligible', False)
                    if _tier in ('STRONG_NOW', 'NOW') and _entry:
                        targets['signal'] = 'STRONG_BUY'
                        _r = sig_data.get('readiness_score', 0)
                        targets['council_note'] = 'Highest conviction (readiness %.0f) -- bot will buy' % _r
                    elif _tier == 'WATCH':
                        targets['signal'] = 'ACCUMULATE'
                        _r = sig_data.get('readiness_score', 0)
                        targets['council_note'] = 'Approaching entry -- readiness %.0f' % _r
                    else:
                        targets['signal'] = 'WAIT'
                        targets['council_note'] = 'Monitoring for signal revival'

                    prices[symbol] = {
                        'price': round(current_price, 2),
                        'change_pct': round(change_pct, 2),
                        'change_amount': round(change_amount, 2),
                        'rsi': rsi,
                        'bid': round(float(quote_data.get('bp', 0)), 2) if quote_data.get('bp') else None,
                        'ask': round(float(quote_data.get('ap', 0)), 2) if quote_data.get('ap') else None,
                        'bid_size': int(quote_data.get('bs', 0)) if quote_data.get('bs') else None,
                        'ask_size': int(quote_data.get('as', 0)) if quote_data.get('as') else None,
                        'daily_high': daily_high,
                        'daily_low': daily_low,
                        'daily_vwap': daily_vwap,
                        'daily_open': daily_open if 'daily_open' in locals() else None,
                        'volume': current_volume,
                        'avg_volume': avg_volume,
                        'company': COMPANY_NAMES.get(symbol, symbol),
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
    """Re-align AI scores with signal engine AFTER data is populated."""
    try:
        import json as _json
        with open('/opt/stonk-ai/signals.json') as _f:
            sigs = {s['symbol']: s for s in _json.load(_f).get('signals', [])}
    except Exception:
        sigs = {}
    
    for symbol, p in prices.items():
        sig = sigs.get(symbol, {})
        total = sig.get('total_score', 0)
        ai_score = int(round(total)) if total else 50
        ai_score = max(30, min(100, ai_score))
        
        tier = sig.get('tier', 'MONITOR')
        if tier in ('STRONG_NOW', 'NOW'):
            sentiment = 80
            sentiment_label = "Bullish"
        elif tier == 'WATCH':
            sentiment = 60
            sentiment_label = "Neutral"
        else:
            sentiment = 40
            sentiment_label = "Bearish"
        
        p['ai_score'] = ai_score
        p['sentiment'] = sentiment
        p['sentiment_label'] = sentiment_label
        p['confirmation_count'] = compute_confirmation_count(p.get('confirmations', {}))

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
    
    # Save to opt directory (atomic write to prevent race with health check)
    opt_file = Path('/opt/stonk-ai/ai_watchlist_live.json')
    try:
        import tempfile, os
        fd, tmp_path = tempfile.mkstemp(dir=str(opt_file.parent), suffix='.json.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
            os.rename(tmp_path, str(opt_file))
            os.chmod(str(opt_file), 0o644)
        except Exception:
            try:
                os.unlink(tmp_path)
            except:
                pass
            raise
        logger.info(f"Saved to {opt_file}")
    except Exception as e:
        logger.error(f"Failed to save to opt: {e}")
    
    # Enrich brain-managed watchlist instead of replacing it
    web_file = Path('/var/www/hedge-fund-website/ai_watchlist_live.json')
    try:
        brain_wl = None
        try:
            with open(web_file) as f:
                brain_wl = json.load(f)
        except Exception:
            pass

        if brain_wl and 'prices' in brain_wl:
            # Update prices for stocks that exist in brain watchlist
            for symbol, p in prices.items():
                if symbol in brain_wl['prices']:
                    brain_wl['prices'][symbol].update(p)
                else:
                    brain_wl['prices'][symbol] = p
                    # Update targets based on real price
                    if p.get('price', 0) > 0:
                        price = p['price']
                        brain_wl['prices'][symbol]['bid'] = round(price * 0.999, 2)
                        brain_wl['prices'][symbol]['ask'] = round(price * 1.001, 2)
                        existing = brain_wl['prices'][symbol].get('targets', {})
                        brain_wl['prices'][symbol]['targets'] = {
                            'conservative_target': round(price * 0.88, 2),
                            'aggressive_target': round(price * 0.82, 2),
                            'stop_loss': round(price * 0.90, 2),
                            'profit_25': round(price * 1.25, 2),
                            'profit_50': round(price * 1.50, 2),
                            'signal': existing.get('signal', 'MONITOR'),
                            'council_note': existing.get('council_note', ''),
                        }
            data_to_save = brain_wl
        else:
            data_to_save = data


        # --- ALIGNMENT SELF-TEST ---
        try:
            import json as _json
            with open('/opt/stonk-ai/signals.json') as _f:
                _sigs = {s['symbol']: s for s in _json.load(_f).get('signals', [])}
            _failures = []
            for _sym, _p in data_to_save.get('prices', {}).items():
                _total = _sigs.get(_sym, {}).get('total_score')
                _ai = _p.get('ai_score')
                if _total is not None and _ai is not None and abs(_ai - round(_total)) > 2:
                    _failures.append(f"{_sym}: ai={_ai} total={round(_total)}")
            if _failures:
                logger.critical(f"ALIGNMENT FAIL: {_failures}")
        except Exception:
            pass
        # ---------------------------
        web_file.parent.mkdir(parents=True, exist_ok=True)
        import tempfile, os
        fd, tmp_path = tempfile.mkstemp(dir=str(web_file.parent), suffix='.json.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data_to_save, f, indent=2)
            os.rename(tmp_path, str(web_file))
            os.chmod(str(web_file), 0o644)
        except Exception:
            try:
                os.unlink(tmp_path)
            except:
                pass
            raise
        logger.info(f"Enriched {len(prices)} prices on brain watchlist")
        return True
    except Exception as e:
        logger.error(f"Failed to save to web: {e}")
        return False


def is_market_open():
    """Check if US stock market is currently open (NYSE/NASDAQ schedule)"""
    now = datetime.now()
    
    # Check if weekend
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Check US market holidays for 2026
    market_holidays_2026 = [
        (1, 1), (1, 19), (2, 16), (4, 3), (5, 25), (6, 19),
        (7, 4), (9, 7), (10, 12), (11, 11), (11, 26), (12, 25),
    ]
    
    today = (now.month, now.day)
    if today in market_holidays_2026:
        return False
    
    return True


def _enrich_with_tiers(prices):
    """Merge tier metadata from signals.json so the watchlist keeps PRIME/BUILDING/WATCHING/TRACKING labels."""
    try:
        import json
        from pathlib import Path
        signals_path = Path("/opt/stonk-ai/signals.json")
        if not signals_path.exists():
            return
        with open(signals_path) as f:
            signals = {s.get("symbol"): s for s in json.load(f).get("signals", [])}
        tier_map = {
            "STRONG_NOW": "BUILDING",
            "NOW": "BUILDING",
            "WATCH": "WATCHING",
            "MONITOR": "TRACKING",
        }
        for sym, data in prices.items():
            sig = signals.get(sym, {})
            signal_tier = sig.get("tier", "MONITOR")
            # PRIME only when entry-eligible; otherwise fall back to BUILDING for STRONG_NOW/NOW
            if sig.get("entry_eligible"):
                display_tier = "PRIME"
            else:
                display_tier = tier_map.get(signal_tier, "TRACKING")
            data["signal_tier"] = signal_tier
            data["display_tier"] = display_tier
            data["tier"] = display_tier
            # Copy confirmations metadata for popup rendering
            if "confirmations" in sig:
                data["confirmations"] = sig["confirmations"]
            if "confirmation_count" in sig:
                data["confirmation_count"] = sig["confirmation_count"]
            elif "confirmations" in data and isinstance(data["confirmations"], dict):
                data["confirmation_count"] = sum(1 for v in data["confirmations"].values() if v is True)
    except Exception as e:
        logger.debug(f"Failed to enrich tiers: {e}")
def get_rsi_from_alpaca(symbol, config=None):
    """Fetch RSI using Alpaca data hub (paid data, no rate limits)"""
    try:
        hub = get_data_hub()
        bars = hub.get_daily_bars([symbol], days=20)
        if symbol in bars and len(bars[symbol]["closes"]) >= 15:
            return calculate_rsi(bars[symbol]["closes"])
    except Exception as e:
        logger.debug(f"Alpaca RSI failed for {symbol}: {e}")
    return None

def get_rsi_from_signals(symbol):
    """Get RSI directly from signals.json (already computed by signal engine)"""
    try:
        import json
        with open("/opt/stonk-ai/signals.json") as f:
            data = json.load(f)
        for sig in data.get("signals", []):
            if sig.get("symbol") == symbol:
                return sig.get("rsi14")
    except Exception:
        pass
    return None


def regenerate_sentiment_for_watchlist(watchlist_symbols):
    """Trigger sentiment regeneration when watchlist changes"""
    try:
        import subprocess
        import sys
        
        # Update generate_sentiment.py with new watchlist
        sentiment_script = Path("/opt/stonk-ai/generate_sentiment.py")
        if sentiment_script.exists():
            # Read current script
            with open(sentiment_script, 'r') as f:
                content = f.read()
            
            # Create new watchlist string
            symbols_str = ', '.join([f'"{s}"' for s in sorted(watchlist_symbols)])
            new_watchlist_line = f"WATCHLIST_TICKERS = [{symbols_str}]"
            
            # Replace the WATCHLIST_TICKERS line
            import re
            pattern = r'WATCHLIST_TICKERS = \[.*?\]'
            if re.search(pattern, content, re.DOTALL):
                content = re.sub(pattern, new_watchlist_line, content, flags=re.DOTALL)
                with open(sentiment_script, 'w') as f:
                    f.write(content)
                logger.info(f"Updated generate_sentiment.py with {len(watchlist_symbols)} symbols")
        
        # Run sentiment generation in background
        subprocess.Popen(
            [sys.executable, "/opt/stonk-ai/generate_sentiment.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd="/opt/stonk-ai"
        )
        logger.info("Triggered sentiment regeneration")
    except Exception as e:
        logger.warning(f"Could not regenerate sentiment: {e}")


def main():
    """Main loop - fetch prices every 60s, RSI every 5 minutes, only during market hours"""
    logger.info("AI Watchlist Price Fetcher Starting")
    
    # Get dynamic watchlist
    watchlist_symbols = get_watchlist_symbols()
    logger.info(f"Monitoring: {', '.join(watchlist_symbols)}")
    
    # Cache for RSI
    rsi_cache = {}
    last_rsi_fetch = 0
    RSI_FETCH_INTERVAL = 300  # 5 minutes
    
    # Track current watchlist to detect changes
    current_watchlist = set(watchlist_symbols)
    
    # Track if we need to regenerate sentiment
    sentiment_regenerated = False
    
    # On startup, check if sentiment files exist for all watchlist symbols
    sentiment_dir = Path("/var/www/hedge-fund-website/sentiment")
    missing_sentiment = [s for s in watchlist_symbols if not (sentiment_dir / f"{s}.json").exists()]
    if missing_sentiment:
        logger.info(f"Missing sentiment for {len(missing_sentiment)} symbols: {missing_sentiment}")
        regenerate_sentiment_for_watchlist(watchlist_symbols)
        sentiment_regenerated = True
    
    config = load_config()
    
    while True:
        # Check market hours
        if not is_market_open():
            logger.debug("Markets closed - sleeping 5 minutes")
            time.sleep(300)
            continue
        
        # Refresh watchlist dynamically each iteration
        new_watchlist_symbols = get_watchlist_symbols()
        new_watchlist_set = set(new_watchlist_symbols)
        
        # Check if watchlist changed
        if new_watchlist_set != current_watchlist:
            removed = current_watchlist - new_watchlist_set
            added = new_watchlist_set - current_watchlist
            if removed or added:
                logger.info(f"🔄 Watchlist changed! Removed: {removed}, Added: {added}")
                # Trigger sentiment regeneration for new symbols
                regenerate_sentiment_for_watchlist(new_watchlist_symbols)
                sentiment_regenerated = True
            current_watchlist = new_watchlist_set
            rsi_cache.clear()
        
        watchlist_symbols = new_watchlist_symbols
        
        # Fetch prices from Alpaca
        prices = fetch_watchlist_prices()
        
        if prices:
            prices = {k: v for k, v in prices.items() if k in current_watchlist}
        
        if prices:
            now = time.time()
            if now - last_rsi_fetch > RSI_FETCH_INTERVAL:
                logger.info("Fetching RSI from Alpaca...")
                file_cache = {}
                
                for symbol in watchlist_symbols:
                    if symbol in prices:
                        # Use Alpaca first, fallback to Yahoo only if needed
                        rsi = get_rsi_from_alpaca(symbol, config)
                        source = 'alpaca'
                        
                        if rsi is None:
                            rsi = get_rsi_from_signals(symbol)
                            source = 'signals_engine'
                        
                        if rsi:
                            rsi_cache[symbol] = rsi
                            # RSI cache removed
                            prices[symbol]['rsi'] = rsi
                            logger.info(f"  {symbol}: RSI={rsi} (via {source})")
                        else:
                            logger.warning(f"  {symbol}: Could not fetch RSI")
                
                # save_rsi_cache removed
                last_rsi_fetch = now
            else:
                file_cache = {}
                for symbol in prices:
                    if symbol in rsi_cache:
                        prices[symbol]['rsi'] = rsi_cache[symbol]
                    else:
                        rsi = get_rsi_from_signals(symbol)
                        if rsi:
                            prices[symbol]['rsi'] = rsi
            
            # ── Extended Hours Data ──
            try:
                hub = get_data_hub()
                ext_data = hub.get_extended_hours_bars(list(prices.keys()))
                for sym, ed in ext_data.items():
                    if sym in prices:
                        for k, v in ed.items():
                            # Don't overwrite real data with empty fallback values
                            if v is None or v == '':
                                continue
                            prices[sym][k] = v
                if ext_data:
                    logger.info(f"Extended hours data for {len(ext_data)} symbols")
            except Exception as e:
                logger.debug(f"Extended hours fetch failed: {e}")
            
            _enrich_with_tiers(prices)
            save_watchlist_data(prices)
            for symbol in list(prices.keys())[:3]:
                p = prices[symbol]
                rsi_str = f"RSI: {p['rsi']:.1f}" if p['rsi'] else "RSI: N/A"
                logger.info(f"{symbol}: ${p['price']:.2f} ({p['change_pct']:+.2f}%) {rsi_str}")
        else:
            logger.warning("Failed to fetch watchlist prices")
        
        time.sleep(60)  # Refresh every 60 seconds


if __name__ == "__main__":
    main()
