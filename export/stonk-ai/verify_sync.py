#!/usr/bin/env python3
"""
Verify all system components are in sync
Run this after any watchlist or threshold changes
"""
import json
import sys
from pathlib import Path

def verify_sync():
    """Verify watchlist, company info, and prices are all aligned"""
    errors = []
    
    # Load all JSON files
    try:
        with open('/var/www/hedge-fund-website/watchlist_changes.json') as f:
            watchlist_data = json.load(f)
        watchlist_symbols = set(watchlist_data['new_watchlist'])
    except Exception as e:
        errors.append(f"❌ Cannot load watchlist_changes.json: {e}")
        watchlist_symbols = set()
    
    try:
        with open('/var/www/hedge-fund-website/company_info.json') as f:
            company_data = json.load(f)
        company_symbols = set(company_data['stocks'].keys())
    except Exception as e:
        errors.append(f"❌ Cannot load company_info.json: {e}")
        company_symbols = set()
    
    try:
        with open('/var/www/hedge-fund-website/ai_watchlist_live.json') as f:
            price_data = json.load(f)
        price_symbols = set(price_data.get('prices', {}).keys())
    except Exception as e:
        errors.append(f"❌ Cannot load ai_watchlist_live.json: {e}")
        price_symbols = set()
    
    # Check 1: Watchlist matches company info
    if watchlist_symbols and company_symbols:
        if watchlist_symbols != company_symbols:
            missing_in_company = watchlist_symbols - company_symbols
            extra_in_company = company_symbols - watchlist_symbols
            if missing_in_company:
                errors.append(f"❌ Symbols in watchlist but not company_info: {missing_in_company}")
            if extra_in_company:
                errors.append(f"❌ Symbols in company_info but not watchlist: {extra_in_company}")
        else:
            print(f"✅ Watchlist and company_info aligned ({len(watchlist_symbols)} symbols)")
    
    # Check 2: Price data has all watchlist symbols
    if watchlist_symbols and price_symbols:
        missing_prices = watchlist_symbols - price_symbols
        if missing_prices:
            errors.append(f"⚠️  Symbols missing price data: {missing_prices}")
        else:
            print(f"✅ All {len(watchlist_symbols)} symbols have price data")
    
    # Check 3: Portfolio matches watchlist
    try:
        with open('/var/www/hedge-fund-website/portfolio_data.json') as f:
            portfolio = json.load(f)
        portfolio_symbols = {p['symbol'] for p in portfolio.get('positions', [])}
        
        # Portfolio positions may differ from watchlist (bot holds other positions)
        extra_positions = portfolio_symbols - watchlist_symbols
        if extra_positions:
            print(f"ℹ️  Portfolio holds {len(extra_positions)} additional positions: {', '.join(extra_positions)}")
    except Exception as e:
        pass  # Portfolio file optional
    
    # Summary
    print("\n" + "="*60)
    if errors:
        print("❌ SYNC ERRORS FOUND:")
        for error in errors:
            print(f"  {error}")
        print("\nFix: Run 'python3 /opt/stonk-ai/dynamic_watchlist_manager.py'")
        sys.exit(1)
    else:
        print("✅ ALL SYSTEMS IN SYNC")
        print(f"   Watchlist: {len(watchlist_symbols)} symbols")
        print(f"   Company info: {len(company_symbols)} symbols")
        print(f"   Price data: {len(price_symbols)} symbols")
        sys.exit(0)

if __name__ == '__main__':
    verify_sync()
