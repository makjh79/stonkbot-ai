# trading_bot.py Patch Guide

`trading_bot.py` writes at least two files:
1. `portfolio_data.json` — current holdings + summary
2. `portfolio_history.json` — daily appended history

## Phase 1: json_compat bridge (10-minute change)

At the **top** of `trading_bot.py`:
```python
from json_compat import load, dump, set_source
set_source("trading_bot")
```

### Replace portfolio_data write

Find:
```python
with open("/opt/stonk-ai/portfolio_data.json", "w") as f:
    json.dump({
        "summary": portfolio_summary,
        "holdings": holdings,
        "timestamp": now,
    }, f)
```

Replace with:
```python
portfolio_data = {
    "summary": portfolio_summary,
    "holdings": holdings,
    "timestamp": now,
}
dump(portfolio_data, "/opt/stonk-ai/portfolio_data.json")
```

### Replace portfolio_history write

Find:
```python
with open("/opt/stonk-ai/portfolio_history.json", "a") as f:  # or write
    # append logic
```

Replace with:
```python
history_record = {
    "date": today,
    "cash": summary["cash"],
    "equity": summary["equity"],
    "total_value": summary["total_value"],
    "day_pnl": summary.get("day_pnl"),
    "total_pnl": summary.get("total_pnl"),
    "positions": len(holdings),
}
dump(history_record, "/opt/stonk-ai/portfolio_history.json")
```

Note: `dump()` on `portfolio_history.json` will call `append_history()` — 
it adds one row, not a full list. If your old logic built a full list and
rewrote it, that still works: pass the list and each element gets appended.

## Phase 2: Native stonkbot_db (15-minute change)

```python
from stonkbot_db import save_portfolio, append_history, heartbeat, export_json_mirrors, get_portfolio

# Write portfolio
save_portfolio(portfolio_summary, holdings)

# Write history row
append_history({
    "date": today,
    "cash": portfolio_summary["cash"],
    "equity": portfolio_summary["equity"],
    "total_value": portfolio_summary["total_value"],
    "day_pnl": portfolio_summary.get("day_pnl"),
    "total_pnl": portfolio_summary.get("total_pnl"),
    "positions": len(holdings),
})

heartbeat("trading_bot", status="ok")
export_json_mirrors()
```

## Phase 3: Read portfolio (if you read it back)

Some logic may re-read `portfolio_data.json` mid-run. Replace:
```python
with open("/opt/stonk-ai/portfolio_data.json") as f:
    data = json.load(f)
```
with:
```python
data = get_portfolio()  # returns dict with summary + holdings
```

## What stays unchanged

- Order execution logic (Alpaca API calls)
- Position sizing logic
- Stop-loss management
- Any Alpaca-specific code

## Rollback note

If you need to switch back to JSON-raw mode:
```python
from json_compat import enable_db
enable_db(False)  # raw JSON mode
```
All `dump()` calls then write actual JSON files again.
