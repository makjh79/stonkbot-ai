import json
import sys
sys.path.insert(0, '/opt/stonk-ai')

import trading_bot
from risk_engine import load_high_beta_symbols

bot = trading_bot.STONKAIBot()

portfolio = json.load(open('/var/www/hedge-fund-website/portfolio_data.json'))
signals = json.load(open('/opt/stonk-ai/signals.json')).get('signals', [])
bot._signals = signals
bot._last_signal_refresh = 1

entry_candidates = []
current_symbols = {p['symbol'] for p in portfolio.get('positions', [])}
hb = load_high_beta_symbols()

bot._add_diversification_entries(entry_candidates, portfolio, current_symbols, hb)

print('div entries:', len(entry_candidates))
for t in entry_candidates:
    print(t['symbol'], t['qty'], t['intended_notional'], t['reason'][:60])
