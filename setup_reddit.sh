#!/bin/bash
# Setup script for Reddit API credentials

echo "=========================================="
echo "STONK.AI Reddit Sentiment Setup"
echo "=========================================="
echo ""
echo "Follow these steps to get Reddit API credentials:"
echo ""
echo "1. Go to: https://www.reddit.com/prefs/apps"
echo "2. Click 'create another app...'"
echo "3. Select 'script' (for personal use)"
echo "4. Fill in:"
echo "   - Name: STONK.AI Sentiment"
echo "   - Description: Stock sentiment analysis"
echo "   - About URL: https://stonkbot.ai"
echo "   - Redirect URI: https://stonkbot.ai/callback"
echo "5. Click 'create app'"
echo ""
echo "You'll see:"
echo "   - personal use script (14 chars) = CLIENT_ID"
echo "   - secret (27 chars) = CLIENT_SECRET"
echo ""
read -p "Enter your CLIENT_ID: " client_id
read -p "Enter your CLIENT_SECRET: " client_secret

# Update config file
config_file="/opt/stonk-ai/reddit_config.json"
cat > "$config_file" << EOF
{
  "reddit": {
    "client_id": "$client_id",
    "client_secret": "$client_secret",
    "user_agent": "stonkbot-sentiment/1.0 by STONK.AI"
  }
}
EOF

echo ""
echo "✅ Credentials saved to $config_file"
echo ""
echo "Testing connection..."
python3 /opt/stonk-ai/reddit_sentiment_analyzer.py --test
