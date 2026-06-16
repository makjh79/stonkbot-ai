#!/usr/bin/env python3
"""
STONK.AI Auto-Recovery Script
Automatically restarts failed services, fixes process accumulation, and handles common issues
"""

import subprocess
import json
import os
import signal
from datetime import datetime

BOT_DIR = '/opt/stonk-ai'
WEB_DIR = '/var/www/hedge-fund-website'
LOG_FILE = '/var/log/stonk_recovery.log'

def log(message):
    """Log with timestamp"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    with open(LOG_FILE, 'a') as f:
        f.write(log_msg + '\n')

def get_process_count(script_name):
    """Get number of running python3 instances of script_name"""
    try:
        result = subprocess.run(['ps', '-C', 'python3', '-o', 'pid,args', '--no-headers'],
                              capture_output=True, text=True)
        if result.returncode != 0:
            return 0
        lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
        pids = [line.split()[0] for line in lines if script_name in line]
        return len(pids)
    except:
        return 0

def cleanup_duplicate_processes(script_name, keep_oldest=True):
    """Clean up duplicate python3 processes, keeping only one"""
    try:
        result = subprocess.run(['ps', '-C', 'python3', '-o', 'pid,args', '--no-headers'],
                              capture_output=True, text=True)
        if result.returncode != 0:
            return 0
        
        lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
        pids = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and script_name in line:
                try:
                    pids.append(int(parts[0]))
                except ValueError:
                    continue
        
        if len(pids) <= 1:
            return 0
        
        # Sort PIDs (oldest first)
        pids.sort()
        
        # Keep the first (oldest) PID, kill the rest
        to_kill = pids[1:] if keep_oldest else pids[:-1]
        
        killed = 0
        for pid in to_kill:
            try:
                os.kill(pid, signal.SIGTERM)
                killed += 1
                log(f"  Killed duplicate {script_name} PID {pid}")
            except ProcessLookupError:
                pass  # Process already gone
            except Exception as e:
                log(f"  Error killing PID {pid}: {e}")
        
        return killed
    except Exception as e:
        log(f"Error cleaning {script_name}: {e}")
        return 0

def is_process_running(script_name):
    """Check if at least one instance is running"""
    return get_process_count(script_name) > 0

def restart_service(script_name, log_file):
    """Restart a service"""
    try:
        # Kill existing python3 instances only (avoid killing cron shells/flock)
        result = subprocess.run(['ps', '-C', 'python3', '-o', 'pid,args', '--no-headers'],
                              capture_output=True, text=True)
        if result.returncode == 0:
            lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and script_name in line:
                    try:
                        pid = int(parts[0])
                        os.kill(pid, signal.SIGTERM)
                    except (ValueError, ProcessLookupError):
                        pass
        
        # Small delay to ensure cleanup
        import time
        time.sleep(1)
        
        # Start new instance with flock to prevent overlap with cron jobs
        lock_map = {
            'fetch_ai_watchlist.py': '/tmp/watchlist.lock',
            'fetch_crowd_sentiment.py': '/tmp/crowd_sentiment.lock',
        }
        lock_file = lock_map.get(script_name)
        if lock_file:
            cmd = f"cd {BOT_DIR} && flock -n {lock_file} python3 {script_name} > {log_file} 2>&1 &"
        else:
            cmd = f"cd {BOT_DIR} && nohup python3 {script_name} > {log_file} 2>&1 &"
        subprocess.Popen(cmd, shell=True, 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL)
        
        log(f"✅ Restarted {script_name}")
        return True
    except Exception as e:
        log(f"❌ Failed to restart {script_name}: {e}")
        return False

def check_and_fix_watchlist_rotation():
    """Check if watchlist rotation is working, fix if not"""
    try:
        rotation_file = f'{WEB_DIR}/watchlist_changes.json'
        
        # Check if file exists
        if not os.path.exists(rotation_file):
            log("⚠️  Watchlist rotation file missing - forcing rotation")
            force_rotation()
            return
        
        # Check freshness
        with open(rotation_file, 'r') as f:
            data = json.load(f)
            timestamp = data.get('timestamp', '')
            if timestamp:
                rotation_time = datetime.fromisoformat(timestamp)
                age_minutes = (datetime.now() - rotation_time).total_seconds() / 60
                
                if age_minutes > 15:
                    log(f"⚠️  Watchlist rotation stale ({age_minutes:.0f} min) - forcing rotation")
                    force_rotation()
                    return
        
        log("✅ Watchlist rotation is healthy")
        
    except Exception as e:
        log(f"❌ Error checking rotation: {e}")
        force_rotation()

def force_rotation():
    """Force a watchlist rotation"""
    try:
        result = subprocess.run(
            ['python3', f'{BOT_DIR}/dynamic_watchlist_manager.py'],
            cwd=BOT_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            log("✅ Forced watchlist rotation successful")
        else:
            log(f"❌ Rotation failed: {result.stderr}")
    except Exception as e:
        log(f"❌ Error forcing rotation: {e}")

def main():
    """Main recovery logic"""
    log("=== STONK.AI Auto-Recovery Check ===")
    
    # First, clean up any accumulated duplicate processes
    log("Checking for process accumulation...")
    scripts_to_clean = [
        'trading_bot.py',
        'fetch_data_simple.py',
        'fetch_ai_watchlist.py',
        'fetch_crowd_sentiment.py'
    ]
    
    total_cleaned = 0
    for script in scripts_to_clean:
        count = get_process_count(script)
        if count > 1:
            log(f"⚠️  Found {count} instances of {script} - cleaning up...")
            cleaned = cleanup_duplicate_processes(script)
            total_cleaned += cleaned
        else:
            log(f"✅ {script}: {count} instance(s)")
    
    if total_cleaned > 0:
        log(f"✅ Cleaned up {total_cleaned} duplicate process(es)")
    
    # Now check if critical services are running and restart if needed
    services = [
        ('trading_bot.py', '/var/log/trading_bot.log'),
        ('fetch_data_simple.py', '/opt/stonk-ai/data_fetcher.log'),
        ('fetch_ai_watchlist.py', '/var/log/watchlist.log'),
        ('fetch_crowd_sentiment.py', '/var/log/crowd_sentiment.log'),
    ]
    
    restarted = 0
    for script, log_file in services:
        if not is_process_running(script):
            log(f"⚠️  {script} not running - restarting")
            if restart_service(script, log_file):
                restarted += 1
        else:
            count = get_process_count(script)
            status = "✅" if count == 1 else "⚠️"
            log(f"{status} {script} is running ({count} instance(s))")
    
    # Check watchlist rotation
    check_and_fix_watchlist_rotation()
    
    # Update health status file
    try:
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'status': 'HEALTHY' if restarted == 0 else 'RECOVERED',
            'duplicates_cleaned': total_cleaned,
            'services_restarted': restarted
        }
        with open(f'{WEB_DIR}/recovery_status.json', 'w') as f:
            json.dump(health_status, f, indent=2)
    except Exception as e:
        log(f"⚠️  Could not write recovery status: {e}")
    
    log(f"=== Recovery complete: {total_cleaned} duplicates cleaned, {restarted} services restarted ===\n")

if __name__ == '__main__':
    main()
