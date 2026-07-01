path = "/opt/stonk-ai/trading_bot.py"
text = open(path).read()

# 1. Add config constants near imports
old_const = """from risk_engine import RiskConfig, RiskEngine, SizingResult, load_high_beta_symbols"""
new_const = """from risk_engine import RiskConfig, RiskEngine, SizingResult, load_high_beta_symbols

# Sector-aware diversification parameters (mirror paper_rebalancer.py)
DIVERSIFICATION_READINESS_MIN = 65.0
DIVERSIFICATION_CONFIRMATIONS_MIN = 2
DIVERSIFICATION_MAX_SECTOR_PCT = 0.30
DIVERSIFICATION_TARGET_PCT = 0.045  # ~4.5% of portfolio per div name"""
if old_const in text:
    text = text.replace(old_const, new_const)
    print("added diversification constants")

# 2. Add helper methods to STONKAIBot class (insert before refresh_signals)
old_signal_lifecycle = "    # ------------------------------------------------------------------\n    # Signal lifecycle\n    # ------------------------------------------------------------------"
new_helpers = '''    # ------------------------------------------------------------------
    # Sector helpers for diversification
    # ------------------------------------------------------------------
    @staticmethod
    def _symbol_sector(symbol: str) -> str:
        """Return sector mapping (synced with signal_engine.py / paper_rebalancer.py)."""
        sectors = {
            "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "NFLX", "CRM", "ORCL", "ADBE", "INTU", "IBM", "INTC", "SNOW", "MDB", "GTLB", "CFLT", "ESTC", "PSTG", "DOCN", "VEEV", "TEAM", "NOW", "NET", "DDOG", "OKTA", "PATH", "PLTR", "UBER", "ABNB", "EXPE", "SPOT", "ROKU", "PINS", "SNAP", "TTD", "SHOP"],
            "Semiconductors": ["AMD", "MU", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS", "MRVL", "NXPI", "QCOM", "SWKS", "TER", "ON", "AVGO", "TXN"],
            "Cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "CYBR", "S"],
            "Fintech": ["HOOD", "COIN", "SQ", "UPST", "AFRM", "SOFI", "PAYO", "LMND", "RELY", "PYPL", "FIS", "V", "GS", "MS", "BLK", "SCHW"],
            "Consumer/Platform": ["UBER", "DKNG", "SHOP", "TTD", "ROKU", "PINS", "SNAP", "ABNB", "EXPE", "SPOT", "ELF", "APP", "DUOL", "CHWY", "ETSY", "LULU", "NKE", "COST", "WMT", "HD"],
            "EV/Mobility": ["TSLA", "RIVN", "LCID", "NIO", "XPEV"],
            "Healthcare": ["UNH", "LLY", "JNJ", "PFE", "ABBV", "MRK", "TMO", "VRTX", "BMY", "REGN", "GILD", "ISRG", "ZBH", "ILMN", "SGEN"],
            "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY"],
            "Industrials": ["GE", "CAT", "UNP", "HON", "UPS", "RTX", "LMT", "DE"],
            "Financials": ["JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "V"],
            "Communications/Media": ["DIS", "CMCSA", "TMUS", "CHTR", "WBD", "PARA"],
        }
        for sector, symbols in sectors.items():
            if symbol in symbols:
                return sector
        return "Other"

    def _sector_exposures(self, portfolio_data: dict) -> dict:
        exposures = {}
        for pos in portfolio_data.get("positions", []):
            sector = self._symbol_sector(pos.get("symbol"))
            exposures[sector] = exposures.get(sector, 0.0) + pos.get("market_value", 0)
        return exposures

    def _add_diversification_entries(
        self,
        entry_candidates: list,
        portfolio_data: dict,
        current_symbols: set,
        high_beta_symbols: set,
    ) -> None:
        """Add near-eligible non-high-beta candidates from underweight sectors.

        This runs after the core entry queue and only deploys if cash is plentiful
        (cash > 40% of portfolio) to avoid crowding out high-conviction momentum entries.
        """
        pv = portfolio_data["account"]["portfolio_value"]
        cash = portfolio_data["account"]["cash"]
        if cash <= pv * 0.40:
            return

        exposures = self._sector_exposures(portfolio_data)
        pv = portfolio_data["account"]["portfolio_value"]
        existing_symbols = {t["symbol"] for t in entry_candidates} | current_symbols

        div_candidates = []
        for sig in self._signals:
            symbol = sig.get("symbol")
            if symbol in existing_symbols:
                continue
            if sig.get("entry_eligible", False):
                continue
            if symbol in high_beta_symbols:
                continue
            readiness = sig.get("readiness_score", 0)
            conf = sig.get("confirmation_count", 0)
            if readiness < DIVERSIFICATION_READINESS_MIN or conf < DIVERSIFICATION_CONFIRMATIONS_MIN:
                continue
            above_ema = sig.get("above_ema20") or sig.get("confirmations", {}).get("above_ema")
            if not above_ema:
                continue
            price = sig.get("price", 0)
            if price <= 0:
                continue
            sector = self._symbol_sector(symbol)
            if exposures.get(sector, 0) >= pv * DIVERSIFICATION_MAX_SECTOR_PCT:
                continue
            div_candidates.append(sig)

        # Sort by readiness and pick enough to deploy cash down to ~40%
        div_candidates.sort(key=lambda s: s.get("readiness_score", 0), reverse=True)
        deploy_cash = cash - pv * 0.40
        deployed_div = 0.0
        for sig in div_candidates:
            if deployed_div >= deploy_cash:
                break
            symbol = sig.get("symbol")
            sector = self._symbol_sector(symbol)
            if exposures.get(sector, 0) >= pv * DIVERSIFICATION_MAX_SECTOR_PCT:
                continue

            price = sig.get("price", 0)
            if price <= 0:
                continue

            target_value = min(pv * DIVERSIFICATION_TARGET_PCT, deploy_cash - deployed_div)
            # Respect live bot's 8% single-stock cap
            max_single_value = pv * self.risk_engine.config.max_single_position_pct
            target_value = min(target_value, max_single_value)

            qty = max(1, int(target_value / price))
            cost = qty * price
            cash_floor = max(self.risk_engine.config.min_cash_pct * pv, self.risk_engine.config.min_cash_absolute)
            if cost > (cash - cash_floor - deployed_div):
                qty = max(1, int((cash - cash_floor - deployed_div) / price))
                cost = qty * price
            if qty <= 0 or cost <= 0:
                continue

            if self._high_beta_buy_blocked(symbol, cost, portfolio_data, high_beta_symbols):
                continue

            entry_candidates.append({
                "symbol": symbol,
                "qty": qty,
                "action": "BUY",
                "reason": f"Diversification entry (readiness {sig.get('readiness_score', 0):.1f}, {conf}/9 conf) - sector underweight",
                "intended_notional": cost,
                "readiness_score": sig.get("readiness_score", 0),
                "tier": sig.get("tier", "WATCH"),
                "diversification": True,
            })
            deployed_div += cost
            exposures[sector] = exposures.get(sector, 0.0) + cost
            logger.info(f"DIV ENTRY queued: {symbol} {qty} shares @ ${price:.2f} ({cost:.0f}) - sector {sector}")

    # ------------------------------------------------------------------
    # Signal lifecycle
    # ------------------------------------------------------------------'''

if old_signal_lifecycle in text and "_add_diversification_entries" not in text:
    text = text.replace(old_signal_lifecycle, new_helpers)
    print("added diversification helper")

# 3. Call diversification helper before sorting entry queue
old_sort = """        # Sort entry queue by readiness (highest first)
        entry_candidates.sort(key=lambda t: t.get("readiness_score", 0), reverse=True)"""
new_sort = """        # Sector-aware diversification: add near-eligible non-high-beta candidates
        # from underweight sectors when cash is plentiful.
        self._add_diversification_entries(entry_candidates, portfolio_data, current_symbols, high_beta_symbols)

        # Sort entry queue by readiness (highest first)
        entry_candidates.sort(key=lambda t: t.get("readiness_score", 0), reverse=True)"""

if old_sort in text and "_add_diversification_entries" not in text:
    text = text.replace(old_sort, new_sort)
    print("wired diversification helper")

open(path, "w").write(text)
print("done")
