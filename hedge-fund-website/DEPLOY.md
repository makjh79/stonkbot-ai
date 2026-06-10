# STONK.AI Deployment Guide
## Step-by-Step Instructions to Get Trading

---

## Overview

This will deploy:
1. **Data Fetcher** - Updates website every 30 seconds
2. **Trading Bot** - Executes trades autonomously
3. **Website** - Displays live portfolio

**Time Required:** 30 minutes  
**Cost:** $5-20/month for VPS  
**Risk:** Start with paper trading (fake money)

---

## Step 1: Get a Server (VPS)

### Recommended Providers:

| Provider | Cheapest Plan | Cost/Month |
|----------|--------------|------------|
| **DigitalOcean** | 1 CPU, 512MB RAM, 10GB SSD | $4 |
| **Linode** | 1 CPU, 1GB RAM, 25GB SSD | $5 |
| **AWS Lightsail** | 1 CPU, 512MB RAM, 20GB SSD | $3.50 |
| **Vultr** | 1 CPU, 512MB RAM, 10GB SSD | $2.50 |

### Requirements:
- Ubuntu 20.04 LTS or 22.04 LTS
- 512MB RAM minimum (1GB recommended)
- 10GB storage
- Internet access

### Setup:
1. Sign up with provider
2. Create Ubuntu 20.04/22.04 droplet/instance
3. Save the IP address and root password
4. SSH into server: `ssh root@YOUR_SERVER_IP`

---

## Step 2: Upload Files to Server

### Option A: SCP (Secure Copy)
From your local machine:
```bash
# Download the files from workspace first
# Then upload to server:
scp -r hedge-fund-website/* root@YOUR_SERVER_IP:/opt/
```

### Option B: Git Clone
On the server:
```bash
# If you pushed to GitHub:
ssh root@YOUR_SERVER_IP
git clone https://github.com/YOUR_USERNAME/stonk-ai.git /opt/stonk-ai
```

### Option C: Manual Upload
1. ZIP the hedge-fund-website folder
2. Upload via SFTP (FileZilla, Cyberduck)
3. Extract on server: `unzip stonk-ai.zip -d /opt/stonk-ai`

---

## Step 3: Install Dependencies

SSH into your server:
```bash
ssh root@YOUR_SERVER_IP

cd /opt/stonk-ai

# Update system
apt-get update && apt-get upgrade -y

# Install Python and pip
apt-get install -y python3 python3-pip

# Install required packages
pip3 install alpaca-trade-api python-dotenv requests
```

---

## Step 4: Configure Environment Variables

Create the .env file:
```bash
nano /opt/stonk-ai/.env
```

Add your Alpaca credentials:
```
ALPACA_API_KEY=PKITYG***
ALPACA_SECRET_KEY=H5ExSkJ***
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_URL=https://data.alpaca.markets
```

**⚠️ IMPORTANT:** Use **paper trading** first! (URL is paper-api.alpaca.markets)

Save: `Ctrl+X`, then `Y`, then `Enter`

---

## Step 5: Install Systemd Services

```bash
# Copy service files
cp /opt/stonk-ai/data-fetcher.service /etc/systemd/system/
cp /opt/stonk-ai/stonk-ai.service /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Create user for services (security)
useradd -r -s /bin/false stonkai 2>/dev/null || true
chown -R stonkai:stonkai /opt/stonk-ai
```

---

## Step 6: Test the Data Fetcher

**First, test manually:**
```bash
cd /opt/stonk-ai
python3 fetch_data.py &
```

**Check if it works:**
```bash
# Watch the log
tail -f data_fetcher.log

# Check if portfolio_data.json was created
ls -la portfolio_data.json

# View the data
cat portfolio_data.json
```

**If working, stop and enable as service:**
```bash
pkill -f fetch_data.py

# Start as service
systemctl start data-fetcher
systemctl enable data-fetcher

# Check status
systemctl status data-fetcher
```

---

## Step 7: Test the Trading Bot

**IMPORTANT: Review the strategy first:**
```bash
cat /opt/stonk-ai/STRATEGY.md | head -100
```

**Test the bot manually (paper trading only!):**
```bash
cd /opt/stonk-ai
python3 trading_bot.py &
```

**Watch the logs:**
```bash
tail -f trading_bot.log
```

**You should see:**
- "STONK.AI Trading Bot v1.0 Starting"
- Portfolio data fetching
- "Market closed, skipping cycle" (if after hours)

