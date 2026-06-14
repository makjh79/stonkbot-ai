# GitHub Repository Setup Guide

## Option 1: Manual (Recommended)

1. **Create repo on GitHub:**
   - URL: https://github.com/new
   - Name: `stonkbot-ai`
   - Visibility: Public or Private
   - ✅ Initialize with README: NO
   - ✅ Add .gitignore: NO
   - ✅ Choose license: NO

2. **Push code:**
   ```bash
   cd /root/.openclaw/workspace
   git remote add origin https://github.com/YOUR_USERNAME/stonkbot-ai.git
   git push -u origin master
   ```

3. **Verify:**
   - Go to `https://github.com/YOUR_USERNAME/stonkbot-ai`
   - Should see all files

## Option 2: Using GitHub Token

If you have a GitHub Personal Access Token:

```bash
# Set your credentials
export GITHUB_TOKEN="your_token_here"
export GITHUB_USERNAME="your_username"

# Create repo via API
curl -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/user/repos \
  -d '{
    "name": "stonkbot-ai",
    "description": "AI-powered trading bot with $100K real portfolio",
    "private": false,
    "auto_init": false
  }'

# Push code
git remote add origin https://github.com/$GITHUB_USERNAME/stonkbot-ai.git
git push -u origin master
```

## What Gets Shared

The repository contains:
- `export/hedge-fund-website/` - Website HTML/JS/CSS
- `export/stonk-ai/` - Python trading bots
- `export/memory/` - Documentation
- `*.md` - Architecture guides, setup docs

## For Another AI to Access

1. **Give them GitHub URL:**
   `https://github.com/YOUR_USERNAME/stonkbot-ai`

2. **They clone it:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/stonkbot-ai.git
   cd stonkbot-ai
   ```

3. **They can now:**
   - Edit code
   - Submit pull requests
   - Collaborate with version control

## Live Site vs GitHub

- **Live site:** https://stonkbot.ai (for viewing)
- **GitHub repo:** For code collaboration
- **Local dev:** http://23.80.82.47:8080/ (your editing)

## Sync Changes

After another AI makes changes on GitHub:

```bash
cd /root/.openclaw/workspace
git pull origin master
# Updates your local copy
```

## Security Note

⚠️ **Don't commit:**
- API keys
- Alpaca credentials
- Passwords
- `.env` files

These are already in `.gitignore` ✓
