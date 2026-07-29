#!/usr/bin/env python3
"""Daily earnings calendar cache (EXPERIMENT.md Amendment 2A).
Fetches Finnhub /calendar/earnings for the next 14 days, keeps the nearest
upcoming report per symbol, writes /opt/stonk-ai/earnings_cache.json.
Fail-safe: on any error, keeps the previous cache (staleness fail-open is
handled by the consumer). Cron: 30 6,13 * * * HKT.
"""
import json, os, time, urllib.request
from datetime import datetime, timedelta, timezone

KEY_PATH = "/opt/stonk-ai/.secrets/finnhub.key"
OUT = "/opt/stonk-ai/earnings_cache.json"
DAYS_AHEAD = 14

def main():
    key = open(KEY_PATH).read().strip()
    today = datetime.now(timezone.utc).date()
    frm, to = today.isoformat(), (today + timedelta(days=DAYS_AHEAD)).isoformat()
    url = f"https://finnhub.io/api/v1/calendar/earnings?from={frm}&to={to}&token={key}"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    events = data.get("earningsCalendar", []) or []

    best = {}
    for e in events:
        sym, date = e.get("symbol"), e.get("date")
        if not sym or not date:
            continue
        rec = {"date": date, "hour": e.get("hour") or "", "eps_estimate": e.get("epsEstimate")}
        if sym not in best or date < best[sym]["date"]:
            best[sym] = rec

    out = {"generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
           "window": f"{frm}..{to}", "events": len(events), "symbols": len(best),
           "earnings": best}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, OUT)
    try:
        os.chown(OUT, 999, 988)  # stonkai:stonkai (was uid 1000 = xcloud)
    except Exception:
        pass
    print(f"earnings_cache.json: {len(best)} symbols ({len(events)} events, {frm}..{to})")

if __name__ == "__main__":
    main()