**If working, stop and enable as service:**
```bash
pkill -f trading_bot.py

# Start as service
systemctl start stonk-ai
systemctl enable stonk-ai

# Check status
systemctl status stonk-ai
```

---

## Step 8: Monitor and Verify

### Check Both Services Are Running:
```bash
# Data fetcher
systemctl status data-fetcher

# Trading bot
systemctl status stonk-ai
```

### View Logs in Real-Time:
```bash
# Data fetcher logs
journalctl -u data-fetcher -f

# Trading bot logs
journalctl -u stonk-ai -f
```

### Check Portfolio Data:
```bash
# Watch portfolio data update
watch -n 1 cat /opt/stonk-ai/portfolio_data.json
```

### Check Trade Log:
```bash
cat /opt/stonk-ai/TRADES_LOG.md
```

---

## Step 9: Host the Website

### Option A: GitHub Pages (Free)

1. Create GitHub repo: `stonk-ai-dashboard`
2. Upload `index.html` and `portfolio_data.json`
3. Enable GitHub Pages in settings
4. Website live at: `https://YOUR_USERNAME.github.io/stonk-ai-dashboard`

**Auto-update script** (run on server):
```bash
#!/bin/bash
# Add to crontab to run every minute
cd /opt/stonk-ai
git add portfolio_data.json
git commit -m "Update portfolio data"
git push origin main
```

### Option B: Cloudflare Pages (Free)

1. Sign up at https://pages.cloudflare.com
2. Create new project
3. Upload `index.html`
4. Set up webhook or manual deploy

### Option C: Any Static Hosting

Upload `index.html` to:
- Netlify (free)
- Vercel (free)
- AWS S3 (minimal cost)
- Your own server

---

## Step 10: Verify Everything Works

### Checklist:

- [ ] Server is running
- [ ] Data fetcher is updating `portfolio_data.json`
- [ ] Trading bot is monitoring positions
- [ ] Website is displaying data
- [ ] All services restart on boot

### Test Commands:

```bash
# Check everything is running
systemctl is-active data-fetcher stonk-ai

# View recent logs
journalctl -u data-fetcher --since "1 hour ago"
journalctl -u stonk-ai --since "1 hour ago"

# Check portfolio
python3 -c "import json; d=json.load(open('portfolio_data.json')); print(f'Portfolio: \${d[\"account\"][\"portfolio_value\"]:,.2f}')"
```

---

## Emergency Procedures

### Stop All Trading Immediately:
```bash
systemctl stop stonk-ai data-fetcher
```

### Restart Everything:
```bash
systemctl restart stonk-ai data-fetcher
```

### View Recent Errors:
```bash
journalctl -u stonk-ai --since "1 hour ago" | grep ERROR
```

### Reset Portfolio State:
```bash
rm /opt/stonk-ai/portfolio_state.json
systemctl restart stonk-ai
```

---

## Troubleshooting

### "Failed to fetch portfolio data"
- Check API keys in `.env`
- Verify Alpaca account is active
- Check network connectivity

### "Permission denied"
```bash
chown -R stonkai:stonkai /opt/stonk-ai
chmod +x /opt/stonk-ai/*.py
```

### "Service failed to start"
```bash
# Check logs
journalctl -u stonk-ai -n 50

# Test manually
python3 /opt/stonk-ai/trading_bot.py
```

### Website not updating
- Check if `portfolio_data.json` exists
- Verify data fetcher is running
- Check file permissions

---

## Next Steps

1. **Monitor for 1 week** (paper trading)
2. **Review logs daily** - make sure trades execute
3. **Message Jarvis weekly** for strategy review
4. **Switch to live trading** (only after paper success)
5. **Scale gradually** - start with $10K, not $100K

---

## Summary

| Step | Action | Status |
|------|--------|--------|
| 1 | Get VPS ($5-20/month) | ☐ |
| 2 | Upload files | ☐ |
| 3 | Install dependencies | ☐ |
| 4 | Configure Alpaca keys | ☐ |
| 5 | Install services | ☐ |
| 6 | Test data fetcher | ☐ |
| 7 | Test trading bot | ☐ |
| 8 | Monitor & verify | ☐ |
| 9 | Host website | ☐ |
| 10 | Deploy complete | ☐ |

**Once deployed, the bot will trade autonomously. You only need to monitor and contact me for weekly reviews or emergencies.**

---

**Questions? Message Jarvis.**
