#!/bin/bash
# Clear stale sentiment lock files older than 90 minutes
find /tmp -maxdepth 1 -name "sentiment.lock" -mmin +90 -delete 2>/dev/null
find /tmp -maxdepth 1 -name "crowd_sentiment.lock" -mmin +90 -delete 2>/dev/null
cd /opt/stonk-ai
/usr/bin/timeout 600 /usr/bin/flock -n /tmp/sentiment.lock python3 /opt/stonk-ai/generate_sentiment.py >> /var/log/stonkbot_sentiment.log 2>&1
