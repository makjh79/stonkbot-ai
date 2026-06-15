#!/bin/bash
# Health check script for STONK.AI services

WEBSITE_DIR="/var/www/hedge-fund-website"
ALERT_LOG="/var/log/stonk_monitor.log"
ISSUES_FILE="/tmp/stonk_issues.txt"

# Clear previous issues
> $ISSUES_FILE

# Check if portfolio data is stale (> 30 minutes old)
if [ -f "$WEBSITE_DIR/portfolio_data.json" ]; then
    DATA_AGE=$(( ($(date +%s) - $(stat -c %Y "$WEBSITE_DIR/portfolio_data.json")) / 60 ))
    if [ $DATA_AGE -gt 30 ]; then
        echo "$(date): WARNING - Portfolio data is ${DATA_AGE} minutes old" >> $ALERT_LOG
        echo "Data stale: ${DATA_AGE} minutes" >> $ISSUES_FILE
        systemctl restart data-fetcher.service
    fi
fi

# Check if services are running
for service in stonk-ai.service data-fetcher.service; do
    if ! systemctl is-active --quiet $service; then
        echo "$(date): ERROR - $service is down, restarting..." >> $ALERT_LOG
        echo "Service down: $service" >> $ISSUES_FILE
        systemctl restart $service
    fi
done

# Check for crash loops
for service in stonk-ai.service data-fetcher.service; do
    RESTART_COUNT=$(journalctl -u $service --since "1 hour ago" | grep -c "Started.*$service")
    if [ $RESTART_COUNT -gt 10 ]; then
        echo "$(date): CRITICAL - $service restarted $RESTART_COUNT times" >> $ALERT_LOG
        echo "Crash loop: $service ($RESTART_COUNT restarts)" >> $ISSUES_FILE
    fi
done

# If there are issues, the file will exist and be non-empty
# Check can be done with: [ -s /tmp/stonk_issues.txt ] && cat /tmp/stonk_issues.txt

echo "$(date): Health check completed" >> $ALERT_LOG
