#!/usr/bin/env python3
"""
STONK.AI Signal Tracker
Tracks BUY signals and their outcomes to calculate accuracy
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
BOT_DIR = '/opt/stonk-ai'
WEB_DIR = '/var/www/hedge-fund-website'
SIGNALS_FILE = f'{BOT_DIR}/signals.json'
ACCURACY_FILE = f'{WEB_DIR}/signal_accuracy.json'
PORTFOLIO_FILE = f'{WEB_DIR}/portfolio_data.json'
WATCHLIST_FILE = f'{WEB_DIR}/ai_watchlist_live.json'

class SignalTracker:
    def __init__(self):
        self.signals = self.load_signals()
        
    def load_signals(self):
        """Load existing signals"""
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, 'r') as f:
                return json.load(f)
        return {'signals': [], 'last_updated': datetime.now().isoformat()}
    
    def save_signals(self):
        """Save signals to file"""
        self.signals['last_updated'] = datetime.now().isoformat()
        with open(SIGNALS_FILE, 'w') as f:
            json.dump(self.signals, f, indent=2)
    
    def load_portfolio(self):
        """Load current portfolio data"""
        if os.path.exists(PORTFOLIO_FILE):
            with open(PORTFOLIO_FILE, 'r') as f:
                return json.load(f)
        return None
    
    def load_watchlist(self):
        """Load current watchlist with targets"""
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, 'r') as f:
                return json.load(f)
        return {'prices': {}}
    
    def detect_new_signals(self):
        """Detect new BUY signals from watchlist"""
        watchlist = self.load_watchlist()
        new_signals = []
        
        for symbol, data in watchlist.get('prices', {}).items():
            # Check if this is a BUY signal (RSI < 35 + signal = BUY)
            rsi = data.get('rsi', 50)
            signal = data.get('targets', {}).get('signal', '')
            
            if rsi is None:
                rsi = 50
            
            if signal == 'BUY' and rsi <= 35:
                # Check if we already have this signal
                existing = [s for s in self.signals['signals'] 
                           if s['symbol'] == symbol and s['status'] == 'active']
                
                if not existing:
                    new_signal = {
                        'id': f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        'symbol': symbol,
                        'type': 'BUY',
                        'entry_price': data.get('price', 0),
                        'entry_rsi': rsi,
                        'timestamp': datetime.now().isoformat(),
                        'targets': {
                            'conservative': data.get('targets', {}).get('conservative_target'),
                            'aggressive': data.get('targets', {}).get('aggressive_target'),
                            'profit_25': data.get('targets', {}).get('profit_25'),
                            'profit_50': data.get('targets', {}).get('profit_50'),
                            'stop_loss': data.get('targets', {}).get('stop_loss')
                        },
                        'status': 'active',
                        'outcome': None,
                        'exit_price': None,
                        'exit_date': None,
                        'return_pct': None,
                        'days_to_outcome': None
                    }
                    new_signals.append(new_signal)
                    print(f"🎯 New BUY signal: {symbol} @ ${data.get('price', 0):.2f} (RSI: {rsi:.1f})")
        
        return new_signals
    
    def check_signal_outcomes(self):
        """Check if active signals have hit targets or stop losses"""
        watchlist = self.load_watchlist()
        portfolio = self.load_portfolio()
        
        for signal in self.signals['signals']:
            if signal['status'] != 'active':
                continue
            
            symbol = signal['symbol']
            current_data = watchlist.get('prices', {}).get(symbol, {})
            current_price = current_data.get('price', 0)
            
            if current_price == 0:
                continue
            
            entry_price = signal['entry_price']
            stop_loss = signal['targets'].get('stop_loss', entry_price * 0.85)
            profit_25 = signal['targets'].get('profit_25', entry_price * 1.25)
            profit_50 = signal['targets'].get('profit_50', entry_price * 1.50)
            
            return_pct = ((current_price - entry_price) / entry_price) * 100
            
            outcome = None
            exit_price = current_price
            
            # Check stop loss
            if current_price <= stop_loss:
                outcome = 'stopped'
                print(f"🛑 {symbol} hit stop loss: ${current_price:.2f} ({return_pct:.1f}%)")
            
            # Check profit targets
            elif current_price >= profit_50:
                outcome = 'profit_50'
                print(f"🎯 {symbol} hit +50% target: ${current_price:.2f} ({return_pct:.1f}%)")
            
            elif current_price >= profit_25:
                outcome = 'profit_25'
                print(f"🎯 {symbol} hit +25% target: ${current_price:.2f} ({return_pct:.1f}%)")
            
            # Check if we actually bought this in portfolio (manual confirmation)
            if portfolio and outcome:
                positions = portfolio.get('positions', [])
                position = next((p for p in positions if p['symbol'] == symbol), None)
                
                if position:
                    signal['status'] = 'closed'
                    signal['outcome'] = outcome
                    signal['exit_price'] = exit_price
                    signal['exit_date'] = datetime.now().isoformat()
                    signal['return_pct'] = round(return_pct, 2)
                    
                    entry_date = datetime.fromisoformat(signal['timestamp'])
                    days = (datetime.now() - entry_date).days
                    signal['days_to_outcome'] = days
    
    def calculate_accuracy_stats(self):
        """Calculate signal accuracy statistics"""
        closed_signals = [s for s in self.signals['signals'] if s['status'] == 'closed']
        
        if not closed_signals:
            return {
                'total_signals': len(self.signals['signals']),
                'win_rate': 0,
                'avg_return': 0,
                'avg_days_to_target': 0,
                'pending_signals': len([s for s in self.signals['signals'] if s['status'] == 'active'])
            }
        
        # Count wins (profit_25 or profit_50) vs losses (stopped)
        wins = [s for s in closed_signals if s['outcome'] in ['profit_25', 'profit_50']]
        losses = [s for s in closed_signals if s['outcome'] == 'stopped']
        
        win_rate = (len(wins) / len(closed_signals)) * 100 if closed_signals else 0
        
        returns = [s['return_pct'] for s in closed_signals if s['return_pct'] is not None]
        avg_return = sum(returns) / len(returns) if returns else 0
        
        days = [s['days_to_outcome'] for s in closed_signals if s['days_to_outcome'] is not None]
        avg_days = sum(days) / len(days) if days else 0
        
        return {
            'total_signals': len(self.signals['signals']),
            'closed_signals': len(closed_signals),
            'win_rate': round(win_rate, 1),
            'avg_return': round(avg_return, 2),
            'avg_days_to_target': round(avg_days, 1),
            'pending_signals': len([s for s in self.signals['signals'] if s['status'] == 'active']),
            'wins': len(wins),
            'losses': len(losses)
        }
    
    def export_for_website(self):
        """Export accuracy data for website display"""
        stats = self.calculate_accuracy_stats()
        
        # Get recent signals (last 10)
        recent = sorted(
            [s for s in self.signals['signals'] if s['status'] == 'active'],
            key=lambda x: x['timestamp'],
            reverse=True
        )[:10]
        
        export_data = {
            'stats': stats,
            'recent_pending': recent,
            'last_updated': datetime.now().isoformat()
        }
        
        with open(ACCURACY_FILE, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        return export_data
    
    def run(self):
        """Main run loop"""
        print("=== STONK.AI Signal Tracker ===")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Detect new signals
        new_signals = self.detect_new_signals()
        if new_signals:
            self.signals['signals'].extend(new_signals)
            print(f"✅ Added {len(new_signals)} new signals")
        else:
            print("ℹ️  No new signals detected")
        
        # Check outcomes
        self.check_signal_outcomes()
        
        # Save and export
        self.save_signals()
        stats = self.export_for_website()
        
        print(f"\n📊 Signal Statistics:")
        print(f"   Total signals: {stats['stats']['total_signals']}")
        print(f"   Active signals: {stats['stats']['pending_signals']}")
        print(f"   Closed signals: {stats['stats'].get('closed_signals', 0)}")
        print(f"   Win rate: {stats['stats']['win_rate']:.1f}%")
        print(f"   Avg return: {stats['stats']['avg_return']:.2f}%")

# Standalone functions for trading_bot.py integration
def log_buy_signal(symbol: str, price: float, rsi: float):
    """Log a buy signal when bot enters a position"""
    try:
        tracker = SignalTracker()
        # Check if signal already exists
        existing = [s for s in tracker.signals['signals'] 
                   if s['symbol'] == symbol and s['status'] == 'active']
        if existing:
            return
        
        # Create new signal
        new_signal = {
            'id': f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'symbol': symbol,
            'type': 'BUY',
            'entry_price': price,
            'entry_rsi': rsi,
            'timestamp': datetime.now().isoformat(),
            'targets': {
                'profit_25': price * 1.25,
                'profit_50': price * 1.50,
                'stop_loss': price * 0.85
            },
            'status': 'active',
            'outcome': None,
            'exit_price': None,
            'exit_date': None,
            'return_pct': None,
            'days_to_outcome': None
        }
        tracker.signals['signals'].append(new_signal)
        tracker.save_signals()
        tracker.export_for_website()
        print(f"🎯 Logged buy signal: {symbol} @ ${price:.2f} (RSI: {rsi:.1f})")
    except Exception as e:
        print(f"Could not log buy signal: {e}")

def update_signal_performance(symbol: str, exit_price: float, outcome: str):
    """Update signal performance when position closes"""
    try:
        tracker = SignalTracker()
        # Find active signal for this symbol
        for signal in tracker.signals['signals']:
            if signal['symbol'] == symbol and signal['status'] == 'active':
                signal['status'] = 'closed'
                signal['outcome'] = outcome
                signal['exit_price'] = exit_price
                signal['exit_date'] = datetime.now().isoformat()
                
                # Calculate return
                if signal['entry_price'] > 0:
                    signal['return_pct'] = ((exit_price - signal['entry_price']) / signal['entry_price']) * 100
                
                # Calculate days held
                entry_date = datetime.fromisoformat(signal['timestamp'])
                days = (datetime.now() - entry_date).days
                signal['days_to_outcome'] = days
                
                tracker.save_signals()
                tracker.export_for_website()
                print(f"📊 Updated signal: {symbol} - {outcome} ({signal['return_pct']:+.2f}%)")
                return
    except Exception as e:
        print(f"Could not update signal performance: {e}")

if __name__ == '__main__':
    tracker = SignalTracker()
    tracker.run()
