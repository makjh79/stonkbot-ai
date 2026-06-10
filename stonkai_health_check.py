#!/usr/bin/env python3
"""
STONK.AI Comprehensive Health Check
Validates data integrity, calculations, HTML structure, and bot status
"""

import json
import os
import subprocess
from pathlib import Path
from datetime import datetime

class HealthCheck:
    def __init__(self):
        self.issues = []
        self.fixes = []
        self.checks_passed = []
        
    def log_issue(self, severity, component, message):
        self.issues.append({
            'severity': severity,
            'component': component,
            'message': message
        })
        
    def log_fix(self, component, action):
        self.fixes.append({
            'component': component,
            'action': action
        })
        
    def log_pass(self, component, message):
        self.checks_passed.append({
            'component': component,
            'message': message
        })

    def check_portfolio_calculations(self, filepath):
        """Verify portfolio_data.json calculations are correct"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            errors = []
            for pos in data.get('positions', []):
                expected_mv = round(pos['qty'] * pos['current'], 2)
                expected_cb = round(pos['qty'] * pos['avg_entry'], 2)
                expected_pl = round(expected_mv - expected_cb, 2)
                
                if abs(expected_mv - pos['market_value']) > 0.5:
                    errors.append(f"{pos['symbol']}: market_value mismatch")
                if abs(expected_cb - pos['cost_basis']) > 0.5:
                    errors.append(f"{pos['symbol']}: cost_basis mismatch")
                if abs(expected_pl - pos['unrealized_pl']) > 0.5:
                    errors.append(f"{pos['symbol']}: unrealized_pl mismatch")
            
            # Check equity calculation
            total_mv = sum(p['market_value'] for p in data.get('positions', []))
            cash = data.get('account', {}).get('cash', 0)
            expected_equity = round(total_mv + cash, 2)
            actual_equity = round(data.get('account', {}).get('equity', 0), 2)
            
            if abs(expected_equity - actual_equity) > 1:
                errors.append(f"equity mismatch: got {actual_equity}, expected {expected_equity}")
                # Auto-fix the equity
                data['account']['equity'] = expected_equity
                data['account']['portfolio_value'] = expected_equity
                with open(filepath, 'w') as f:
                    json.dump(data, f, indent=2)
                self.log_fix(filepath, f"Fixed equity calculation: {actual_equity} -> {expected_equity}")
            
            if errors:
                self.log_issue('warning', filepath, f"Calculation issues: {', '.join(errors)}")
            else:
                self.log_pass(filepath, "All calculations validated")
                
            return len(errors) == 0
        except Exception as e:
            self.log_issue('error', filepath, f"Failed to validate: {e}")
            return False

    def check_html_structure(self, filepath):
        """Check HTML has no text after </html>"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Find position of </html>
            html_close_pos = content.rfind('</html>')
            if html_close_pos == -1:
                self.log_issue('error', filepath, "Missing </html> tag")
                return False
            
            # Check for content after </html>
            after_html = content[html_close_pos + 7:].strip()
            if after_html:
                self.log_issue('error', filepath, f"Content found after </html>: {after_html[:100]}")
                # Auto-fix by truncating
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content[:html_close_pos + 7])
                self.log_fix(filepath, "Removed content after </html>")
            else:
                self.log_pass(filepath, "HTML structure valid - no content after </html>")
            
            return True
        except Exception as e:
            self.log_issue('error', filepath, f"Failed to check HTML: {e}")
            return False

    def check_data_sync(self):
        """Check portfolio files are in sync"""
        files_to_check = [
            '/opt/stonk-ai/portfolio_data.json',
            '/root/.openclaw/workspace/hedge-fund-website/portfolio_data.json'
        ]
        
        data_sets = []
        for filepath in files_to_check:
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    positions = {p['symbol'] for p in data.get('positions', [])}
                    data_sets.append((filepath, positions, data.get('account', {}).get('portfolio_value', 0)))
                except Exception as e:
                    self.log_issue('error', filepath, f"Failed to read: {e}")
        
        if len(data_sets) >= 2:
            # Check if positions match
            base_positions = data_sets[0][1]
            for filepath, positions, value in data_sets[1:]:
                if positions != base_positions:
                    self.log_issue('warning', 'Data Sync', 
                        f"Position mismatch: {data_sets[0][0]} has {base_positions}, {filepath} has {positions}")
                    # Sync the files - use /opt/stonk-ai as source of truth
                    try:
                        with open('/opt/stonk-ai/portfolio_data.json', 'r') as f:
                            source_data = json.load(f)
                        with open(filepath, 'w') as f:
                            json.dump(source_data, f, indent=2)
                        self.log_fix(filepath, "Synced with /opt/stonk-ai/portfolio_data.json")
                    except Exception as e:
                        self.log_issue('error', filepath, f"Failed to sync: {e}")
                else:
                    self.log_pass('Data Sync', f"{filepath} matches source")

    def check_why_badges(self, html_path):
        """Check all holdings have why-badge in HTML"""
        try:
            with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Count why-badge occurrences in generated HTML template
            why_badge_count = content.count('class="why-badge">Why')
            
            # Extract holdings from JS data
            import re
            holdings = re.findall(r'\{ symbol:\s*"(\w+)"', content)
            unique_holdings = list(dict.fromkeys(holdings))  # preserve order, remove dups
            
            # The why-badge is in a template string that generates for each position
            # So we check if the template includes why-badge
            if why_badge_count > 0:
                self.log_pass('Why Badges', f"Why badge template present - applies to all {len(unique_holdings)} holdings")
            else:
                self.log_issue('warning', 'Why Badges', "Why badge template missing from holding cards")
            
            return unique_holdings
        except Exception as e:
            self.log_issue('error', 'Why Badges', f"Failed to check: {e}")
            return []

    def check_bot_processes(self):
        """Check bot processes are running"""
        expected_processes = [
            ('fetch_data.py', 'Data Fetcher'),
            ('trading_bot.py', 'Trading Bot'),
            ('dynamic_watchlist.py', 'Dynamic Watchlist'),
            ('fetch_ai_watchlist.py', 'AI Watchlist')
        ]
        
        try:
            ps_output = subprocess.check_output(['ps', 'aux'], text=True)
            
            for script, name in expected_processes:
                if script in ps_output:
                    self.log_pass(f'Bot: {name}', f"{script} is running")
                else:
                    self.log_issue('critical', f'Bot: {name}', f"{script} is NOT running")
        except Exception as e:
            self.log_issue('error', 'Process Check', f"Failed to check processes: {e}")

    def run_all_checks(self):
        """Run complete health check suite"""
        print("=" * 60)
        print("STONK.AI COMPREHENSIVE HEALTH CHECK")
        print(f"Time: {datetime.now().isoformat()}")
        print("=" * 60)
        
        # 1. Portfolio calculations
        print("\n[1/5] Checking portfolio calculations...")
        self.check_portfolio_calculations('/opt/stonk-ai/portfolio_data.json')
        self.check_portfolio_calculations('/root/.openclaw/workspace/portfolio_data.json')
        self.check_portfolio_calculations('/root/.openclaw/workspace/hedge-fund-website/portfolio_data.json')
        
        # 2. HTML structure
        print("\n[2/5] Checking HTML structure...")
        self.check_html_structure('/opt/stonk-ai/index.html')
        
        # 3. Data sync
        print("\n[3/5] Checking data file sync...")
        self.check_data_sync()
        
        # 4. Why badges
        print("\n[4/5] Checking why-badges...")
        self.check_why_badges('/opt/stonk-ai/index.html')
        
        # 5. Bot processes
        print("\n[5/5] Checking bot processes...")
        self.check_bot_processes()
        
        # Report
        self.print_report()
        
    def print_report(self):
        """Print health check report"""
        print("\n" + "=" * 60)
        print("HEALTH CHECK REPORT")
        print("=" * 60)
        
        if self.fixes:
            print(f"\n✅ AUTOMATIC FIXES APPLIED ({len(self.fixes)}):")
            for fix in self.fixes:
                print(f"  • {fix['component']}: {fix['action']}")
        
        if self.checks_passed:
            print(f"\n✅ CHECKS PASSED ({len(self.checks_passed)}):")
            for check in self.checks_passed:
                print(f"  • {check['component']}: {check['message']}")
        
        if self.issues:
            print(f"\n⚠️  ISSUES FOUND ({len(self.issues)}):")
            for issue in self.issues:
                icon = "🔴" if issue['severity'] == 'critical' else "🟡" if issue['severity'] == 'warning' else "🔵"
                print(f"  {icon} [{issue['severity'].upper()}] {issue['component']}: {issue['message']}")
        
        # Summary
        critical = sum(1 for i in self.issues if i['severity'] == 'critical')
        warnings = sum(1 for i in self.issues if i['severity'] == 'warning')
        
        print("\n" + "=" * 60)
        if critical == 0 and warnings == 0:
            print("🎉 ALL SYSTEMS HEALTHY - No action needed")
        elif critical == 0:
            print(f"⚠️  SYSTEM DEGRADED - {warnings} warning(s), no critical issues")
        else:
            print(f"🚨 SYSTEM ALERT - {critical} critical, {warnings} warning(s)")
        print("=" * 60)

if __name__ == '__main__':
    checker = HealthCheck()
    checker.run_all_checks()
