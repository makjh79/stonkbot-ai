# STONK.AI - Autonomous AI Trading System

A complete AI-designed, code-executed trading system for Alpaca paper trading.

## What This Is

**STONK.AI** is a $100K trading experiment where:
- **AI (Jarvis)** designed the complete strategy
- **Python code** executes trades autonomously
- **You** only intervene for emergencies or scheduled reviews
- **Cost: ~$0/month** after setup (AI only involved when you message)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  AI (Jarvis) - Strategy Designer                            │
│  • Designed complete trading strategy (STRATEGY.md)         │
│  • Built autonomous trading bot (trading_bot.py)            │
│  • Emergency oversight only                                 │
│  • Cost: One-time (this session)                            │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Your Server/VPS - Runs 24/7                                │
│  • Data Fetcher (fetch_data.py) - Updates website data      │
│  • Trading Bot (trading_bot.py) - Executes trades           │
│  • Cost: $5-20/month (VPS)                                  │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│  Alpaca Paper Trading                                       │
│  • Executes real trades with fake money                     │
│  • Cost: $0                                                 │
└─────────────────────────────────────────────────────────────┘
```

## Files Overview

| File | Purpose | Cost |
|------|---------|------|
| **STRATEGY.md** | Complete trading strategy | $0 |
| **trading_bot.py** | Autonomous trading bot | $0 |
| **fetch_data.py** | Website data updater | $0 |
| **index.html** | Live dashboard website | $0 |
| **setup.sh** | One-command installation | $0 |

## Quick Start

### 1. Get Alpaca Account
```bash
# Sign up at https://alpaca.markets
# Generate API keys
# IMPORTANT: Use paper trading (fake money) first!
```

### 2. Install on Server
```bash
git clone <your-repo>
cd hedge-fund-website
./setup.sh
```

### 3. Configure API Keys
```bash
sudo nano /opt/stonk-ai/.env
# Add:
# ALPACA_API_KEY=your_key_here
# ALPACA_SECRET_KEY=your_secret_here
# ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

### 4. Start Services
```bash
# Data fetcher (keeps website live)
sudo systemctl start data-fetcher
sudo systemctl enable data-fetcher

# Trading bot (executes trades autonomously)
sudo systemctl start stonk-ai
sudo systemctl enable stonk-ai
```

### 5. Verify Everything Works
```bash
# Check data fetcher
sudo systemctl status data-fetcher
sudo journalctl -u data-fetcher -f

# Check trading bot
sudo systemctl status stonk-ai
sudo journalctl -u stonk-ai -f

# Check portfolio data
watch -n 1 cat /opt/stonk-ai/portfolio_data.json
```

### 6. Host Website
Upload `index.html` to any static host:
- GitHub Pages (free)
- Cloudflare Pages (free)
- Netlify (free)

## Trading Strategy

See **STRATEGY.md** for complete rules, but summary:

### Portfolio Allocation
| Sector | Target | Holdings |
|--------|--------|----------|
| Tech Giants | 25% | AAPL, MSFT, GOOGL, META, NVDA |
| AI/Growth | 30% | AMD, PLTR, APP, CRWD |
| Fintech | 5% | HOOD, SOFI |
| Defense/Income | 5% | AVGO, SCHD, SGOV |
| Cash | 35% | Dry powder |

### Risk Management
- **Stop Loss:** -15% (automatic execution)
- **Take Profit:** +25% (trim 25%), +50% (full exit)
- **Max Position:** 15% of portfolio
- **Trade Limits:** 3/day, 10/week

### Bot Behavior
1. Monitors all positions 24/7
2. Executes stop losses automatically
3. Takes profits per strategy
4. Rebalances when needed
5. Logs all decisions
6. Alerts on emergencies

## Monthly Costs

| Component | Cost |
|-----------|------|
| VPS/Server | $5-20/month |
| Alpaca API | $0 (paper trading) |
| Website Hosting | $0 (GitHub/Cloudflare) |
| AI Assistant | $0 unless contacted |
| **Total** | **$5-20/month** |

## When to Contact AI (Jarvis)

### ✅ Contact Weekly
- Review performance
- Strategy adjustments
- Minor tweaks

### ✅ Contact Immediately (Emergency)
- Portfolio down >20%
- Any stock down >30%
- Major market crash
- Bot malfunction
- Unexpected behavior

### ❌ Don't Contact For
- Normal trading activity
- Stop loss execution
- Take profit execution
- Daily price movements
- Rebalancing trades

## Monitoring

### Check Bot Status
```bash
# Is it running?
sudo systemctl status stonk-ai

# View recent trades
sudo journalctl -u stonk-ai -f

# View trade history
cat /opt/stonk-ai/TRADES_LOG.md
```

### Check Portfolio
```bash
# Live data file
watch -n 1 cat /opt/stonk-ai/portfolio_data.json

# Website data (auto-updates every 30s)
# Just open index.html in browser
```

### Emergency Stop
```bash
# Stop trading immediately
sudo systemctl stop stonk-ai

# Stop data fetcher
sudo systemctl stop data-fetcher
```

## Safety Features

1. **Paper Trading First** - Test with fake money
2. **Stop Losses** - Automatic -15% exits
3. **Position Limits** - Max 15% per stock
4. **Cash Buffer** - 35% minimum cash
5. **Trade Limits** - Max 3/day prevents overtrading
6. **Emergency Alerts** - Critical issues logged
7. **Human Override** - Stop anytime with systemctl

## Troubleshooting

**Bot not starting?**
```bash
# Check logs
sudo journalctl -u stonk-ai -n 50

# Common issues:
# - Missing API keys in .env
# - Alpaca account not active
# - Network connectivity
```

**Website not updating?**
```bash
# Check data fetcher
sudo journalctl -u data-fetcher -f

# Verify JSON file exists
ls -la /opt/stonk-ai/portfolio_data.json
```

**Emergency: Stop Everything**
```bash
sudo systemctl stop stonk-ai data-fetcher
```

## Next Steps

1. **Start with paper trading** - Test for 1-2 weeks
2. **Monitor daily** - Check logs, verify trades
3. **Weekly review** - Message Jarvis for strategy check
4. **Consider live trading** - Only after paper success
5. **Scale gradually** - Start with $10K, not full $100K

## Support

- **Emergency:** Message Jarvis immediately
- **Weekly review:** Message Jarvis for performance analysis
- **Documentation:** See STRATEGY.md for complete trading rules
- **Logs:** Check trading_bot.log and data_fetcher.log

---

**Remember:** This is an experiment. The goal is learning + beating the market over 1-3 years. Not getting rich quick. Start with paper trading, be patient, let the bot work.

**Last Updated:** June 6, 2026  
**Version:** 1.0  
**Strategy Designer:** Jarvis (AI Assistant)
