# TOOLS.md - Local Notes

## ⚠️ CRITICAL: Website File Locations

**ALWAYS edit files in `/var/www/hedge-fund-website/`**
**NEVER edit files in `/root/.openclaw/workspace/hedge-fund-website/` (old/stale copy)**

The web server runs from `/var/www/hedge-fund-website/` on port 8080.
Changes to `/root/.openclaw/workspace/hedge-fund-website/` are NOT served.

**Key Files:**
- `/var/www/hedge-fund-website/index.html` - Main website (THIS IS THE ONE TO EDIT)
- `/var/www/hedge-fund-website/portfolio_data.json` - Live portfolio data
- `/var/www/hedge-fund-website/ai_watchlist_live.json` - Watchlist data

**Check before editing:**
```bash
ls -la /var/www/hedge-fund-website/index.html  # Should show recent timestamp
```

---

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

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## Related

- [Agent workspace](/concepts/agent-workspace)
