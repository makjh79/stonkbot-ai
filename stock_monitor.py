#!/usr/bin/env python3
"""
Stock Monitor for Howie
Tracks: NOW, HOOD, SOFI, AVGO, MSFT, NFLX, UNH, NVO, NVOX, META, AMZN, WFC, BABA, JD
Alerts via Telegram
Includes: Price alerts, Technical levels, Unusual Options Activity
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Stock configuration
WATCHLIST = {
    "NOW": {
        "name": "ServiceNow",
        "alerts": {"pct_threshold": 5.0, "price_high": 150.0, "price_low": 120.0},
        "levels": {"support": [125.0, 115.0, 105.0], "resistance": [145.0, 155.0, 170.0]}
    },
    "HOOD": {
        "name": "Robinhood",
        "alerts": {"pct_threshold": 5.0, "price_high": 100.0, "price_low": 75.0},
        "levels": {"support": [75.0, 65.0, 55.0], "resistance": [90.0, 100.0, 115.0]}
    },
    "SOFI": {
        "name": "SoFi Technologies",
        "alerts": {"pct_threshold": 5.0, "price_high": 25.0, "price_low": 15.0},
        "levels": {"support": [12.0, 10.0, 8.0], "resistance": [18.0, 22.0, 28.0]}
    },
    "AVGO": {
        "name": "Broadcom",
        "alerts": {"pct_threshold": 5.0, "price_high": 500.0, "price_low": 420.0},
        "levels": {"support": [450.0, 420.0, 380.0], "resistance": [500.0, 550.0, 600.0]}
    },
    "MSFT": {
        "name": "Microsoft",
        "alerts": {"pct_threshold": 5.0, "price_high": 500.0, "price_low": 420.0},
        "levels": {"support": [440.0, 400.0, 360.0], "resistance": [500.0, 540.0, 590.0]}
    },
    "NFLX": {
        "name": "Netflix",
        "alerts": {"pct_threshold": 5.0, "price_high": 100.0, "price_low": 75.0},
        "levels": {"support": [85.0, 75.0, 65.0], "resistance": [100.0, 115.0, 130.0]}
    },
    "UNH": {
        "name": "UnitedHealth",
        "alerts": {"pct_threshold": 5.0, "price_high": 420.0, "price_low": 350.0},
        "levels": {"support": [380.0, 350.0, 320.0], "resistance": [420.0, 460.0, 500.0]}
    },
    "NVO": {
        "name": "Novo-Nordisk",
        "alerts": {"pct_threshold": 5.0, "price_high": 50.0, "price_low": 38.0},
        "levels": {"support": [36.0, 32.0, 28.0], "resistance": [48.0, 55.0, 65.0]}
    },
    "NVOX": {
        "name": "Defiance 2X NVDA",
        "alerts": {"pct_threshold": 8.0, "price_high": 18.0, "price_low": 12.0},
        "levels": {"support": [12.0, 9.0, 7.0], "resistance": [18.0, 25.0, 35.0]}
    },
    "META": {
        "name": "Meta Platforms",
        "alerts": {"pct_threshold": 5.0, "price_high": 670.0, "price_low": 550.0},
        "levels": {"support": [550.0, 500.0, 450.0], "resistance": [650.0, 700.0, 760.0]}
    },
    "AMZN": {
        "name": "Amazon",
        "alerts": {"pct_threshold": 5.0, "price_high": 290.0, "price_low": 240.0},
        "levels": {"support": [230.0, 200.0, 170.0], "resistance": [260.0, 290.0, 320.0]}
    },
    "WFC": {
        "name": "Wells Fargo",
        "alerts": {"pct_threshold": 5.0, "price_high": 85.0, "price_low": 70.0},
        "levels": {"support": [60.0, 55.0, 48.0], "resistance": [75.0, 85.0, 95.0]}
    },
    "BABA": {
        "name": "Alibaba",
        "alerts": {"pct_threshold": 5.0, "price_high": 140.0, "price_low": 110.0},
        "levels": {"support": [120.0, 110.0, 95.0], "resistance": [140.0, 160.0, 185.0]}
    },
    "JD": {
        "name": "JD.com",
        "alerts": {"pct_threshold": 5.0, "price_high": 45.0, "price_low": 25.0},
        "levels": {"support": [28.0, 24.0, 20.0], "resistance": [35.0, 42.0, 50.0]}
    },
}

DATA_FILE = Path("/root/.openclaw/workspace/stock_data.json")
EXTENDED_DATA_FILE = Path("/root/.openclaw/workspace/extended_data.json")
ALERT_HISTORY_FILE = Path("/root/.openclaw/workspace/alert_history.json")
OPTIONS_DATA_FILE = Path("/root/.openclaw/workspace/options_data.json")
FILINGS_DATA_FILE = Path("/root/.openclaw/workspace/filings_data.json")
FRED_DATA_FILE = Path("/root/.openclaw/workspace/fred_data.json")
PREDICTION_DATA_FILE = Path("/root/.openclaw/workspace/prediction_data.json")
BUDGET_FILE = Path("/root/.openclaw/workspace/budget_tracker.json")
MA_DATA_FILE = Path("/root/.openclaw/workspace/ma_data.json")
ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

# API Keys for market data
FINNHUB_API_KEY = os.environ.get('FINNHUB_API_KEY', '')
POLYGON_API_KEY = os.environ.get('POLYGON_API_KEY', 'vnHD6Gqmbs1puFiMyf_B1z2eYMKVXeRL')

# Budget settings
MONTHLY_BUDGET = 20.00  # USD
BUDGET_WARNING_PCT = 0.75  # Warn at 75% of budget

# 13F filing sources
FILING_SOURCES = [
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=13F-HR&company=&State=&Country=&SIC=&owner=include&count=40&output=atom",
]

# FRED API endpoints for key interest rate data (no API key needed for basic series)
FRED_SERIES = {
    "DFF": {"name": "Federal Funds Effective Rate", "impact": "high"},
    "SOFR": {"name": "SOFR", "impact": "high"},
    "DGS10": {"name": "10-Year Treasury Yield", "impact": "high"},
    "DGS2": {"name": "2-Year Treasury Yield", "impact": "high"},
    "DGS30": {"name": "30-Year Treasury Yield", "impact": "medium"},
    "T10Y2Y": {"name": "10Y-2Y Spread", "impact": "high"},
    "DPRIME": {"name": "Bank Prime Loan Rate", "impact": "medium"},
}

# Prediction markets - DISABLED (markets closed, causing 404 errors)
# To re-enable: Research current active markets at https://polymarket.com
PREDICTION_MARKETS = {
    # "fed_rates": {
    #     "polymarket": "will-the-fed-cut-rates-in-june",
    #     "keywords": ["rate cut", "Fed", "FOMC"],
    #     "impact_stocks": ["SOFI", "HOOD", "WFC", "UNH"],
    #     "threshold": 5.0
    # },
}

def load_data():
    """Load previous day's data for comparison"""
    if DATA_FILE.exists():
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_data(data):
    """Save current data"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_alert_history():
    """Load alert history to avoid spam"""
    if ALERT_HISTORY_FILE.exists():
        with open(ALERT_HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_alert_history(history):
    """Save alert history"""
    with open(ALERT_HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def load_ma_data():
    """Load moving average data"""
    if MA_DATA_FILE.exists():
        with open(MA_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_ma_data(data):
    """Save moving average data"""
    with open(MA_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def calculate_moving_averages(symbol):
    """Calculate 50, 100, 200 day moving averages for a stock"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get 1 year of data to ensure we have enough for 200 MA
        hist = ticker.history(period="1y")
        if len(hist) < 200:
            return None
        
        mas = {
            "50": round(hist['Close'].rolling(window=50).mean().iloc[-1], 2),
            "100": round(hist['Close'].rolling(window=100).mean().iloc[-1], 2),
            "200": round(hist['Close'].rolling(window=200).mean().iloc[-1], 2),
            "price": round(hist['Close'].iloc[-1], 2),
            "timestamp": datetime.now().isoformat()
        }
        
        return mas
    except Exception as e:
        print(f"Error calculating MAs for {symbol}: {e}")
        return None

