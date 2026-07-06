#!/usr/bin/env python3
"""Cancel stuck AAPL sell order(s) via raw Alpaca API."""
import json, requests, sys

with open('/opt/stonk-ai/alpaca_config.json') as f:
    cfg = json.load(f)

headers = {
    "APCA-API-KEY-ID": cfg["api_key"],
    "APCA-API-SECRET-KEY": cfg["api_secret"],
}
base = cfg.get("base_url", "https://paper-api.alpaca.markets")
symbol = "AAPL"

print(f"Fetching open orders for {symbol}...")
resp = requests.get(f"{base}/v2/orders?status=open&symbols={symbol}", headers=headers)
resp.raise_for_status()
orders = resp.json()

sell_orders = [o for o in orders if o.get("side") == "sell"]

if not sell_orders:
    print(f"No open SELL orders found for {symbol}.")
    if orders:
        print("\nOther open orders:")
        for o in orders:
            print(f"  {o['symbol']} {o['side']} qty={o['qty']} type={o['type']} status={o['status']} id={o['id']}")
    sys.exit(0)

print(f"Found {len(sell_orders)} open SELL order(s) for {symbol}:")
for o in sell_orders:
    print(f"  id={o['id']} qty={o['qty']} limit={o.get('limit_price','market')} status={o['status']}")

for o in sell_orders:
    oid = o["id"]
    try:
        d = requests.delete(f"{base}/v2/orders/{oid}", headers=headers)
        d.raise_for_status()
        print(f"  -> Cancelled order {oid}")
    except Exception as e:
        print(f"  -> FAILED to cancel {oid}: {e}")

print("Done.")
