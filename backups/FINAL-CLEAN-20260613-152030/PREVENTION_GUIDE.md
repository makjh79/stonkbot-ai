# Prevention Guide: Avoiding Sync Issues

## What Went Wrong Today

1. **Hardcoded data in HTML** - `companyInfo` object had stale symbols
2. **No verification** - Changes to watchlist weren't validated
3. **No atomic updates** - Price data and company info updated separately

## Prevention System (Now Implemented)

### 1. Daily Automated Verification

**Runs every day at 7 PM:**
```
✅ Sync check (watchlist vs company_info vs prices)
✅ Threshold consistency (bot vs manager vs website)
✅ Price accuracy (vs Yahoo Finance)
```

**If issues found:**
- Logs specific mismatches
- Suggests fixes
- Alerts via system logs

### 2. Manual Verification Commands

Run these after ANY change:

```bash
# Check all files are in sync
cd /opt/stonk-ai && python3 verify_sync.py

# Check RSI/volume thresholds match
cd /opt/stonk-ai && python3 verify_thresholds.py

# Check prices vs Yahoo
cd /opt/stonk-ai && python3 verify_prices.py
```

### 3. Architecture Rules

**✅ DO:**
- Fetch all data from JSON files dynamically
- Update cache buster on every HTML change
- Run verification after any config change
- Use atomic updates (update all related files together)

**❌ DON'T:**
- Hardcode symbol lists in HTML
- Update only one component (website but not bot)
- Skip verification after changes
- Forget to increment cache buster

### 4. Change Checklist

Before completing any task:

- [ ] Ran `verify_sync.py` - no errors?
- [ ] Ran `verify_thresholds.py` - consistent?
- [ ] Cache buster incremented in HTML?
- [ ] Hard refresh tested in browser?
- [ ] All 3 components (website/bot/manager) updated?

### 5. Emergency Fix

If sync breaks:

```bash
# 1. Force manager refresh
cd /opt/stonk-ai && python3 dynamic_watchlist_manager.py

# 2. Verify
python3 verify_sync.py

# 3. Update cache buster in index.html

# 4. Hard refresh browser
```

## Files Location

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | System design principles |
| `PREVENTION_GUIDE.md` | This file - how to avoid issues |
| `verify_sync.py` | Check symbol alignment |
| `verify_thresholds.py` | Check RSI/volume consistency |
| `verify_prices.py` | Check price accuracy |

## Current Status

```
✅ Daily verification: Enabled (7 PM daily)
✅ Symbol sync: 20 symbols aligned
✅ Thresholds: RSI <35, volume 1.5x (all components)
✅ Dynamic loading: company_info.json auto-updates
```

## Next Time You Make Changes

1. Update the relevant component(s)
2. Run verification scripts
3. Fix any issues
4. Increment cache buster
5. Test with hard refresh
6. Done!

**The system now self-checks daily and prevents manual errors.**
