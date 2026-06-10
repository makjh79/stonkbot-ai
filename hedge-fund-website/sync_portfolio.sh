#!/bin/bash
# Sync portfolio data from live bot to website
# Run this every minute during market hours

SOURCE="/opt/stonk-ai/portfolio_data.json"
DEST="/root/.openclaw/workspace/hedge-fund-website/portfolio_data.json"

if [ -f "$SOURCE" ]; then
    # Check if source is newer or different
    if [ ! -f "$DEST" ] || [ "$SOURCE" -nt "$DEST" ]; then
        cp "$SOURCE" "$DEST"
        echo "$(date): Portfolio data synced"
    fi
fi
