#!/usr/bin/env python3
"""
Dynamic Watchlist Manager - Aggressive Auto-replacement
Scans full market for opportunities, runs every 5 minutes
"""

import json
import requests
from datetime import datetime, timedelta
import os
import sys

# Configuration - GAME CHANGING: TIGHT, DYNAMIC, TIERED SYSTEM
WATCHLIST_CONFIG = {
    'max_stocks': 15,  # Reduced from 20 - focus on quality
    'min_stocks': 5,
    'refresh_interval_minutes': 5,
    
    # REMOVAL THRESHOLDS - Much stricter for constant rotation
    'remove_rsi_above': 50,  # REMOVE if RSI > 50 (moved past buy zone)
    'remove_rsi_below': 25,  # REMOVE if RSI < 25 (oversold, wait for bounce)
    'remove_price_change_day': 5,  # REMOVE if up > 5% (chased, missed entry)
    'remove_underperform_sp500': -3,  # REMOVE if lagging S&P by 3%
    'max_days_in_watchlist': 3,  # REMOVE after 3 days if no RSI <40 signal
    
    # ADDITION THRESHOLDS - High bar but achievable
    'add_rsi_min': 28,  # Must be in buy zone (slightly lower for more opportunities)
    'add_rsi_max': 48,  # But not too hot
    'add_ai_score_min': 60,  # Quality threshold (was 70, lowered for rotation)
    
    # TIER THRESHOLDS for frontend display
    'tier_now_rsi_max': 35,
    'tier_now_ai_min': 75,  # High conviction
    'tier_watch_rsi_max': 48,
    'tier_watch_ai_min': 60,  # Quality entry zone
}

# Permanent positions (don't auto-replace these)
# ETFs excluded from watchlist (manual trading only, no auto-rotation)
ETF_SYMBOLS = {'SQQQ', 'TQQQ', 'SPY', 'QQQ', 'IWM', 'VIX', 'GLD', 'SLV', 'USO', 'TLT',
               'XLE', 'XLF', 'XLK', 'XLI', 'XLP', 'XLU', 'XLV', 'XLY', 'XBI',
               'ARKK', 'ARKG', 'ARKF', 'ARKW', 'ARKX', 'BITO', 'SOXL', 'SOXS'}

def load_current_watchlist():
    """Load current watchlist from JSON file"""
    try:
        with open('/var/www/hedge-fund-website/watchlist_changes.json', 'r') as f:
            data = json.load(f)
            return data.get('new_watchlist', [])
    except Exception as e:
        print(f"⚠️ Could not load watchlist from JSON: {e}")
        # Fallback to default (individual stocks only - no ETFs)
        return ['COIN', 'DKNG', 'NET', 'PATH', 'SHOP', 'SQ', 'UPST', 'PLTR', 'CRWD', 'HOOD']

# Current watchlist - loaded dynamically from JSON
CURRENT_WATCHLIST = load_current_watchlist()

# Expanded candidate pool - Top 200 liquid stocks
CANDIDATE_POOL = [
    # Magnificent 7 + Big Tech
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', 'NFLX', 'AMD', 'INTC', 'QCOM', 'AVGO', 'CRM', 'ORCL', 'IBM', 'CSCO',
    # Growth/Tech
    'PLTR', 'CRWD', 'SNOW', 'NET', 'DDOG', 'OKTA', 'FSLY', 'TWLO', 'ASAN', 'ZM', 'DOCU', 'SHOP', 'SQ', 'UPST', 'SOFI', 'HOOD',
    # Semiconductors
    'MU', 'LRCX', 'AMAT', 'KLAC', 'SNPS', 'CDNS', 'MRVL', 'NXPI',
    # EV/Auto
    'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'GM', 'F',
    # Travel/Leisure
    'ABNB', 'UBER', 'LYFT', 'EXPE', 'BKNG', 'MAR', 'HLT', 'CCL', 'RCL', 'NCLH',
    # Fintech
    'COIN', 'PYPL', 'AFRM', 'HOOD', 'SOFI', 'LMND', 'ROOT', 'RELY',
    # Healthcare/Bio
    'MRNA', 'BNTX', 'PFE', 'JNJ', 'ABBV', 'LLY', 'UNH', 'CVS', 'MRK',
    # Consumer
    'AMZN', 'COST', 'WMT', 'TGT', 'HD', 'LOW', 'NKE', 'LULU', 'ETSY', 'CHWY', 'DKNG', 'PENN',
    # Media/Entertainment
    'DIS', 'NFLX', 'ROKU', 'SPOT', 'SNAP', 'PINS', 'TWTR', 'TTWO', 'EA', 'ATVI',
    # Energy
    'XLE', 'XOM', 'CVX', 'COP', 'EOG', 'MPC', 'VLO', 'SLB', 'OXY',
    # Industrials
    'CAT', 'DE', 'BA', 'GE', 'HON', 'MMM', 'UPS', 'FDX', 'CSX', 'UNP',
    # Crypto/Blockchain
    'MSTR', 'HOOD', 'COIN', 'RIOT', 'MARA', 'BITF', 'CLSK',
    # China Tech
    'BABA', 'JD', 'PDD', 'BIDU', 'NTES', 'TCEHY', 'DIDI',
    # SaaS/Mid-cap
    'VEEV', 'NOW', 'TEAM', 'ATLASSIAN', 'ZOOM', 'SLACK', 'NOTION', 'FIGMA',
    # Airlines/Transport
    'DAL', 'UAL', 'AAL', 'LUV', 'JBLU',
    # Additional Growth
    'RBLX', 'U', 'DDOG', 'NET', 'CRWD', 'OKTA',
]

