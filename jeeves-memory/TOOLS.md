# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### SSH

- **stonkbot-ai-web** → 23.80.82.47, user: root, key: `~/.openclaw/workspace/.ssh/id_stonkbot_root`
  - Live web root: `/var/www/hedge-fund-website/`
  - Nginx config: `/etc/nginx/sites-enabled/mak-capital`
  - Note: Cloudflare sits in front of the HTTP origin on this host.

### Finnhub API

- Key saved at: `~/.openclaw/workspace/.secrets/finnhub.key` (chmod 600)
- Used for: watchlist popup news sentiment
- Server script: `/root/.openclaw/workspace/scripts/generate_sentiment.py`
- Cron: hourly at `0 * * * *`

### macOS Local Voice

- Skill: `macos-local-voice` (ClawHub) — status: ready
- `yap` binary: `~/.openclaw/workspace/bin/yap` → symlinked to `~/.local/bin/yap`
- `ffmpeg` binary: `~/.openclaw/workspace/bin/ffmpeg` → symlinked to `~/.local/bin/ffmpeg`
- **Default English voice:** `Daniel` (British)
- Locale quirk: system locale `en_US@rg=hkzzzz` is not supported by `yap`; always pass locale explicitly, e.g. `node stt.mjs <file> en_US`
- Use for: local STT/TTS without API keys or network

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
- Local fallback: `Daniel` (macOS built-in)
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Related

- [Agent workspace](/concepts/agent-workspace)
