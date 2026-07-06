#!/usr/bin/env python3
"""
STONK.AI Trade Logger
Logs all trades for the "Watch the Experiment" live feed
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class TradeEvent:
    """Represents a single trade event"""
    timestamp: str
    symbol: str
    action: str  # 'BUY', 'SELL', 'TRIM', 'STOP_LOSS', 'TAKE_PROFIT'
    qty: int
    price: float
    total_value: float
    strategy: str  # 'RSI Signal', 'Stop Loss', 'Profit Take', etc.
    rationale: str
    pnl_impact: Optional[float] = None  # Realized P&L for sells
    pnl_pct: Optional[float] = None  # Percentage gain/loss
    order_id: Optional[str] = None  # Alpaca order ID (for future compatibility)
    readiness_score: Optional[float] = None  # Entry readiness (signal quality)
    tier: Optional[str] = None  # Entry tier (STRONG_NOW / NOW / WATCH / MONITOR)
    confirmation_count: Optional[int] = None  # Number of signal confirmations at entry
    total_score: Optional[float] = None  # Raw signal engine total score at entry
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @property
    def action_emoji(self) -> str:
        """Get emoji for action type"""
        emojis = {
            'BUY': '🟢',
            'SELL': '🔴',
            'TRIM': '🟡',
            'STOP_LOSS': '🛑',
            'TAKE_PROFIT': '✅',
            'AUTO_ENTRY': '🤖'
        }
        return emojis.get(self.action, '⚪')
    
    @property
    def action_color(self) -> str:
        """Get CSS color class"""
        colors = {
            'BUY': 'var(--accent-green)',
            'SELL': 'var(--accent-red)',
            'TRIM': 'var(--accent-yellow)',
            'STOP_LOSS': '#ef4444',
            'TAKE_PROFIT': '#22c55e',
            'AUTO_ENTRY': '#06b6d4'
        }
        return colors.get(self.action, 'var(--text-muted)')


class TradeLogger:
    """
    Central trade logging system
    - Logs to JSON for website
    - Maintains last 100 trades
    - Auto-saves to web-accessible file
    """
    
    def __init__(self, 
                 log_file: Path = Path('trades_log.json'),
                 website_file: Path = Path('/var/www/hedge-fund-website/trades_log.json')):
        self.log_file = log_file
        self.website_file = website_file
        self.trades: List[TradeEvent] = []
        self.max_trades = 100
        self.load()
    
    def load(self):
        """Load existing trades from file"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                    self.trades = [TradeEvent(**t) for t in data.get('trades', [])]
                    logger.info(f"Loaded {len(self.trades)} historical trades")
            except Exception as e:
                logger.error(f"Failed to load trade log: {e}")
                self.trades = []
    
    def save(self):
        """Save trades to both local and website files"""
        data = {
            'last_updated': datetime.now().isoformat(),
            'trade_count': len(self.trades),
            'trades': [t.to_dict() for t in self.trades[-self.max_trades:]]  # Keep last 100
        }
        
        try:
            # Save to local file
            with open(self.log_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Save to website directory
            self.website_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.website_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved {len(self.trades)} trades to log")
        except Exception as e:
            logger.error(f"Failed to save trade log: {e}")
    
    def log_trade(self, 
                  symbol: str,
                  action: str,
                  qty: int,
                  price: float,
                  strategy: str,
                  rationale: str,
                  pnl_impact: Optional[float] = None,
                  pnl_pct: Optional[float] = None,
                  readiness_score: Optional[float] = None,
                  tier: Optional[str] = None,
                  confirmation_count: Optional[int] = None,
                  total_score: Optional[float] = None):
        """Log a new trade"""
        
        trade = TradeEvent(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            action=action,
            qty=qty,
            price=price,
            total_value=qty * price,
            strategy=strategy,
            rationale=rationale,
            pnl_impact=pnl_impact,
            pnl_pct=pnl_pct,
            readiness_score=readiness_score,
            tier=tier,
            confirmation_count=confirmation_count,
            total_score=total_score,
        )
        
        self.trades.append(trade)
        
        # Trim to max
        if len(self.trades) > self.max_trades:
            self.trades = self.trades[-self.max_trades:]
        
        self.save()
        
        logger.info(f"📝 Trade logged: {action} {qty} {symbol} @ ${price:.2f} ({strategy})")
        
        return trade
    
    def get_recent_trades(self, count: int = 20) -> List[TradeEvent]:
        """Get most recent trades"""
        return self.trades[-count:][::-1]  # Reverse for newest first
    
    def get_trades_by_symbol(self, symbol: str) -> List[TradeEvent]:
        """Get all trades for a specific symbol"""
        return [t for t in self.trades if t.symbol == symbol][::-1]
    
    def get_daily_summary(self) -> Dict:
        """Get summary of today's trades"""
        today = datetime.now().strftime('%Y-%m-%d')
        today_trades = [t for t in self.trades if t.timestamp.startswith(today)]
        
        buys = [t for t in today_trades if t.action == 'BUY']
        sells = [t for t in today_trades if t.action in ['SELL', 'TRIM']]
        
        total_bought = sum(t.total_value for t in buys)
        total_sold = sum(t.total_value for t in sells)
        
        return {
            'date': today,
            'total_trades': len(today_trades),
            'buys': len(buys),
            'sells': len(sells),
            'total_bought': total_bought,
            'total_sold': total_sold,
            'net_flow': total_sold - total_bought
        }


# Global trade logger instance
trade_logger = TradeLogger()


if __name__ == "__main__":
    # Test the logger
    print("Testing trade logger...")
    
    # Log some test trades
    trade_logger.log_trade(
        symbol="HOOD",
        action="BUY",
        qty=25,
        price=83.46,
        strategy="RSI Signal",
        rationale="RSI below 30, strong buying signal detected"
    )
    
    trade_logger.log_trade(
        symbol="NVDA",
        action="SELL",
        qty=5,
        price=213.75,
        strategy="Stop Loss",
        rationale="-15% stop loss triggered",
        pnl_impact=-47.25,
        pnl_pct=-4.23
    )
    
    print(f"Logged {len(trade_logger.trades)} trades")
    print(f"Recent trades: {len(trade_logger.get_recent_trades(5))}")
