# STONK.AI Collaboration Guide

> For AI assistants collaborating on the STONK.AI trading bot

## Quick Access

- **Repo**: `https://github.com/makjh79/stonkbot-ai`
- **Live Site**: Auto-deploys on every push to `master`
- **Staging Branch**: `staging` (for testing before production)
- **Owner**: H Mak (Howie)

## Multi-Agent Workflow (STAGING BRANCH)

**⚠️ CRITICAL: Never push directly to `master`. Auto-deploy is LIVE.**

### For Frontend Changes (Jeeves/Jarvis)

```bash
# 1. Always start fresh from master
git checkout main
git pull origin main

# 2. Switch to staging branch
git checkout staging
git pull origin staging

# 3. Make your changes to website/index.html
# Edit, test locally if possible

# 4. Commit with [READY] flag when done
git add website/index.html
git commit -m "[READY] Fix: Clear description of what changed"
git push origin staging

# 5. Notify H Mak — he'll review and merge to master
```

### What [READY] Means
- Code is complete and tested
- Ready for H Mak to review
- No more changes coming in this batch

### Jarvis (Me) Will
- Merge staging → master when H Mak approves
- Handle any conflicts between our changes
- Keep master stable

### Coordination Rules
1. **Check before you start**: `git fetch origin` — see if staging has unmerged changes
2. **One agent at a time on staging** — coordinate with Jarvis if both working
3. **Small, focused commits** — easier to review and rollback
4. **Never commit API keys** — already gitignored, but important

## Setup (Old Workflow - use staging above instead)

## Critical Files

| File | Purpose | Auto-Deploys? |
|------|---------|---------------|
| `website/index.html` | Live dashboard | ✅ Yes (30s delay) |
| `alpaca_config.json` | API keys | ❌ Never (gitignored) |

## Bot Files (Read-Only Suggestions)

Bot code lives in `/opt/stonk-ai/` on the server. To suggest changes:

1. Copy the file to this repo's `suggestions/` folder
2. Add comments explaining your changes
3. Submit PR for review

## Workflow

### 1. Make Changes

Edit files in `workspace/` directory.

### 2. Test if Possible

For HTML changes: open `website/index.html` in browser.

### 3. Commit

```bash
git add website/index.html
git commit -m "Fix: Clear description of what changed and why"
```

### 4. Push & Deploy

```bash
# If you have write access
git push origin master

# Auto-deploy triggers in ~30 seconds
# Check live site to verify
```

## ⚠️ Rules

1. **Never commit API keys** — `alpaca_config.json` is gitignored
2. **Test HTML locally first** — prevents broken live site
3. **Clear commit messages** — owner needs to understand changes
4. **Don't break the bot** — trading logic changes need discussion

## Questions?

Tag `@makjh79` in commit messages or PR descriptions.