# Load Alpaca config
def load_alpaca_config():
    try:
        with open('/opt/stonk-ai/alpaca_config.json', 'r') as f:
            config = json.load(f)
            return config.get('api_key'), config.get('api_secret')
    except Exception as e:
        print(f"❌ Could not load Alpaca config: {e}")
        return None, None

ALPACA_KEY, ALPACA_SECRET = load_alpaca_config()

def load_watchlist_data():
    """Load current watchlist data from JSON"""
    try:
        with open('/var/www/hedge-fund-website/ai_watchlist_live.json', 'r') as f:
            return json.load(f)
    except:
        return {'prices': {}}

def load_market_indices():
    """Load S&P 500 performance for comparison"""
    try:
        with open('/var/www/hedge-fund-website/market_indices.json', 'r') as f:
            data = json.load(f)
            sp500 = data.get('indices', {}).get('S&P 500', {})
            return sp500.get('return_pct', 0)
    except:
        return 0

def load_candidate_data(symbol):
    """Fetch data for a candidate stock from Alpaca"""
    if not ALPACA_KEY:
        return None
    
    try:
        from alpaca_trade_api import REST
        
        api = REST(ALPACA_KEY, ALPACA_SECRET, 
                   base_url='https://paper-api.alpaca.markets')
        
        # Get latest bar
        bars = api.get_latest_bar(symbol)
        if bars:
            return {
                'symbol': symbol,
                'price': bars.c,
                'change_pct': ((bars.c - bars.o) / bars.o * 100) if bars.o else 0,
                'volume': bars.v,
                'rsi': 50,  # Will calculate or fetch separately
            }
    except Exception as e:
        # Silently skip errors for speed
        pass
    return None

def calculate_ai_score(price_data, sp500_return):
    """Calculate AI score for candidate - includes vs S&P comparison"""
    score = 50  # Base score
    
    price_change = price_data.get('change_pct', 0)
    
    # Price momentum factor
    if price_change > 2:
        score += 15
    elif price_change > 0:
        score += 10
    elif price_change < -5:
        score -= 15
    
    # Volume factor
    volume = price_data.get('volume', 0)
    if volume > 5000000:  # High volume
        score += 10
    elif volume > 1000000:
        score += 5
    
    # Relative strength vs S&P 500
    vs_sp500 = price_change - sp500_return
    if vs_sp500 > 2:
        score += 10
    elif vs_sp500 < -3:
        score -= 10
    
    return min(100, max(0, score))

