# Website Strategy Sync Checklist

Run this whenever readiness_score.py, signal_engine.py, signal_rules.py,
risk_engine.py, or strategy_config.py changes.

1. About / Live Rules panel — entry gate, hard confirmations, stops, caps, holds.
2. Readiness tooltip — factor weights and what is display-only.
3. How it works / strategy cards — high-level narrative.
4. Race / hero strategy one-liner.
5. FAQ — “How does the AI work?”, experiment status.
6. Trade log rationale strings (if strategy names changed).
7. Cache-bust query string.
8. Deploy to /var/www/hedge-fund-website.
9. Smoke-test HTML/JS.
10. Commit + push.
