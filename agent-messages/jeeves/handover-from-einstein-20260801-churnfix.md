From: Einstein
To: Jeeves
Timestamp: 2026-08-01T14:58:00+08:00
Subject: Churn fix deployed — rotation disabled + min hold raised

Jeeves,

Howie asked me to fix the strategy churn. I diagnosed it and made two live code changes on the VPS while the US market is closed. Effective Monday Aug 3 open.

What changed:

1. `risk_engine.py` — `rotation_enabled` set to `False`.
   - The rotation loop (2-hour cooldown, trim 20% of overweight low-readiness positions to fund new high-readiness entries) was responsible for ~205 sells and −$2,241 realized PnL in the Jul 7 rebase window.
   - It was also trimming winners before they could run. Buy-and-hold of the bot's first purchases would have been roughly flat; the strategy was −$8,402.

2. `trading_bot.py` — minimum hold period raised:
   - RISK_ON: 2 → 5 days
   - RISK_OFF: 1 → 3 days
   - CRISIS: still 0
   - The thesis-broken exit (readiness < 40) is now gated by the same min-hold period, so it cannot panic-sell a new position on a single noisy signal.

Backups:
- `/opt/stonk-ai/backups/risk_engine-pre-rotation-disable-20260801-1455.py`
- `/opt/stonk-ai/backups/trading_bot-pre-minhold-20260801-1458.py`

`stonk-ai.service` was restarted after both changes and is active.

What to watch next week:
- Daily trade count should drop sharply. The 0.4-day average hold should lengthen.
- Monitor `trade_quality.json` / `factor_attribution.json` for PF and median hold.
- If churn falls but winners still do not get captured, the next fixes are:
  - Add a profit-taking / scale-out rule.
  - Widen the hard-cut floor beyond 3% (currently 1×ATR or 3%, whichever is wider).
  - Demote MACD and intraday as positive entry confirmations — live attribution shows negative edge.

I also updated `EXPERIMENT.md` with a post-protocol change log and will push the code to GitHub now.

— Einstein
