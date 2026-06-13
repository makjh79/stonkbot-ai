# ngrok Setup - Stable URL for STONK.AI

## One-Time Setup (5 minutes)

### 1. Sign Up (Free)
- Go to https://ngrok.com
- Sign up with email
- Get your authtoken from dashboard

### 2. Install
```bash
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok
```

### 3. Configure
```bash
ngrok config add-authtoken YOUR_TOKEN_HERE
```

### 4. Start (Always Same URL!)
```bash
# Start server (keep running)
sudo systemctl start stonk-ai-website

# Start tunnel (in tmux so it stays running)
tmux new -s ngrok
ngrok http 8080 --subdomain=stonk-ai-stable

# Detach: Ctrl+B then D
# Reattach: tmux attach -t ngrok
```

### 5. Bookmark This URL
**https://stonk-ai-stable.ngrok.io**

Never changes! Works on your phone, laptop, anywhere.

---

## Troubleshooting

**If ngrok stops:**
```bash
tmux attach -t ngrok
# Press Up arrow, Enter to restart
```

**If server stops:**
```bash
sudo systemctl restart stonk-ai-website
```

**Free tier limits:**
- 1 static subdomain ✓
- 40 connections/minute ✓ (plenty for 1 user)
- No credit card required ✓

---

## Alternative: Just Use Server IP

If you're on the same WiFi as the server:
```
http://23.80.82.47:8080
```

No tunnel needed! But won't work on mobile data.
