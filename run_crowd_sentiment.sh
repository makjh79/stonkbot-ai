#!/bin/bash
# Clear stale crowd sentiment lock files older than 90 minutes
find /tmp -maxdepth 1 -name "crowd_sentiment.lock" -mmin +90 -delete 2>/dev/null
cd /opt/stonk-ai
/usr/bin/timeout 300 /usr/bin/flock -n /tmp/crowd_sentiment.lock python3 /opt/stonk-ai/fetch_crowd_sentiment.py >> /var/log/crowd_sentiment.log 2>&1
