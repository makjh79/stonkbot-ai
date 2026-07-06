#!/usr/bin/env python3
"""
Cash Strategy Monitor
Tracks cash management and crash deploy activity
Sends alerts when actions are taken
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CASH_LOG = Path('/opt/stonk-ai/cash_strategy_log.json')
ALERT_THRESHOLD = 0.08  # Alert when cash drops below 8%

def load_portfolio_data():
    """Load current portfolio data"""
    try:
        with open('/var/www/hedge-fund-website/portfolio_data.json') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Could not load portfolio data: {e}")
        return None

def load_market_indices():
    """Load S&P 500 data"""
    try:
        with open('/var/www/hedge-fund-website/market_indices.json') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Could not load market indices: {e}")
        return None

def check_cash_status():
    """Check current cash position vs strategy thresholds"""
    data = load_portfolio_data()
    if not data:
        return None
    
    cash = data['account']['cash']
    portfolio_value = data['account']['portfolio_value']
    cash_pct = cash / portfolio_value if portfolio_value > 0 else 0
    
    status = {
        'timestamp': datetime.now().isoformat(),
        'cash': cash,
        'portfolio_value': portfolio_value,
        'cash_pct': round(cash_pct * 100, 2),
        'status': 'normal'
    }
    
    if cash_pct < 0.05:
        status['status'] = 'critical'
        status['action_needed'] = 'Cash raise will trigger - trimming overbought positions'
    elif cash_pct < 0.10:
        status['status'] = 'warning'
        status['action_needed'] = 'Below 10% minimum - new buys blocked'
    elif cash_pct < 0.12:
        status['status'] = 'caution'
        status['action_needed'] = 'Approaching 10% floor'
    
    return status

def check_crash_deploy_readiness():
    """Check if crash deploy conditions are approaching"""
    market_data = load_market_indices()
    if not market_data:
        return None
    
    sp500 = market_data.get('indices', {}).get('S&P 500', {})
    if not sp500:
        return None
    
    drop_pct = sp500.get('return_pct', 0)
    
    readiness = {
        'timestamp': datetime.now().isoformat(),
        'sp500_return': drop_pct,
        'status': 'normal'
    }
    
    if drop_pct <= -15:
        readiness['status'] = 'deploy_3'
        readiness['action'] = 'Final deploy level (-15%) - 30% cash deployment'
    elif drop_pct <= -10:
        readiness['status'] = 'deploy_2'
        readiness['action'] = 'Second deploy level (-10%) - 40% cash deployment'
    elif drop_pct <= -5:
        readiness['status'] = 'deploy_1'
        readiness['action'] = 'First deploy level (-5%) - 30% cash deployment'
    elif drop_pct <= -3:
        readiness['status'] = 'approaching'
        readiness['action'] = f'Approaching deploy zone ({drop_pct:.1f}%)'
    
    return readiness

def log_strategy_event(event_type, details):
    """Log cash strategy events"""
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'type': event_type,
        'details': details
    }
    
    logs = []
    if CASH_LOG.exists():
        with open(CASH_LOG) as f:
            logs = json.load(f)
    
    logs.append(log_entry)
    
    # Keep last 100 events
    logs = logs[-100:]
    
    with open(CASH_LOG, 'w') as f:
        json.dump(logs, f, indent=2)

def generate_daily_report():
    """Generate daily cash strategy report"""
    cash_status = check_cash_status()
    crash_status = check_crash_deploy_readiness()
    
    report = []
    report.append("=" * 50)
    report.append("CASH STRATEGY DAILY REPORT")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 50)
    
    if cash_status:
        report.append(f"\n💰 CASH POSITION:")
        report.append(f"   Cash: ${cash_status['cash']:,.2f}")
        report.append(f"   Portfolio: ${cash_status['portfolio_value']:,.2f}")
        report.append(f"   Cash %: {cash_status['cash_pct']:.1f}%")
        report.append(f"   Status: {cash_status['status'].upper()}")
        if 'action_needed' in cash_status:
            report.append(f"   Action: {cash_status['action_needed']}")
    
    if crash_status:
        report.append(f"\n📉 CRASH DEPLOY STATUS:")
        report.append(f"   S&P 500 Return: {crash_status['sp500_return']:.2f}%")
        report.append(f"   Status: {crash_status['status'].upper()}")
        if 'action' in crash_status:
            report.append(f"   Action: {crash_status['action']}")
    
    report.append("\n" + "=" * 50)
    
    return '\n'.join(report)

if __name__ == "__main__":
    print(generate_daily_report())
