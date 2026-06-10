# Website Transparency Features

## Suggested Additions for STONK.AI Website

### 1. Strategy Panel (Static)
Show the complete trading strategy:
```
📋 STRATEGY RULES
━━━━━━━━━━━━━━━━━━━━
Stop Loss: -15%
Take Profit: +25% (trim), +50% (exit)
Max Position: 15%
Cash Buffer: 35%
Trade Limits: 3/day, 10/week
```

### 2. Bot Status Panel (Live)
Show current bot status:
```
🤖 BOT STATUS
━━━━━━━━━━━━━━━━━━━━
Status: Active ✅
Mode: Paper Trading
Last Check: 2 minutes ago
Next Trade Window: Market Open
Daily Trades: 0/3
Weekly Trades: 0/10
```

### 3. Pending Actions (Live)
Show what the bot is watching:
```
👀 MONITORING
━━━━━━━━━━━━━━━━━━━━
📉 Near Stop Loss: None
📈 Near Take Profit: None
⚖️ Rebalance Needed: No
💰 Cash Deployable: Yes (35%)
```

### 4. Trade Log (Recent)
Show last 5 trades:
```
📊 RECENT ACTIVITY
━━━━━━━━━━━━━━━━━━━━
BUY 10 AMD @ $464 - Take profit trim
BUY 20 PLTR @ $137 - Buy the dip
(No stop losses today)
```

### 5. Decision Rationale
When trades happen, show why:
```
🧠 LAST DECISION
━━━━━━━━━━━━━━━━━━━━
Bought 10 AMD
Reason: Stop loss at -15% not hit,
position down -6.7%, thesis intact,
buying the dip per strategy.
Confidence: High
```

## Implementation Options

### Option A: Simple Status Banner
Add to index.html - static strategy + live bot status

### Option B: Live Activity Feed
Bot writes to activity.json, website displays

### Option C: Full Transparency Dashboard
New page showing all bot decisions and reasoning

## My Recommendation

**Start with Option A** - Add these 3 panels to index.html:
1. Strategy Rules (static)
2. Bot Status (reads from portfolio_data.json)
3. Recent Activity (reads from TRADES_LOG.md)

This gives visitors confidence that the bot is:
- ✅ Following clear rules
- ✅ Active and monitoring
- ✅ Making transparent decisions

Want me to add these panels to the website?
