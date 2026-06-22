#!/bin/bash
cd /root/.openclaw/workspace
git pull origin master
cp /root/.openclaw/workspace/website/index.html /var/www/hedge-fund-website/index.html
cp /root/.openclaw/workspace/website/performance.html /var/www/hedge-fund-website/performance.html
cp /root/.openclaw/workspace/scripts/fetch_data_simple.py /opt/stonk-ai/fetch_data_simple.py
cp /root/.openclaw/workspace/scripts/health_check.py /opt/stonk-ai/health_check.py
cp /root/.openclaw/workspace/scripts/generate_sentiment.py /opt/stonk-ai/generate_sentiment.py
cp /root/.openclaw/workspace/scripts/run_sentiment.sh /opt/stonk-ai/run_sentiment.sh
cp /root/.openclaw/workspace/scripts/run_crowd_sentiment.sh /opt/stonk-ai/run_crowd_sentiment.sh
chmod +x /opt/stonk-ai/run_sentiment.sh /opt/stonk-ai/run_crowd_sentiment.sh
# Restart services that received code updates
systemctl restart data-fetcher.service
systemctl restart stonk-monitor.service
echo "Deployed at $(date)" >> /var/www/hedge-fund-website/deploy.log
