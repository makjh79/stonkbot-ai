# Handover from Einstein — 2026-07-23

## For Jeeves

1. **Pre-registered experiment is live:** `/opt/stonk-ai/EXPERIMENT.md` (committed this morning, before outcome-tracker data lands). Window Jul 22 → Aug 15. Entry logic, stop widths, caps, tier thresholds are FROZEN. If you change any of them, log a one-line justification in EXPERIMENT.md. Keep/kill rules inside are pre-committed — do not renegotiate them after seeing data.

2. **Race card + About scoreboard rebased to Jul 7 pv** (99866.86, the 16:00 UTC snapshot). Bot return on those two surfaces now uses the same window as the indices. Hero/badge/chart still vs $100K. Commit f0453a1.

3. **Canonical frontend source is `/opt/stonk-ai/website/index.html`.** The `/var/www/hedge-fund-website/` git checkout is a stale artifact (root index.html not in its HEAD, its website/index.html is Jul 14). Never edit there — deploy.yml cp's from /opt/stonk-ai. I wasted 20 min on this today; don't repeat it.

4. **Jul 22 session verified clean:** 9 sells, 0 buys, 0 flips. PAYO/CHWY/ELF/ROKU "new" entry dates were timestamp restamps, not phantom buys — quantities reconcile exactly from sells. No logging gap.

5. **Watch item:** below-VWAP trailing tightening fired 4 stops at −2.6% to −3.5% on Jul 22. Pre-registered trigger: two more sub−3% stops this week → ATR-gate or retire. Track it.

— Einstein
