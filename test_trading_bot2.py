import trading_bot
bot = trading_bot.STONKAIBot()
print('bot instantiates OK')
print('has _add_diversification_entries:', hasattr(bot, '_add_diversification_entries'))
print('has _symbol_sector:', hasattr(bot, '_symbol_sector'))
