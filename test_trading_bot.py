import trading_bot
bot = trading_bot.STONKAIBot()
print('trading_bot instantiates OK')
print('high beta buy gate exists:', hasattr(bot, '_high_beta_buy_blocked'))
print('risk engine has trim:', hasattr(bot.risk_engine, 'check_high_beta_basket'))
print('cap enabled:', bot.risk_engine.config.high_beta_basket_cap_enabled)
print('max pct:', bot.risk_engine.config.max_high_beta_deployed_pct)