def evaluate_stock(symbol, data, sp500_return):
    """Evaluate if stock should stay in watchlist - GAME CHANGING STRICT CRITERIA"""
    if not data:
        return {'keep': False, 'reason': 'No data available', 'action': 'REPLACE', 'tier': None}
    
    # Exclude ETFs from watchlist (manual trading only)
    if symbol in ETF_SYMBOLS:
        return {'keep': False, 'reason': 'ETF excluded - individual stocks only', 'action': 'REPLACE', 'tier': None}
    
    rsi = data.get('rsi') or 50
    change_pct = data.get('change_pct') or 0
    ai_score = data.get('ai_score') or 50
    
    # Check time-based removal (max 3 days in watchlist without signal)
    days_in_watchlist = data.get('days_in_watchlist', 0)
    if days_in_watchlist >= WATCHLIST_CONFIG['max_days_in_watchlist'] and rsi > 40:
        return {'keep': False, 'reason': f'Stale ({days_in_watchlist} days, RSI {rsi:.1f})', 'action': 'REPLACE', 'tier': None}
    
    # Check removal conditions - STRICT ROTATION
    if rsi > WATCHLIST_CONFIG['remove_rsi_above']:
        return {'keep': False, 'reason': f'RSI {rsi:.1f} > {WATCHLIST_CONFIG["remove_rsi_above"]} (past buy zone)', 'action': 'REPLACE', 'tier': None}
    
    if rsi < WATCHLIST_CONFIG['remove_rsi_below']:
        return {'keep': False, 'reason': f'RSI {rsi:.1f} < {WATCHLIST_CONFIG["remove_rsi_below"]} (too oversold)', 'action': 'REPLACE', 'tier': None}
    
    if change_pct > WATCHLIST_CONFIG['remove_price_change_day']:
        return {'keep': False, 'reason': f'Up {change_pct:.1f}% (chased)', 'action': 'REPLACE', 'tier': None}
    
    vs_sp500 = change_pct - sp500_return
    if vs_sp500 < WATCHLIST_CONFIG['remove_underperform_sp500']:
        return {'keep': False, 'reason': f'Lagging S&P by {abs(vs_sp500):.1f}%', 'action': 'REPLACE', 'tier': None}
    
    # Assign TIER based on quality
    tier = 'MONITOR'
    if rsi <= WATCHLIST_CONFIG['tier_now_rsi_max'] and ai_score >= WATCHLIST_CONFIG['tier_now_ai_min']:
        tier = 'NOW'
    elif rsi <= WATCHLIST_CONFIG['tier_watch_rsi_max'] and ai_score >= WATCHLIST_CONFIG['tier_watch_ai_min']:
        tier = 'WATCH'
    
    return {'keep': True, 'reason': f'RSI {rsi:.1f}, AI {ai_score} - {tier}', 'action': 'KEEP', 'tier': tier}

def find_replacement_candidates(sp500_return, current_symbols):
    """Find stocks to add to watchlist - SCAN FULL POOL"""
    candidates = []
    
    print(f"\n🔍 Scanning {len(CANDIDATE_POOL)} stocks for opportunities...")
    
    checked = 0
    for symbol in CANDIDATE_POOL:
        if symbol in current_symbols:
            continue
        
        data = load_candidate_data(symbol)
        checked += 1
        
        if data:
            ai_score = calculate_ai_score(data, sp500_return)
            
            # Lower threshold for more opportunities
            if ai_score >= WATCHLIST_CONFIG['add_ai_score_min']:
                candidates.append({
                    'symbol': symbol,
                    'data': data,
                    'ai_score': ai_score,
                    'change_pct': data.get('change_pct', 0),
                    'reason': f'AI Score {ai_score}, +{data.get("change_pct", 0):.1f}%'
                })
                print(f"  ✓ {symbol}: Score {ai_score} (found in {checked} checks)")
        
        # Limit checks for speed - check top 50 candidates max
        if checked >= 50:
            break
    
    # Sort by AI score descending
    candidates.sort(key=lambda x: x['ai_score'], reverse=True)
    return candidates

def is_market_open():
    """Check if US stock market is currently open (NYSE/NASDAQ schedule)"""
    now = datetime.now()
    
    # Check if weekend
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Check US market holidays for 2026
    # Format: (month, day)
    market_holidays_2026 = [
        (1, 1),   # New Year's Day
        (1, 19),  # Martin Luther King Jr. Day
        (2, 16),  # Presidents' Day
        (4, 3),   # Good Friday
        (5, 25),  # Memorial Day
        (6, 19),  # Juneteenth (observed June 19, 2026 is Friday)
        (7, 4),   # Independence Day
        (9, 7),   # Labor Day
        (10, 12), # Columbus Day
        (11, 11), # Veterans Day
        (11, 26), # Thanksgiving
        (12, 25), # Christmas
    ]
    
    today = (now.month, now.day)
    if today in market_holidays_2026:
        return False
    
    # Market hours: 9:30 AM - 4:00 PM ET (rough check - within trading hours)
    # This is simplified - doesn't account for early close days
    hour = now.hour
    minute = now.minute
    current_minutes = hour * 60 + minute
    
    # Convert to ET (UTC-4 or UTC-5 depending on DST) - simplified
    # Market open: 9:30 = 570 minutes
    # Market close: 16:00 = 960 minutes
    # We'll just check if it's a weekday and not a holiday
    # Detailed hours check would require proper timezone handling
    
    return True