def check_ma_crossovers(symbol, config, current_price, alert_history):
    """Check for moving average crossovers (Golden Cross / Death Cross)"""
    alerts = []
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    
    mas = calculate_moving_averages(symbol)
    if not mas:
        return alerts
    
    prev_data = load_ma_data()
    prev_symbol_data = prev_data.get(symbol, {})
    
    ma_periods = [
        ("50", "50-day"),
        ("100", "100-day"),
        ("200", "200-day")
    ]
    
    for ma_key, ma_name in ma_periods:
        ma_value = mas.get(ma_key)
        if not ma_value:
            continue
        
        prev_ma = prev_symbol_data.get(ma_key)
        
        # Check for crossover
        if prev_ma:
            was_above = prev_symbol_data.get('price', current_price) > prev_ma
            is_above = current_price > ma_value
            
            if was_above != is_above:
                # Crossover occurred
                direction = "ABOVE" if is_above else "BELOW"
                emoji = "🚀" if is_above else "🔻"
                cross_type = "Golden Cross" if is_above else "Death Cross"
                
                alert_key = f"{symbol}_ma{ma_key}_{today}"
                if alert_key not in alert_history:
                    alerts.append({
                        "symbol": symbol,
                        "name": config["name"],
                        "type": "ma_crossover",
                        "message": f"{emoji} MA ALERT | {symbol} crossed {direction} {ma_name} MA\n   Price: ${current_price:.2f} | MA{ma_key}: ${ma_value:.2f}\n   ({cross_type})",
                        "priority": "high" if ma_key == "200" else "medium"
                    })
                    alert_history[alert_key] = now.isoformat()
        else:
            # First run - just store the data, no alert
            pass
    
    # Update stored MA data
    prev_data[symbol] = mas
    save_ma_data(prev_data)
    
    return alerts

def check_technical_levels(symbol, config, current_price, alert_history):
    """Check if price is near support/resistance levels"""
    alerts = []
    now = datetime.now()
    levels = config.get("levels", {})
    support_levels = levels.get("support", [])
    resistance_levels = levels.get("resistance", [])
    
    # Define "near" threshold as 2% from the level
    threshold_pct = 0.02
    
    # Check support levels (price near or below support)
    for i, level in enumerate(support_levels):
        distance_pct = abs(current_price - level) / level
        if distance_pct <= threshold_pct:
            # Only alert once per level per day
            alert_key = f"{symbol}_support_{level}_{now.strftime('%Y-%m-%d')}" 
            if alert_key not in alert_history:
                if current_price < level:
                    emoji = "🔻"
                    status = "BROKE BELOW"
                else:
                    emoji = "🛡️"
                    status = "TESTING"
                
                alerts.append({
                    "symbol": symbol,
                    "name": config["name"],
                    "type": "support",
                    "message": f"{emoji} SUPPORT | {symbol} {status} S{i+1} @ ${level:.2f} | Current: ${current_price:.2f}",
                    "priority": "high" if current_price < level else "medium"
                })
                alert_history[alert_key] = now.isoformat()
    
    # Check resistance levels (price near or above resistance)
    for i, level in enumerate(resistance_levels):
        distance_pct = abs(current_price - level) / level
        if distance_pct <= threshold_pct:
            alert_key = f"{symbol}_resistance_{level}_{now.strftime('%Y-%m-%d')}"
            if alert_key not in alert_history:
                if current_price > level:
                    emoji = "🚀"
                    status = "BROKE ABOVE"
                else:
                    emoji = "⛰️"
                    status = "TESTING"
                
                alerts.append({
                    "symbol": symbol,
                    "name": config["name"],
                    "type": "resistance",
                    "message": f"{emoji} RESISTANCE | {symbol} {status} R{i+1} @ ${level:.2f} | Current: ${current_price:.2f}",
                    "priority": "high" if current_price > level else "medium"
                })
                alert_history[alert_key] = now.isoformat()
    
    return alerts

