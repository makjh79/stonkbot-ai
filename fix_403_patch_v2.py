#!/usr/bin/env python3
"""Patch trading_bot.py with 403 dedup guard + market-order sell wrapper."""
import sys

FILE = '/opt/stonk-ai/trading_bot.py'
MARKER = '# --- 403 GUARD (auto-injected'

def main():
    with open(FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    if MARKER in content:
        print("403 guard already present. Nothing to do.")
        sys.exit(0)

    guard_lines = [
        "",
        "# --- 403 GUARD (auto-injected 2026-06-29) ---",
        "# Blocks duplicate sell orders when an open sell already exists for the symbol.",
        "# Also forces market orders for all sell exits (to avoid stale limit prices on falling stocks).",
        "_original_submit_order = AlpacaClient.submit_order",
        "_original_build_payload = AlpacaClient._build_order_payload",
        "",
        "def _guarded_submit_order(self, symbol, qty, side, dry_run=False, use_limit=True, twap_threshold=100):",
        "    if side.lower() == 'sell' and not dry_run:",
        "        try:",
        "            open_orders = self.list_orders(status='open', symbols=[symbol])",
        "            for o in open_orders:",
        "                if getattr(o, 'side', '').lower() == 'sell':",
        "                    import logging",
        "                    logging.getLogger(__name__).warning(",
        '                        f"Blocked duplicate sell for {symbol}: open order {getattr(o, \u0027id\u0027, \u0027?\u0027)} exists"',
        "                    )",
        "                    class _BlockedOrder:",
        '                        id = f"blocked_dup_{getattr(o, \u0027id\u0027, \u0027?\u0027)}"',
        '                        status = "blocked"',
        "                        symbol = symbol",
        "                    return _BlockedOrder()",
        "        except Exception as e:",
        '            logging.getLogger(__name__).error(f"Error checking open orders for {symbol}: {e}")',
        "    return _original_submit_order(self, symbol, qty, side, dry_run=dry_run, use_limit=use_limit, twap_threshold=twap_threshold)",
        "",
        "def _market_on_sell_payload(self, symbol, qty, side, use_limit=True):",
        "    # Force market orders for all sells (stops/exits must execute; limit orders can go stale above market)",
        "    if side.lower() == 'sell':",
        "        return _original_build_payload(self, symbol, qty, side, use_limit=False)",
        "    return _original_build_payload(self, symbol, qty, side, use_limit=use_limit)",
        "",
        "AlpacaClient.submit_order = _guarded_submit_order",
        "AlpacaClient._build_order_payload = _market_on_sell_payload",
        "# --- END 403 GUARD ---",
        "",
    ]
    guard = "\n".join(guard_lines)

    insert_marker = 'if __name__ == "__main__":'
    if insert_marker in content:
        idx = content.index(insert_marker)
        content = content[:idx] + guard + content[idx:]
    else:
        content = content + guard

    with open(FILE, 'w', encoding='utf-8') as f:
        f.write(content)

    print("Patched trading_bot.py with 403 dedup guard and market-order sell wrapper.")

if __name__ == '__main__':
    main()
