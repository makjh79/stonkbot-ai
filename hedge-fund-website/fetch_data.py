#!/usr/bin/env python3
"""
STONK.AI Data Fetcher
Minimal script to keep portfolio_data.json fresh
Runs 24/7, fetches from Alpaca every 30 seconds during market hours
Zero AI cost - just runs automatically
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Try to import alpaca, fall back to requests if not available
try:
    import alpaca_trade_api as tradeapi
    USE_SDK = True
except ImportError:
    import requests
    USE_SDK = False
    print("Alpaca SDK not found, using requests fallback")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_fetcher.log'),
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

class DataFetcher:
    """Fetches portfolio data from Alpaca and saves to JSON"""
    
    def __init__(self):
        config = load_alpaca_config()
        self.api_key = config.get('api_key') or config.get('APCA_API_KEY_ID')
        self.api_secret = config.get('api_secret') or config.get('APCA_API_SECRET_KEY')
        self.base_url = config.get('base_url', 'https://paper-api.alpaca.markets')
        self.data_url = os.getenv('ALPACA_DATA_URL', 'https://data.alpaca.markets')
        self.output_file = Path(__file__).parent / 'portfolio_data.json'
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API keys not found. Set ALPACA_API_KEY and ALPACA_SECRET_KEY")
        
        if USE_SDK:
            self.api = tradeapi.REST(
                key_id=self.api_key,
                secret_key=self.api_secret,
                base_url=self.base_url
            )
        else:
            self.session = requests.Session()
            self.session.headers.update({
                'APCA-API-KEY-ID': self.api_key,
                'APCA-API-SECRET-KEY': self.api_secret
            })
        
        logger.info(f"DataFetcher initialized (SDK: {USE_SDK})")
        logger.info(f"Output file: {self.output_file}")
    
    def is_market_open(self) -> bool:
        """Check if US equity markets are open"""
        now = datetime.now()
        
        # Check if weekday (Mon-Fri = 0-4)
        if now.weekday() >= 5:
            return False
        
        # Rough ET check (UTC-4 or UTC-5 depending on DST)
        # Market hours: 9:30 AM - 4:00 PM ET
        et_offset = -4 if self.is_dst() else -5
        et_hour = (now.hour + et_offset) % 24
        et_minute = now.minute
        et_time = et_hour * 100 + et_minute
        
        return 930 <= et_time < 1600
    
    def is_dst(self) -> bool:
        """Check if currently DST (rough approximation)"""
        now = datetime.now()
        # DST starts second Sunday in March, ends first Sunday in November
        # This is a rough check
        if now.month < 3 or now.month > 11:
            return False
        if 4 <= now.month <= 10:
            return True
        return False  # Simplify for March/November transition
    
    def fetch_portfolio_data(self) -> dict:
        """Fetch current portfolio data from Alpaca"""
        try:
            if USE_SDK:
                return self._fetch_with_sdk()
            else:
                return self._fetch_with_requests()
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            return {}
    
    def _fetch_with_sdk(self) -> dict:
        """Fetch using Alpaca SDK"""
        account = self.api.get_account()
        positions = self.api.list_positions()
        
        portfolio_data = {
            "timestamp": datetime.now().isoformat(),
            "status": "live",
            "account": {
                "portfolio_value": float(account.portfolio_value),
                "cash": float(account.cash),
                "buying_power": float(account.buying_power),
                "equity": float(account.equity)
            },
            "positions": []
        }
        
        total_pl = 0
        for pos in positions:
            position_data = {
                "symbol": pos.symbol,
                "qty": int(pos.qty),
                "avg_entry": float(pos.avg_entry_price),
                "current": float(pos.current_price),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
                "unrealized_pl": float(pos.unrealized_pl),
                "unrealized_plpc": float(pos.unrealized_plpc) * 100
            }
            portfolio_data["positions"].append(position_data)
            total_pl += float(pos.unrealized_pl)
        
        portfolio_data["total_pl"] = total_pl
        # Calculate total_pl_pct based on actual cost basis, not fixed 100000
        total_cost = sum(p["cost_basis"] for p in portfolio_data["positions"])
        portfolio_data["total_pl_pct"] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        return portfolio_data
    
    def _fetch_with_requests(self) -> dict:
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
            "timestamp": datetime.now().isoformat(),
            "status": "live",
            "account": {
                "portfolio_value": float(account.get('portfolio_value', 0)),
                "cash": float(account.get('cash', 0)),
                "buying_power": float(account.get('buying_power', 0)),
                "equity": float(account.get('equity', 0))
            },
            "positions": []
        }
        
        total_pl = 0
        for pos in positions:
            position_data = {
                "symbol": pos.get('symbol', ''),
                "qty": int(pos.get('qty', 0)),
                "avg_entry": float(pos.get('avg_entry_price', 0)),
                "current": float(pos.get('current_price', 0)),
                "market_value": float(pos.get('market_value', 0)),
                "cost_basis": float(pos.get('cost_basis', 0)),
                "unrealized_pl": float(pos.get('unrealized_pl', 0)),
                "unrealized_plpc": float(pos.get('unrealized_plpc', 0)) * 100
            }
            portfolio_data["positions"].append(position_data)
            total_pl += float(pos.get('unrealized_pl', 0))
        
        portfolio_data["total_pl"] = total_pl
        # Calculate total_pl_pct based on actual cost basis, not fixed 100000
        total_cost = sum(p["cost_basis"] for p in portfolio_data["positions"])
        portfolio_data["total_pl_pct"] = (total_pl / total_cost * 100) if total_cost > 0 else 0
        
        return portfolio_data
    
    def save_data(self, data: dict):
        """Save portfolio data to JSON file"""
        try:
            with open(self.output_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Data saved to {self.output_file}")
        except Exception as e:
            logger.error(f"Failed to save data: {e}")
    
    def run(self):
        """Main loop - runs forever"""
        logger.info("=" * 60)
        logger.info("STONK.AI Data Fetcher Starting")
        logger.info("Fetching every 30 seconds during market hours")
        logger.info("=" * 60)
        
        while True:
            try:
                if self.is_market_open():
                    data = self.fetch_portfolio_data()
                    if data:
                        self.save_data(data)
                        value = data.get('account', {}).get('portfolio_value', 0)
                        pl = data.get('total_pl', 0)
                        logger.info(f"Updated: ${value:,.2f} ({pl:+,.2f})")
                    else:
                        logger.warning("No data received from Alpaca")
                else:
                    logger.debug("Market closed, skipping fetch")
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
            
            # Sleep 30 seconds
            time.sleep(30)


if __name__ == "__main__":
    fetcher = DataFetcher()
    fetcher.run()
