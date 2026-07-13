#!/usr/bin/env python3
"""Fetch fresh daily bars from Alpaca SIP and write website/history/*.json files for sparklines."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alpaca_data import AlpacaDataHub

HISTORY_DIR = Path('/var/www/hedge-fund-website/history')
WATCHLIST_FILE = Path('/var/www/hedge-fund-website/ai_watchlist_live.json')
PORTFOLIO_FILE = Path('/var/www/hedge-fund-website/portfolio_data.json')


def load_symbols() -> set:
    symbols = set()
    try:
        w = json.load(open(WATCHLIST_FILE))
        symbols.update(w.get('prices', {}).keys())
    except Exception:
        pass
    try:
        p = json.load(open(PORTFOLIO_FILE))
        for pos in p.get('positions', []):
            symbols.add(pos['symbol'])
    except Exception:
        pass
    return symbols


def save_history(symbol: str, data: dict):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    timestamps = data.get('timestamps', [])
    opens = data.get('opens', [])
    highs = data.get('highs', [])
    lows = data.get('lows', [])
    closes = data.get('closes', [])
    volumes = data.get('volumes', [])
    # If opens missing, approximate with prior close
    history = []
    for i, ts in enumerate(timestamps):
        date = ts[:10] if isinstance(ts, str) else ts.isoformat()[:10]
        history.append({
            "date": date,
            "open": round(opens[i], 4) if i < len(opens) and opens else round(closes[i-1] if i > 0 else closes[i], 4),
            "high": round(highs[i], 4) if i < len(highs) else round(closes[i], 4),
            "low": round(lows[i], 4) if i < len(lows) else round(closes[i], 4),
            "close": round(closes[i], 4),
            "volume": int(volumes[i]) if i < len(volumes) else 0,
        })
    out = {
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "source": "alpaca_sip",
        "history": history,
    }
    with open(HISTORY_DIR / f"{symbol}.json", 'w') as f:
        json.dump(out, f, indent=2)


def write_manifest(symbols: list):
    manifest = {
        "tickers": sorted(symbols),
        "generated_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "source": "alpaca_sip",
        "days": 30,
    }
    with open(HISTORY_DIR / "manifest.json", 'w') as f:
        json.dump(manifest, f, indent=2)


def main():
    symbols = load_symbols()
    if not symbols:
        print("No symbols found")
        return
    print(f"Fetching history for {len(symbols)} symbols")
    client = AlpacaDataHub()
    bars = client.get_daily_bars(list(symbols), days=45)
    ok = 0
    for sym, data in bars.items():
        if data and data.get('closes'):
            save_history(sym, data)
            ok += 1
        else:
            print(f"No bars for {sym}")
    write_manifest(list(bars.keys()))
    print(f"Saved history for {ok}/{len(symbols)} symbols")


if __name__ == "__main__":
    main()
