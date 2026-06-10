#!/bin/bash
# STONK.AI Complete Setup Script
# Sets up both data fetcher and autonomous trading bot

set -e

echo "🤖 STONK.AI Complete Setup"
echo "=========================="
echo ""

# Create user
sudo useradd -r -s /bin/false stonkai 2>/dev/null || echo "User already exists"

# Create directory
sudo mkdir -p /opt/stonk-ai
sudo cp -r * /opt/stonk-ai/

# Set permissions
sudo chown -R stonkai:stonkai /opt/stonk-ai

# Install dependencies
cd /opt/stonk-ai
echo "📦 Installing dependencies..."
sudo pip3 install -q alpaca-trade-api python-dotenv requests

# Copy env file if not exists
if [ ! -f /opt/stonk-ai/.env ]; then
    sudo cp .env.example /opt/stonk-ai/.env
    echo ""
    echo "⚠️  IMPORTANT: You must edit /opt/stonk-ai/.env with your Alpaca API keys!"
    echo ""
fi

# Install systemd services
echo "🔧 Installing services..."
sudo cp data-fetcher.service /etc/systemd/system/
sudo cp stonk-ai.service /etc/systemd/system/
sudo systemctl daemon-reload

echo ""
echo "✅ Setup Complete!"
echo "=================="
echo ""
echo "📁 Files installed to: /opt/stonk-ai/"
echo ""
echo "Next Steps:"
echo "-----------"
echo "1. Edit config:  sudo nano /opt/stonk-ai/.env"
echo "   Add your Alpaca API keys (paper trading recommended)"
echo ""
echo "2. Review strategy:  cat /opt/stonk-ai/STRATEGY.md"
echo "   Understand the autonomous trading rules"
echo ""
echo "3. Start services:"
echo "   sudo systemctl start data-fetcher   # Website data"
echo "   sudo systemctl start stonk-ai       # Trading bot"
echo ""
echo "4. Enable auto-start:"
echo "   sudo systemctl enable data-fetcher"
echo "   sudo systemctl enable stonk-ai"
echo ""
echo "5. Check status:"
echo "   sudo systemctl status data-fetcher"
echo "   sudo systemctl status stonk-ai"
echo ""
echo "6. View logs:"
echo "   sudo journalctl -u data-fetcher -f"
echo "   sudo journalctl -u stonk-ai -f"
echo ""
echo "📊 Website files:"
echo "   - index.html - Main dashboard"
echo "   - portfolio_data.json - Live data (auto-updated)"
echo ""
echo "🤖 Bot files:"
echo "   - trading_bot.py - Autonomous trading"
echo "   - STRATEGY.md - Complete strategy rules"
echo "   - TRADES_LOG.md - Trade history"
echo ""
echo "⚠️  IMPORTANT SAFETY NOTES:"
echo "   - Start with PAPER trading (fake money)"
echo "   - Bot runs autonomously - review STRATEGY.md first"
echo "   - Emergency triggers will alert you to check logs"
echo "   - Contact Jarvis only for emergencies or scheduled reviews"
echo ""
echo "💰 Costs:"
echo "   - Data Fetcher: $0 (your server)"
echo "   - Trading Bot: $0 (your server)"
echo "   - Website: $0 (GitHub/Cloudflare Pages)"
echo "   - AI Assistant: $0 unless you contact for help"
echo ""
