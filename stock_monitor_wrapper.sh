#!/bin/bash
# Stock Monitor Wrapper - calls Python and sends alerts via OpenClaw tools

WORKSPACE="/root/.openclaw/workspace"
MODE="${1:-check}"
TELEGRAM_TARGET="8795294800"
EMAIL="Mak.joonhowe@gmail.com"

cd "$WORKSPACE"

# Run the Python monitor
python3 stock_monitor.py "$MODE"

# Send daily summary if it exists
if [ -f "/tmp/stock_summary.txt" ]; then
    SUMMARY=$(cat /tmp/stock_summary.txt)
    # Telegram
    openclaw message send --target "telegram:$TELEGRAM_TARGET" --message "$SUMMARY"
    # Email (if configured)
    echo "$SUMMARY" | mail -s "Daily Stock Summary - $(date +%Y-%m-%d)" "$EMAIL" 2>/dev/null || true
    rm -f /tmp/stock_summary.txt
fi

# Send alerts if they exist
if [ -f "/tmp/stock_alerts.txt" ]; then
    ALERTS=$(cat /tmp/stock_alerts.txt)
    # Telegram
    openclaw message send --target "telegram:$TELEGRAM_TARGET" --message "$ALERTS"
    # Email
    echo "$ALERTS" | mail -s "Stock Alert - $(date +%Y-%m-%d %H:%M)" "$EMAIL" 2>/dev/null || true
    rm -f /tmp/stock_alerts.txt
fi
