# StonkBOT SQLite Migration — Deployment Package

## What's in this package

| File | Purpose |
|------|---------|
| `stonkbot_schema_v1.sql` | SQLite schema — run once |
| `migrate_to_sqlite.py` | One-shot migration from JSON files |
| `stonkbot_db.py` | Core DB wrapper — import in all scripts |
| `stonkbot_healthcheck.py` | Unified healthcheck (replaces monitor) |
| `json_compat.py` | **Backward-compat adapter** — drop-in replacement for json.load/json.dump calls so scripts don't need rewrites yet |
| `systemd/stonkbot-healthcheck.service` | Systemd service for healthcheck |
| `systemd/stonkbot-healthcheck.timer` | Runs every 5 min during market hours |
| `systemd/stonkbot-db-ready.service` | Dummy target so other units know DB is ready |
| `patches/signal_engine_patch.md` | How to convert signal_engine.py |
| `patches/trading_bot_patch.md` | How to convert trading_bot.py |
| `deploy.sh` | Copies all files + sets permissions |

## Deployment Steps

### 1. Copy files to VPS

```bash
# From your local machine, copy this folder to VPS
rsync -avz stonkbot-sqlite/ root@23.80.82.47:/opt/stonk-ai/
```

Then on VPS:
```bash
cd /opt/stonk-ai
chmod +x migrate_to_sqlite.py stonkbot_healthcheck.py deploy.sh
chmod 0644 stonkbot_schema_v1.sql stonkbot_db.py json_compat.py
```

### 2. Back up current state

```bash
mkdir -p /opt/stonk-ai/backup-json-$(date +%Y%m%d)
cp /opt/stonk-ai/*.json /opt/stonk-ai/backup-json-$(date +%Y%m%d)/
cp /var/www/hedge-fund-website/*.json /opt/stonk-ai/backup-json-$(date +%Y%m%d)/
```

### 3. **STOP TRADING**

```bash
# Stop anything that writes JSONs
sudo systemctl stop stonk-ai-trading-bot  # or however it's named
sudo systemctl stop stonk-ai-signal-engine
sudo systemctl stop stonk-ai-watchlist-manager
# Wait 2 minutes to ensure all cron cycles complete
sleep 120
```

### 4. Create database

```bash
cd /opt/stonk-ai
sqlite3 stonkbot.db < stonkbot_schema_v1.sql
chown stonkai:stonkai stonkbot.db
chmod 0644 stonkbot.db
```

### 5. Run migration

```bash
cd /opt/stonk-ai
python3 migrate_to_sqlite.py
```

Look for:
```
✅ All checks passed
📁 JSON mirrors written to /var/www/hedge-fund-website
```

If validation fails, **DO NOT PROCEED**. Review the counts.

### 6. Install systemd units

```bash
sudo cp systemd/stonkbot-*.service systemd/stonkbot-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable stonkbot-healthcheck.timer
sudo systemctl start stonkbot-healthcheck.timer
sudo systemctl enable stonkbot-db-ready.service
```

### 7. Enable healthcheck + test

```bash
python3 /opt/stonk-ai/stonkbot_healthcheck.py --check --report
# Should print: ✅ All systems healthy
```

### 8. Re-enable trading with JSON adapter (Phase 1)

Phase 1 uses `json_compat.py` — your scripts can keep using `json.load()` and `json.dump()` patterns, but data goes to SQLite.

Example patch for `signal_engine.py`:

```python
# At top of signal_engine.py, replace:
# import json
# with:
from json_compat import load, dump, set_source
set_source("signal_engine")  # tells DB who is writing

# Then replace:
# with open("/opt/stonk-ai/signals.json", "w") as f:
#     json.dump(signals, f)
# with:
dump(signals, "/opt/stonk-ai/signals.json")
```

That's it. `json_compat.py` intercepts the write, stores to SQLite, AND writes the JSON mirror so the website still works.

### 9. Gradual hardening (Phase 2)

Over the next week, replace `json_compat` calls with native `stonkbot_db.py` calls:

```python
from stonkbot_db import save_signals, heartbeat, export_json_mirrors

save_signals(signals, run_id=run_id)
heartbeat("signal_engine", status="ok")
export_json_mirrors()
```

This gives you atomic writes, validation, and no JSON file locking.

### 10. Remove old files (after 1 week of stable operation)

```bash
# Once you're confident, delete the old JSON-only cron jobs
rm /opt/stonk-ai/check_sentiment_freshness.py  # if it only wrote JSONs
rm /opt/stonk-ai/heartbeat_tracker.py  # replaced by DB heartbeats
# Keep backup-json-YYYYMMDD folder forever
```

## Migration Priority

Convert in this order:

1. `signal_engine.py` → `save_signals()` (fixes your signals write failures)
2. `trading_bot.py` → `save_portfolio()` + `get_portfolio()`
3. `fetch_ai_watchlist.py` → `save_watchlist()` (eliminates dual-writer bug)
4. `comprehensive_monitor.py` → delete, use `stonkbot_healthcheck.py`
5. `heartbeat_tracker.py` → delete, use `stonkbot_db.heartbeat()`
6. Everything else → `json_compat.py` bridge

## Rollback Plan

If anything goes wrong:

```bash
# 1. Stop new scripts
sudo systemctl stop stonkbot-healthcheck.timer

# 2. Restore JSON files
sudo cp /opt/stonk-ai/backup-json-$(date +%Y%m%d)/*.json /opt/stonk-ai/
sudo cp /opt/stonk-ai/backup-json-$(date +%Y%m%d)/*.json /var/www/hedge-fund-website/

# 3. Revert script changes (git checkout or remove json_compat import)
# 4. Restart old services
```

The JSON files are untouched during the migration — `migrate_to_sqlite.py` only reads them. Your originals stay in place until you delete them.

## Known Gotchas

- **WAL mode** creates `stonkbot.db-wal` and `stonkbot.db-shm` files. These are normal. Don't delete them while DB is open.
- If a script crashes mid-write, SQLite rolls back. JSON files would be half-written.
- `json_compat.py` requires `set_source()` to know which process is writing. Call it once at module load.
- `stonkbot_db.py` checks `STONKBOT_DB` env var for path override. Default is `/opt/stonk-ai/stonkbot.db`.
