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

# Import trade logger
from trade_logger import trade_logger, TradeEvent
from signal_tracker import log_buy_signal, update_signal_performance

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
ALPACA_CONFIG_FILE = Path(__file__).parent / "alpaca_config.json"

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
    
    # THE COUNCIL'S AGGRESSIVE STRATEGY - MAX ALPHA
    MAX_POSITION_SIZE = 0.25  # Max 25% in top conviction plays (more concentrated)
    STOP_LOSS_PCT = -10.0  # -10% stop loss (cut losers faster)
    TAKE_PROFIT_TRIM = 15.0  # Trim at +15% (take gains quicker, compound faster)
    TAKE_PROFIT_FULL = 30.0  # Full exit at +30% (lock in profits)
    MAX_SECTOR_DEVIATION = 20.0  # Allow more concentration in winners
    MIN_CASH_ABSOLUTE = 500  # Keep $500 cash minimum (NO MARGIN), deploy rest
    
    # NO WHITELIST - Bot buys ANY watchlist signal
    # Removed: ALLOWED_RSI_SYMBOLS whitelist
    # Now uses full dynamic watchlist from watchlist_changes.json
    
    # Keep these for rebalancing decisions
    CORE_POSITIONS = ['PLTR', 'AMD', 'CRWD', 'HOOD', 'AAPL', 'NVDA']
    SELL_LIST = ['MSFT', 'SOFI', 'SCHD', 'SGOV']
    
    # AGGRESSIVE target allocations - Higher conviction weights
    TARGET_ALLOCATIONS = {
        'AMD': 0.25,   # 25% - Highest conviction (max position)
        'PLTR': 0.15,  # 15% - AI/Conviction play
        'NVDA': 0.12,  # 12% - AI chip leader
        'CRWD': 0.10,  # 10% - Cybersecurity
        'HOOD': 0.08,  # 8% - Crypto/fintech
        'AAPL': 0.08,  # 8% - Reduced safety anchor
        'GOOGL': 0.05, # 5% - Search/AI
    }
    
    # Trading Limits - UNLIMITED (The Council has full autonomy)
    MAX_TRADES_PER_DAY = 999  # Unlimited daily trades
    MAX_TRADES_PER_WEEK = 9999  # Unlimited weekly trades
    REBALANCE_THRESHOLD = 0.03
    
    # Only buy Core positions
    RSI_ENTRY_ENABLED = True  # ENABLED: Aggressive dip buying
    RSI_ENTRY_THRESHOLD = 35.0  # Buy earlier (RSI < 35 instead of 30)
    RSI_ENTRY_POSITION_SIZE = 0.10  # 10% per dip buy (more aggressive sizing)
    MAX_RSI_POSITIONS_PER_DAY = 2  # Allow 2 dip buys per day
    # Dynamic watchlist - loaded from watchlist_changes.json
    # Falls back to core positions if watchlist unavailable
    @classmethod
    def get_allowed_symbols(cls):
        """Load symbols from watchlist rotation"""
        try:
            with open('/var/www/hedge-fund-website/watchlist_changes.json', 'r') as f:
                data = json.load(f)
                symbols = data.get('new_watchlist', [])
                if len(symbols) >= 8:
                    return symbols
        except Exception as e:
            logger.debug(f"Could not load watchlist: {e}")
        # Fallback to core positions
        return ['PLTR', 'AMD', 'CRWD', 'HOOD', 'NVDA', 'GOOGL', 'TQQQ', 'SQQQ']
    
    ALLOWED_RSI_SYMBOLS = None  # Deprecated - use get_allowed_symbols() instead
    VOLUME_MULTIPLIER = 1.5  # 1.5x average volume for entry confirmation
    
    # ENABLE momentum trading for alpha generation
    DIP_BUY_ENABLED = True
    MOMENTUM_ENABLED = True
    MOMENTUM_POSITION_SIZE = 0.08  # 8% for momentum plays
    MOMENTUM_THRESHOLD = 5.0  # Buy on +5% momentum days
    SPECULATIVE_ENABLED = False
    
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


