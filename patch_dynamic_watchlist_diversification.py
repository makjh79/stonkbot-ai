path = "/opt/stonk-ai/dynamic_watchlist_manager.py"
text = open(path).read()

# 1. Add div threshold config constants
old_config = """MAX_HIGH_BETA_DEPLOYED_PCT = 0.35
HIGH_BETA_SPY_BETA_THRESHOLD = 1.2
HIGH_BETA_SPY_CORR_THRESHOLD = 0.70
CORRELATION_REPORT_PATH = Path("/var/www/hedge-fund-website/correlation_report.json")"""
new_config = """MAX_HIGH_BETA_DEPLOYED_PCT = 0.35
HIGH_BETA_SPY_BETA_THRESHOLD = 1.2
HIGH_BETA_SPY_CORR_THRESHOLD = 0.70
CORRELATION_REPORT_PATH = Path("/var/www/hedge-fund-website/correlation_report.json")

# Diversification candidate thresholds (mirror paper_rebalancer.py / trading_bot.py)
DIVERSIFICATION_READINESS_MIN = 65.0
DIVERSIFICATION_CONFIRMATIONS_MIN = 2
DIVERSIFICATION_MAX_SECTOR_PCT = 0.30"""
if old_config in text:
    text = text.replace(old_config, new_config)
    print("added div config")

# 2. Add _symbol_sector helper if not present (sync with signal_engine / paper_rebalancer)
if "def _symbol_sector" not in text:
    old = "def load_high_beta_symbols() -> set:"
    new = '''def _symbol_sector(symbol: str) -> str:
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


def load_high_beta_symbols() -> set:'''
    if old in text:
        text = text.replace(old, new)
        print("added _symbol_sector helper")

# 3. Compute sector exposures before buy candidate loop
old_exposure = """    # High-beta basket guard for Next Buys display
    high_beta_symbols = load_high_beta_symbols()
    cash = portfolio.get("account", {}).get("cash", 0) if portfolio else 0
    deployed = portfolio_value - cash
    if deployed > 0:
        high_beta_mv = sum(p.get("market_value", 0) for p in portfolio.get("positions", []) if p.get("symbol") in high_beta_symbols)
        high_beta_pct = high_beta_mv / deployed if deployed > 0 else 0.0
    else:
        high_beta_pct = 0.0

    # Build current position lookup
    positions = {"""
new_exposure = """    # High-beta basket guard for Next Buys display
    high_beta_symbols = load_high_beta_symbols()
    cash = portfolio.get("account", {}).get("cash", 0) if portfolio else 0
    deployed = portfolio_value - cash
    if deployed > 0:
        high_beta_mv = sum(p.get("market_value", 0) for p in portfolio.get("positions", []) if p.get("symbol") in high_beta_symbols)
        high_beta_pct = high_beta_mv / deployed if deployed > 0 else 0.0
    else:
        high_beta_pct = 0.0

    # Sector exposures for diversification status
    sector_exposures = {}
    for p in portfolio.get("positions", []):
        sector = _symbol_sector(p.get("symbol"))
        sector_exposures[sector] = sector_exposures.get(sector, 0.0) + p.get("market_value", 0)

    # Build current position lookup
    positions = {"""
if old_exposure in text and "sector_exposures" not in text:
    text = text.replace(old_exposure, new_exposure)
    print("added sector exposure calc")

# 4. Add diversification status to buy logic
old_status = """        if symbol in high_beta_symbols and high_beta_pct >= MAX_HIGH_BETA_DEPLOYED_PCT:
            status = "high_beta_blocked"
            reason = f"High-beta basket at {high_beta_pct:.1%} (cap {MAX_HIGH_BETA_DEPLOYED_PCT:.1%})"
        elif held_info:"""
new_status = """        if symbol in high_beta_symbols and high_beta_pct >= MAX_HIGH_BETA_DEPLOYED_PCT:
            status = "high_beta_blocked"
            reason = f"High-beta basket at {high_beta_pct:.1%} (cap {MAX_HIGH_BETA_DEPLOYED_PCT:.1%})"
        elif (not entry_eligible
              and not held_info
              and symbol not in high_beta_symbols
              and pdata.get("readiness_score", 0) >= DIVERSIFICATION_READINESS_MIN
              and pdata.get("confirmation_count", 0) >= DIVERSIFICATION_CONFIRMATIONS_MIN
              and (pdata.get("above_ema20") or pdata.get("confirmations", {}).get("above_ema"))
              and sector_exposures.get(_symbol_sector(symbol), 0) < portfolio_value * DIVERSIFICATION_MAX_SECTOR_PCT):
            status = "diversification"
            reason = f"Diversification candidate (readiness {pdata.get('readiness_score', 0):.1f}, {pdata.get('confirmation_count', 0)}/9 conf)"
        elif held_info:"""
if old_status in text and "diversification" not in text:
    text = text.replace(old_status, new_status)
    print("added diversification status")

open(path, "w").write(text)
print("done")
