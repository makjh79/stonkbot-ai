# ✅ Updated: Trading Bot Now Uses Existing Alpaca Config

## What Was Changed

The new autonomous trading bot (`trading_bot.py`) and data fetcher (`fetch_data.py`) have been updated to use your **existing Alpaca configuration**.

### Previous Setup (New)
- Required `.env` file with environment variables
- Used Alpaca SDK primarily

### Updated Setup (Now)
- Uses existing `/root/.openclaw/workspace/alpaca_config.json`
- Falls back to `.env` if config file not found
- Supports both Alpaca SDK and requests (fallback)
- Compatible with your existing scripts

## Files That Connect to Alpaca

| File | Uses Config | Fallback |
|------|-------------|----------|
| `trading_bot.py` | ✅ alpaca_config.json | .env file |
| `fetch_data.py` | ✅ alpaca_config.json | .env file |
| `buy_the_dip.py` | ✅ alpaca_config.json | None |
| `trade_executor.py` | ✅ alpaca_config.json | None |

## Your Existing Config File

Located at: `/root/.openclaw/workspace/alpaca_config.json`

```json
{
  "api_key": "PK...",
  "api_secret": "...",
  "base_url": "https://paper-api.alpaca.markets",
  "data_url": "https://data.alpaca.markets"
}
```

## What the New Bot Does

### Autonomous Features:
1. **Monitors positions 24/7** during market hours
2. **Executes stop losses** at -15% automatically
3. **Takes profits** at +25% (trim) and +50% (full exit)
4. **Checks rebalancing** needs daily
5. **Enforces trade limits** (3/day, 10/week)
6. **Logs all trades** to TRADES_LOG.md
7. **Updates website data** every 30 seconds

### Risk Management:
- Stop loss: -15% (automatic)
- Max position: 15% of portfolio
- Min cash: 30% buffer
- Trade limits prevent overtrading

## Deployment Commands

### Quick Start:
```bash
# 1. Copy files to server
scp -r hedge-fund-website/* root@YOUR_SERVER_IP:/opt/stonk-ai/

# 2. SSH into server
ssh root@YOUR_SERVER_IP

# 3. Install dependencies
cd /opt/stonk-ai
pip3 install alpaca-trade-api python-dotenv requests

# 4. Setup services
./setup.sh

# 5. Start everything
systemctl start data-fetcher stonk-ai
systemctl enable data-fetcher stonk-ai
```

### Check Status:
```bash
# View logs
journalctl -u data-fetcher -f
journalctl -u stonk-ai -f

# Check services
systemctl status data-fetcher stonk-ai

# View portfolio data
watch -n 1 cat /opt/stonk-ai/portfolio_data.json
```

## Comparison: Old vs New

| Feature | Old Scripts | New Bot |
|---------|-------------|---------|
| **Automation** | Manual execution | Fully autonomous |
| **Stop losses** | Manual | Automatic -15% |
| **Take profits** | Manual | Automatic +25%/+50% |
| **Rebalancing** | Manual | Automatic checks |
| **Trade limits** | None | 3/day, 10/week |
| **Logging** | Basic | Comprehensive |
| **Risk mgmt** | Basic | Full strategy rules |

## Next Steps

1. **Deploy to server** (follow DEPLOY.md)
2. **Test with paper trading** for 1 week
3. **Monitor daily** via logs
4. **Message me weekly** for strategy review

## Emergency Stop

If anything goes wrong:
```bash
systemctl stop stonk-ai data-fetcher
```

---

**The bot is ready. It will use your existing Alpaca config and trade autonomously once deployed.**