def is_market_open():
    """Check if US stock market is currently open (NYSE/NASDAQ schedule)"""
    now = datetime.now()
    
    # Check if weekend
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Check US market holidays for 2026
    market_holidays_2026 = [
        (1, 1),   # New Year's Day
        (1, 19),  # Martin Luther King Jr. Day
        (2, 16),  # Presidents' Day
        (4, 3),   # Good Friday
        (5, 25),  # Memorial Day
        (6, 19),  # Juneteenth
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
    
    return True


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

    def load_dynamic_watchlist(self) -> List[str]:
        """Load watchlist from dynamic rotation file"""
        try:
            with open('/var/www/hedge-fund-website/watchlist_changes.json', 'r') as f:
                data = json.load(f)
                symbols = data.get('new_watchlist', [])
                if len(symbols) >= 8:
                    logger.debug(f"Loaded {len(symbols)} symbols from dynamic watchlist")
                    return symbols
        except Exception as e:
            logger.debug(f"Could not load dynamic watchlist: {e}")
        
        # Fallback to static list
        fallback = ['DKNG', 'COIN', 'UPST', 'ROKU', 'ABNB', 'SHOP', 'SQ', 'RIVN', 'NET', 'SNOW']
        logger.debug(f"Using fallback watchlist: {len(fallback)} symbols")
        return fallback
    
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
        # Calculate total_pl_pct based on actual cost basis
        total_cost = sum(p['cost_basis'] for p in portfolio_data['positions'])
        portfolio_data['total_pl_pct'] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        # Save to file for website
        with open(self.portfolio_data_file, 'w') as f:
            json.dump(portfolio_data, f, indent=2)
        
        # Also save to web directory for live display
        web_file = Path('/var/www/hedge-fund-website/portfolio_data.json')
        try:
            web_file.parent.mkdir(parents=True, exist_ok=True)
            with open(web_file, 'w') as f:
                json.dump(portfolio_data, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not write to web file: {e}")
        
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
        # Calculate total_pl_pct based on actual cost basis
        total_cost = sum(p['cost_basis'] for p in portfolio_data['positions'])
        portfolio_data['total_pl_pct'] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        # Save to file for website
        with open(self.portfolio_data_file, 'w') as f:
            json.dump(portfolio_data, f, indent=2)
        
        # Also save to web directory for live display
        web_file = Path('/var/www/hedge-fund-website/portfolio_data.json')
        try:
            web_file.parent.mkdir(parents=True, exist_ok=True)
            with open(web_file, 'w') as f:
                json.dump(portfolio_data, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not write to web file: {e}")
        
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
        if cash_pct < 0.30:  # Need 30% cash for rebalancing
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
    
    def check_council_rebalancing(self, portfolio_data: Dict) -> List[Dict]:
        """Execute The Council's Compromise Plan:
        1. Sell MSFT, SOFI, SCHD, SGOV (Jones + Paulson)
        2. Add to PLTR, AMD, CRWD, HOOD (Wood)
        3. Maintain 50% cash target
        """
        trades = []
        
        positions = {p['symbol']: p for p in portfolio_data.get('positions', [])}
        cash = portfolio_data['account']['cash']
        portfolio_value = portfolio_data['account']['portfolio_value']
        
        # PHASE 1: Sell Tier 3 positions (Jones + Paulson)
        for symbol in StrategyConfig.SELL_LIST:
            if symbol in positions:
                pos = positions[symbol]
                trades.append({
                    'symbol': symbol,
                    'qty': pos['qty'],
                    'action': 'SELL',
                    'reason': f"Council Plan: Sell {symbol} (Tier 3) to raise cash and concentrate in Core 6",
                    'current_pl': pos['unrealized_plpc']
                })
                logger.info(f"COUNCIL PLAN: Selling {symbol} - {pos['unrealized_plpc']:+.1f}%")
        
        # PHASE 2: Build Core positions (Wood)
        # Only buy if we have plenty of cash (target 50%)
        cash_pct = cash / portfolio_value
        
        if cash_pct > 0.50 and trades:  # Only buy after selling
            # Calculate freed cash from sells
            freed_cash = sum(positions[s]['market_value'] for s in StrategyConfig.SELL_LIST if s in positions)
            available_for_core = freed_cash * 0.70  # Use 70% of freed cash for core
            
            # Priority: AMD > PLTR > CRWD > HOOD
            core_priority = ['AMD', 'PLTR', 'CRWD', 'HOOD']
            
            for symbol in core_priority:
                if symbol in positions:
                    pos = positions[symbol]
                    current_value = pos['market_value']
                    target_value = portfolio_value * StrategyConfig.TARGET_ALLOCATIONS.get(symbol, 0.05)
                    
                    if current_value < target_value * 0.8:  # If below 80% of target
                        add_value = min(target_value - current_value, available_for_core / len(core_priority))
                        if add_value > 1000:  # Minimum $1K trade
                            qty = int(add_value / pos['current'])
                            if qty > 0:
                                trades.append({
                                    'symbol': symbol,
                                    'qty': qty,
                                    'action': 'BUY',
                                    'reason': f"Council Plan: Add to {symbol} Core position (Wood conviction)",
                                    'target_pct': StrategyConfig.TARGET_ALLOCATIONS.get(symbol, 0.05) * 100
                                })
                                logger.info(f"COUNCIL PLAN: Adding to {symbol} - target {StrategyConfig.TARGET_ALLOCATIONS.get(symbol, 0.05)*100:.0f}%")
        
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
        
        # Cash/Margin check - handle margin accounts properly
        cash = portfolio_data['account']['cash']
        buying_power = portfolio_data['account'].get('buying_power', cash)
        
        # For margin accounts: negative cash is OK if buying power is sufficient
        # Only alert if buying power is critically low (< 25% of portfolio)
        buying_power_pct = buying_power / total_value if total_value > 0 else 0
        
        if cash < 0:
            # Margin account - check buying power instead
            if buying_power_pct < 0.25:
                alerts.append(f"WARNING: Buying power low at {buying_power_pct:.1%} (margin: ${abs(cash):,.2f})")
            else:
                # Info only - not an emergency
                logger.info(f"Margin usage: ${abs(cash):,.2f} (buying power: {buying_power_pct:.1%})")
        else:
            # Cash account - check absolute minimum (NO MARGIN)
            if cash < StrategyConfig.MIN_CASH_ABSOLUTE:
                alerts.append(f"WARNING: Cash buffer low at ${cash:,.2f} (need ${StrategyConfig.MIN_CASH_ABSOLUTE} minimum)")
        
        return alerts
    
    def execute_trade(self, trade: Dict) -> bool:
        """Execute a trade through Alpaca - NEVER use margin"""
        try:
            # Check cash before buying (NO MARGIN)
            if trade['action'] == 'BUY':
                try:
                    account = self.api.get_account() if USE_SDK else None
                    if account:
                        cash = float(account.cash)
                        price = self.get_current_price(trade['symbol'])
                        cost = trade['qty'] * price
                        if cost > cash:
                            logger.error(f"INSUFFICIENT CASH: Need ${cost:.2f}, have ${cash:.2f} - NO MARGIN USED")
                            return False
                except Exception as e:
                    logger.warning(f"Could not verify cash before trade: {e}")
            
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
            
            # Log RSI entry signal for accuracy tracking
            if 'RSI' in trade.get('reason', '').upper() and trade['action'] == 'BUY':
                try:
                    price = self.get_current_price(trade['symbol'])
                    rsi = trade.get('rsi', 35.0)
                    log_buy_signal(trade['symbol'], price, rsi)
                except Exception as e:
                    logger.debug(f"Could not log signal: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"FAILED to execute {trade}: {e}")
            return False
    
    def log_trade(self, trade: Dict, order_id: str):
        """Log trade to TRADES_LOG.md and JSON for website"""
        try:
            # Log to markdown
            with open(self.trades_log_file, 'a') as f:
                f.write(f"\n\n---\n\n")
                f.write(f"## {datetime.now().strftime('%B %d, %Y - %I:%M %p UTC')} - AUTONOMOUS TRADE\n\n")
                f.write(f"**Action:** {trade['action']} {trade['qty']} {trade['symbol']}\n\n")
                f.write(f"**Reason:** {trade['reason']}\n\n")
                f.write(f"**Order ID:** {order_id}\n\n")
            
            # Log to JSON for website trade log
            try:
                from trade_logger import trade_logger
                
                # Get current price from Alpaca
                price = 0
                try:
                    if USE_SDK and self.api:
                        quote = self.api.get_latest_quote(trade['symbol'])
                        price = quote.ap if quote.ap > 0 else quote.bp
                    else:
                        base = self.base_url.rstrip('/').replace('paper-api', 'data')
                        resp = self.session.get(f"{base}/v2/stocks/quotes/latest?symbols={trade['symbol']}", timeout=10)
                        if resp.status_code == 200:
                            quote = resp.json().get('quotes', {}).get(trade['symbol'], {})
                            price = quote.get('ap', 0) or quote.get('bp', 0)
                except Exception as e:
                    logger.debug(f"Could not get price for trade log: {e}")
                    price = trade.get('price', 0)
                
                # Determine strategy from reason
                strategy = 'Manual'
                if 'stop loss' in trade['reason'].lower():
                    strategy = 'Stop Loss'
                elif 'profit' in trade['reason'].lower() or 'trim' in trade['reason'].lower():
                    strategy = 'Profit Take'
                elif 'rebalance' in trade['reason'].lower():
                    strategy = 'Rebalance'
                elif 'RSI' in trade['reason'].upper():
                    strategy = 'RSI Signal'
                
                trade_logger.log_trade(
                    symbol=trade['symbol'],
                    action=trade['action'],
                    qty=trade['qty'],
                    price=price,
                    strategy=strategy,
                    rationale=trade['reason'],
                    pnl_impact=trade.get('pnl_impact'),
                    pnl_pct=trade.get('pnl_pct')
                )
                logger.info(f"Trade logged to JSON for website: {trade['symbol']} {trade['action']}")
            except Exception as e:
                logger.error(f"Failed to log trade to JSON: {e}")
                
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
        
        # Priority 0: THE COUNCIL'S COMPROMISE PLAN
        # Execute Jones + Paulson + Soros + Wood unified strategy
        council_trades = self.check_council_rebalancing(portfolio_data)
        for trade in council_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
        
        # Priority 1: COUNCIL WATCHLIST MODE
        # Auto-buy when Council targets hit
        council_watchlist_trades = self.check_council_watchlist(portfolio_data)
        for trade in council_watchlist_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
                logger.info(f"🦁 COUNCIL WATCHLIST TRADE: {trade['symbol']} - {trade.get('council', 'UNKNOWN')}")
        
        # Priority 2: Take profits
        profit_trades = self.check_take_profits(portfolio_data)
        for trade in profit_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
        
        # Priority 3: Standard rebalancing
        rebalance_trades = self.check_rebalancing(portfolio_data)
        for trade in rebalance_trades:
            if self.state.can_trade():
                self.execute_trade(trade)
        
        # Priority 4: RSI Auto-Entry (Core positions only)
        if StrategyConfig.RSI_ENTRY_ENABLED:
            entry_trades = self.check_rsi_entries(portfolio_data)
            for trade in entry_trades:
                if self.state.can_trade():
                    self.execute_trade(trade)
        
        # Priority 5-7: DISABLED per Council recommendation
        # No dip buys, no momentum, no speculative
        if StrategyConfig.DIP_BUY_ENABLED:
            pass  # Disabled
        if StrategyConfig.MOMENTUM_ENABLED:
            pass  # Disabled
        if StrategyConfig.SPECULATIVE_ENABLED:
            pass  # Disabled
    
    def check_rsi_entries(self, portfolio_data: Dict) -> List[Dict]:
        """Check for RSI-based entry signals - buy oversold stocks"""
        entries = []
        
        # Get watchlist stocks from dynamic rotation
        watchlist_symbols = self.state.load_dynamic_watchlist()
        
        # Get current positions
        current_positions = {pos['symbol'] for pos in portfolio_data.get('positions', [])}
        
        # Check cash available - NEVER use margin
        cash = portfolio_data['account']['cash']
        portfolio_value = portfolio_data['account']['portfolio_value']
        
        # Keep minimum $500 cash buffer for fees/safety, never use margin
        MIN_CASH_BUFFER = 500
        
        # Only enter if we have enough cash (NO MARGIN)
        available_cash = cash - MIN_CASH_BUFFER
        if available_cash < 100:  # Need at least $100 for a trade
            logger.debug(f"Insufficient cash: ${cash:.2f} (keeping ${MIN_CASH_BUFFER} buffer)")
            return entries
        
        for symbol in watchlist_symbols:
            # Skip if already holding
            if symbol in current_positions:
                continue
            
            # Get RSI and volume data
            try:
                rsi = self.fetch_rsi_for_symbol(symbol)
                volume_data = self.fetch_volume_for_symbol(symbol)
                
                if rsi and rsi <= StrategyConfig.RSI_ENTRY_THRESHOLD:
                    # Check volume confirmation (1.5x average)
                    volume_ok = True
                    if volume_data:
                        current_vol = volume_data.get('current', 0)
                        avg_vol = volume_data.get('average', 0)
                        if avg_vol > 0:
                            vol_ratio = current_vol / avg_vol
                            volume_ok = vol_ratio >= StrategyConfig.VOLUME_MULTIPLIER
                            if not volume_ok:
                                logger.debug(f"{symbol}: Volume {vol_ratio:.1f}x below {StrategyConfig.VOLUME_MULTIPLIER}x threshold")
                    
                    if volume_ok:
                        # Calculate position size based on AVAILABLE CASH (NO MARGIN)
                        position_value = min(available_cash * 0.5, portfolio_value * StrategyConfig.RSI_ENTRY_POSITION_SIZE)
                        price = self.get_current_price(symbol)
                        qty = max(1, int(position_value / price))
                        
                        # Double check we have enough cash (NO MARGIN)
                        trade_cost = qty * price
                        if trade_cost > available_cash:
                            qty = int(available_cash / price)
                            if qty < 1:
                                logger.debug(f"{symbol}: Insufficient cash for even 1 share")
                                continue
                        
                        entries.append({
                            'symbol': symbol,
                            'qty': qty,
                            'action': 'BUY',
                            'reason': f'RSI Auto-Entry: RSI {rsi:.1f} (below {StrategyConfig.RSI_ENTRY_THRESHOLD}) with volume confirmation [CASH ONLY]',
                            'rsi': rsi
                        })
                        logger.info(f"RSI ENTRY SIGNAL: {symbol} at RSI {rsi:.1f} (qty: {qty}, cash: ${available_cash:.2f})")
            except Exception as e:
                logger.debug(f"Could not check RSI for {symbol}: {e}")
        
        return entries
    
    def fetch_rsi_for_symbol(self, symbol: str) -> Optional[float]:
        """Fetch RSI for a symbol - uses Yahoo Finance (free) as primary source"""
        try:
            import requests
            import time
            
            # Use Yahoo Finance for free historical data
            end = int(time.time())
            start = end - (30 * 24 * 60 * 60)  # 30 days
            
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            params = {
                'period1': start,
                'period2': end,
                'interval': '1d',
                'events': 'history'
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://finance.yahoo.com/',
            }
            
            # Retry logic with exponential backoff
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    resp = requests.get(url, params=params, headers=headers, timeout=10)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        result = data.get('chart', {}).get('result', [{}])[0]
                        closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', [])
                        
                        # Filter out None values
                        valid_closes = [c for c in closes if c is not None]
                        
                        if len(valid_closes) >= 15:
                            # Calculate RSI
                            gains = []
                            losses = []
                            
                            for i in range(1, len(valid_closes)):
                                change = valid_closes[i] - valid_closes[i-1]
                                if change > 0:
                                    gains.append(change)
                                    losses.append(0)
                                else:
                                    gains.append(0)
                                    losses.append(abs(change))
                            
                            # Use last 14 periods
                            avg_gain = sum(gains[-14:]) / 14
                            avg_loss = sum(losses[-14:]) / 14
                            
                            if avg_loss == 0:
                                return 100.0
                            
                            rs = avg_gain / avg_loss
                            rsi = 100 - (100 / (1 + rs))
                            
                            logger.debug(f"Yahoo RSI for {symbol}: {rsi:.1f}")
                            return rsi
                        
                        logger.debug(f"Could not get RSI for {symbol} from Yahoo - insufficient data")
                        return None
                    elif resp.status_code == 429:
                        # Rate limited - wait and retry
                        wait_time = (attempt + 1) * 2
                        logger.debug(f"Yahoo rate limit for {symbol}, waiting {wait_time}s")
                        time.sleep(wait_time)
                    else:
                        logger.debug(f"Yahoo error {resp.status_code} for {symbol}")
                        return None
                        
                except Exception as e:
                    logger.debug(f"Yahoo attempt {attempt+1} failed for {symbol}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
            
            return None
        except Exception as e:
            logger.debug(f"Could not fetch RSI for {symbol}: {e}")
            return None
    
    def fetch_volume_for_symbol(self, symbol: str) -> Optional[Dict]:
        """Fetch current and average volume for a symbol"""
        try:
            import requests
            import time
            
            # Use Yahoo Finance for volume data
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            params = {
                'range': '1mo',
                'interval': '1d'
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                result = data.get('chart', {}).get('result', [{}])[0]
                volumes = result.get('indicators', {}).get('quote', [{}])[0].get('volume', [])
                
                # Filter out None values
                valid_volumes = [v for v in volumes if v is not None]
                
                if len(valid_volumes) >= 10:
                    current_vol = valid_volumes[-1]  # Most recent
                    avg_vol = sum(valid_volumes[:-1]) / len(valid_volumes[:-1])  # Average of previous days
                    
                    return {
                        'current': current_vol,
                        'average': avg_vol
                    }
            return None
        except Exception as e:
            logger.debug(f"Could not fetch volume for {symbol}: {e}")
            return None
    
    def check_dip_buys(self, portfolio_data: Dict) -> List[Dict]:
        """Check for dip buying opportunities - buy stocks down >3% today"""
        entries = []
        
        if not StrategyConfig.DIP_BUY_ENABLED:
            return entries
        
        # Watchlist to monitor for dips
        watchlist = ['DKNG', 'COIN', 'UPST', 'ROKU', 'ABNB', 'SHOP', 'SQ', 'RIVN', 'NET', 'SNOW']
        current_positions = {pos['symbol'] for pos in portfolio_data.get('positions', [])}
        
        cash = portfolio_data['account']['cash']
        portfolio_value = portfolio_data['account']['portfolio_value']
        
        # Check cash available (NO MARGIN)
        available_cash = cash - StrategyConfig.MIN_CASH_ABSOLUTE
        if available_cash < 100:
            logger.debug(f"Insufficient cash for dip entries: ${cash:.2f} (keeping ${StrategyConfig.MIN_CASH_ABSOLUTE} buffer)")
            return entries
        
        for symbol in watchlist:
            if symbol in current_positions:
                continue
            
            try:
                # Get today's change
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest
                
                creds = load_alpaca_config()
                client = StockHistoricalDataClient(creds['api_key'], creds['api_secret'])
                
                # Get latest quote
                quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quotes = client.get_stock_latest_quote(quote_request)
                
                if symbol in quotes.data:
                    current_price = quotes.data[symbol].ask_price
                    
                    # Get yesterday's close
                    from alpaca.data.requests import StockBarsRequest
                    from alpaca.data.timeframe import TimeFrame
                    
                    bars_request = StockBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=TimeFrame.Day,
                        limit=2
                    )
                    bars = client.get_stock_bars(bars_request)
                    
                    if symbol in bars.data and len(bars.data[symbol]) >= 2:
                        prev_close = bars.data[symbol][-2].close
                        change_pct = ((current_price - prev_close) / prev_close) * 100
                        
                        if change_pct <= StrategyConfig.DIP_BUY_THRESHOLD:
                            position_value = portfolio_value * StrategyConfig.DIP_BUY_POSITION_SIZE
                            qty = max(1, int(position_value / current_price))
                            
                            entries.append({
                                'symbol': symbol,
                                'qty': qty,
                                'action': 'BUY',
                                'reason': f'Dip Buy: Down {change_pct:.1f}% today',
                                'price': current_price
                            })
                            logger.info(f"DIP BUY SIGNAL: {symbol} down {change_pct:.1f}%")
            except Exception as e:
                logger.debug(f"Could not check dip for {symbol}: {e}")
        
        return entries
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol"""
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestQuoteRequest
            
            creds = load_alpaca_config()
            client = StockHistoricalDataClient(creds['api_key'], creds['api_secret'])
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = client.get_stock_latest_quote(request)
            
            if symbol in quotes.data:
                return quotes.data[symbol].ask_price
            return 100.0
        except:
            return 100.0
    
    def check_momentum_entries(self, portfolio_data: Dict) -> List[Dict]:
        """Check for momentum stocks - buy breakouts up >2% today"""
        entries = []
        
        if not StrategyConfig.MOMENTUM_ENABLED:
            return entries
        
        # Watchlist for momentum
        watchlist = ['DKNG', 'COIN', 'UPST', 'ROKU', 'ABNB', 'SHOP', 'SQ', 'RIVN', 'NET', 'SNOW',
                     'GME', 'AMC', 'LCID', 'FSR', 'SPCE', 'ARKK']
        current_positions = {pos['symbol'] for pos in portfolio_data.get('positions', [])}
        
        cash = portfolio_data['account']['cash']
        portfolio_value = portfolio_data['account']['portfolio_value']
        
        # Check cash available (NO MARGIN)
        available_cash = cash - StrategyConfig.MIN_CASH_ABSOLUTE
        if available_cash < 100:
            logger.debug(f"Insufficient cash for momentum entries: ${cash:.2f} (keeping ${StrategyConfig.MIN_CASH_ABSOLUTE} buffer)")
            return entries
        
        for symbol in watchlist:
            if symbol in current_positions:
                continue
            
            try:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
                from alpaca.data.timeframe import TimeFrame
                
                client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
                
                # Get latest quote
                quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quotes = client.get_stock_latest_quote(quote_request)
                
                if symbol in quotes.data:
                    current_price = quotes.data[symbol].ask_price
                    
                    # Get yesterday's close
                    bars_request = StockBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=TimeFrame.Day,
                        limit=2
                    )
                    bars = client.get_stock_bars(bars_request)
                    
                    if symbol in bars.data and len(bars.data[symbol]) >= 2:
                        prev_close = bars.data[symbol][-2].close
                        change_pct = ((current_price - prev_close) / prev_close) * 100
                        
                        if change_pct >= StrategyConfig.MOMENTUM_THRESHOLD:
                            position_value = portfolio_value * StrategyConfig.MOMENTUM_POSITION_SIZE
                            qty = max(1, int(position_value / current_price))
                            
                            entries.append({
                                'symbol': symbol,
                                'qty': qty,
                                'action': 'BUY',
                                'reason': f'Momentum Chase: Up {change_pct:.1f}% today',
                                'price': current_price
                            })
                            logger.info(f"MOMENTUM SIGNAL: {symbol} up {change_pct:.1f}% - CHASING!")
            except Exception as e:
                logger.debug(f"Could not check momentum for {symbol}: {e}")
        
        return entries
    
    def check_speculative_entries(self, portfolio_data: Dict) -> List[Dict]:
        """Check for speculative/meme stock opportunities"""
        entries = []
        
        if not StrategyConfig.SPECULATIVE_ENABLED:
            return entries
        
        current_positions = {pos['symbol'] for pos in portfolio_data.get('positions', [])}
        cash = portfolio_data['account']['cash']
        portfolio_value = portfolio_data['account']['portfolio_value']
        
        # Check cash available (NO MARGIN)
        available_cash = cash - StrategyConfig.MIN_CASH_ABSOLUTE
        if available_cash < 100:
            logger.debug(f"Insufficient cash for speculative entries: ${cash:.2f} (keeping ${StrategyConfig.MIN_CASH_ABSOLUTE} buffer)")
            return entries
        
        for symbol in StrategyConfig.SPECULATIVE_STOCKS:
            if symbol in current_positions:
                continue
            
            try:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
                from alpaca.data.timeframe import TimeFrame
                
                creds = load_alpaca_config()
                client = StockHistoricalDataClient(creds['api_key'], creds['api_secret'])
                
                # Get latest quote
                quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
                quotes = client.get_stock_latest_quote(quote_request)
                
                if symbol in quotes.data:
                    current_price = quotes.data[symbol].ask_price
                    
                    # Get yesterday's close
                    bars_request = StockBarsRequest(
                        symbol_or_symbols=symbol,
                        timeframe=TimeFrame.Day,
                        limit=5
                    )
                    bars = client.get_stock_bars(bars_request)
                    
                    if symbol in bars.data and len(bars.data[symbol]) >= 2:
                        prev_close = bars.data[symbol][-2].close
                        change_pct = ((current_price - prev_close) / prev_close) * 100
                        
                        # Buy if down 4%+ (speculative dip) or up 5%+ (meme momentum)
                        if change_pct <= -4.0 or change_pct >= 5.0:
                            position_value = portfolio_value * StrategyConfig.SPECULATIVE_POSITION_SIZE
                            qty = max(1, int(position_value / current_price))
                            
                            signal_type = "Speculative Dip" if change_pct < 0 else "Meme Momentum"
                            entries.append({
                                'symbol': symbol,
                                'qty': qty,
                                'action': 'BUY',
                                'reason': f'{signal_type}: {symbol} {change_pct:+.1f}% (high volatility)',
                                'price': current_price
                            })
                            logger.info(f"SPECULATIVE SIGNAL: {symbol} {change_pct:+.1f}% - {signal_type.upper()}!")
            except Exception as e:
                logger.debug(f"Could not check speculative for {symbol}: {e}")
        
        return entries
    
    def check_council_watchlist(self, portfolio_data: Dict) -> List[Dict]:
        """COUNCIL MODE: Check Council watchlist and execute aggressive trades"""
        entries = []
        
        current_positions = {pos['symbol'] for pos in portfolio_data.get('positions', [])}
        cash = portfolio_data['account']['cash']
        portfolio_value = portfolio_data['account']['portfolio_value']
        
        # Council Watchlist with targets
        council_watchlist = [
            {'symbol': 'DKNG', 'target': 22.00, 'max_position': 0.20, 'council': 'SOROS', 'conviction': 'HIGH'},
            {'symbol': 'COIN', 'target': 120.00, 'max_position': 0.10, 'council': 'JONES', 'conviction': 'MEDIUM'},
            {'symbol': 'UPST', 'target': 28.00, 'max_position': 0.15, 'council': 'PAULSON', 'conviction': 'HIGH'},
            {'symbol': 'SHOP', 'target': 105.00, 'max_position': 0.10, 'council': 'WOOD', 'conviction': 'MEDIUM'},
            {'symbol': 'ROKU', 'target': 95.00, 'max_position': 0.08, 'council': 'WOOD', 'conviction': 'MEDIUM'},
            {'symbol': 'SQ', 'target': 60.00, 'max_position': 0.08, 'council': 'PAULSON', 'conviction': 'MEDIUM'},
            {'symbol': 'RIVN', 'target': 12.00, 'max_position': 0.05, 'council': 'SOROS', 'conviction': 'SPECULATIVE'},
        ]
        
        for stock in council_watchlist:
            if stock['symbol'] in current_positions:
                continue
            
            try:
                current_price = self.get_current_price(stock['symbol'])
                
                # Buy if price at or below target (with 5% buffer)
                if current_price <= stock['target'] * 1.05:
                    position_value = portfolio_value * stock['max_position']
                    qty = max(1, int(position_value / current_price))
                    
                    # Ensure we have enough cash
                    if cash >= qty * current_price:
                        entries.append({
                            'symbol': stock['symbol'],
                            'qty': qty,
                            'action': 'BUY',
                            'reason': f"COUNCIL MODE: {stock['council']} conviction - Target ${stock['target']:.2f} hit!",
                            'price': current_price,
                            'council': stock['council']
                        })
                        logger.info(f"COUNCIL: {stock['symbol']} at ${current_price:.2f} - {stock['council']}!")
            except Exception as e:
                logger.debug(f"Council check failed for {stock['symbol']}: {e}")
        
        return entries

    def run(self):
        """Main loop - runs forever"""
        logger.info("=" * 70)
        logger.info("STONK.AI Trading Bot v1.0 Starting")
        logger.info("Strategy: AGGRESSIVE ALPHA MODE")
        logger.info("- Max position: 25% (concentrated bets)")
        logger.info("- Stop loss: -10% (cut losers fast)")
        logger.info("- Take profit: +15% trim / +30% exit (compound quickly)")
        logger.info("- Dip buying: 10% positions (aggressive sizing)")
        logger.info("- Momentum: ENABLED (chase winners)")
        logger.info("- Cash target: 30% (deploy 70% capital)")
        logger.info("Check interval: 60 seconds (trades only during market hours)")
        logger.info("=" * 70)
        
        while True:
            try:
                # Check if markets are open (skip trading on weekends/holidays)
                if not is_market_open():
                    now = datetime.now()
                    if now.weekday() >= 5:
                        reason = "weekend"
                    else:
                        reason = "holiday"
                    logger.info(f"Markets closed ({reason}) - Monitoring only, no trading")
                    time.sleep(300)  # Check every 5 minutes when closed
                    continue
                
                self.run_cycle()
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
            
            time.sleep(60)  # Check every minute during market hours


if __name__ == "__main__":
    bot = STONKAIBot()
    bot.run()
