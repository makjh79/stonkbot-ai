#!/usr/bin/env python3
"""
STONK.AI Health Check Script
Monitors bot processes and sends alerts if issues detected
"""

import subprocess
import json
import os
import sys
from datetime import datetime, timedelta

# Configuration
BOT_DIR = '/opt/stonk-ai'
WEB_DIR = '/var/www/hedge-fund-website'
ALPACA_CONFIG = f'{BOT_DIR}/alpaca_config.json'

# Process identifiers (check by script name, not hardcoded PID)
REQUIRED_PROCESSES = {
    'trading_bot.py': {'name': 'StonkBOT Trading', 'critical': True},
    'fetch_data_simple.py': {'name': 'Data Fetcher', 'critical': True},
    'fetch_ai_watchlist.py': {'name': 'AI Watchlist', 'critical': False},
    'fetch_crowd_sentiment.py': {'name': 'Crowd Sentiment', 'critical': False},
}

def find_process_by_script(script_name):
    """Find process by script name (not hardcoded PID)"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', script_name],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            # Return the first valid PID
            for pid in pids:
                if pid and pid.isdigit():
                    return int(pid)
    except Exception:
        pass
    return None

def check_processes():
    """Check if required processes are running"""
    status = {}
    all_healthy = True
    
    for script, info in REQUIRED_PROCESSES.items():
        pid = find_process_by_script(script)
        is_running = pid is not None
        
        status[script] = {
            'running': is_running,
            'pid': pid,
            'name': info['name'],
            'critical': info['critical']
        }
        
        if not is_running and info['critical']:
            all_healthy = False
    
    return status, all_healthy

def check_data_freshness():
    """Check if data files are being updated"""
    issues = []
    
    files_to_check = {
        'portfolio_data.json': 300,  # 5 minutes
        'ai_watchlist_live.json': 300,  # 5 minutes
        'market_indices.json': 3600,  # 1 hour
        'watchlist_changes.json': 600,  # 10 minutes - rotation check
    }
    
    for filename, max_age in files_to_check.items():
        filepath = f'{WEB_DIR}/{filename}'
        if os.path.exists(filepath):
            mtime = os.path.getmtime(filepath)
            age_seconds = (datetime.now() - datetime.fromtimestamp(mtime)).total_seconds()
            
            if age_seconds > max_age:
                issues.append(f"{filename} is stale ({age_seconds/60:.0f} min old)")
        else:
            issues.append(f"{filename} is missing")
    
    return issues

def check_disk_space():
    """Check disk space"""
    try:
        result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            percent_used = int(parts[4].replace('%', ''))
            
            if percent_used > 90:
                return f"CRITICAL: Disk {percent_used}% full"
            elif percent_used > 80:
                return f"WARNING: Disk {percent_used}% full"
    except Exception:
        pass
    return None

def check_alpaca_connection():
    """Check if Alpaca API is configured"""
    if not os.path.exists(ALPACA_CONFIG):
        return "Alpaca config missing"
    
    try:
        with open(ALPACA_CONFIG, 'r') as f:
            config = json.load(f)
            if not config.get('api_key') or not (config.get('secret_key') or config.get('api_secret')):
                return "Alpaca credentials incomplete"
    except Exception as e:
        return f"Alpaca config error: {e}"
    
    return None

def check_watchlist_rotation():
    """Check if watchlist rotation is working"""
    try:
        # Check if rotation file exists and is recent
        rotation_file = f'{WEB_DIR}/watchlist_changes.json'
        if not os.path.exists(rotation_file):
            return "Watchlist rotation: File missing (rotation not running)"
        
        # Check timestamp
        with open(rotation_file, 'r') as f:
            data = json.load(f)
            timestamp = data.get('timestamp', '')
            if timestamp:
                from datetime import datetime
                rotation_time = datetime.fromisoformat(timestamp)
                age_minutes = (datetime.now() - rotation_time).total_seconds() / 60
                
                if age_minutes > 15:
                    return f"Watchlist rotation: Stale ({age_minutes:.0f} min old, should be <10 min)"
                
                # Check if symbols are being tracked
                symbols = data.get('new_watchlist', [])
                if len(symbols) < 5:
                    return f"Watchlist rotation: Only {len(symbols)} symbols (should be 8-20)"
        
        return None
    except Exception as e:
        return f"Watchlist rotation error: {e}"

def check_signal_accuracy():
    """Check if signal tracking is working"""
    signal_file = f'{WEB_DIR}/signal_accuracy.json'
    if os.path.exists(signal_file):
        try:
            with open(signal_file, 'r') as f:
                data = json.load(f)
                total = data.get('stats', {}).get('total_signals', 0)
                if total == 0:
                    return "Signal tracking: No signals recorded yet (watchlist may not have BUY opportunities)"
        except:
            return "Signal tracking: Error reading accuracy data"
    else:
        return "Signal tracking: accuracy file missing"
    return None


def check_sentiment_freshness():
    """Check if watchlist popup sentiment files are fresh"""
    sentiment_dir = f'{WEB_DIR}/sentiment'
    if not os.path.exists(sentiment_dir):
        return "News sentiment: sentiment directory missing"

    expected_tickers = [
        'COIN', 'NET', 'PATH', 'SHOP', 'SQ', 'NIO', 'GM', 'ORCL',
        'AAPL', 'TSLA', 'NVDA', 'META', 'GOOGL', 'TWLO', 'ASAN',
    ]

    max_age_seconds = 7200  # 2 hours (cron runs every 15 min)
    issues = []
    now = datetime.now()

    for ticker in expected_tickers:
        filepath = f'{sentiment_dir}/{ticker}.json'
        if not os.path.exists(filepath):
            issues.append(f"News sentiment: missing {ticker}.json")
            continue

        # Prefer JSON updated_at/timestamp, fall back to file mtime
        json_updated_at = None
        try:
            with open(filepath, 'r') as f:
                payload = json.load(f)
                ts_str = payload.get('updated_at') or payload.get('timestamp')
                if ts_str:
                    # Handle ISO timestamps with timezone
                    ts_str = ts_str.replace('Z', '+00:00')
                    json_updated_at = datetime.fromisoformat(ts_str)
                    if json_updated_at.tzinfo:
                        json_updated_at = json_updated_at.replace(tzinfo=None)
        except Exception:
            pass

        if json_updated_at:
            age_seconds = (now - json_updated_at).total_seconds()
        else:
            mtime = os.path.getmtime(filepath)
            age_seconds = (now - datetime.fromtimestamp(mtime)).total_seconds()

        if age_seconds > max_age_seconds:
            issues.append(
                f"News sentiment: {ticker}.json is stale ({age_seconds/3600:.1f}h old, max 2h)"
            )

    if issues:
        return issues
    return None


def check_portfolio_history():
    """Check portfolio history has enough unique days for the performance chart."""
    history_file = f'{WEB_DIR}/portfolio_history.json'
    min_days = 7

    if not os.path.exists(history_file):
        return f"Portfolio history: {history_file} missing"

    try:
        with open(history_file, 'r') as f:
            data = json.load(f)
        checks = data.get('checks', [])
        days = sorted(set(c['timestamp'][:10] for c in checks if len(c.get('timestamp', '')) >= 10))
        if len(days) < min_days:
            return f"Portfolio history: only {len(days)} unique days (need >= {min_days}); performance chart may break"
    except Exception as e:
        return f"Portfolio history: error reading file ({e})"

    return None


def generate_report():
    """Generate health check report"""
    report = {
        'timestamp': datetime.now().isoformat(),
        'status': 'HEALTHY',
        'issues': []
    }
    
    # Check processes
    process_status, all_healthy = check_processes()
    report['processes'] = process_status
    
    if not all_healthy:
        report['status'] = 'DEGRADED'
        for script, info in process_status.items():
            if info['critical'] and not info['running']:
                report['issues'].append(f"CRITICAL: {info['name']} is not running")
    
    # Check data freshness
    stale_files = check_data_freshness()
    if stale_files:
        report['status'] = 'DEGRADED'
        report['issues'].extend(stale_files)
    
    # Check disk space
    disk_issue = check_disk_space()
    if disk_issue:
        report['status'] = 'DEGRADED' if 'WARNING' in disk_issue else 'CRITICAL'
        report['issues'].append(disk_issue)
    
    # Check Alpaca
    alpaca_issue = check_alpaca_connection()
    if alpaca_issue:
        report['status'] = 'DEGRADED'
        report['issues'].append(alpaca_issue)
    
    # Check signal tracking
    signal_issue = check_signal_accuracy()
    if signal_issue:
        report['issues'].append(signal_issue)
    
    # Check watchlist rotation
    rotation_issue = check_watchlist_rotation()
    if rotation_issue:
        report['status'] = 'DEGRADED'
        report['issues'].append(rotation_issue)
    
    # Check portfolio history has enough days for chart
    history_issue = check_portfolio_history()
    if history_issue:
        report['status'] = 'DEGRADED'
        report['issues'].append(history_issue)

    # Check watchlist popup sentiment freshness
    sentiment_issues = check_sentiment_freshness()
    if sentiment_issues:
        report['status'] = 'DEGRADED'
        report['issues'].extend(sentiment_issues)
    
    return report

def save_health_status(report):
    """Save health status to JSON for website display"""
    health_file = f'{WEB_DIR}/health_status.json'
    with open(health_file, 'w') as f:
        json.dump(report, f, indent=2)

if __name__ == '__main__':
    report = generate_report()
    save_health_status(report)
    
    # Print report
    print(f"=== STONK.AI Health Check ===")
    print(f"Status: {report['status']}")
    print(f"Time: {report['timestamp']}")
    print()
    
    print("Processes:")
    for script, info in report['processes'].items():
        status = "✅" if info['running'] else "❌"
        print(f"  {status} {info['name']}: PID {info['pid'] or 'NOT RUNNING'}")
    
    if report['issues']:
        print("\nIssues:")
        for issue in report['issues']:
            print(f"  ⚠️  {issue}")
    else:
        print("\n✅ All systems healthy!")
