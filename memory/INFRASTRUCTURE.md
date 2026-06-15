# STONK.AI Infrastructure Documentation

## Service Architecture

### Core Services

**1. stonk-ai.service (Trading Bot)**
- File: `/opt/stonk-ai/trading_bot.py`
- User: `stonkai`
- Status: Active
- Purpose: Main trading logic, order execution

**2. data-fetcher.service (Data Refresh)**
- File: `/opt/stonk-ai/fetch_data_simple.py` ⚠️ (was incorrectly set to fetch_data.py)
- User: `stonkai`
- Status: Active
- Purpose: Fetches market data, updates website JSON files

**3. stonk-monitor.timer (Health Checks)**
- Script: `/root/.openclaw/workspace/monitor_services.sh`
- Frequency: Every 5 minutes
- Purpose: Restarts failed services, alerts on stale data

## File Locations

### Website (Live)
- Path: `/var/www/hedge-fund-website/`
- Served by: nginx on port 8080
- **IMPORTANT**: Edit files here, NOT in workspace

### Source Code
- Path: `/opt/stonk-ai/`
- Key files:
  - `trading_bot.py` - Main bot
  - `fetch_data_simple.py` - Data fetcher (note: NOT fetch_data.py!)
  - `fetch_ai_watchlist.py` - AI watchlist updates
  - `fetch_market_indices.py` - Market data

### Website Source (GitHub)
- Path: `/root/.openclaw/workspace/website/index.html`
- Auto-deploys to live site on git push

## Common Issues & Prevention

### Issue 1: Data Not Refreshing
**Symptoms**: Website shows old prices, timestamp not updating
**Causes**:
- data-fetcher.service crashed (check with `systemctl status data-fetcher`)
- Permission errors on log files
- Wrong filename in systemd config

**Prevention**:
- ✅ Health monitor auto-restarts failed services
- ✅ File permissions checked on startup
- ✅ systemd config validated

### Issue 2: Website Not Updating After Git Push
**Symptoms**: GitHub shows new code but website unchanged
**Causes**:
- GitHub Actions workflow failed
- SSH key authentication issue
- Wrong file path in deploy script

**Check**:
```bash
cat /var/www/hedge-fund-website/deploy.log  # Shows last deploy time
```

### Issue 3: Permission Denied Errors
**Symptoms**: Services fail to write to JSON files
**Fix**:
```bash
chown -R stonkai:stonkai /opt/stonk-ai/
chown www-data:www-data /var/www/hedge-fund-website/*.json
```

## Monitoring

### Health Check Script
Location: `/root/.openclaw/workspace/monitor_services.sh`

Checks every 5 minutes:
1. Data freshness (< 30 minutes old)
2. Service status (auto-restart if down)
3. Crash loops (> 10 restarts/hour = alert)

### Logs
- Service logs: `journalctl -u stonk-ai.service`
- Data fetcher: `journalctl -u data-fetcher.service`
- Health monitor: `/var/log/stonk_monitor.log`
- Deploy log: `/var/www/hedge-fund-website/deploy.log`

## Critical File Mappings

| File | Purpose | Updated By |
|------|---------|------------|
| portfolio_data.json | Current holdings, cash, P&L | trading_bot.py |
| ai_watchlist_live.json | AI stock picks with prices | fetch_ai_watchlist.py |
| market_indices.json | S&P 500, NASDAQ, etc. | fetch_market_indices.py |
| trades_log.json | Recent trades | trading_bot.py |
| index.html | Website UI | GitHub auto-deploy |

## Quick Diagnostics

```bash
# Check all services
systemctl status stonk-ai.service data-fetcher.service

# Check data freshness
ls -la /var/www/hedge-fund-website/*.json

# View recent errors
journalctl -u data-fetcher.service --since "1 hour ago"

# Manual data refresh
cd /opt/stonk-ai && python3 fetch_data_simple.py

# Check GitHub deploy status
cat /var/www/hedge-fund-website/deploy.log
```