def update_watchlist():
    """Main function to update watchlist - AGGRESSIVE MODE"""
    print(f"\n{'='*70}")
    print(f"🔄 Watchlist Update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    
    # Skip rotation when markets are closed
    if not is_market_open():
        now = datetime.now()
        if now.weekday() >= 5:
            reason = "weekend"
        else:
            reason = "market holiday"
        print(f"📅 Markets closed ({reason}) - Skipping rotation, tracking current watchlist")
        print(f"Current watchlist: {', '.join(CURRENT_WATCHLIST)}")
        return None
    
    print(f"📊 Config: RSI {WATCHLIST_CONFIG['remove_rsi_below']}-{WATCHLIST_CONFIG['remove_rsi_above']} | Daily >{WATCHLIST_CONFIG['remove_price_change_day']}% | Max {WATCHLIST_CONFIG['max_days_in_watchlist']} days")
    
    watchlist_data = load_watchlist_data()
    prices = watchlist_data.get('prices', {})
    sp500_return = load_market_indices()
    
    print(f"📈 S&P 500 Return: {sp500_return:+.2f}%")
    
    # Load watchlist metadata to track days in watchlist
    watchlist_meta = {}
    try:
        with open('/var/www/hedge-fund-website/watchlist_meta.json', 'r') as f:
            watchlist_meta = json.load(f)
    except:
        pass
    
    # Update days in watchlist for existing stocks
    today = datetime.now().date().isoformat()
    for symbol in CURRENT_WATCHLIST:
        if symbol not in watchlist_meta:
            watchlist_meta[symbol] = {'added_date': today, 'days': 0}
        else:
            added_date = datetime.fromisoformat(watchlist_meta[symbol]['added_date']).date()
            days_in_list = (datetime.now().date() - added_date).days
            watchlist_meta[symbol]['days'] = days_in_list
            # Add to price data for evaluation
            if symbol in prices:
                prices[symbol]['days_in_watchlist'] = days_in_list
    
    # Evaluate current stocks
    to_remove = []
    to_keep = []
    tier_summary = {'NOW': [], 'WATCH': [], 'MONITOR': []}
    
    for symbol in CURRENT_WATCHLIST:
        data = prices.get(symbol, {})
        evaluation = evaluate_stock(symbol, data, sp500_return)
        
        if evaluation['keep']:
            to_keep.append(symbol)
            tier = evaluation.get('tier', 'MONITOR')
            tier_summary[tier].append(symbol)
            print(f"  ✅ {symbol}: {evaluation['reason']}")
        else:
            to_remove.append({
                'symbol': symbol,
                'reason': evaluation['reason'],
                'action': evaluation['action']
            })
            print(f"  ❌ {symbol}: {evaluation['reason']} → {evaluation['action']}")
            # Remove from metadata
            if symbol in watchlist_meta:
                del watchlist_meta[symbol]
    
    # Find replacements if needed
    needed = WATCHLIST_CONFIG['max_stocks'] - len(to_keep)
    new_additions = []
    
    if needed > 0:
        print(f"\n🔍 Need {needed} replacement(s)...")
        current_symbols = set(to_keep) | set(prices.keys())
        candidates = find_replacement_candidates(sp500_return, current_symbols)
        
        for candidate in candidates[:needed]:
            new_additions.append(candidate)
            symbol = candidate['symbol']
            print(f"  ➕ Adding {symbol}: {candidate['reason']}")
            # Add to metadata
            watchlist_meta[symbol] = {'added_date': today, 'days': 0}
            # Assign tier
            ai_score = candidate['ai_score']
            if ai_score >= WATCHLIST_CONFIG['tier_now_ai_min']:
                tier_summary['NOW'].append(symbol)
            elif ai_score >= WATCHLIST_CONFIG['tier_watch_ai_min']:
                tier_summary['WATCH'].append(symbol)
            else:
                tier_summary['MONITOR'].append(symbol)
    
    # Save metadata
    try:
        with open('/var/www/hedge-fund-website/watchlist_meta.json', 'w') as f:
            json.dump(watchlist_meta, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save watchlist metadata: {e}")
    
    # Build update log with tier info
    update_log = {
        'timestamp': datetime.now().isoformat(),
        'config': WATCHLIST_CONFIG,
        'sp500_return': sp500_return,
        'removed': to_remove,
        'added': [{'symbol': a['symbol'], 'reason': a['reason'], 'ai_score': a['ai_score']} for a in new_additions],
        'new_watchlist': to_keep + [a['symbol'] for a in new_additions],
        'tiers': tier_summary,
        'summary': {
            'total': len(to_keep) + len(new_additions),
            'now_count': len(tier_summary['NOW']),
            'watch_count': len(tier_summary['WATCH']),
            'monitor_count': len(tier_summary['MONITOR'])
        }
    }
    
    # Save log
    with open('/var/www/hedge-fund-website/watchlist_changes.json', 'w') as f:
        json.dump(update_log, f, indent=2)
    
    # ALSO update the live watchlist file immediately to clear old symbols
    # This ensures the fetcher gets clean data on next iteration
    try:
        live_file = '/var/www/hedge-fund-website/ai_watchlist_live.json'
        if os.path.exists(live_file):
            with open(live_file, 'r') as f:
                live_data = json.load(f)
            # Keep only symbols in new watchlist
            live_data['prices'] = {k: v for k, v in live_data.get('prices', {}).items() 
                                    if k in update_log['new_watchlist']}
            # Add placeholder for new symbols that don't have data yet
            for symbol in update_log['new_watchlist']:
                if symbol not in live_data['prices']:
                    live_data['prices'][symbol] = {
                        'price': 0,
                        'change_pct': 0,
                        'rsi': 50,
                        'targets': {'signal': 'LOADING', 'council_note': 'Fetching data...'}
                    }
            live_data['timestamp'] = datetime.now().isoformat()
            with open(live_file, 'w') as f:
                json.dump(live_data, f, indent=2)
            print(f"🧹 Cleaned live watchlist, removed old symbols")
    except Exception as e:
        print(f"⚠️ Could not clean live watchlist: {e}")
    
    # ALSO update company_info.json to match new watchlist
    try:
        company_info_file = '/var/www/hedge-fund-website/company_info.json'
        if os.path.exists(company_info_file):
            with open(company_info_file, 'r') as f:
                company_data = json.load(f)
            
            # Keep only symbols in new watchlist
            company_data['stocks'] = {k: v for k, v in company_data.get('stocks', {}).items() 
                                       if k in update_log['new_watchlist']}
            
            # Add placeholder for new symbols
            for symbol in update_log['new_watchlist']:
                if symbol not in company_data['stocks']:
                    company_data['stocks'][symbol] = {
                        'company': symbol,
                        'strategy': 'Dynamic watchlist addition',
                        'catalyst': 'AI-identified opportunity',
                        'risk': 'Market volatility'
                    }
            
            company_data['timestamp'] = datetime.now().isoformat()
            with open(company_info_file, 'w') as f:
                json.dump(company_data, f, indent=2)
            print(f"📋 Updated company_info.json with {len(company_data['stocks'])} symbols")
    except Exception as e:
        print(f"⚠️ Could not update company_info.json: {e}")
    
    # Update current watchlist for next run
    CURRENT_WATCHLIST[:] = update_log['new_watchlist']
    
    # Print tier summary
    print(f"\n📊 TIER BREAKDOWN:")
    print(f"  🔥 NOW ({len(tier_summary['NOW'])}): {', '.join(tier_summary['NOW']) if tier_summary['NOW'] else 'None'}")
    print(f"  👀 WATCH ({len(tier_summary['WATCH'])}): {', '.join(tier_summary['WATCH']) if tier_summary['WATCH'] else 'None'}")
    print(f"  📋 MONITOR ({len(tier_summary['MONITOR'])}): {', '.join(tier_summary['MONITOR']) if tier_summary['MONITOR'] else 'None'}")
    print(f"\n📊 Summary: {len(to_keep)} kept | {len(to_remove)} removed | {len(new_additions)} added")
    print(f"💾 New watchlist: {', '.join(update_log['new_watchlist'])}")
    print(f"{'='*70}\n")
    
    return update_log

if __name__ == '__main__':
    update_watchlist()
