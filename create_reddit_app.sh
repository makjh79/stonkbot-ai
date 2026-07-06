#!/bin/bash
# Automated Reddit App Setup Helper

clear
echo "═══════════════════════════════════════════════════════"
echo "  STONK.AI - Reddit App Setup Assistant"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "This script will help you create a Reddit app."
echo ""
echo "📱 STEP 1: Open this URL in your browser:"
echo ""
echo "   https://www.reddit.com/prefs/apps"
echo ""
echo "   (Make sure you're logged into Reddit)"
echo ""
read -p "Press ENTER when you've opened the URL..."

clear
echo "═══════════════════════════════════════════════════════"
echo "  STEP 2: Create the App"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "1. Scroll to bottom and click 'create another app...'"
echo ""
echo "2. Fill in these EXACT values:"
echo ""
echo "   ┌────────────────────────────────────────────────────┐"
echo "   │  Name:           STONK.AI Sentiment                │"
echo "   │  App type:       ☑️ script (for personal use)      │"
echo "   │  Description:    Stock sentiment analysis          │"
echo "   │  About URL:      https://stonkbot.ai             │"
echo "   │  Redirect URI:   https://stonkbot.ai/callback    │"
echo "   └────────────────────────────────────────────────────┘"
echo ""
echo "3. Click 'create app'"
echo ""
read -p "Press ENTER when you've created the app..."

clear
echo "═══════════════════════════════════════════════════════"
echo "  STEP 3: Get Your Credentials"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "After creating, you'll see two values:"
echo ""
echo "   personal use script   xxxxxxxxxxxxxx  ← 14 chars"
echo "   secret                xxxxxxxxxxxxxxxxxxxxxxxxxxx  ← 27 chars"
echo ""
echo "⚠️  IMPORTANT: Copy these NOW - the secret won't be shown again!"
echo ""
read -p "Press ENTER when you have your credentials ready..."

clear
echo "═══════════════════════════════════════════════════════"
echo "  STEP 4: Save Credentials"
echo "═══════════════════════════════════════════════════════"
echo ""

# Get credentials from user
read -p "Enter CLIENT_ID (14 chars): " client_id
read -p "Enter CLIENT_SECRET (27 chars): " client_secret

# Validate
if [ ${#client_id} -ne 14 ]; then
    echo "❌ Error: CLIENT_ID should be 14 characters, got ${#client_id}"
    exit 1
fi

if [ ${#client_secret} -ne 27 ]; then
    echo "❌ Error: CLIENT_SECRET should be 27 characters, got ${#client_secret}"
    exit 1
fi

# Save to config
cat > /opt/stonk-ai/reddit_config.json << EOF
{
  "reddit": {
    "client_id": "$client_id",
    "client_secret": "***",
    "user_agent": "stonkbot-sentiment/1.0 by STONK.AI"
  }
}
EOF

chmod 600 /opt/stonk-ai/reddit_config.json

echo ""
echo "✅ Credentials saved to /opt/stonk-ai/reddit_config.json"
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  STEP 5: Test Connection"
echo "═══════════════════════════════════════════════════════"
echo ""

# Run test
python3 /opt/stonk-ai/reddit_sentiment_analyzer.py --test

if [ $? -eq 0 ]; then
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  ✅ SUCCESS! Reddit Sentiment is Ready!"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    echo "The analyzer will run automatically every 30 minutes."
    echo "First run will happen within 30 minutes."
    echo ""
    echo "Your watchlist will now show REAL Reddit sentiment!"
    echo ""
else
    echo ""
    echo "❌ Test failed. Please check your credentials and try again."
    echo "   Run this script again: /opt/stonk-ai/create_reddit_app.sh"
fi
