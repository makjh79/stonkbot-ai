#!/bin/bash

# STONK.AI Trading Bot Launcher

echo "🤖 STONK.AI Trading Bot"
echo "========================"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python 3.8+"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Check for API keys (config file or env)
if [ -f "../alpaca_config.json" ]; then
    echo "✅ Found alpaca_config.json - using stored credentials"
elif [ -z "$ALPACA_API_KEY" ] || [ -z "$ALPACA_SECRET_KEY" ]; then
    echo ""
    echo "⚠️  Warning: Alpaca API credentials not found!"
    echo ""
    echo "Options:"
    echo "  1. Create ../alpaca_config.json with your credentials"
    echo "  2. Set environment variables:"
    echo "     export ALPACA_API_KEY='your_key'"
    echo "     export ALPACA_SECRET_KEY='your_secret'"
    echo ""
    exit 1
fi

# Run the bot
echo "🚀 Starting trading bot..."
echo "=========================="
echo "Mode: $([ "$ALPACA_PAPER" = "false" ] && echo "🔴 LIVE TRADING" || echo "🔧 PAPER TRADING")"
echo "=========================="
python3 alpaca_trader.py
