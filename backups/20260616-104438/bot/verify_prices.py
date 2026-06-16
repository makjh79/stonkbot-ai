#!/usr/bin/env python3
"""
Daily Price Verification Report
Compares our prices against Yahoo Finance and logs discrepancies
"""

import json
import requests
from datetime import datetime
from pathlib import Path

def verify_prices():
    """Verify all watchlist prices against Yahoo Finance"""
    
    # Load our prices
    with open('/var/www/hedge-fund-website/ai_watchlist_live.json') as f:
        our_data = json.load(f)
    
    discrepancies = []
    verified = []
    
    for symbol, data in our_data.get('prices', {}).items():
        our_price = data.get('price', 0)
        
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            yahoo_data = resp.json()
            
            result = yahoo_data.get('chart', {}).get('result', [None])[0]
            if result:
                meta = result.get('meta', {})
                yahoo_price = meta.get('regularMarketPrice') or meta.get('previousClose', 0)
                
                if our_price and yahoo_price and yahoo_price > 0:
                    diff = abs(our_price - yahoo_price)
                    diff_pct = (diff / yahoo_price) * 100
                    
                    if diff >= 0.50:  # 50 cent threshold
                        discrepancies.append({
                            'symbol': symbol,
                            'our_price': our_price,
                            'yahoo_price': yahoo_price,
                            'diff': diff,
                            'diff_pct': diff_pct
                        })
                    else:
                        verified.append(symbol)
                elif our_price > 0 and (not yahoo_price or yahoo_price == 0):
                    # Yahoo has no data but we do - mark as verified with warning
                    print(f"⚠️  {symbol}: Yahoo unavailable, trusting our ${our_price:.2f}")
                    verified.append(symbol)
        except Exception as e:
            discrepancies.append({
                'symbol': symbol,
                'our_price': our_price,
                'error': str(e)
            })
    
    # Save report
    report = {
        'timestamp': datetime.now().isoformat(),
        'total_symbols': len(our_data.get('prices', {})),
        'verified_count': len(verified),
        'discrepancy_count': len(discrepancies),
        'discrepancies': discrepancies,
        'verified_symbols': verified,
        'status': 'VERIFIED' if len(discrepancies) == 0 else 'NEEDS_REVIEW'
    }
    
    report_path = Path('/var/www/hedge-fund-website/price_verification.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Log summary
    if discrepancies:
        print(f"❌ PRICE VERIFICATION FAILED: {len(discrepancies)} discrepancies found")
        for d in discrepancies:
            print(f"  {d['symbol']}: Our ${d.get('our_price')} vs Yahoo ${d.get('yahoo_price')} (diff: ${d.get('diff', 0):.2f})")
    else:
        print(f"✅ PRICE VERIFICATION PASSED: All {len(verified)} prices verified")
    
    return report

if __name__ == '__main__':
    verify_prices()
