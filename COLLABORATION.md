# STONK.AI Collaboration Guide

> For AI assistants collaborating on the STONK.AI trading bot

## Quick Access

- **Repo**: `https://github.com/makjh79/stonkbot-ai`
- **Live Site**: Auto-deploys on every push to `master`
- **Owner**: H Mak (Howie)

## Setup

```bash
# Clone the repo
git clone https://github.com/makjh79/stonkbot-ai.git
cd stonkbot-ai

# Create a branch for your changes
git checkout -b feature/your-change-name
```

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
