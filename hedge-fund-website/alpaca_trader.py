#!/usr/bin/env python3
"""
STONK.AI - Real Alpaca Trading Bot
Connects to Alpaca Markets API for live/paper trading
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('STONK.AI')

class AlpacaTrader:
    """Real-time trading bot with Alpaca Markets integration"""
    
    def __init__(self, api_key: str = None, secret_key: str = None, paper: bool = True):
        """
        Initialize Alpaca trader
        
        Args:
            api_key: Alpaca API key (or from env ALPACA_API_KEY)
            secret_key: Alpaca secret key (or from env ALPACA_SECRET_KEY)
            paper: Use paper trading (True) or live trading (False)
        """
        # Try to load from config file first
        config_path = '../alpaca_config.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            self.api_key = api_key or config.get('api_key') or os.getenv('ALPACA_API_KEY')
            self.secret_key = secret_key or config.get('api_secret') or os.getenv('ALPACA_SECRET_KEY')
        else:
            self.api_key = api_key or os.getenv('ALPACA_API_KEY')
            self.secret_key = secret_key or os.getenv('ALPACA_SECRET_KEY')
        self.paper = paper
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials required. Set ALPACA_API_KEY and ALPACA_SECRET_KEY env vars.")
        
        # Base URLs
        if paper:
            self.base_url = 'https://paper-api.alpaca.markets'
            self.data_url = 'https://data.alpaca.markets'
            logger.info("🔧 Using PAPER trading (test mode)")
        else:
            self.base_url = 'https://api.alpaca.markets'
            self.data_url = 'https://data.alpaca.markets'
            logger.warning("⚠️ Using LIVE trading mode - REAL MONEY!")
        
        # Trading strategy config
        self.config = {
            'stop_loss_pct': -15.0,
            'profit_trim_pct': 25.0,
            'profit_exit_pct': 50.0,
            'max_position_pct': 20.0,
            'min_cash_reserve': 15000,
            'max_daily_entries': 2,
            'rsi_oversold': 30,
            'volume_threshold': 2.0,
            'conviction_threshold': 70,
            'sector_limit': 35.0
        }
        
        # Track daily activity
        self.daily_stats = {
            'entries_today': 0,
            'exits_today': 0,
            'last_reset': datetime.now().date()
        }
        
        logger.info("🤖 STONK.AI Bot initialized")
    
    def _headers(self) -> Dict:
        """Return authentication headers"""
        return {
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.secret_key
        }
    
    def get_account(self) -> Dict:
        """Fetch account information"""
        try:
            response = requests.get(
                f'{self.base_url}/v2/account',
                headers=self._headers()
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch account: {e}")
            return {}
    
    def get_positions(self) -> List[Dict]:
        """Fetch current positions"""
        try:
            response = requests.get(
                f'{self.base_url}/v2/positions',
                headers=self._headers()
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []
    
    def get_orders(self, status: str = 'open') -> List[Dict]:
        """Fetch orders"""
        try:
            response = requests.get(
                f'{self.base_url}/v2/orders',
                headers=self._headers(),
                params={'status': status}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            return []
    
    def place_order(self, symbol: str, qty: int, side: str, 
                    order_type: str = 'market', 
                    time_in_force: str = 'day') -> Optional[Dict]:
        """
        Place an order
        
        Args:
            symbol: Stock symbol
            qty: Quantity
            side: 'buy' or 'sell'
            order_type: 'market', 'limit', etc.
            time_in_force: 'day', 'gtc', etc.
        """
        try:
            data = {
                'symbol': symbol,
                'qty': qty,
                'side': side,
                'type': order_type,
                'time_in_force': time_in_force
            }
            
            response = requests.post(
                f'{self.base_url}/v2/orders',
                headers=self._headers(),
                json=data
            )
            response.raise_for_status()
            order = response.json()
            
            logger.info(f"🎯 Order placed: {side.upper()} {qty} {symbol} @ {order_type}")
            return order
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    def close_position(self, symbol: str) -> Optional[Dict]:
        """Close a position"""
        try:
            response = requests.delete(
                f'{self.base_url}/v2/positions/{symbol}',
                headers=self._headers()
            )
            response.raise_for_status()
            logger.info(f"🔴 Position closed: {symbol}")
            return response.json()
        except Exception as e:
            logger.error(f"Failed to close position {symbol}: {e}")
            return None
    
    def get_bars(self, symbol: str, timeframe: str = '1D', 
                  limit: int = 100) -> List[Dict]:
        """
        Get price bars for technical analysis
        
        Args:
            symbol: Stock symbol
            timeframe: '1Min', '5Min', '15Min', '1H', '1D'
            limit: Number of bars
        """
        try:
            response = requests.get(
                f'{self.data_url}/v2/stocks/{symbol}/bars',
                headers=self._headers(),
                params={
                    'timeframe': timeframe,
                    'limit': limit,
                    'feed': 'sip'  # Use SIP for most accurate data
                }
            )
            response.raise_for_status()
            return response.json().get('bars', [])
        except Exception as e:
            logger.error(f"Failed to fetch bars for {symbol}: {e}")
            return []
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(prices) < period + 1:
            return 50.0  # Neutral if insufficient data
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get latest quote"""
        try:
            response = requests.get(
                f'{self.data_url}/v2/stocks/{symbol}/quotes/latest',
                headers=self._headers()
            )
            response.raise_for_status()
            return response.json().get('quote', {})
        except Exception as e:
            logger.error(f"Failed to get quote for {symbol}: {e}")
            return None
    
    def check_stop_losses(self) -> List[Dict]:
        """
        Check all positions for stop loss triggers
        Returns list of positions to close
        """
        positions = self.get_positions()
        account = self.get_account()
        portfolio_value = float(account.get('portfolio_value', 0))
        
        to_close = []
        
        for position in positions:
            symbol = position['symbol']
            entry_price = float(position['avg_entry_price'])
            current_price = float(position['current_price'])
            unrealized_plpct = float(position['unrealized_plpc']) * 100
            
            # Check stop loss
            if unrealized_plpct <= self.config['stop_loss_pct']:
                logger.warning(f"🛑 STOP LOSS triggered: {symbol} at {unrealized_plpct:.2f}%")
                to_close.append({
                    'symbol': symbol,
                    'action': 'stop_loss',
                    'pl_pct': unrealized_plpct,
                    'qty': position['qty']
                })
            
            # Check profit targets
            elif unrealized_plpct >= self.config['profit_exit_pct']:
                logger.info(f"🎯 PROFIT EXIT triggered: {symbol} at +{unrealized_plpct:.2f}%")
                to_close.append({
                    'symbol': symbol,
                    'action': 'profit_exit',
                    'pl_pct': unrealized_plpct,
                    'qty': position['qty']
                })
            
            elif unrealized_plpct >= self.config['profit_trim_pct']:
                # Trim 25% of position
                trim_qty = int(float(position['qty']) * 0.25)
                if trim_qty > 0:
                    logger.info(f"✂️ PROFIT TRIM: {symbol} trim {trim_qty} shares at +{unrealized_plpct:.2f}%")
                    self.place_order(symbol, trim_qty, 'sell')
        
        return to_close
    
    def scan_for_entries(self, watchlist: List[str] = None) -> List[Dict]:
        """
        Scan for entry opportunities
        Returns list of potential entries
        """
        # Reset daily counters if new day
        today = datetime.now().date()
        if today != self.daily_stats['last_reset']:
            self.daily_stats['entries_today'] = 0
            self.daily_stats['exits_today'] = 0
            self.daily_stats['last_reset'] = today
        
        # Check daily limit
        if self.daily_stats['entries_today'] >= self.config['max_daily_entries']:
            logger.info(f"📊 Daily entry limit reached ({self.config['max_daily_entries']})")
            return []
        
        # Check cash reserve
        account = self.get_account()
        cash = float(account.get('cash', 0))
        portfolio_value = float(account.get('portfolio_value', 97000))
        
        if cash < self.config['min_cash_reserve']:
            logger.info(f"💰 Cash reserve protected (${cash:,.2f})")
            return []
        
        opportunities = []
        deployable_cash = min(cash - self.config['min_cash_reserve'], 
                              portfolio_value * 0.08)  # Max 8% per position
        
        # Default scan universe
        if not watchlist:
            watchlist = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA',
                'AMD', 'NFLX', 'CRM', 'SHOP', 'SQ', 'ROKU', 'ZM'
            ]
        
        for symbol in watchlist:
            try:
                # Get price data for RSI
                bars = self.get_bars(symbol, '1D', 20)
                if len(bars) < 14:
                    continue
                
                prices = [bar['c'] for bar in bars]
                rsi = self.calculate_rsi(prices)
                
                # Get quote
                quote = self.get_quote(symbol)
                if not quote:
                    continue
                
                current_price = float(quote.get('ap', 0))  # Ask price
                volume = quote.get('v', 0)  # Volume
                avg_volume = sum([bar['v'] for bar in bars[-5:]]) / 5
                volume_ratio = volume / avg_volume if avg_volume > 0 else 1
                
                # Check entry criteria
                if (rsi < self.config['rsi_oversold'] and 
                    volume_ratio >= self.config['volume_threshold']):
                    
                    # Calculate conviction score
                    conviction = min(100, 70 + (30 - rsi) + (volume_ratio * 10))
                    
                    if conviction >= self.config['conviction_threshold']:
                        qty = int(deployable_cash / current_price)
                        if qty > 0:
                            opportunities.append({
                                'symbol': symbol,
                                'price': current_price,
                                'rsi': rsi,
                                'volume_ratio': volume_ratio,
                                'conviction': conviction,
                                'qty': qty,
                                'investment': qty * current_price
                            })
                            
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
                continue
        
        # Sort by conviction
        opportunities.sort(key=lambda x: x['conviction'], reverse=True)
        return opportunities[:2]  # Max 2 entries per scan
    
    def execute_exits(self, exits: List[Dict]):
        """Execute position exits"""
        for exit_trade in exits:
            symbol = exit_trade['symbol']
            action = exit_trade['action']
            
            if action in ['stop_loss', 'profit_exit']:
                self.close_position(symbol)
                self.daily_stats['exits_today'] += 1
            
            # Log activity
            self.log_activity({
                'timestamp': datetime.now().isoformat(),
                'type': 'exit',
                'symbol': symbol,
                'action': action,
                'pl_pct': exit_trade.get('pl_pct', 0)
            })
    
    def execute_entries(self, entries: List[Dict]):
        """Execute position entries"""
        for entry in entries:
            symbol = entry['symbol']
            qty = entry['qty']
            
            # Place buy order
            order = self.place_order(symbol, qty, 'buy')
            
            if order:
                self.daily_stats['entries_today'] += 1
                
                # Log activity
                self.log_activity({
                    'timestamp': datetime.now().isoformat(),
                    'type': 'entry',
                    'symbol': symbol,
                    'qty': qty,
                    'price': entry['price'],
                    'investment': entry['investment'],
                    'rsi': entry['rsi'],
                    'conviction': entry['conviction']
                })
    
    def log_activity(self, activity: Dict):
        """Log trading activity to JSON file"""
        log_file = 'activity_log.json'
        
        try:
            # Load existing
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    logs = json.load(f)
            else:
                logs = []
            
            # Add new activity
            logs.append(activity)
            
            # Keep last 1000 entries
            logs = logs[-1000:]
            
            # Save
            with open(log_file, 'w') as f:
                json.dump(logs, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")
    
    def update_portfolio_data(self):
        """Update portfolio_data.json for website display"""
        try:
            account = self.get_account()
            positions = self.get_positions()
            
            portfolio_data = {
                'timestamp': datetime.now().isoformat(),
                'positions': [],
                'account': {
                    'equity': float(account.get('equity', 0)),
                    'cash': float(account.get('cash', 0)),
                    'buying_power': float(account.get('buying_power', 0)),
                    'portfolio_value': float(account.get('portfolio_value', 0))
                },
                'status': 'live',
                'total_pl': float(account.get('equity', 0)) - 100000,
                'total_pl_pct': ((float(account.get('equity', 0)) - 100000) / 100000) * 100
            }
            
            # Add position details
            for pos in positions:
                portfolio_data['positions'].append({
                    'symbol': pos['symbol'],
                    'qty': int(float(pos['qty'])),
                    'avg_entry': float(pos['avg_entry_price']),
                    'current': float(pos['current_price']),
                    'market_value': float(pos['market_value']),
                    'cost_basis': float(pos['cost_basis']),
                    'unrealized_pl': float(pos['unrealized_pl']),
                    'unrealized_plpc': float(pos['unrealized_plpc']) * 100
                })
            
            # Save to file
            with open('portfolio_data.json', 'w') as f:
                json.dump(portfolio_data, f, indent=2)
            
            logger.info(f"💾 Portfolio data updated: ${portfolio_data['account']['portfolio_value']:,.2f}")
            
        except Exception as e:
            logger.error(f"Failed to update portfolio data: {e}")
    
    def run(self, interval: int = 60):
        """
        Main trading loop
        
        Args:
            interval: Seconds between scans (default: 60)
        """
        logger.info("🚀 Starting STONK.AI Trading Bot")
        logger.info(f"⏱️  Scan interval: {interval}s")
        logger.info(f"📊 Config: {json.dumps(self.config, indent=2)}")
        
        while True:
            try:
                # Check if market is open
                clock = requests.get(
                    f'{self.base_url}/v2/clock',
                    headers=self._headers()
                ).json()
                
                if not clock.get('is_open'):
                    logger.info("🔒 Market closed. Waiting...")
                    time.sleep(300)  # Check every 5 minutes
                    continue
                
                logger.info("🔔 Market open. Running strategy...")
                
                # Step 1: Check stop losses and profit targets
                exits = self.check_stop_losses()
                if exits:
                    logger.info(f"🔴 Executing {len(exits)} exits")
                    self.execute_exits(exits)
                
                # Step 2: Scan for new entries
                entries = self.scan_for_entries()
                if entries:
                    logger.info(f"🟢 Found {len(entries)} entry opportunities")
                    for opp in entries:
                        logger.info(f"  📈 {opp['symbol']}: RSI {opp['rsi']:.1f}, "
                                  f"Conviction {opp['conviction']:.0f}%")
                    self.execute_entries(entries)
                
                # Step 3: Update portfolio data file
                self.update_portfolio_data()
                
                logger.info(f"✅ Cycle complete. Sleep {interval}s...")
                logger.info(f"📊 Daily: {self.daily_stats['entries_today']} entries, "
                          f"{self.daily_stats['exits_today']} exits")
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
            
            time.sleep(interval)


def main():
    """Entry point"""
    # Check for credentials
    api_key = os.getenv('ALPACA_API_KEY')
    secret_key = os.getenv('ALPACA_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ Error: Alpaca credentials not found!")
        print("Set environment variables:")
        print("  export ALPACA_API_KEY='your_key'")
        print("  export ALPACA_SECRET_KEY='your_secret'")
        print("")
        print("For paper trading (recommended for testing):")
        print("  export ALPACA_PAPER='true'")
        return
    
    # Use paper trading by default
    paper = os.getenv('ALPACA_PAPER', 'true').lower() == 'true'
    
    # Create and run bot
    bot = AlpacaTrader(api_key=api_key, secret_key=secret_key, paper=paper)
    
    # Run with 60-second scan interval
    bot.run(interval=60)


if __name__ == '__main__':
    main()
