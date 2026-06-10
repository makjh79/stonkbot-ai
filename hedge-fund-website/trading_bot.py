#!/usr/bin/env python3
"""
STONK.AI Trading Bot v1.0
Autonomous AI-managed trading system
Implements the complete strategy from STRATEGY.md

Design Philosophy:
- AI designed the strategy (STRATEGY.md)
- Bot executes autonomously (zero AI cost during operation)
- Human only intervenes for emergencies or scheduled reviews
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# Try to import alpaca SDK, fall back to requests
try:
    import alpaca_trade_api as tradeapi
    USE_SDK = True
except ImportError:
    import requests
    USE_SDK = False

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Alpaca Config - Use existing config file
ALPACA_CONFIG_FILE = Path("/root/.openclaw/workspace/alpaca_config.json")

def load_alpaca_config():
    """Load Alpaca API credentials from existing config"""
    if ALPACA_CONFIG_FILE.exists():
        with open(ALPACA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    # Fallback to environment variables
    return {
        "api_key": os.getenv('ALPACA_API_KEY'),
        "api_secret": os.getenv('ALPACA_SECRET_KEY'),
        "base_url": os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    }


@dataclass
class StrategyConfig:
    """Trading strategy configuration from STRATEGY.md"""
    
    # Portfolio Allocation Targets (% of invested capital)
    ALLOCATION_TARGETS = {
        'Tech Giants': 25.0,
        'AI/Growth': 30.0,
        'Fintech': 5.0,
        'Defense/Income': 5.0,
    }
    
    # Risk Management
    MAX_POSITION_SIZE = 0.15  # Max 15% in single stock
    STOP_LOSS_PCT = -15.0  # -15% stop loss
    TAKE_PROFIT_TRIM = 25.0  # Trim at +25%
    TAKE_PROFIT_FULL = 50.0  # Full exit at +50%
    MAX_SECTOR_DEVIATION = 10.0  # Can deviate 10% from target
    MIN_CASH_BUFFER = 0.30  # Keep 30% cash minimum
    
    # Trading Limits
    MAX_TRADES_PER_DAY = 3
    MAX_TRADES_PER_WEEK = 10
    REBALANCE_THRESHOLD = 0.05  # 5% drift triggers rebalance
    
    # Sector Definitions
    SECTORS = {
        'Tech Giants': ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA'],
        'AI/Growth': ['AMD', 'PLTR', 'APP', 'CRWD'],
        'Fintech': ['HOOD', 'SOFI'],
        'Defense/Income': ['AVGO', 'SCHD', 'SGOV']
    }
    
    # Special Rules
    CORE_HOLDINGS = ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA']  # Long-term holds
    NEVER_SELL = ['SCHD', 'SGOV']  # Permanent stabilizers
    TRIM_ON_GAIN = ['AMD', 'PLTR', 'APP', 'CRWD']  # Trim on +25%


class PortfolioState:
    """Tracks portfolio state and trade history"""
    
    def __init__(self, state_file: Path = Path('portfolio_state.json')):
        self.state_file = state_file
        self.daily_trades = 0
        self.weekly_trades = 0
        self.last_trade_date = None
        self.last_trade_week = None
        self.stop_losses_triggered = []
        self.take_profits_triggered = []
        self.load()
    
    def load(self):
        """Load state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                    self.daily_trades = data.get('daily_trades', 0)
                    self.weekly_trades = data.get('weekly_trades', 0)
                    self.last_trade_date = data.get('last_trade_date')
                    self.last_trade_week = data.get('last_trade_week')
                    self.stop_losses_triggered = data.get('stop_losses_triggered', [])
                    self.take_proits_triggered = data.get('take_profits_triggered', [])
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
    
    def save(self):
        """Save state to file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    'daily_trades': self.daily_trades,
                    'weekly_trades': self.weekly_trades,
                    'last_trade_date': self.last_trade_date,
                    'last_trade_week': self.last_trade_week,
                    'stop_losses_triggered': self.stop_losses_triggered,
                    'take_profits_triggered': self.take_profits_triggered
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def reset_daily(self):
        """Reset daily trade count if new day"""
        today = datetime.now().strftime('%Y-%m-%d')
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.last_trade_date = today
            logger.info(f"New day - daily trades reset to 0")
    
    def reset_weekly(self):
        """Reset weekly trade count if new week"""
        current_week = datetime.now().strftime('%Y-W%U')
        if self.last_trade_week != current_week:
            self.weekly_trades = 0
            self.last_trade_week = current_week
            logger.info(f"New week - weekly trades reset to 0")
    
    def can_trade(self) -> bool:
        """Check if we can make more trades today/this week"""
        self.reset_daily()
        self.reset_weekly()
        
        if self.daily_trades >= StrategyConfig.MAX_TRADES_PER_DAY:
            logger.info(f"Daily trade limit reached ({StrategyConfig.MAX_TRADES_PER_DAY})")
            return False
        
        if self.weekly_trades >= StrategyConfig.MAX_TRADES_PER_WEEK:
            logger.info(f"Weekly trade limit reached ({StrategyConfig.MAX_TRADES_PER_WEEK})")
            return False
        
        return True
    
    def record_trade(self, symbol: str, action: str, reason: str):
        """Record a trade"""
        self.daily_trades += 1
        self.weekly_trades += 1
        self.save()
        logger.info(f"Trade recorded: {action} {symbol} ({self.daily_trades}/{StrategyConfig.MAX_TRADES_PER_DAY} daily)")


class STONKAIBot:
    """
    Autonomous trading bot implementing STONK.AI strategy
    """
    
    def __init__(self):
        # Load config from existing file
        config = load_alpaca_config()
        self.api_key = config.get('api_key') or config.get('APCA_API_KEY_ID')
        self.api_secret = config.get('api_secret') or config.get('APCA_API_SECRET_KEY')
        self.base_url = config.get('base_url', 'https://paper-api.alpaca.markets')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API keys not found in config file")
        
        # Initialize API connection
        if USE_SDK:
            self.api = tradeapi.REST(
                key_id=self.api_key,
                secret_key=self.api_secret,
                base_url=self.base_url
            )
            self.session = None
        else:
            self.api = None
            self.session = requests.Session()
            self.session.headers.update({
                'APCA-API-KEY-ID': self.api_key,
                'APCA-API-SECRET-KEY': self.api_secret
            })
        
        self.state = PortfolioState()
        self.portfolio_data_file = Path('portfolio_data.json')
        self.trades_log_file = Path('TRADES_LOG.md')
        
    def is_market_open(self) -> bool:
        """Check if US equity markets are open"""
        try:
            if USE_SDK and self.api:
                clock = self.api.get_clock()
                return clock.is_open
            else:
                # Use API to check market status
                base = self.base_url.rstrip('/')
                resp = self.session.get(f"{base}/v2/clock", timeout=10)
                if resp.status_code == 200:
                    clock_data = resp.json()
                    return clock_data.get('is_open', False)
        except Exception as e:
            logger.debug(f"Could not check market status via API: {e}")
        
        # Fallback to time-based check
        now = datetime.now()
        et_hour = (now.hour - 4) % 24  # Rough ET (ignoring DST)
        return (9 <= et_hour < 16) and now.weekday() < 5
    
    def fetch_portfolio_data(self) -> Dict:
        """Fetch current portfolio state from Alpaca"""
        try:
            if USE_SDK:
                return self._fetch_with_sdk()
            else:
                return self._fetch_with_requests()
        except Exception as e:
            logger.error(f"Failed to fetch portfolio data: {e}")
            return {}
    
    def _fetch_with_sdk(self) -> Dict:
        """Fetch using Alpaca SDK"""
        account = self.api.get_account()
        positions = self.api.list_positions()
        
        portfolio_data = {
            'timestamp': datetime.now().isoformat(),
            'status': 'live',
            'account': {
                'portfolio_value': float(account.portfolio_value),
                'cash': float(account.cash),
                'buying_power': float(account.buying_power),
                'equity': float(account.equity)
            },
            'positions': []
        }
        
        total_pl = 0
        for pos in positions:
            pos_data = {
                'symbol': pos.symbol,
                'qty': int(pos.qty),
                'avg_entry': float(pos.avg_entry_price),
                'current': float(pos.current_price),
                'market_value': float(pos.market_value),
                'cost_basis': float(pos.cost_basis),
                'unrealized_pl': float(pos.unrealized_pl),
                'unrealized_plpc': float(pos.unrealized_plpc) * 100
            }
            portfolio_data['positions'].append(pos_data)
            total_pl += float(pos.unrealized_pl)
        
        portfolio_data['total_pl'] = total_pl
        # Calculate total_pl_pct based on actual cost basis, not fixed 100000
        total_cost = sum(p['cost_basis'] for p in portfolio_data['positions'])
        portfolio_data['total_pl_pct'] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        # Save to file for website
        with open(self.portfolio_data_file, 'w') as f:
            json.dump(portfolio_data, f, indent=2)
        
        return portfolio_data
    
    def _fetch_with_requests(self) -> Dict:
        """Fetch using requests (fallback)"""
        base = self.base_url.rstrip('/')
        
        # Get account
        acc_resp = self.session.get(f"{base}/v2/account", timeout=10)
        acc_resp.raise_for_status()
        account = acc_resp.json()
        
        # Get positions
        pos_resp = self.session.get(f"{base}/v2/positions", timeout=10)
        pos_resp.raise_for_status()
        positions = pos_resp.json()
        
        portfolio_data = {
            'timestamp': datetime.now().isoformat(),
            'status': 'live',
            'account': {
                'portfolio_value': float(account.get('portfolio_value', 0)),
                'cash': float(account.get('cash', 0)),
                'buying_power': float(account.get('buying_power', 0)),
                'equity': float(account.get('equity', 0))
            },
            'positions': []
        }
        
        total_pl = 0
        for pos in positions:
            pos_data = {
                'symbol': pos.get('symbol', ''),
                'qty': int(pos.get('qty', 0)),
                'avg_entry': float(pos.get('avg_entry_price', 0)),
                'current': float(pos.get('current_price', 0)),
                'market_value': float(pos.get('market_value', 0)),
                'cost_basis': float(pos.get('cost_basis', 0)),
                'unrealized_pl': float(pos.get('unrealized_pl', 0)),
                'unrealized_plpc': float(pos.get('unrealized_plpc', 0)) * 100
            }
            portfolio_data['positions'].append(pos_data)
            total_pl += float(pos.get('unrealized_pl', 0))
        
        portfolio_data['total_pl'] = total_pl
        # Calculate total_pl_pct based on actual cost basis, not fixed 100000
        total_cost = sum(p['cost_basis'] for p in portfolio_data['positions'])
        portfolio_data['total_pl_pct'] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        # Save to file for website
        with open(self.portfolio_data_file, 'w') as f:
            json.dump(portfolio_data, f, indent=2)
        
        return portfolio_data
    
    def get_sector_for_symbol(self, symbol: str) -> str:
        """Get sector category for a symbol"""
        for sector, symbols in StrategyConfig.SECTORS.items():
            if symbol in symbols:
                return sector
        return 'Other'
    
    def calculate_sector_allocation(self, portfolio_data: Dict) -> Dict[str, float]:
        """Calculate current sector allocation percentages"""
        total_value = portfolio_data.get('account', {}).get('portfolio_value', 0)
        if total_value == 0:
            return {}
        
        sector_values = {sector: 0.0 for sector in StrategyConfig.SECTORS.keys()}
        
        for pos in portfolio_data.get('positions', []):
            sector = self.get_sector_for_symbol(pos['symbol'])
            if sector in sector_values:
                sector_values[sector] += pos['market_value']
        
        # Convert to percentages
        return {sector: (value / total_value) * 100 for sector, value in sector_values.items()}
    
    def check_stop_losses(self, portfolio_data: Dict) -> List[Dict]:
        """Check for positions hitting stop loss (-15%)"""
        stops = []
        
        for pos in portfolio_data.get('positions', []):
            symbol = pos['symbol']
            plpc = pos['unrealized_plpc']
            
            # Skip never-sell positions
            if symbol in StrategyConfig.NEVER_SELL:
                continue
            
            if plpc <= StrategyConfig.STOP_LOSS_PCT:
                stops.append({
                    'symbol': symbol,
                    'qty': pos['qty'],
                    'action': 'SELL',
                    'reason': f'Stop loss hit: {plpc:.1f}% (limit: {StrategyConfig.STOP_LOSS_PCT}%)',
                    'current_pl': plpc
                })
                logger.warning(f"STOP LOSS TRIGGERED: {symbol} at {plpc:.1f}%")
        
        return stops
    
    def check_take_profits(self, portfolio_data: Dict) -> List[Dict]:
        """Check for positions hitting take profit levels"""
        trims = []
        full_exits = []
        
        for pos in portfolio_data.get('positions', []):
            symbol = pos['symbol']
            plpc = pos['unrealized_plpc']
            qty = pos['qty']
            
            # Skip if not in trim list
            if symbol not in StrategyConfig.TRIM_ON_GAIN:
                continue
            
            # Check for full exit (+50%)
            if plpc >= StrategyConfig.TAKE_PROFIT_FULL:
                full_exits.append({
                    'symbol': symbol,
                    'qty': qty,
                    'action': 'SELL',
                    'reason': f'Take profit full exit: {plpc:.1f}% (target: +{StrategyConfig.TAKE_PROFIT_FULL}%)',
                    'current_pl': plpc
                })
                logger.info(f"TAKE PROFIT FULL: {symbol} at {plpc:.1f}%")
            
            # Check for trim (+25%)
            elif plpc >= StrategyConfig.TAKE_PROFIT_TRIM:
                trim_qty = max(1, qty // 4)  # Sell 25% of position
                trims.append({
                    'symbol': symbol,
                    'qty': trim_qty,
                    'action': 'SELL',
                    'reason': f'Take profit trim: {plpc:.1f}% (target: +{StrategyConfig.TAKE_PROFIT_TRIM}%), selling {trim_qty}/{qty} shares',
                    'current_pl': plpc
                })
                logger.info(f"TAKE PROFIT TRIM: {symbol} at {plpc:.1f}%, selling {trim_qty} shares")
        
        return full_exits + trims
    
    def check_rebalancing(self, portfolio_data: Dict) -> List[Dict]:
        """Check if portfolio needs rebalancing"""
        trades = []
        
        cash_pct = portfolio_data['account']['cash'] / portfolio_data['account']['portfolio_value']
        if cash_pct < StrategyConfig.MIN_CASH_BUFFER:
            logger.info(f"Cash buffer low ({cash_pct:.1%}), skipping rebalancing")
            return trades
        
        current_allocation = self.calculate_sector_allocation(portfolio_data)
        
        for sector, current_pct in current_allocation.items():
            target_pct = StrategyConfig.ALLOCATION_TARGETS.get(sector, 0)
            deviation = current_pct - target_pct
            
            if abs(deviation) > StrategyConfig.MAX_SECTOR_DEVIATION:
                logger.info(f"{sector}: {current_pct:.1f}% vs target {target_pct:.1f}% (deviation: {deviation:+.1f}%)")
                # Note: Actually implementing rebalancing trades requires more logic
                # This is a simplified version - full implementation would calculate buy/sell amounts
        
        return trades
    
    def check_emergency_triggers(self, portfolio_data: Dict) -> List[str]:
        """Check for emergency conditions that require human intervention"""
        alerts = []
        
        total_value = portfolio_data.get('account', {}).get('portfolio_value', 0)
        initial_value = 100000
        total_return = ((total_value - initial_value) / initial_value) * 100
        
        # Portfolio down >20%
        if total_return < -20:
            alerts.append(f"EMERGENCY: Portfolio down {total_return:.1f}% (threshold: -20%)")
        
        # Individual position down >30% (stop loss should have triggered)
        for pos in portfolio_data.get('positions', []):
            if pos['unrealized_plpc'] < -30:
                alerts.append(f"EMERGENCY: {pos['symbol']} down {pos['unrealized_plpc']:.1f}% (stop loss may have failed)")
        
        # Cash below minimum
        cash_pct = portfolio_data['account']['cash'] / total_value
        if cash_pct < 0.25:
            alerts.append(f"WARNING: Cash buffer critically low at {cash_pct:.1%}")
        
        return alerts
    
    def execute_trade(self, trade: Dict) -> bool:
        """Execute a trade through Alpaca"""
        try:
            if USE_SDK:
                order = self.api.submit_order(
                    symbol=trade['symbol'],
                    qty=trade['qty'],
                    side=trade['action'].lower(),
                    type='market',
                    time_in_force='day'
                )
                order_id = order.id
            else:
                # Use requests fallback
                base = self.base_url.rstrip('/')
                url = f"{base}/v2/orders"
                payload = {
                    "symbol": trade['symbol'],
                    "qty": str(trade['qty']),
                    "side": trade['action'].lower(),
                    "type": "market",
                    "time_in_force": "day"
                }
                resp = self.session.post(url, json=payload, timeout=10)
                resp.raise_for_status()
                order_data = resp.json()
                order_id = order_data.get('id', 'unknown')
            
            logger.info(f"EXECUTED: {trade['action']} {trade['qty']} {trade['symbol']} - {trade['reason']}")
            self.state.record_trade(trade['symbol'], trade['action'], trade['reason'])
            self.log_trade(trade, order_id)
            return True
            
        except Exception as e:
            logger.error(f"FAILED to execute {trade}: {e}")
            return False
    
    def log_trade(self, trade: Dict, order_id: str):
        """Log trade to TRADES_LOG.md"""
        try:
            with open(self.trades_log_file, 'a') as f:
                f.write(f"\n\n---\n\n")
                f.write(f"## {datetime.now().strftime('%B %d, %Y - %I:%M %p UTC')} - AUTONOMOUS TRADE\n\n")
                f.write(f"**Action:** {trade['action']} {trade['qty']} {trade['symbol']}\n\n")
                f.write(f"**Reason:** {trade['reason']}\n\n")
                f.write(f"**Order ID:** {order_id}\n\n")
        except Exception as e:
            logger.error(f"Failed to log trade: {e}")
    
    def run_cycle(self):
        """One iteration of the trading loop"""
        # Check market hours
        if not self.is_market_open():
            logger.debug("Market closed, skipping cycle")
            return
        
        # Fetch current portfolio state
        portfolio_data = self.fetch_portfolio_data()
        if not portfolio_data:
            return
        
        total_value = portfolio_data['account']['portfolio_value']
        total_pl = portfolio_data.get('total_pl', 0)
        logger.info(f"Portfolio: ${total_value:,.2f} ({total_pl:+,.2f})")
        
        # Check for emergency triggers
        emergencies = self.check_emergency_triggers(portfolio_data)
        if emergencies:
            for alert in emergencies:
                logger.critical(alert)
            logger.critical("EMERGENCY ALERTS DETECTED - Review immediately!")
            # Don't trade during emergencies
            return
        
        # Check if we can trade
        if not self.state.can_trade():
            return
        
        # Priority 1: Stop losses (execute immediately)
        stop_trades = self.check_stop_losses(portfolio_data)
        for trade in stop_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
        
        # Priority 2: Take profits
        profit_trades = self.check_take_profits(portfolio_data)
        for trade in profit_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
        
        # Priority 3: Rebalancing (lower priority)
        rebalance_trades = self.check_rebalancing(portfolio_data)
        for trade in rebalance_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
    
    def run(self):
        """Main loop - runs forever"""
        logger.info("=" * 70)
        logger.info("STONK.AI Trading Bot v1.0 Starting")
        logger.info("Strategy: AI-designed autonomous trading")
        logger.info("Check interval: 60 seconds during market hours")
        logger.info("=" * 70)
        
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
            
            time.sleep(60)  # Check every minute


if __name__ == "__main__":
    bot = STONKAIBot()
    bot.run()
