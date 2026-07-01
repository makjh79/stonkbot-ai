path = "/opt/stonk-ai/trading_bot.py"
text = open(path).read()

old = '''        exit_trades.extend(self.risk_engine.check_concentration(portfolio_data))
        exit_trades.extend(self.risk_engine.check_high_beta_basket(portfolio_data, high_beta_symbols))
        exit_trades.extend(self.thesis_manager.check_thesis_exits(portfolio_data, self._signals))'''

new = '''        exit_trades.extend(self.risk_engine.check_concentration(portfolio_data))
        # High-beta basket trim is intentionally NOT wired here yet; the first version
        # only blocks new high-beta buys. Trim logic lives in risk_engine for later.
        exit_trades.extend(self.thesis_manager.check_thesis_exits(portfolio_data, self._signals))'''

if old in text:
    text = text.replace(old, new)
    open(path, "w").write(text)
    print("removed high-beta trim from live bot exit logic")
else:
    print("pattern not found")
