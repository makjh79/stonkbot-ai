# TOOLS.md - Local Notes

## ⚠️ CRITICAL: Website File Locations (GitHub Auto-Deploy)

**⚠️ WARNING: GitHub auto-deploy is ENABLED**
Any push to GitHub will overwrite `/var/www/hedge-fund-website/index.html`

### Correct Workflow:

**Option 1: Edit source file (RECOMMENDED)**
```bash
# Edit the source file
nano /root/.openclaw/workspace/website/index.html

# Commit and push (triggers auto-deploy)
cd /root/.openclaw/workspace
git add website/index.html
git commit -m "Your changes"
git push origin master

# Wait 30 seconds for auto-deploy
```

**Option 2: Edit live file (QUICK TEST)**
```bash
# Edit live file
nano /var/www/hedge-fund-website/index.html

# Sync back to source (CRITICAL - or changes will be lost!)
cp /var/www/hedge-fund-website/index.html /root/.openclaw/workspace/website/index.html
cd /root/.openclaw/workspace
git add website/index.html
git commit -m "Sync live changes"
git push origin master
```

**Option 3: Helper script**
```bash
# After editing live file, run this to sync and commit:
/root/.openclaw/workspace/sync-website-changes.sh "Your commit message"
```

### Key Files:
- **Source:** `/root/.openclaw/workspace/website/index.html` → GitHub → Auto-deploy
- **Live:** `/var/www/hedge-fund-website/index.html` (OVERWRITTEN on deploy!)
- **Data:** `/var/www/hedge-fund-website/portfolio_data.json` (bot-generated, safe)

### Check Deploy Status:
```bash
tail /var/www/hedge-fund-website/deploy.log
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
