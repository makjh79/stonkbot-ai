from risk_engine import RiskEngine, RiskConfig, load_high_beta_symbols
import json

config = RiskConfig()
engine = RiskEngine(config=config)
portfolio = json.load(open('/var/www/hedge-fund-website/portfolio_data.json'))
hb = load_high_beta_symbols()
trades = engine.check_high_beta_basket(portfolio, hb)
print('trades:', trades)
