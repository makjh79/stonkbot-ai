#!/bin/bash
# Sync website changes from live to source and commit
# Usage: ./sync-website-changes.sh "Your commit message"

set -e

COMMIT_MSG="${1:-Sync website changes from live site}"
LIVE_FILE="/var/www/hedge-fund-website/index.html"
SOURCE_FILE="/root/.openclaw/workspace/website/index.html"
WORKSPACE_DIR="/root/.openclaw/workspace"

echo "🔄 Syncing website changes..."

# Check if live file exists
if [ ! -f "$LIVE_FILE" ]; then
    echo "❌ Error: Live file not found: $LIVE_FILE"
    exit 1
fi

# Check if there are differences
echo "🔍 Checking for changes..."
if diff -q "$LIVE_FILE" "$SOURCE_FILE" > /dev/null 2>&1; then
    echo "✅ No changes to sync (files are identical)"
    exit 0
fi

# Show diff summary
echo "📝 Changes detected:"
diff -u "$SOURCE_FILE" "$LIVE_FILE" | head -20

echo ""
echo "💾 Copying live changes to source..."
cp "$LIVE_FILE" "$SOURCE_FILE"

echo "📤 Committing to Git..."
cd "$WORKSPACE_DIR"
git add website/index.html
git commit -m "$COMMIT_MSG"

echo "🚀 Pushing to GitHub (triggers auto-deploy)..."
git push origin master

echo ""
echo "✅ Done! Changes synced and deployed."
echo "⏳ Wait ~30 seconds for auto-deploy to complete."
echo "📋 Check status: tail /var/www/hedge-fund-website/deploy.log"
