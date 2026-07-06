# signal_engine.py Patch Guide

## Phase 1: json_compat bridge (5-minute change)

At the **top** of `signal_engine.py`, replace:
```python
import json
```
with:
```python
import json  # keep this as fallback
from json_compat import load, dump, set_source
set_source("signal_engine")
```

Then find your **write** logic (usually near the end):
```python
# OLD:
with open("/opt/stonk-ai/signals.json", "w") as f:
    json.dump(signals, f)
```
Replace with:
```python
# NEW:
dump(signals, "/opt/stonk-ai/signals.json", run_id=run_timestamp)
```

That's it. The script will:
1. Write to SQLite `signals` table (atomic, no collisions)
2. Mirror to `/var/www/hedge-fund-website/signals.json` for the frontend
3. Record its own heartbeat

## Phase 2: Native stonkbot_db (15-minute change)

Replace the import block:
```python
from stonkbot_db import save_signals, heartbeat, export_json_mirrors
```

Replace the write logic:
```python
# OLD:
dump(signals, "/opt/stonk-ai/signals.json", run_id=run_timestamp)

# NEW:
save_signals(signals, run_id=run_timestamp, generated_at=run_timestamp)
heartbeat("signal_engine", status="ok")
export_json_mirrors()
```

## Phase 3: Remove JSON file references entirely

Search for these strings in signal_engine.py and delete or replace:
- `/opt/stonk-ai/signals.json` → remove (DB is source of truth)
- `/var/www/.../signals.json` → remove (mirror is handled by `export_json_mirrors()`)

## What stays unchanged

- `signals` object structure (list of dicts)
- Scoring logic, confirmation calculation
- Anything that reads data — change `json.load()` to `load()` only

## Verification after deploy

```bash
# After running signal_engine once:
python3 -c "
from stonkbot_db import get_signals
sigs = get_signals()
print(f'Signals in DB: {len(sigs)}')
print(f'PRIME count: {len([s for s in sigs if s[\"frontend_tier\"] == \"PRIME\"])}')
"
```

You should see matching counts vs old signals.json.
