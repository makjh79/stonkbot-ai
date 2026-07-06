# Gemini Strategy Assessment (June 27, 2026)

## Strengths identified
- Inverted volume logic (volume on rising prices) — institutional accumulation signal
- Layered stop architecture (hard stop + ATR trailing + VWAP intraday)
- Dynamic watchlist with self-tuning feedback loop
- IV-adjusted position sizing (defensive during earnings/panic)

## Vulnerabilities flagged
1. **Beta 1.34** — acting as leveraged S&P ETF. Backtest Sharpe likely subsidized by bull market. Capturing beta, not alpha.
2. **Negative live Sharpe (-1.23)** — 38 trades not significant, but backtest→live gap suggests possible lookahead bias or regime shift
3. **STRONG_NOW 2x cap conflict** — 2x sizing often hits 8% max position cap, making STRONG_NOW identical to NOW in practice
4. **Midpoint limit adverse selection** — fills on losers (crashing through midpoint), misses on winners (ripping away)

## Recommendations
1. **Activate regime detection** — master switch: if credit spreads widen or SPY < 50d EMA, shrink max position 8%→4%, raise cash floor 5%→50%
2. **Fix execution** — STRONG_NOW should cross spread and take ask, or use VWAP execution over 5-min window
3. **Market-neutral filter** — introduce short selling or hedge with SPY puts/VIXY calls when portfolio beta >1.2

## Action items for Jeeves
- [ ] Implement regime detection master switch (data already available: SHY/TLT, LQD/HYG, VIXY)
- [ ] Fix STRONG_NOW sizing: either raise cap to 12% for STRONG tier or use 1.5x instead of 2x
- [ ] Test for lookahead bias in backtest
- [ ] Consider aggressive execution for STRONG_NOW (take ask / VWAP 5-min)
- [ ] Explore beta hedging strategy
## Gemini Assessment 2 (post-revision)

### Strengths confirmed
- Macro-aware regime detection (credit spreads, yield curve)
- Volatility-adjusted sizing (IV-based)
- Layered exit logic (hard stop + ATR + thesis + VWAP)
- Self-tuning loop (non-bought watchlist tracking)

### New vulnerabilities flagged
1. **Backtest vs live mismatch** — backtest uses daily T+1, live bot scans every 5 min with 15-min bars + intraday VWAP. Different execution environments.
2. **Time horizon clash** — entering on 15-min momentum but holding for 20 days. If regime flips on day 4, trapped for 16 more days.
3. **Slippage risk** — escalate to market order for NOW entries is dangerous for mid-caps. Should use marketable limit (ask + 1 cent) instead.
4. **Drawdown math** — backtest shows -25.4% max DD but bot halts at -15%. Did the halt not trigger in backtest?

### Action items
- [ ] Build intraday backtest or add slippage assumptions to daily backtest
- [ ] Consider shorter min-hold or allow regime-based early exit
- [ ] Change escalation from market to marketable limit (ask + 1 cent)
- [ ] Verify drawdown halt in backtest matches live behavior

## Gemini Assessment 3 (post-PEAD + strategy switching)

### Strengths
- Regime awareness (mean reversion in RISK_OFF)
- Intraday timing filter (skip >3% pump)
- Risk management floors (sector cap, DD halt)

### Critical flaws flagged
1. **Curve-fitting trap** — 9 factors, specific weights, arbitrary thresholds = too many degrees of freedom. Likely memorized past noise, not finding true edge.
2. **Backtest math poor** — Sharpe 0.73, Max DD -37.7%, alpha zero, beta 0.98 = expensive S&P 500 index fund with worse drawdowns.
3. **Slippage underestimated** — crossing spread on 130 mid-caps costs >8bps in high-IV environments. 1778 trades × slight underestimation = returns wiped out.
4. **Survivorship bias** — 130 stocks selected today, backtested over 18 months = invalid. Stocks that blew up/delisted during that period are excluded.

### Action items
- [ ] Reduce degrees of freedom (simplify factors, fewer arbitrary thresholds)
- [ ] Verify slippage assumption with actual Alpaca spread data
- [ ] Address survivorship bias — include historical universe members that would have been selected at the time
- [ ] Consider whether the complexity is adding value or just curve-fitting
