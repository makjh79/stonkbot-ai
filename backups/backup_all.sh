#!/bin/bash
# Comprehensive backup script for STONK.AI trading bot and website

BACKUP_DIR="/root/.openclaw/workspace/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="stonkai_backup_${TIMESTAMP}"

echo "🔄 Starting comprehensive backup..."
echo "Timestamp: $TIMESTAMP"

# Create temp backup directory
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}"

# 1. Backup trading bot code
echo "📦 Backing up trading bot..."
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}/stonk-ai"
cp -r /opt/stonk-ai/* "${BACKUP_DIR}/${BACKUP_NAME}/stonk-ai/" 2>/dev/null || echo "  ⚠️  Some files in /opt/stonk-ai/ not copied"

# 2. Backup website files
echo "🌐 Backing up website..."
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}/website"
cp /var/www/hedge-fund-website/*.html "${BACKUP_DIR}/${BACKUP_NAME}/website/" 2>/dev/null
cp /var/www/hedge-fund-website/*.json "${BACKUP_DIR}/${BACKUP_NAME}/website/" 2>/dev/null
cp /var/www/hedge-fund-website/*.js "${BACKUP_DIR}/${BACKUP_NAME}/website/" 2>/dev/null
cp /var/www/hedge-fund-website/*.css "${BACKUP_DIR}/${BACKUP_NAME}/website/" 2>/dev/null

# 3. Backup workspace files
echo "💼 Backing up workspace..."
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}/workspace"
cp -r /root/.openclaw/workspace/*.md "${BACKUP_DIR}/${BACKUP_NAME}/workspace/" 2>/dev/null
cp -r /root/.openclaw/workspace/*.sh "${BACKUP_DIR}/${BACKUP_NAME}/workspace/" 2>/dev/null
cp -r /root/.openclaw/workspace/*.py "${BACKUP_DIR}/${BACKUP_NAME}/workspace/" 2>/dev/null

# 4. Backup configuration
echo "⚙️  Backing up configuration..."
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}/config"
crontab -l > "${BACKUP_DIR}/${BACKUP_NAME}/config/crontab.txt" 2>/dev/null
ls -la /opt/stonk-ai/ > "${BACKUP_DIR}/${BACKUP_NAME}/config/stonkai_files.txt" 2>/dev/null
ls -la /var/www/hedge-fund-website/ > "${BACKUP_DIR}/${BACKUP_NAME}/config/website_files.txt" 2>/dev/null

# 5. Backup systemd services (if any)
echo "🔧 Backing up systemd services..."
mkdir -p "${BACKUP_DIR}/${BACKUP_NAME}/systemd"
cp /etc/systemd/system/stonk-ai.service "${BACKUP_DIR}/${BACKUP_NAME}/systemd/" 2>/dev/null
cp /etc/systemd/system/data-fetcher.service "${BACKUP_DIR}/${BACKUP_NAME}/systemd/" 2>/dev/null

# 6. Create manifest
echo "📝 Creating manifest..."
cat > "${BACKUP_DIR}/${BACKUP_NAME}/MANIFEST.txt" << EOF
STONK.AI Backup Manifest
==========================
Timestamp: $(date)
Backup Name: ${BACKUP_NAME}

Contents:
- stonk-ai/        : Trading bot code and scripts
- website/         : Website HTML, CSS, JS, JSON files
- workspace/       : Workspace configuration and helper scripts
- config/          : Cron jobs, file listings
- systemd/         : Systemd service files

Git Repository:
$(cd /root/.openclaw/workspace && git remote -v 2>/dev/null || echo "Git info unavailable")

Last Commit:
$(cd /root/.openclaw/workspace && git log -1 --oneline 2>/dev/null || echo "Git info unavailable")
EOF

# 7. Create tarball
echo "📦 Creating tarball..."
cd "${BACKUP_DIR}"
tar -czf "${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}"
rm -rf "${BACKUP_NAME}"

# 8. Clean up old backups (keep last 10)
echo "🧹 Cleaning up old backups..."
ls -t ${BACKUP_DIR}/stonkai_backup_*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm

BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)

echo ""
echo "✅ Backup Complete!"
echo "==================="
echo "Backup: ${BACKUP_NAME}.tar.gz"
echo "Size: ${BACKUP_SIZE}"
echo "Location: ${BACKUP_DIR}/"
echo ""
echo "Files backed up:"
ls -1 "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
