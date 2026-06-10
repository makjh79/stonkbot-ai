# 🤖 STONK.AI Trading Bot Setup

Real Alpaca Markets integration for live automated trading.

---

## 📋 Prerequisites

- Python 3.8+
- Alpaca Markets account (free)
- $100K capital (or paper trading for testing)

---

## 🔑 Step 1: Get Alpaca API Keys

1. Sign up at [https://alpaca.markets/](https://alpaca.markets/)
2. Go to **Paper Trading** (recommended for testing)
3. Generate API keys:
   - API Key ID
   - Secret Key

---

## 🛠️ Step 2: Install & Configure

```bash
# 1. Clone/navigate to the hedge-fund-website directory
cd hedge-fund-website

# 2. Set up Python environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys (choose one method)

# Method A: Environment variables
export ALPACA_API_KEY='your_api_key_here'
export ALPACA_SECRET_KEY='your_secret_key_here'
export ALPACA_PAPER='true'  # Set to 'false' for live trading

# Method B: .env file
cp .env.example .env
# Edit .env with your credentials
```

---

## 🚀 Step 3: Run the Bot

```bash
# Make script executable
chmod +x run_bot.sh

# Run the bot
./run_bot.sh
```

Or directly with Python:
```bash
python3 alpaca_trader.py
```

---

## ⚙️ Configuration

Edit `alpaca_trader.py` to customize strategy:

```python
self.config = {
    'stop_loss_pct': -15.0,        # Sell at -15%
    'profit_trim_pct': 25.0,       # Trim 25% at +25%
    'profit_exit_pct': 50.0,       # Full exit at +50%
    'max_position_pct': 20.0,      # Max 20% per stock
    'min_cash_reserve': 15000,     # Keep $15K minimum
    'max_daily_entries': 2,        # Max 2 new stocks/day
    'rsi_oversold': 30,            # RSI threshold
    'volume_threshold': 2.0,       # 2x avg volume
    'conviction_threshold': 70,     # 70% AI confidence
    'sector_limit': 35.0           # Max 35% per sector
}
```

---

## 📊 What the Bot Does

### ✅ Automated Exits
- **Stop Loss**: Sells at -15% (hard stop)
- **Profit Trim**: Sells 25% of position at +25%
- **Profit Exit**: Full exit at +50%

### ✅ Automated Entries (NEW!)
Scans 5,000+ stocks and auto-buys when:
- RSI < 30 (oversold)
- Volume 2x average
- AI conviction > 70%
- Cash above $15K reserve
- Max 2 entries per day

### 📈 Portfolio Management
- Max 20% position size
- Sector diversification
- Cash buffer protection
- Real-time position tracking

---

## 📁 Files Created

| File | Purpose |
|------|---------|
| `portfolio_data.json` | Live portfolio snapshot for website |
| `activity_log.json` | Trading activity history |
| `trading_bot.log` | Bot logs & errors |

---

## 🔒 Security

- ✅ API keys stored in environment (not in code)
- ✅ Paper trading by default (safe to test)
- ✅ Only reads portfolio data (website display)
- ✅ No external access to your account

---

## 🧪 Testing (Paper Trading)

```bash
export ALPACA_PAPER='true'
./run_bot.sh
```

Runs with fake money. Test all features safely.

---

## 🔴 Live Trading

**⚠️ WARNING: Real Money**

```bash
export ALPACA_PAPER='false'
./run_bot.sh
```

This uses REAL money. Make sure:
- Tested extensively in paper mode
- Understand all risks
- Can afford to lose the capital

---

## 📡 How It Works

1. **Bot starts** → Connects to Alpaca API
2. **Every 60 seconds**:
   - Checks stop losses (-15%)
   - Checks profit targets (+25%/+50%)
   - Scans for new entries (RSI <30, volume spike)
   - Updates portfolio_data.json for website
3. **Website** reads portfolio_data.json → Displays real data

---

## 🐛 Troubleshooting

| Error | Solution |
|-------|----------|
| "API credentials not found" | Set ALPACA_API_KEY and ALPACA_SECRET_KEY |
| "Market closed" | Bot only runs 9:30 AM - 4:00 PM ET |
| "Failed to fetch" | Check internet connection |
| "Order rejected" | Check buying power / position limits |

---

## 💰 Costs

| Service | Cost |
|---------|------|
| Alpaca API | **Free** (commission-free trades) |
| Market data | **Free** (basic SIP feed) |
| Hosting | **Free** (runs on your machine) |
| **Total** | **$0/month** |

---

## 🚀 Next Steps

1. ✅ Get Alpaca API keys
2. ✅ Install & run in paper mode
3. ✅ Verify trades are executing
4. ✅ Check website shows real data
5. ✅ Switch to live mode (when ready)

---

**Questions?** Check `trading_bot.log` for detailed activity.

**Ready to make money?** 🚀
