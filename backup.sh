#!/bin/bash
# STONK.AI Backup Script
# Backs up critical data files daily

BACKUP_DIR="/opt/stonk-ai/backups"
DATA_DIR="/var/www/hedge-fund-website"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory if not exists
mkdir -p $BACKUP_DIR

# Backup portfolio history
cp $DATA_DIR/portfolio_history.json $BACKUP_DIR/portfolio_history_$DATE.json 2>/dev/null

# Backup trades log
cp $DATA_DIR/trades_log.json $BACKUP_DIR/trades_log_$DATE.json 2>/dev/null

# Backup signals
cp /opt/stonk-ai/signals.json $BACKUP_DIR/signals_$DATE.json 2>/dev/null

# Keep only last 30 days of backups
find $BACKUP_DIR -name "*.json" -mtime +30 -delete

echo "✅ Backup completed: $DATE"
echo "   Files backed up:"
echo "   - portfolio_history.json"
echo "   - trades_log.json"
echo "   - signals.json"