def load_options_data():
    """Load previous options data"""
    if OPTIONS_DATA_FILE.exists():
        with open(OPTIONS_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_options_data(data):
    """Save options data"""
    with open(OPTIONS_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_finnhub_data(symbols):
    """Fetch premarket/after-hours data from Finnhub"""
    import requests
    
    if not FINNHUB_API_KEY:
        return {}
    
    data = {}
    
    for symbol in symbols:
        try:
            # Quote endpoint gives current price including premarket
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token=***"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                quote = response.json()
                
                current = quote.get('c', 0)  # Current price
                prev_close = quote.get('pc', current)  # Previous close
                open_price = quote.get('o', current)  # Open
                high = quote.get('h', current)  # High
                low = quote.get('l', current)  # Low
                
                if current > 0:
                    change_pct = ((current - prev_close) / prev_close) * 100 if prev_close else 0
                    
                    # Determine session based on time
                    now = datetime.now()
                    hour_et = (now.hour - 4) % 24  # Convert UTC to ET (approx)
                    
                    if 4 <= hour_et < 9:
                        session = "premarket"
                    elif 9 <= hour_et < 16:
                        session = "regular"
                    elif 16 <= hour_et < 20:
                        session = "after_hours"
                    else:
                        session = "overnight"
                    
                    data[symbol] = {
                        "price": round(current, 2),
                        "change_pct": round(change_pct, 2),
                        "prev_close": round(prev_close, 2),
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "volume": 0,  # Finnhub quote doesn't include volume
                        "timestamp": now.isoformat(),
                        "session": session,
                        "source": "finnhub"
                    }
        except Exception as e:
            print(f"Error fetching {symbol} from Finnhub: {e}")
    
    return data

def fetch_stock_data(symbols, include_extended=True):
    """Fetch stock data using Finnhub (premarket) -> Alpaca (extended) -> yfinance (fallback)"""
    data = {}
    
    # Try Finnhub FIRST for accurate premarket/after-hours data
    if include_extended and FINNHUB_API_KEY:
        try:
            finnhub_data = fetch_finnhub_data(symbols)
            data.update(finnhub_data)
            if finnhub_data:
                print(f"✅ Finnhub: {len(finnhub_data)} symbols")
        except Exception as e:
            print(f"Finnhub fetch failed: {e}")
    
    # Fallback to Alpaca for remaining symbols
    remaining_symbols = [s for s in symbols if s not in data]
    if include_extended and remaining_symbols:
        try:
            alpaca_data = fetch_alpaca_extended_data(remaining_symbols)
            data.update(alpaca_data)
            if alpaca_data:
                print(f"✅ Alpaca: {len(alpaca_data)} symbols")
        except Exception as e:
            print(f"Alpaca fetch failed, falling back to yfinance: {e}")
    
    # Fallback to yfinance for any symbols Alpaca missed
    remaining_symbols = [s for s in symbols if s not in data]
    if remaining_symbols:
        try:
            import yfinance as yf
            for symbol in remaining_symbols:
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="2d")
                    if len(hist) >= 1:
                        current = hist['Close'].iloc[-1]
                        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current
                        change_pct = ((current - prev_close) / prev_close) * 100 if prev_close else 0
                        
                        data[symbol] = {
                            "price": round(current, 2),
                            "change_pct": round(change_pct, 2),
                            "prev_close": round(prev_close, 2),
                            "volume": int(hist['Volume'].iloc[-1]) if 'Volume' in hist.columns else 0,
                            "timestamp": datetime.now().isoformat(),
                            "session": "regular",
                            "source": "yfinance"
                        }
                except Exception as e:
                    print(f"Error fetching {symbol} from yfinance: {e}")
        except ImportError:
            print("yfinance not installed. Run: pip install yfinance")
    
    return data

def load_alpaca_config():
    """Load Alpaca API credentials"""
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def fetch_alpaca_extended_data(symbols):
    """Fetch extended hours data from Alpaca Markets"""
    import requests
    
    config = load_alpaca_config()
    if not config:
        return {}
    
    data = {}
    headers = {
        "APCA-API-KEY-ID": config["api_key"],
        "APCA-API-SECRET-KEY": config["api_secret"]
    }
    
    try:
        # Get latest bars for all symbols at once (more efficient)
        symbols_str = ",".join(symbols)
        url = f"{config['data_url']}/v2/stocks/bars/latest?symbols={symbols_str}"
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            bars_data = response.json().get('bars', {})
            
            for symbol, bar in bars_data.items():
                if bar:
                    current_price = bar.get('c', 0)  # Close price
                    prev_close = bar.get('o', current_price)  # Open as proxy for prev close
                    
                    if current_price > 0:
                        change_pct = ((current_price - prev_close) / prev_close) * 100 if prev_close else 0
                        volume = bar.get('v', 0)
                        timestamp = bar.get('t', datetime.now().isoformat())
                        
                        data[symbol] = {
                            "price": round(current_price, 2),
                            "change_pct": round(change_pct, 2),
                            "prev_close": round(prev_close, 2),
                            "volume": volume,
                            "timestamp": timestamp,
                            "session": "extended",
                            "source": "alpaca"
                        }
    except Exception as e:
        print(f"Error fetching Alpaca extended data: {e}")
    
    return data

def fetch_options_flow(symbol):
    """Fetch options data and look for unusual activity"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get options expirations
        expirations = ticker.options
        if not expirations:
            return None
            
        unusual_flow = []
        
        # Check next 3 expiration dates
        for exp_date in expirations[:3]:
            try:
                opt_chain = ticker.option_chain(exp_date)
                calls = opt_chain.calls
                puts = opt_chain.puts
                
                # Look for unusual volume vs OI
                for opt_type, chain in [('CALL', calls), ('PUT', puts)]:
                    if chain.empty:
                        continue
                    
                    # Filter for meaningful volume
                    active = chain[chain['volume'] >= 100]
                    
                    for _, row in active.iterrows():
                        strike = row['strike']
                        volume = int(row['volume'])
                        oi = int(row['openInterest']) if 'openInterest' in row else 0
                        
                        # Unusual if volume > 3x OI and OI > 0
                        if oi > 0 and volume > oi * 3:
                            unusual_flow.append({
                                'symbol': symbol,
                                'expiration': exp_date,
                                'strike': strike,
                                'type': opt_type,
                                'volume': volume,
                                'open_interest': oi,
                                'ratio': round(volume / oi, 1) if oi > 0 else 0,
                                'last_price': round(row['lastPrice'], 2),
                                'iv': round(row['impliedVolatility'], 2) if 'impliedVolatility' in row else 0
                            })
            except Exception as e:
                continue
                
        return unusual_flow if unusual_flow else None
    except Exception as e:
        return None

def check_alerts(current_data, previous_data):
    """Check for alert conditions including technical levels"""
    alerts = []
    alert_history = load_alert_history()
    now = datetime.now()
    
    for symbol, config in WATCHLIST.items():
        if symbol not in current_data:
            continue
            
        current = current_data[symbol]
        alert_config = config["alerts"]
        price = current["price"]
        change_pct = current["change_pct"]
        
        # Check percentage threshold
        if abs(change_pct) >= alert_config["pct_threshold"]:
            alert_key = f"{symbol}_pct_{now.strftime('%Y-%m-%d')}"
            if alert_key not in alert_history:
                direction = "📈 UP" if change_pct > 0 else "📉 DOWN"
                alerts.append({
                    "symbol": symbol,
                    "name": config["name"],
                    "type": "percentage",
                    "message": f"{direction} {abs(change_pct):.2f}% | {symbol} @ ${price:.2f}",
                    "priority": "high" if abs(change_pct) >= 8 else "medium"
                })
                alert_history[alert_key] = now.isoformat()
        
        # Check price thresholds
        if price >= alert_config["price_high"]:
            alert_key = f"{symbol}_high_{now.strftime('%Y-%m-%d')}"
            if alert_key not in alert_history:
                alerts.append({
                    "symbol": symbol,
                    "name": config["name"],
                    "type": "price_high",
                    "message": f"⬆️ HIGH ALERT | {symbol} broke above ${alert_config['price_high']:.2f} | Current: ${price:.2f}",
                    "priority": "medium"
                })
                alert_history[alert_key] = now.isoformat()
        
        if price <= alert_config["price_low"]:
            alert_key = f"{symbol}_low_{now.strftime('%Y-%m-%d')}"
            if alert_key not in alert_history:
                alerts.append({
                    "symbol": symbol,
                    "name": config["name"],
                    "type": "price_low",
                    "message": f"⬇️ LOW ALERT | {symbol} dropped below ${alert_config['price_low']:.2f} | Current: ${price:.2f}",
                    "priority": "high"
                })
                alert_history[alert_key] = now.isoformat()
        
        # Check support/resistance technical levels
        level_alerts = check_technical_levels(symbol, config, price, alert_history)
        alerts.extend(level_alerts)
        
        # Check moving average crossovers
        ma_alerts = check_ma_crossovers(symbol, config, price, alert_history)
        alerts.extend(ma_alerts)
        
        # Check for extended hours gaps (pre-market/after-hours)
        ext_price = current.get("ext_price")
        ext_gap_pct = current.get("ext_gap_pct")
        if ext_price and ext_gap_pct and abs(ext_gap_pct) >= 3.0:
            alert_key = f"{symbol}_ext_gap_{now.strftime('%Y-%m-%d')}"
            if alert_key not in alert_history:
                direction = "📈" if ext_gap_pct > 0 else "📉"
                session = "Pre-market" if datetime.now().hour < 14 else "After-hours"
                alerts.append({
                    "symbol": symbol,
                    "name": config["name"],
                    "type": "extended_hours",
                    "message": f"🌙 EXTENDED HOURS | {symbol} {session} gap\n   {direction} {abs(ext_gap_pct):.2f}% | Extended: ${ext_price:.2f} vs Close: ${price:.2f}",
                    "priority": "high" if abs(ext_gap_pct) >= 5 else "medium"
                })
                alert_history[alert_key] = now.isoformat()
    
    # Clean old alerts (keep 7 days)
    cutoff = (now - timedelta(days=7)).isoformat()
    alert_history = {k: v for k, v in alert_history.items() if v > cutoff}
    save_alert_history(alert_history)
    
    # Also check for macro/FRED alerts
    fred_alerts = check_fred_alerts()
    alerts.extend(fred_alerts)
    
    # Also check for prediction market alerts
    pred_alerts = check_prediction_alerts()
    alerts.extend(pred_alerts)
    
    return alerts

def check_options_alerts():
    """Check for unusual options activity"""
    alerts = []
    prev_options = load_options_data()
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    
    for symbol in WATCHLIST.keys():
        try:
            flow = fetch_options_flow(symbol)
            if flow:
                for trade in flow[:3]:  # Top 3 per symbol
                    alert_key = f"{symbol}_opt_{trade['strike']}_{trade['expiration']}_{today}"
                    if alert_key not in prev_options:
                        emoji = "📞 CALL" if trade['type'] == 'CALL' else "🛡️ PUT"
                        alerts.append({
                            "symbol": symbol,
                            "type": "options",
                            "message": f"{emoji} UNUSUAL | {symbol} {trade['strike']:.0f} {trade['expiration']} | Vol: {trade['volume']} vs OI: {trade['open_interest']} ({trade['ratio']}x)",
                            "priority": "medium"
                        })
                        prev_options[alert_key] = now.isoformat()
        except Exception as e:
            continue
    
    # Clean old options alerts (keep 3 days)
    cutoff = (now - timedelta(days=3)).isoformat()
    prev_options = {k: v for k, v in prev_options.items() if v > cutoff}
    save_options_data(prev_options)
    
    return alerts

def load_filings_data():
    """Load previous filings data"""
    if FILINGS_DATA_FILE.exists():
        with open(FILINGS_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_filings_data(data):
    """Save filings data"""
    with open(FILINGS_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_13f_filings():
    """Fetch recent 13F-HR filings from SEC and check for watchlist stocks"""
    import urllib.request
    import xml.etree.ElementTree as ET
    
    filings = []
    prev_filings = load_filings_data()
    now = datetime.now()
    
    try:
        # SEC EDGAR RSS feed for 13F-HR filings
        url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=13F-HR&company=&State=&Country=&SIC=&owner=include&count=40&output=atom"
        
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; OpenClaw Bot; Contact: jarvis@openclaw.ai)'
            }
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
            
        # Parse Atom feed
        root = ET.fromstring(content)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        for entry in root.findall('atom:entry', ns):
            title = entry.find('atom:title', ns)
            updated = entry.find('atom:updated', ns)
            link = entry.find('atom:link', ns)
            
            if title is None:
                continue
                
            title_text = title.text or ""
            
            # Check if any watchlist symbol is in the filing title
            for symbol in WATCHLIST.keys():
                if symbol in title_text.upper():
                    filing_id = f"{symbol}_{updated.text if updated is not None else ''}"
                    
                    if filing_id not in prev_filings:
                        # Parse filer name from title
                        filer = title_text.split('-')[0].strip() if '-' in title_text else title_text[:60]
                        
                        filing = {
                            'symbol': symbol,
                            'name': WATCHLIST[symbol]['name'],
                            'filer': filer,
                            'date': updated.text[:10] if updated is not None else now.strftime('%Y-%m-%d'),
                            'link': link.get('href') if link is not None else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&type=13F-HR&dateb=&owner=include&count=40"
                        }
                        filings.append(filing)
                        prev_filings[filing_id] = now.isoformat()
                        break
        
        # Clean old filings data (keep 30 days)
        cutoff = (now - timedelta(days=30)).isoformat()
        prev_filings = {k: v for k, v in prev_filings.items() if v > cutoff}
        save_filings_data(prev_filings)
        
    except Exception as e:
        print(f"Error fetching 13F filings: {e}")
        return None
    
    return filings if filings else None

def check_filings_alerts():
    """Check for new 13F filings involving watchlist stocks"""
    alerts = []
    filings = fetch_13f_filings()
    
    if filings:
        for filing in filings:
            alerts.append({
                'symbol': filing['symbol'],
                'type': '13f_filing',
                'message': f"📋 13F FILING | {filing['symbol']} ({filing['name']})\n   Filer: {filing['filer']}\n   Date: {filing['date']}",
                'priority': 'medium'
            })
    
    return alerts

def load_fred_data():
    """Load previous FRED data"""
    if FRED_DATA_FILE.exists():
        with open(FRED_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_fred_data(data):
    """Save FRED data"""
    with open(FRED_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

_FRED_API_KEY = os.environ.get('FRED_API_KEY', '10e9ddc049bbeab7b72d445eca80dce7')
_FRED_KEY_WARNING_SHOWN = False

def fetch_fred_data(series_id):
    """Fetch latest data point from FRED API"""
    import urllib.request
    global _FRED_KEY_WARNING_SHOWN
    
    # Check if API key is set
    if not _FRED_API_KEY:
        if not _FRED_KEY_WARNING_SHOWN:
            print("Note: FRED_API_KEY not set. Get free key at https://fred.stlouisfed.org/docs/api/api_key.html")
            _FRED_KEY_WARNING_SHOWN = True
        return None
    
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&sort_order=desc&limit=1&file_type=json&api_key={_FRED_API_KEY}"
        
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenClaw Bot)'}
        )
        
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
        
        if 'observations' in data and len(data['observations']) > 0:
            obs = data['observations'][0]
            return {
                'date': obs['date'],
                'value': float(obs['value']) if obs['value'] != '.' else None
            }
    except Exception as e:
        print(f"Error fetching FRED {series_id}: {e}")
    
    return None

def check_fred_alerts():
    """Check for significant changes in interest rate data"""
    alerts = []
    prev_data = load_fred_data()
    now = datetime.now()
    
    # Thresholds for significant changes
    thresholds = {
        'DFF': 0.25,        # 25bps change
        'SOFR': 0.25,
        'DGS10': 0.10,      # 10bps change
        'DGS2': 0.10,
        'DGS30': 0.10,
        'T10Y2Y': 0.05,
        'DPRIME': 0.25,
    }
    
    for series_id, config in FRED_SERIES.items():
        try:
            current = fetch_fred_data(series_id)
            if current is None or current['value'] is None:
                continue
            
            prev_value = prev_data.get(series_id, {}).get('value')
            prev_date = prev_data.get(series_id, {}).get('date')
            
            # Check if new data point
            if prev_date != current['date']:
                # Check for significant change
                if prev_value is not None:
                    change = abs(current['value'] - prev_value)
                    threshold = thresholds.get(series_id, 0.10)
                    
                    if change >= threshold:
                        direction = "📈" if current['value'] > prev_value else "📉"
                        impact_emoji = "🔥" if config['impact'] == 'high' else "⚡"
                        
                        alerts.append({
                            'type': 'fred_macro',
                            'message': f"{impact_emoji} FRED UPDATE | {config['name']} ({series_id})\n   {direction} {current['value']:.3f}% (was {prev_value:.3f}%)\n   Change: {change*100:.1f}bps | As of {current['date']}",
                            'priority': 'high' if config['impact'] == 'high' else 'medium'
                        })
                
                # Update stored data
                prev_data[series_id] = current
        except Exception as e:
            print(f"Error checking FRED {series_id}: {e}")
            continue
    
    save_fred_data(prev_data)
    return alerts

def generate_fred_summary():
    """Generate FRED interest rate summary"""
    lines = ["\n📊 INTEREST RATE & MACRO DATA", "=" * 50]
    
    fred_data = load_fred_data()
    
    # Fetch fresh data for summary
    for series_id, config in FRED_SERIES.items():
        try:
            current = fetch_fred_data(series_id)
            if current and current['value'] is not None:
                fred_data[series_id] = current
        except:
            pass
    
    save_fred_data(fred_data)
    
    # Format key rates
    lines.append("\n🏦 KEY RATES:")
    
    if 'DFF' in fred_data and fred_data['DFF']['value']:
        lines.append(f"   Fed Funds: {fred_data['DFF']['value']:.3f}%")
    
    if 'SOFR' in fred_data and fred_data['SOFR']['value']:
        lines.append(f"   SOFR: {fred_data['SOFR']['value']:.3f}%")
    
    if 'DGS10' in fred_data and fred_data['DGS10']['value']:
        lines.append(f"   10Y Treasury: {fred_data['DGS10']['value']:.3f}%")
    
    if 'DGS2' in fred_data and fred_data['DGS2']['value']:
        lines.append(f"   2Y Treasury: {fred_data['DGS2']['value']:.3f}%")
    
    # Yield curve spread
    if 'T10Y2Y' in fred_data and fred_data['T10Y2Y']['value']:
        spread = fred_data['T10Y2Y']['value']
        curve_emoji = "⚠️ INVERTED" if spread < 0 else "✅ Normal"
        lines.append(f"   10Y-2Y Spread: {spread:.3f}% {curve_emoji}")
    
    # Interest rate sensitivity for watchlist
    lines.append("\n📈 INTEREST RATE SENSITIVITY:")
    sensitive_stocks = [
        ("SOFI", "High - FinTech lender, NIM sensitive"),
        ("HOOD", "Medium-High - Trading activity drops with rates"),
        ("NVO", "Medium - Pharma, USD strength impacts"),
        ("META", "Low-Medium - Ad spend may slow with rates"),
        ("AMZN", "Medium - Consumer spending sensitive"),
    ]
    
    for symbol, context in sensitive_stocks:
        if symbol in WATCHLIST:
            lines.append(f"   {symbol}: {context}")
    
    return "\n".join(lines)

def load_prediction_data():
    """Load previous prediction market data"""
    if PREDICTION_DATA_FILE.exists():
        with open(PREDICTION_DATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_prediction_data(data):
    """Save prediction market data"""
    with open(PREDICTION_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def fetch_polymarket_data(market_slug):
    """Fetch market data from Polymarket API"""
    import urllib.request
    
    try:
        url = f"https://clob.polymarket.com/markets/{market_slug}"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenClaw Bot)'}
        )
        
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read())
            
        if 'markets' in data and len(data['markets']) > 0:
            market = data['markets'][0]
            return {
                'question': market.get('question', 'Unknown'),
                'probability': float(market.get('probability', 0)) * 100,
                'volume': market.get('volume', 0),
                'liquidity': market.get('liquidity', 0),
                'active': market.get('active', True),
                'end_date': market.get('end_date_iso', ''),
                'description': market.get('description', '')
            }
    except Exception as e:
        print(f"Error fetching Polymarket {market_slug}: {e}")
    
    return None

def check_prediction_alerts():
    """Check for significant changes in prediction markets"""
    alerts = []
    prev_data = load_prediction_data()
    now = datetime.now()
    
    for market_key, config in PREDICTION_MARKETS.items():
        try:
            slug = config.get('polymarket')
            if not slug:
                continue
                
            current = fetch_polymarket_data(slug)
            if current is None:
                continue
            
            prev = prev_data.get(market_key, {})
            prev_prob = prev.get('probability')
            
            # Check for significant probability change
            if prev_prob is not None:
                change = abs(current['probability'] - prev_prob)
                threshold = config.get('threshold', 5.0)
                
                if change >= threshold:
                    direction = "📈 UP" if current['probability'] > prev_prob else "📉 DOWN"
                    impacted = ", ".join(config['impact_stocks'])
                    
                    alerts.append({
                        'type': 'prediction_market',
                        'message': f"🎯 POLYMARKET SHIFT | {current['question'][:50]}...\n   {direction} to {current['probability']:.1f}% (was {prev_prob:.1f}%)\n   Impact: {impacted}\n   Volume: ${current.get('volume', 0):,.0f}",
                        'priority': 'high' if change >= 10 else 'medium'
                    })
            
            # Update stored data
            prev_data[market_key] = current
            
        except Exception as e:
            print(f"Error checking prediction market {market_key}: {e}")
            continue
    
    save_prediction_data(prev_data)
    return alerts

def generate_prediction_summary():
    """Generate prediction market summary"""
    lines = ["\n🎯 PREDICTION MARKETS", "=" * 50]
    
    pred_data = load_prediction_data()
    
    # Fetch fresh data
    for market_key, config in PREDICTION_MARKETS.items():
        try:
            slug = config.get('polymarket')
            if slug:
                current = fetch_polymarket_data(slug)
                if current:
                    pred_data[market_key] = current
        except:
            pass
    
    save_prediction_data(pred_data)
    
    # Display relevant markets
    lines.append("\n📊 ACTIVE MARKETS:")
    
    market_display = []
    for market_key, config in PREDICTION_MARKETS.items():
        if market_key in pred_data:
            data = pred_data[market_key]
            prob = data.get('probability', 0)
            impacted = ", ".join(config['impact_stocks'])
            market_display.append(f"   {data['question'][:40]}...: {prob:.1f}%\n      → Impacts: {impacted}")
    
    if market_display:
        lines.extend(market_display)
    else:
        lines.append("   No active markets fetched")
    
    # Rate sensitivity matrix
    lines.append("\n📈 PREDICTION MARKET SENSITIVITY:")
    sensitivity_matrix = [
        ("SOFI/HOOD", "Fed rate cuts, recession odds"),
        ("BABA/JD", "China tariffs, trade policy"),
        ("NVO", "GLP-1 Medicare coverage"),
        ("META", "Tech regulation, TikTok ban"),
    ]
    
    for stocks, driver in sensitivity_matrix:
        lines.append(f"   {stocks}: {driver}")
    
    return "\n".join(lines)

def load_budget_data():
    """Load budget tracking data"""
    if BUDGET_FILE.exists():
        with open(BUDGET_FILE, 'r') as f:
            return json.load(f)
    return {
        "monthly_budget": MONTHLY_BUDGET,
        "month": datetime.now().strftime("%Y-%m"),
        "spent": 0.00,
        "warning_sent": False,
        "cap_sent": False,
        "runs": []
    }

def save_budget_data(data):
    """Save budget tracking data"""
    with open(BUDGET_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def check_budget(run_cost=0.05):
    """Check budget status and return warning if near limit"""
    budget = load_budget_data()
    current_month = datetime.now().strftime("%Y-%m")
    
    # Reset if new month
    if budget["month"] != current_month:
        budget = {
            "monthly_budget": MONTHLY_BUDGET,
            "month": current_month,
            "spent": 0.00,
            "warning_sent": False,
            "cap_sent": False,
            "runs": []
        }
    
    # Add this run
    budget["spent"] += run_cost
    budget["runs"].append({
        "time": datetime.now().isoformat(),
        "cost": run_cost
    })
    
    # Keep only last 100 runs
    budget["runs"] = budget["runs"][-100:]
    
    # Check thresholds
    warning_threshold = MONTHLY_BUDGET * BUDGET_WARNING_PCT
    alerts = []
    
    if budget["spent"] >= MONTHLY_BUDGET and not budget["cap_sent"]:
        alerts.append({
            "type": "budget",
            "priority": "high",
            "message": f"🚨 BUDGET CAP REACHED\n   Monthly spend: ${budget['spent']:.2f} / ${MONTHLY_BUDGET:.2f}\n   Alerts paused until next month."
        })
        budget["cap_sent"] = True
    elif budget["spent"] >= warning_threshold and not budget["warning_sent"]:
        alerts.append({
            "type": "budget",
            "priority": "medium",
            "message": f"⚠️ BUDGET WARNING\n   Monthly spend: ${budget['spent']:.2f} / ${MONTHLY_BUDGET:.2f} ({(budget['spent']/MONTHLY_BUDGET)*100:.0f}%)\n   Approaching monthly limit."
        })
        budget["warning_sent"] = True
    
    save_budget_data(budget)
    return alerts

def generate_budget_summary():
    """Generate budget summary"""
    budget = load_budget_data()
    lines = ["\n💰 BUDGET STATUS", "=" * 50]
    lines.append(f"\n   Monthly Budget: ${MONTHLY_BUDGET:.2f}")
    lines.append(f"   Spent This Month: ${budget['spent']:.2f}")
    lines.append(f"   Remaining: ${max(0, MONTHLY_BUDGET - budget['spent']):.2f}")
    lines.append(f"   Usage: {(budget['spent']/MONTHLY_BUDGET)*100:.1f}%")
    lines.append(f"   Runs Today: {len([r for r in budget['runs'] if r['time'].startswith(datetime.now().strftime('%Y-%m-%d'))])}")
    return "\n".join(lines)

def generate_ma_summary():
    """Generate moving average summary for watchlist stocks"""
    lines = ["\n📊 MOVING AVERAGES", "=" * 50]
    
    ma_entries = []
    
    for symbol, config in WATCHLIST.items():
        mas = calculate_moving_averages(symbol)
        if not mas:
            continue
        
        price = mas['price']
        ma50 = mas.get('50')
        ma100 = mas.get('100')
        ma200 = mas.get('200')
        
        if not all([ma50, ma100, ma200]):
            continue
        
        # Determine position relative to MAs
        position = ""
        trend_score = 0
        
        if price > ma50 > ma100 > ma200:
            position = "🟢 Strong Uptrend (Price > 50 > 100 > 200)"
            trend_score = 3
        elif price > ma50 > ma200:
            position = "🟡 Bullish (Price > 50 > 200)"
            trend_score = 2
        elif price > ma200:
            position = "⚪ Above 200 MA"
            trend_score = 1
        elif price < ma50 < ma100 < ma200:
            position = "🔴 Strong Downtrend (Price < 50 < 100 < 200)"
            trend_score = -3
        elif price < ma50 < ma200:
            position = "🟠 Bearish (Price < 50 < 200)"
            trend_score = -2
        elif price < ma200:
            position = "⚪ Below 200 MA"
            trend_score = -1
        else:
            position = "📊 Mixed"
            trend_score = 0
        
        ma_entries.append({
            "symbol": symbol,
            "name": config["name"],
            "price": price,
            "ma50": ma50,
            "ma100": ma100,
            "ma200": ma200,
            "position": position,
            "trend_score": trend_score
        })
    
    if not ma_entries:
        lines.append("\n   No MA data available.")
        return "\n".join(lines)
    
    # Sort by trend strength
    ma_entries.sort(key=lambda x: x["trend_score"], reverse=True)
    
    # Show strong trends
    strong_bullish = [e for e in ma_entries if e["trend_score"] >= 2]
    strong_bearish = [e for e in ma_entries if e["trend_score"] <= -2]
    
    if strong_bullish:
        lines.append("\n🟢 BULLISH TRENDS:")
        for e in strong_bullish:
            lines.append(f"   {e['symbol']}: ${e['price']:.2f}")
            lines.append(f"      {e['position']}")
    
    if strong_bearish:
        lines.append("\n🔴 BEARISH TRENDS:")
        for e in strong_bearish:
            lines.append(f"   {e['symbol']}: ${e['price']:.2f}")
            lines.append(f"      {e['position']}")
    
    # Near crossovers (price within 2% of a key MA)
    lines.append("\n⚠️ NEAR CROSSOVERS:")
    crossover_candidates = []
    for e in ma_entries:
        for ma_name, ma_key, ma_val in [("50-day", "ma50", e["ma50"]), ("200-day", "ma200", e["ma200"])]:
            if ma_val:
                dist_pct = abs(e["price"] - ma_val) / ma_val * 100
                if dist_pct <= 2:
                    direction = "above" if e["price"] > ma_val else "below"
                    crossover_candidates.append(f"   {e['symbol']}: {dist_pct:.1f}% {direction} {ma_name} (${ma_val:.2f})")
    
    if crossover_candidates:
        lines.extend(crossover_candidates)
    else:
        lines.append("   None near crossover")
    
    return "\n".join(lines)

def generate_filings_summary():
    """Generate 13F filings summary"""
    lines = [f"\n📋 13F INSTITUTIONAL FILINGS", "=" * 50]
    
    filings = fetch_13f_filings()
    
    if filings:
        lines.append(f"\n🔔 New filings detected:")
        for f in filings:
            lines.append(f"\n{f['symbol']} ({f['name']}):")
            lines.append(f"   Filer: {f['filer']}")
            lines.append(f"   Filed: {f['date']}")
            lines.append(f"   Link: {f['link']}")
    else:
        lines.append("\nNo new 13F filings for watchlist stocks.")
    
    return "\n".join(lines)

def generate_daily_summary(current_data):
    """Generate daily market summary"""
    if not current_data:
        return "No data available for summary."
    
    lines = [f"📊 Daily Stock Summary - {datetime.now().strftime('%Y-%m-%d')}", "=" * 50]
    
    # Sort by change percentage
    sorted_stocks = sorted(
        current_data.items(),
        key=lambda x: x[1].get("change_pct", 0),
        reverse=True
    )
    
    lines.append("\n🟢 TOP GAINERS:")
    gainers = [(s, d) for s, d in sorted_stocks if d.get("change_pct", 0) > 0]
    for symbol, data in gainers[:5]:
        name = WATCHLIST.get(symbol, {}).get("name", symbol)
        lines.append(f"  {symbol} ({name}): ${data['price']:.2f} (+{data['change_pct']:.2f}%)")
    
    lines.append("\n🔴 TOP DECLINERS:")
    decliners = [(s, d) for s, d in sorted_stocks if d.get("change_pct", 0) < 0]
    for symbol, data in decliners[-5:]:
        name = WATCHLIST.get(symbol, {}).get("name", symbol)
        lines.append(f"  {symbol} ({name}): ${data['price']:.2f} ({data['change_pct']:.2f}%)")
    
    lines.append("\n📋 FULL WATCHLIST:")
    for symbol, data in sorted_stocks:
        name = WATCHLIST.get(symbol, {}).get("name", symbol)
        emoji = "🟢" if data.get("change_pct", 0) > 0 else "🔴" if data.get("change_pct", 0) < 0 else "⚪"
        lines.append(f"  {emoji} {symbol}: ${data['price']:.2f} ({data.get('change_pct', 0):+.2f}%)")
    
    return "\n".join(lines)

def generate_options_summary():
    """Generate options flow summary"""
    lines = [f"\n📈 OPTIONS FLOW - {datetime.now().strftime('%Y-%m-%d')}", "=" * 50]
    
    unusual_found = False
    for symbol in WATCHLIST.keys():
        try:
            flow = fetch_options_flow(symbol)
            if flow:
                unusual_found = True
                lines.append(f"\n🔥 {symbol}:")
                for trade in flow[:3]:  # Top 3
                    emoji = "📞" if trade['type'] == 'CALL' else "🛡️"
                    lines.append(f"  {emoji} {trade['strike']:.0f} {trade['type']} {trade['expiration']}")
                    lines.append(f"     Vol: {trade['volume']} | OI: {trade['open_interest']} | {trade['ratio']}x ratio")
        except:
            continue
    
    if not unusual_found:
        lines.append("\nNo unusual options activity detected.")
    
    return "\n".join(lines)

def generate_technical_summary(current_data):
    """Generate technical levels summary showing price position relative to S/R"""
    lines = ["\n📊 TECHNICAL LEVELS - Price vs Support/Resistance", "=" * 50]
    
    technical_entries = []
    
    for symbol, config in WATCHLIST.items():
        if symbol not in current_data:
            continue
            
        price = current_data[symbol]["price"]
        levels = config.get("levels", {})
        support = levels.get("support", [])
        resistance = levels.get("resistance", [])
        
        # Find nearest support below and resistance above
        nearest_support = None
        nearest_resistance = None
        support_dist = float('inf')
        resistance_dist = float('inf')
        
        for s in support:
            dist = (price - s) / s * 100  # % distance
            if dist >= -5:  # At, near, or somewhat above
                if abs(dist) < abs(support_dist):
                    support_dist = dist
                    nearest_support = s
        
        for r in resistance:
            dist = (r - price) / r * 100  # % distance
            if dist >= -5:  # At, near, or somewhat below
                if abs(dist) < abs(resistance_dist):
                    resistance_dist = dist
                    nearest_resistance = r
        
        # Determine position
        position = ""
        alert_score = 0
        
        if nearest_support is not None and abs(support_dist) <= 2:
            position = f"🛡️ AT SUPPORT (${nearest_support:.0f})"
            alert_score = 2
        elif nearest_resistance is not None and abs(resistance_dist) <= 2:
            position = f"⛰️ AT RESISTANCE (${nearest_resistance:.0f})"
            alert_score = 2
        elif nearest_support is not None and support_dist <= 5:
            position = f"🔺 Near Support (${nearest_support:.0f}, {support_dist:.1f}% below)"
            alert_score = 1
        elif nearest_resistance is not None and resistance_dist <= 5:
            position = f"🔻 Near Resistance (${nearest_resistance:.0f}, {resistance_dist:.1f}% above)"
            alert_score = 1
        elif nearest_support and nearest_resistance:
            position = f"📈 Between S${nearest_support:.0f} - R${nearest_resistance:.0f}"
            alert_score = 0
        else:
            continue
        
        technical_entries.append({
            "symbol": symbol,
            "name": config["name"],
            "price": price,
            "position": position,
            "score": alert_score
        })
    
    # Sort by alert score (higher = more important)
    technical_entries.sort(key=lambda x: x["score"], reverse=True)
    
    if not technical_entries:
        lines.append("\nNo stocks near key levels.")
        return "\n".join(lines)
    
    # First show stocks at/near key levels
    at_levels = [e for e in technical_entries if e["score"] >= 2]
    if at_levels:
        lines.append("\n🔥 AT KEY LEVELS:")
        for entry in at_levels:
            lines.append(f"  {entry['symbol']} (${entry['price']:.2f}): {entry['position']}")
    
    # Then show stocks approaching levels
    approaching = [e for e in technical_entries if e["score"] == 1]
    if approaching:
        lines.append("\n⚠️ APPROACHING LEVELS:")
        for entry in approaching:
            lines.append(f"  {entry['symbol']} (${entry['price']:.2f}): {entry['position']}")
    
    return "\n".join(lines)

def main():
    """Main monitoring function"""
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    
    # Check budget before proceeding
    budget_alerts = check_budget(run_cost=0.03)  # ~3 cents per run
    if budget_alerts:
        for alert in budget_alerts:
            print(alert['message'])
            if alert['priority'] == 'high':
                # Budget cap reached - skip this run
                with open("/tmp/budget_alert.txt", "w") as f:
                    f.write(alert['message'])
                return 0
    
    symbols = list(WATCHLIST.keys())
    previous_data = load_data()
    current_data = fetch_stock_data(symbols)
    
    if not current_data:
        print("Failed to fetch stock data")
        return 1
    
    if mode == "summary":
        # Daily summary mode
        summary = generate_daily_summary(current_data)
        fred_summary = generate_fred_summary()
        prediction_summary = generate_prediction_summary()
        technical_summary = generate_technical_summary(current_data)
        options_summary = generate_options_summary()
        filings_summary = generate_filings_summary()
        full_summary = summary + "\n" + fred_summary + "\n" + prediction_summary + "\n" + technical_summary + "\n" + options_summary + "\n" + filings_summary
        print(full_summary)
        
        # Save for alerting
        with open("/tmp/stock_summary.txt", "w") as f:
            f.write(full_summary)
    
    elif mode == "technical":
        # Technical levels check
        technical_summary = generate_technical_summary(current_data)
        print(technical_summary)
        
        with open("/tmp/technical_summary.txt", "w") as f:
            f.write(technical_summary)
    
    elif mode == "filings":
        # 13F filings check
        filings_alerts = check_filings_alerts()
        
        if filings_alerts:
            alert_text = "🚨 13F FILING ALERT\n" + "=" * 30 + "\n\n"
            for alert in filings_alerts:
                alert_text += f"{alert['message']}\n\n"
            
            print(alert_text)
            
            with open("/tmp/filings_alerts.txt", "w") as f:
                f.write(alert_text)
        else:
            print("No new 13F filings.")
    
    elif mode == "macro":
        # FRED macro data check
        fred_alerts = check_fred_alerts()
        
        if fred_alerts:
            alert_text = "🚨 MACRO ALERT\n" + "=" * 30 + "\n\n"
            for alert in fred_alerts:
                alert_text += f"{alert['message']}\n\n"
            
            print(alert_text)
            
            with open("/tmp/macro_alerts.txt", "w") as f:
                f.write(alert_text)
        else:
            print("No significant macro changes.")
    
    elif mode == "prediction":
        # Prediction market check
        pred_alerts = check_prediction_alerts()
        
        if pred_alerts:
            alert_text = "🎯 PREDICTION MARKET ALERT\n" + "=" * 30 + "\n\n"
            for alert in pred_alerts:
                alert_text += f"{alert['message']}\n\n"
            
            print(alert_text)
            
            with open("/tmp/prediction_alerts.txt", "w") as f:
                f.write(alert_text)
        else:
            print("No significant prediction market changes.")
    
    elif mode == "ma":
        # Moving averages summary
        ma_summary = generate_ma_summary()
        print(ma_summary)
        
        with open("/tmp/ma_summary.txt", "w") as f:
            f.write(ma_summary)
            
    elif mode == "check":
        # Alert checking mode
        alerts = check_alerts(current_data, previous_data)
        
        if alerts:
            alert_text = "🚨 STOCK ALERTS\n" + "=" * 30 + "\n\n"
            for alert in alerts:
                alert_text += f"{alert['message']}\n\n"
            
            print(alert_text)
            
            # Save for sending
            with open("/tmp/stock_alerts.txt", "w") as f:
                f.write(alert_text)
        else:
            print("No new alerts at this time.")
            
    elif mode == "options":
        # Options flow check
        options_alerts = check_options_alerts()
        
        if options_alerts:
            alert_text = "🚨 UNUSUAL OPTIONS ACTIVITY\n" + "=" * 30 + "\n\n"
            for alert in options_alerts:
                alert_text += f"{alert['message']}\n\n"
            
            print(alert_text)
            
            with open("/tmp/options_alerts.txt", "w") as f:
                f.write(alert_text)
        else:
            print("No unusual options activity detected.")
    
    # Save current data for next comparison
    save_data(current_data)
    return 0

if __name__ == "__main__":
    sys.exit(main())
