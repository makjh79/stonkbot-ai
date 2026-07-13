#!/usr/bin/env python3
"""
STONK.AI Popup Content Generator v2

Generates fresh, v2-aligned narratives for all holdings every 2 minutes.
Uses the quality-momentum signal engine and actual risk engine stop levels.
Saves to /var/www/hedge-fund-website/popup_content.json
"""

import re
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from signal_engine import COMPANY_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BOT_DIR = Path("/opt/stonk-ai")
WEB_DIR = Path("/var/www/hedge-fund-website")
POPUP_FILE = WEB_DIR / "popup_content.json"
PORTFOLIO_FILE = WEB_DIR / "portfolio_data.json"
WATCHLIST_FILE = WEB_DIR / "ai_watchlist_live.json"
WATCHLIST_NARRATIVES_FILE = WEB_DIR / "watchlist_narratives.json"
SIGNALS_FILE = BOT_DIR / "signals.json"
ENRICHMENT_FILE = BOT_DIR / "signal_enrichment.json"
RISK_STATE_FILE = BOT_DIR / "risk_state.json"
RISK_CONFIG_FILE = BOT_DIR / "risk_config.json"

# 2026 US market holidays (month, day)
MARKET_HOLIDAYS_2026 = {
    (1, 1), (1, 19), (2, 16), (4, 3), (5, 25), (6, 19),
    (7, 4), (9, 7), (10, 12), (11, 11), (11, 26), (12, 25),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def is_market_open() -> bool:
    """Rough US market hours check in UTC (14:30-21:00 UTC, Mon-Fri, no holidays)."""
    n = now()
    if n.weekday() >= 5:
        return False
    if (n.month, n.day) in MARKET_HOLIDAYS_2026:
        return False
    # 14:30-21:00 UTC = 09:30-16:00 ET
    start = n.replace(hour=14, minute=30, second=0, microsecond=0)
    end = n.replace(hour=21, minute=0, second=0, microsecond=0)
    return start <= n <= end


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.error(f"Could not load {path}: {e}")
        return {}


def load_signals_map() -> dict:
    """Map symbol -> signal data from signals.json, merged with enrichment fallback."""
    data = load_json(SIGNALS_FILE)
    signals = data.get("signals", [])
    sig_map = {s["symbol"]: s for s in signals if "symbol" in s}

    # For symbols not actively scored, merge enrichment data so popups still have context
    enrichment = load_json(ENRICHMENT_FILE).get("data", {})
    for symbol, e in enrichment.items():
        if symbol not in sig_map:
            sig_map[symbol] = {
                "symbol": symbol,
                "total_score": 0,
                "momentum_score": 0,
                "quality_score": 0,
                "risk_score": 0,
                "regime_score": 0,
                "thesis": "",
                "drivers": [],
                "sector": e.get("metrics", {}).get("sector", "Other"),
                "earnings": e.get("earnings"),
                "recommendation": e.get("recommendation"),
                "news": e.get("news"),
            }
        else:
            # Ensure enrichment fields are present even for scored symbols
            for key in ("earnings", "recommendation"):
                if key not in sig_map[symbol]:
                    sig_map[symbol][key] = e.get(key)
            # Always merge news from enrichment (has alpaca_url, alpaca_source)
            if "news" not in sig_map[symbol]:
                sig_map[symbol]["news"] = e.get("news")
            elif isinstance(sig_map[symbol].get("news"), dict) and isinstance(e.get("news"), dict):
                sig_map[symbol]["news"].update(e.get("news"))
    return sig_map


def load_risk_state() -> dict:
    return load_json(RISK_STATE_FILE)


def load_risk_config() -> dict:
    if RISK_CONFIG_FILE.exists():
        return load_json(RISK_CONFIG_FILE)
    # Defaults matching risk_engine.py
    return {
        "hard_stop_loss_pct": -0.10,
        "trailing_stop_pct": -0.10,
        "trailing_stop_atr_multiplier": 2.5,
        "trim_profit_pct": 0.25,
        "full_exit_profit_pct": 0.50,
    }


def get_stop_levels(symbol: str, position: dict, risk_config: dict, risk_state: dict, signal_data: dict) -> dict:
    """Compute effective hard stop and trailing stop levels."""
    avg_entry = position.get("avg_entry", 0)
    peak = risk_state.get("position_high_water_marks", {}).get(symbol, avg_entry)
    atr_pct = risk_state.get("position_atr_pct", {}).get(symbol)

    # Hard stop from cost basis
    hard_stop = avg_entry * (1 + risk_config.get("hard_stop_loss_pct", -0.10))

    # Trailing stop from peak, volatility-aware only if ATR% was recorded
    base_trailing_pct = abs(risk_config.get("trailing_stop_pct", -0.10))
    if atr_pct and atr_pct > 0:
        atr_mult = risk_config.get("trailing_stop_atr_multiplier", 2.5)
        trailing_pct = max(base_trailing_pct, atr_pct * atr_mult)
    else:
        trailing_pct = base_trailing_pct

    trailing_stop = peak * (1 - trailing_pct)

    # VWAP stop (from Alpaca paid data)
    vwap = signal_data.get("daily_vwap")
    vwap_stop = round(vwap * 0.98, 2) if vwap and vwap > 0 else None  # 2% below VWAP

    return {
        "hard_stop": round(hard_stop, 2),
        "trailing_stop": round(trailing_stop, 2),
        "vwap_stop": vwap_stop,
        "vwap": round(vwap, 2) if vwap else None,
        "peak": round(peak, 2),
        "trailing_pct": round(trailing_pct * 100, 1),
    }


def signal_label(pl_percent: float, total_score: float, tier: str) -> str:
    if pl_percent >= 25:
        return "PROFIT_ZONE"
    if pl_percent <= -8:
        return "WARNING"
    if tier == "NOW":
        return "STRONG"
    if tier == "WATCH":
        return "GREEN"
    if total_score >= 45:
        return "HOLD"
    return "TRACKING"

# ═══════════════════════════════════════════════════════════════════════
# COMPANY ONE-LINERS — trader shorthand, not Wikipedia
# ═══════════════════════════════════════════════════════════════════════

_COMPANY_NOTES = {
    "AAPL": "iPhone cash cow, services flywheel compounding margins. $3T ecosystem lock-in.",
    "ABBV": "pharma giant. Humira biosimilar competition phased, Skyrizi + Rinvoq immunology growth.",
    "ABNB": "travel marketplace. Host supply growth drives take rate. Cyclical travel demand exposure.",
    "ADBE": "creative software monopoly. Photoshop, Acrobat, Experience Cloud. AI Firefly monetization.",
    "AFRM": "buy-now-pay-later platform for e-commerce. Interest income + merchant network growth. Consumer credit cycle exposure.",
    "AMAT": "semiconductor equipment. Sells the picks and shovels to the chip cycle.",
    "AMD": "Intel's only real x86 rival. MI300 taking GPU share from NVDA in inference workloads.",
    "AMZN": "AWS margins fund retail dominance. Logistics moat nobody can replicate at scale.",
    "APP": "mobile ad tech platform. Game monetization + AI-driven ad optimization/AppLovin.",
    "ARM": "Arm architecture licensing. Royalty model. AI data center adoption is the growth story.",
    "ASML": "EUV lithography monopoly. Every advanced chip needs their machines. China export risk.",
    "AVGO": "Custom AI silicon for Google and Meta. VMware acquisition shifts mix toward recurring software revenue.",
    "BAC": "money-center bank. Consumer + commercial. Net interest income and rate sensitivity.",
    "BLK": "asset management colossus. iShares ETF monopoly. Aladdin risk platform. $10T AUM.",
    "BMY": "big pharma. Revlimid patent cliff, Opdivo oncology franchise. Pipeline M&A (Karuna) story.",
    "CAT": "heavy machinery and construction equipment. Global infrastructure / mining capex. China demand macro bellwether.",
    "CDNS": "EDA software. Cadence, chip design tools for semiconductor industry. AI-assisted design.",
    "CFLT": "Confluent. Managed Kafka streaming data. Event streaming for real-time apps.",
    "CHTR": "cable broadband monopoly. Spectrum brand. Video cord-cutting continues, broadband grows.",
    "CHWY": "online pet food and pharmacy subscription. Chewy brand. Sticky auto-ship revenue.",
    "CMCSA": "cable + NBCUniversal. Broadband pricing. Peacock streaming. Theme parks.",
    "COIN": "crypto exchange. Revenue volatile with trading volumes. Diversifying into staking and Base L2.",
    "COP": "oil and gas exploration. Permian and Alaska assets. Production growth story.",
    "COST": "membership warehouse retail. Low prices, ultra-loyal customers, defensive consumer play.",
    "CRM": "Salesforce. CRM cloud leader. Data Cloud + AI. Acquisitions (Slack, Tableau) integration.",
    "CRWD": "endpoint security leader. Falcon platform dominance. Recovery from 2024 outage.",
    "CVX": "integrated supermajor. Permian, LNG, renewables. Dividend fortress.",
    "CYBR": "cybersecurity. Privileged access management (PAM). Identity security.",
    "DDOG": "cloud infrastructure monitoring. Multi-cloud observability play. Usage-based revenue.",
    "DE": "agricultural equipment. John Deere precision farming. Commodity price sensitivity.",
    "DIS": "media empire in transition. Streaming profitability improving. Parks cash cow. Linear TV decline.",
    "DKNG": "sports betting and iGaming platform. State legalization tailwind. Marketing spend intensive.",
    "DOCN": "developer cloud for SMBs. Simple pricing vs AWS. Niche player with sticky revenue.",
    "DUOL": "language learning app. Subscription growth and DAU engagement. AI-powered content creation.",
    "ELF": "mass-market beauty / cosmetics. Gen Z brand power. Growth outpacing legacy beauty.",
    "EOG": "shale oil and gas. Permian + Bakken. Low-cost producer. Capital returns focused.",
    "ESTC": "Elastic. Search + observability + security. Open-source ELK stack. Consumption pricing.",
    "ETSY": "handmade / artisan e-commerce. Pandemic pull-forward normalizing. Marketplace flywheel.",
    "EXPE": "online travel agency. Expedia / Hotels.com brands. Travel recovery and margin story.",
    "FIS": "fintech infrastructure. Core banking and payments tech. Spun out Worldpay.",
    "FTNT": "Fortinet. Network security (firewall) + SASE. Enterprise cybersecurity leader.",
    "GE": "conglomerate breakup. Vernova (power/renewables) and GE Aerospace spin. Aviation is core.",
    "GILD": "biotech. HIV treatment leader, cell therapy and oncology pivot. M&A for growth.",
    "GOOGL": "Search ad monopoly under regulatory pressure. YouTube and Cloud are the real growth drivers.",
    "GS": "investment bank + wealth management. Trading, M&A, asset management. Market proxy.",
    "GTLB": "DevOps platform. AI-powered CI/CD. Usage-based revenue. Competing with Microsoft GitHub.",
    "HD": "home improvement retail fortress. Housing turnover and rate sensitive. Cyclical but margin resilient.",
    "HON": "industrial conglomerate. Aerospace, building tech, safety. Software-driven manufacturing.",
    "HOOD": "retail brokerage. Payment for order flow model. Crypto and options revenue growing.",
    "IBM": "hybrid cloud + consulting + mainframe. AI (Watson, Granite). Turnaround story.",
    "ILMN": "DNA sequencing. Genomics tools for clinical and research. Short-read monopoly under pressure.",
    "INTC": "semiconductor foundry. IDM 2.0 strategy. Catching TSMC in process nodes. Capex heavy.",
    "INTU": "financial software. TurboTax and QuickBooks. Mint shutdown. AI-assisted finances.",
    "ISRG": "surgical robotics. Da Vinci install base drives recurring instrument sales. Procedure growth tailwind.",
    "JNJ": "healthcare conglomerate. Pharma + med devices + consumer. Spinning off Kenvue. Defensive staple.",
    "JPM": "biggest US bank. Universal banking model. Fortress balance sheet under Jamie Dimon.",
    "KLAC": "process control equipment for chip fabs. Near-monopoly in defect inspection.",
    "LCID": "luxury EV maker. Burning cash, Saudi-backed. Production ramp is the only thing that matters.",
    "LLY": "pharma giant riding the GLP-1 obesity wave. Mounjaro/Zepbound revenue compounding. Duopoly with Novo Nordisk.",
    "LMND": "AI-native insurance disruptor. Home / renters / pet coverage. Loss ratio -> profitability path.",
    "LMT": "defense prime. F-35, missile systems. Government budget dependent.",
    "LRCX": "wafer fab equipment. Highly leveraged to NAND capex cycles.",
    "LULU": "premium athleisure. Lululemon brand. International expansion. Peloton adjacency.",
    "META": "Facebook + Instagram ad machine prints cash. Reality Labs is a long-term metaverse bet.",
    "MDB": "NoSQL database. Atlas cloud revenue growing 30%+. Developer mindshare leader.",
    "MPC": "oil refiner + midstream + retail. Marathon brand. Crack spread sensitive.",
    "MRK": "big pharma. Keytruda is the world's top-selling drug. Animal health spin. Patent cliff coming.",
    "MRVL": "semiconductor networking + custom AI silicon. Data center and 5G infra exposure.",
    "MS": "investment bank + E*Trade + asset management. Wealth management fees.",
    "MSFT": "Azure is #2 cloud, Office is a monopoly, OpenAI partnership gives them AI distribution.",
    "MU": "DRAM/NAND memory cyclical. AI demand driving HBM pricing power. Boom-bust name.",
    "NET": "Cloudflare. CDN, zero-trust, edge compute. Internet infrastructure layer.",
    "NFLX": "streaming leader. Ad-tier and password crackdown driving subscriber growth. Content moat.",
    "NIO": "Chinese EV maker. Battery swap stations. Competitive with Tesla / BYD in China.",
    "NKE": "sportswear global leader. Direct-to-consumer pivot. China market exposure.",
    "NOW": "ServiceNow. Enterprise workflow SaaS. ITSM leader. AI copilots.",
    "NVDA": "GPU monopoly for AI training. Data center revenue compounding 80%+. CUDA moat is unbreachable near-term.",
    "NXPI": "automotive semiconductor. EV power electronics, radar, secure connectivity.",
    "OKTA": "identity management. SSO and access control. Margins expanding post-Salesforce competition.",
    "ON": "ON Semiconductor. Power management, SiC for EVs. Industrial + automotive.",
    "ORCL": "enterprise database and cloud. Multi-cloud database. Cerner healthcare data. AI RAG.",
    "OXY": "oil and gas. Permian focus. Buffett-backed. Occidental / Anadarko synergies.",
    "PANW": "Palo Alto Networks. Enterprise firewall + security platform. SASE and zero-trust.",
    "PARA": "Paramount Global. CBS, cable, Paramount+. Streaming wars. M&A target (Skydance deal).",
    "PATH": "UiPath. Robotic process automation (RPA). Enterprise automation, AI integration.",
    "PAYO": "cross-border payments for SMBs and freelancers. Emerging market revenue. Take rate expansion story.",
    "PFE": "pharma. COVID windfall gone. Oncology rebuild via Seagen acquisition. Pipeline dependent.",
    "PINS": "visual search and social commerce. Ad recovery play. Amazon partnership driving monetization.",
    "PLTR": "government and enterprise data analytics. AI platform expansion driving commercial growth.",
    "PSTG": "Pure Storage. Flash storage arrays. Evergreen subscription model. Enterprise IT spend.",
    "PSX": "downstream refiner and midstream. Phillips 66. Energy infrastructure consolidation.",
    "PYPL": "digital payments. Braintree growing, branded checkout losing share to Apple Pay.",
    "QCOM": "mobile Snapdragon chips and 5G modems. Apple modem threat looming.",
    "REGN": "biotech. Dupixent franchise (dermatitis, asthma). Monoclonal antibody platform powerhouse.",
    "RELY": "digital remittance platform. Competing with Western Union wire transfers. Latam volume growth.",
    "RIVN": "adventure EV trucks and vans. Amazon delivery fleet contract is the lifeline. Cash burn is critical risk.",
    "RKLB": "small launch vehicle. Neutron rocket development is the next catalyst. Space systems revenue growing.",
    "ROKU": "streaming device and platform. Roku OS for TV OEMs. Ad inventory monetization.",
    "RTX": "defense and aerospace. Pratt & Whitney engines, Collins. Supply chain recovery.",
    "S": "AI-native endpoint security. Growth rate slowing but differentiation vs CRWD is the debate.",
    "SCHW": "brokerage and wealth. Zero-commission model, NIM sensitive to rates.",
    "SGEN": "biotech, acquired by Pfizer. ADC (antibody-drug conjugate) oncology tech.",
    "SHOP": "e-commerce platform for SMBs. Merchant solutions revenue growing. Margin turnaround story.",
    "SLB": "oilfield services. Completion, drilling, digital. Rig count levered.",
    "SNAP": "ephemeral social media. Snap Ads and AR lens. Alternatives to Meta.",
    "SNOW": "cloud data warehouse. Consumption model. Growth slowing, profitability improving.",
    "SNPS": "Synopsys. EDA + IP for chip design monopoly. AI design tools acquisition.",
    "SOFI": "neobank with lending, deposits, and Galileo fintech infra. Student loan refinancing origin story.",
    "SPOT": "audio streaming leader. Premium subscriber growth and margin expansion from cost discipline.",
    "SQ": "fintech ecosystem. Cash App and Square POS. Bitcoin revenue is volatile, margins are the story.",
    "SWKS": "Skyworks. RF semiconductors for smartphones and IoT. Apple concentration risk.",
    "TEAM": "Atlassian. Jira + Confluence developer tools. Cloud shift. Team collaboration.",
    "TER": "semiconductor test equipment leader. Robotics/automation arm. Cyclical recovery tied to chip demand.",
    "TMO": "life sciences tools and diagnostics giant. Biopharma capex cycle. M&A roll-up strategy.",
    "TMUS": "mobile carrier. 5G network leader. Customer poaching from Verizon/AT&T.",
    "TSLA": "EV market leader losing share to BYD and legacy OEMs. Real optionality is FSD and robotaxi.",
    "TTD": "Trade Desk. Programmatic ad tech platform. Connected TV (CTV) growth. Cookie deprecation play.",
    "TXN": "Texas Instruments. Analog and embedded semiconductors. Industrial + auto dividend aristocrat.",
    "TWLO": "cloud communications API. Engagement data platform expanding. Path to profitability is the thesis.",
    "UBER": "ride-share and delivery dominance. FCF inflection. Autonomous vehicle partner risk.",
    "UNH": "managed care titan — health insurance, pharmacy benefits (Optum), Medicare. Moves on CMS rates and drug pricing policy.",
    "UNP": "Union Pacific Railroad. Cross-country freight. Economic activity barometer.",
    "UPS": "parcel delivery duopoly with FedEx. B2C e-commerce spikes. Margin compression.",
    "UPST": "AI-powered lending marketplace. Personal / auto loans. High credit-cycle beta.",
    "V": "payments network duopoly. VisaNet infrastructure. Cross-border volume recovery.",
    "VEEV": "life sciences SaaS. Pharma CRM, clinical data, and marketing. Subscription model for biotech.",
    "VRTX": "gene therapy. Cystic fibrosis monopoly (Trikafta). Casgevy CRISPR launch for sickle cell.",
    "WBD": "Warner Bros Discovery. HBOMax + Discovery+ merger. Content cost cutting focus.",
    "WFC": "US bank, recovering from scandals. Consumer focused. Rate and turnaround story.",
    "WMT": "retail fortress. Walmart US, Sam's Club, international. Grocery + omnichannel.",
    "XOM": "supermajor oil. Upstream + downstream + chemicals. Permian and Guyana acceleration.",
    "XPEV": "Chinese EV maker. XPeng. Autonomous driving focus. Sedan / SUV models.",
    "ZBH": "orthopedic devices. Knees, hips, spine. Elective procedure recovery.",
    "ZS": "zero-trust security gateway. Cloud-native. Competing with NET in SASE market.",
}

# ═══════════════════════════════════════════════════════════════════════
# COMPANY-SPECIFIC RISK DESCRIPTIONS — not generic sector templates — not generic sector templates
# ═══════════════════════════════════════════════════════════════════════

_COMPANY_RISKS = {
    "AAPL": "iPhone upgrade cycle stalling, China demand erosion, services regulatory risk",
    "NVDA": "AI capex air pocket, China export restrictions, AMD/Google internal chip competition",
    "AMD": "GPU share gains priced in, x86 slowdown from Intel comeback, console cycle declining",
    "MSFT": "Azure growth deceleration, AI monetization lag, OPEX bloat from OpenAI investment",
    "GOOGL": "Search disruption from AI chatbots, antitrust breakup risk, YouTube ad pricing pressure",
    "AMZN": "AWS growth slowing, retail margin compression, re-investment cycle eating FCF",
    "META": "Reels monetization lag, Reality Labs cash drain, ad market cyclicality",
    "TSLA": "EV demand normalization, FSD timeline slippage, China price war crushing margins",
    "AVGO": "VMware integration risk, customer concentration (Google/Meta buy 40%+ of revenue), semiconductor cyclicality",
    "MU": "Memory glut if AI demand slows, capex overbuild risk, China DRAM competition (CXMT)",
    "AMAT": "Chip equipment cycle downturn, China export restrictions, Korea capex cuts",
    "LRCX": "NAND capex cuts, China export exposure, memory cycle downturn hitting WFE spend",
    "KLAC": "Inspection equipment cycle, China export risk, fab capex deferral",
    "ASML": "China export restrictions are the binary risk, EUV shipment delays, fab capex pull-ins already price the upside",
    "QCOM": "Apple in-house modem threat, handset cycle weakness, royalty disputes",
    "ARM": "Royalty rate compression, client concentration (Google/Apple), high-multiple de-rating risk",
    "SMCI": "Hyperscaler bargaining power compressing margins, Nvidia GPU allocation dependency, audit overhang",
    "PLTR": "Government contract lumpiness, high multiple means growth miss punishes the stock",
    "SNOW": "Consumption growth slowing, competition from Databricks and BigQuery, NRR declining",
    "DDOG": "Cloud spend optimization hitting usage revenue, competition from Grafana and Splunk",
    "MDB": "Atlas growth deceleration, competition from Snowflake and Databricks, developer preference shifts",
    "NET": "SASE competition from ZS and PANW, zero-trust market fragmenting, code-key incident reputation risk",
    "CRWD": "Post-outage churn risk, PANW and S competitive pressure, large-enterprise deal lengthening",
    "OKTA": "Security incident overhang, Salesforce competition in identity, large-deal cycle elongation",
    "ZS": "SASE market crowding, zero-trust commoditization, sales cycle lengthening",
    "DOCN": "Hyperscaler price war crushing SMB cloud pricing, scale disadvantage, churn risk in down cycle",
    "LCID": "Cash burn runway, production ramp delays, Saudi ownership overhang. Not investable without execution.",
    "RIVN": "Cash burn is existential, Amazon van contract renegotiation risk, pickup truck demand weakening",
    "SHOP": "SMB churn in downturn, competitive pressure from Amazon and WooCommerce, revenue take rate pressure",
    "COIN": "Crypto volume collapse in risk-off, regulation (SEC), staking revenue under legal threat",
    "HOOD": "PFOF regulatory risk, crypto volume volatility, retail trading decline in bear markets",
    "PYPL": "Branded checkout losing share to Apple Pay, Braintree take rate compression, turnaround execution risk",
    "UBER": "AV partners could disintermediate, driver supply/demand imbalance, regulatory pressure on gig classification",
    "ABNB": "Travel demand normalization post-revenge-spend, host regulation risk, hotels competing on price",
    "NFLX": "Content spend arms race, ad-tier ARPU dilution, sub saturation in developed markets",
    "DIS": "Linear TV decline accelerating, streaming unprofitability, parks cyclicality, CEO transition risk",
    "RKLB": "Launch failure risk, Neutron rocket schedule slippage, small-launch market limited, cash runway",
    "SPOT": "Label relationship renegotiation, podcast investment ROI unclear, ad-tier margin dilution",
    "SQ": "Cash App regulatory scrutiny, Bitcoin revenue volatility, forward-guidance risk from macro sensitivity",
    "TWLO": "Growth deceleration, competitive pressure from AWS Pinpoint and Bandwidth, path to GAAP profitability unproven",
    "GTLB": "GitHub (Microsoft) competition, AI feature monetization uncertain, usage-based revenue volatile",
    "S": "CRWD competitive pressure, growth rate slowing, path to profitability longer than peers",
    "PINS": "User growth plateau, Amazon partnership revenue ramp uncertain, ad market cyclicality",
    "RBLX": "Bookings conversion to revenue timing, metaverse adoption uncertain, path to profitability multi-year",
    "DUOL": "Language learning market saturation, AI competition from ChatGPT, monetization ceiling uncertain",
    "AFRM": "consumer credit losses in downturn, merchant concentration, rising funding costs",
    "CAT": "China construction slowdown, commodity price collapse, inventory destocking",
    "COST": "membership growth saturation, international expansion execution, wage inflation",
    "HD": "housing market freeze from high rates, DIY demand normalization, lumber cost volatility",
    "LLY": "GLP-1 supply constraints, Novo Nordisk competition, insurance formulary pushback",
    "LMND": "loss ratio volatility, catastrophic event exposure, cash runway to profitability",
    "MRVL": "data center buildout slowdown, custom silicon competition, China telecom exposure",
    "PAYO": "regulatory scrutiny on cross-border payments, FX volatility, SMB customer churn",
    "RELY": "remittance volume tied to immigration flows, FX headwinds, regulatory licensing",
    "SOFI": "student loan refinancing policy risk, deposit beta pressure, Galileo customer concentration",
    "TER": "memory overbuild cutting test demand, auto/robotics slowdown, China fab restrictions",
    "TMO": "biopharma R&D budget cuts, China diagnostics competition, M&A integration risk",
    "UNH": "CMS rate cuts, GLP-1 cost inflation for insurers, regulatory overhaul risk",
    "UPST": "recession -&gt; loan defaults spike, funding partner pullback, AI model bias scrutiny",
}

# ═══════════════════════════════════════════════════════════════════════
# HOLDINGS NARRATIVE GENERATORS (v3)
# ═══════════════════════════════════════════════════════════════════════


_EARNINGS_RE = re.compile(r'\b(earnings|EPS|beat estimates|missed estimates|guidance (upgrade|cut)|revenue surge|profit surge|sales beat)\b', re.IGNORECASE)

def _infer_pead(signal_data):
    """Infer post-earnings announcement drift from Alpaca news headlines."""
    news = signal_data.get("news") or {}
    headline = news.get("alpaca_headline", "") if isinstance(news, dict) else ""
    has_earnings = bool(_EARNINGS_RE.search(headline))
    confirmations = signal_data.setdefault("confirmations", {})
    if "earnings_confirmed" not in confirmations:
        confirmations["earnings_confirmed"] = has_earnings
        if has_earnings:
            signal_data["confirmation_count"] = signal_data.get("confirmation_count", 0) + 1
    # Update denominator in tier_reason to reflect 10-factor pool (including PEAD + relvol + vwap)
    if "tier_reason" in signal_data and ("/8" in str(signal_data.get("tier_reason", "")) or "/9" in str(signal_data.get("tier_reason", ""))):
        signal_data["tier_reason"] = signal_data["tier_reason"].replace("/9", "/10")



def nice_join(items, sep=', ', last_sep=' and '):
    if not items:
        return ''
    *rest, last = items
    if not rest:
        return last
    return sep.join(rest) + last_sep + last

def _visible_confirmation_count(signal_data):
    """Count green lights exactly as buildFactorChips does on the frontend."""
    conf = signal_data.get("confirmations", {})
    m = signal_data.get("momentum_score")
    ms = m if m is not None else conf.get("momentum_score")
    if ms is None and isinstance(conf.get("momentum_score"), (int, float)):
        ms = conf["momentum_score"]
    count = 0
    if ms is not None and ms >= 50:
        count += 1
    if conf.get("rsi_signal") in ('bullish', 'neutral', 'oversold'):
        count += 1
    if conf.get("volume_confirmed") is True:
        count += 1
    if conf.get("macd_turning") is True:
        count += 1
    if conf.get("above_ema") is True:
        count += 1
    if conf.get("sector_strong") is True:
        count += 1
    if conf.get("intraday_confirmed") is True:
        count += 1
    if conf.get("options_confirmed") is True:
        count += 1
    if conf.get("earnings_confirmed") is True:
        count += 1
    if conf.get("relvol_confirmed") is True:
        count += 1
    if conf.get("vwap_confirmed") is True:
        count += 1
    return count


def _what_it_is(symbol, signal_data, sector, company):
    """'One sentence. Trader shorthand — crisp.'"""
    name = company if company and company != symbol else symbol
    note = _COMPANY_NOTES.get(symbol)
    if note:
        return f"{name} — {note}"
    blurbs = {
        "Semiconductors":    "chip / semiconductor name",
        "AI/Growth":        "AI / high-growth tech name",
        "Tech Giants":      "mega-cap tech / cloud name",
        "Fintech":          "payments / lending / digital finance name",
        "Consumer/Platform": "consumer platform / marketplace name",
        "Cloud/Data":       "enterprise cloud / data software name",
        "EV/Mobility":      "electric vehicle / mobility name",
        "Retail/Lifestyle":  "retail / brand / lifestyle name",
        "Cybersecurity":    "cybersecurity / zero-trust name",
        "Healthcare":      "healthcare / pharma / managed care name",
        "Energy":          "oil / gas / renewable energy name",
        "Industrials":      "aerospace / manufacturing / industrial name",
        "Financials":       "bank / broker / insurance name",
        "Communications":   "telecom / comms infra / streaming name",
        "Tech Expansion":   "legacy tech / hardware name",
    }
    blurb = blurbs.get(sector, f"{sector} name" if sector != "Other" else "small-cap name")
    return f"{name} — {blurb}."

def _why_bot_bought(signal_data, position, thesis_data=None):
    """Why we entered — trader note, not a robot log."""
    entry_readiness = thesis_data.get("entry_readiness", 0) if thesis_data else signal_data.get("readiness_score", 0)
    confirmations = thesis_data.get("confirmations", {}) if thesis_data else signal_data.get("confirmations", {})
    entry_price = position.get("avg_entry", 0)
    conf_count = _visible_confirmation_count(signal_data)

    conviction = "high-conviction" if entry_readiness >= 80 else "standard" if entry_readiness >= 60 else "moderate"
    sigs = []
    if confirmations.get("above_ema"):      sigs.append("price above 20-day EMA")
    if confirmations.get("sector_strong"):  sigs.append("hot sector")
    if confirmations.get("volume_confirmed"): sigs.append("volume confirming the move")
    if confirmations.get("macd_turning"):     sigs.append("MACD curling up")
    if confirmations.get("rsi_signal") == "oversold": sigs.append("RSI washed out")
    if confirmations.get("earnings_confirmed"): sigs.append("post-earnings drift in play")
    if confirmations.get("intraday_confirmed"): sigs.append("intraday momentum")
    if confirmations.get("options_confirmed"): sigs.append("options skew bullish")
    if confirmations.get("relvol_confirmed"): sigs.append("volume surge confirming move")
    if confirmations.get("vwap_confirmed"): sigs.append("price above VWAP -- buyers in control")

    if sigs:
        return f"Sniped at ${entry_price:.2f}. {conviction} read of {entry_readiness:.0f} with {conf_count} green lights: {nice_join(sigs[:3])}."
    return f"Sniped at ${entry_price:.2f}. {conviction} read of {entry_readiness:.0f}."

def _how_its_doing(position, signal_data, watchlist_data):
    """'How the position is acting. No filler.'"""
    pl_pct = position.get("unrealized_plpc", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    price = position.get("current", 0) or 0
    avg   = position.get("avg_entry", 0) or 0

    if pl_pct >= 25:
        tone = f"Up {pl_pct:.1f}% — printing hard and deep in profit."
    elif pl_pct >= 5:
        tone = f"Up {pl_pct:.1f}% — momentum building."
    elif pl_pct >= -5:
        tone = f"Flat — {pl_pct:+.1f}%. Waiting for the next leg."
    elif pl_pct >= -10:
        tone = f"Down {abs(pl_pct):.1f}%. Under pressure, thesis breathing room shrinking."
    else:
        tone = f"Down {abs(pl_pct):.1f}% — thesis on thin ice. Stops will do the talking."

    tier_note = {
        "STRONG_NOW": "Signal locked at STRONG NOW. Thesis intact.",
        "NOW":        "Signal holding at NOW. Thesis intact.",
        "WATCH":     "Signal slipped to WATCH. Thesis cooling.",
        "MONITOR":   "Signal faded to MONITOR. Thesis on life support.",
        "TRACKING":  "Signal gone quiet — bench patrol.",
    }.get(tier, "")

    if price and avg:
        basis = f" Entry ${avg:.2f} → now ${price:.2f}."
    else:
        basis = ""
    return f"{tone} {tier_note}{basis}"

def _what_moves_it(signal_data):
    """What is driving it. PMs do not read spreadsheets aloud."""
    catalysts = []
    news = signal_data.get("news")
    if isinstance(news, dict):
        headline = news.get("alpaca_headline") or news.get("sample_headline")
        sentiment = news.get("alpaca_sentiment") or news.get("sentiment_label", "")
        if headline:
            clean = headline[:100] + ("..." if len(headline) > 100 else "")
            if sentiment in ("bullish", "bearish"):
                catalysts.append(f'{sentiment.capitalize()} headline driving tape: “{clean}”')
            else:
                catalysts.append(f'Headline moving the name: “{clean}”')

    mom = signal_data.get("momentum_20d", 0)
    if mom and mom > 0.15:
        catalysts.append(f"20-day momentum running hot at +{mom*100:.0f}%")
    elif mom and mom > 0.05:
        catalysts.append(f"20-day momentum firm at +{mom*100:.0f}%")
    elif mom and mom < -0.15:
        catalysts.append(f"20-day slide at {mom*100:.0f}% — deep enough to watch for a reversal")
    elif mom and mom < -0.05:
        catalysts.append(f"20-day slide at {mom*100:.0f}% — watching for a floor")

    if catalysts:
        return " ".join(catalysts) + "."
    return "No headline catalyst active right now — riding the pure technical setup."

def _iv_scalar(iv):
    """Return a scalar IV from either a float or the new IV-summary dict."""
    if iv is None:
        return None
    if isinstance(iv, dict):
        return iv.get("iv_30d") or iv.get("options_implied_vol") or None
    try:
        return float(iv)
    except (TypeError, ValueError):
        return None


def _what_kills_it(symbol, position, signal_data, watchlist_data, stops):
    """The bear case. Short, surgical, no robot-speak."""
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    vol = signal_data.get("volatility_20d")
    iv  = _iv_scalar(signal_data.get("options_implied_vol"))
    spy_corr = signal_data.get("spy_corr_20d")

    risks = []
    cr = _COMPANY_RISKS.get(symbol)
    if cr:
        risks.append(cr)
    else:
        map_ = {
            "Semiconductors":    "chip cycle downturn and capex pull-back",
            "AI/Growth":        "AI hype deflation and rate sensitivity",
            "Tech Giants":      "growth deceleration and regulatory heat",
            "Fintech":          "regulatory crackdown and credit-loss creep",
            "Consumer/Platform": "consumer spending slowdown",
            "Cloud/Data":       "enterprise IT spend freeze",
            "EV/Mobility":      "EV price war and demand destruction",
            "Retail/Lifestyle":  "discretionary spending pullback",
            "Cybersecurity":    "competitive pricing and budget pressure",
            "Healthcare":      "drug pricing policy and trial failure risk",
            "Energy":          "oil price volatility",
            "Industrials":      "cyclical demand slowdown",
            "Financials":       "credit losses and rate-sensitive margins",
            "Communications":   "advertising decline andcord-cutting",
            "Tech Expansion":   "legacy business decline and execution risk",
        }
        sr = map_.get(sector)
        if sr:
            risks.append(sr)

    if spy_corr and spy_corr > 0.80:
        risks.append("clones the S&P move-for-move")
    elif spy_corr and spy_corr > 0.60:
        risks.append("high beta to the broad market")

    vol_note = None
    if vol and vol > 0.45:
        vol_note = f"wild volatility ({vol*100:.0f}% annualized)"
    elif vol and vol > 0.30:
        vol_note = f"elevated volatility ({vol*100:.0f}%)"
    if vol_note:
        risks.append(vol_note)
    if iv and iv > 0.6:
        risks.append(f"options pricing fear (IV {iv*100:.0f}%)")

    hard = stops.get("hard_stop", 0)
    trail = stops.get("trailing_stop", 0)
    vwap  = stops.get("vwap_stop")
    stop_parts = [f"hard ${hard:.2f}"]
    if trail and trail > 0:
        stop_parts.append(f"trailing ${trail:.2f}")
    if vwap and vwap > 0:
        stop_parts.append(f"VWAP ${vwap:.2f}")

    if risks:
        return "The bear case: " + "; ".join(risks) + f". Stops: {', '.join(stop_parts)}."
    return f"Standard equity risk. Stops: {', '.join(stop_parts)}."

def _confidence_level(position, signal_data, watchlist_data):
    """Plain-English conviction — decisive, no hedging."""
    pl_pct = position.get("unrealized_plpc", 0)
    readiness = signal_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")

    if tier == "STRONG_NOW":
        if pl_pct >= 10:   return "Locked in. Highest-conviction play and it is already printing."
        elif pl_pct >= 0:  return "Locked in. Highest-conviction play — position building gains."
        else:               return "Locked in on conviction. Short-term drawdown, but the thesis is intact."
    elif tier == "NOW":
        if pl_pct >= 5:    return "Solid. Signal holding and the position is green."
        elif pl_pct >= 0:  return "Solid. Signal alive, roughly flat."
        else:               return "Shaky. Signal alive but position is bleeding. Eyes wide open."
    elif tier == "WATCH":
        return "Cooling off. Readiness slipped below the entry zone. Patience required."
    elif tier == "MONITOR":
        if readiness < 40: return "Thesis broken. Readiness below 40. Exit is the next move."
        else:              return "Staring at the exit door. Readiness is fading fast."
    else:
        return "No edge. Watching from the bench."

# ─────────────────────────────────────────────────────────────────────
# HOLDINGS narrative (replaces generate_dynamic_narrative)
# ─────────────────────────────────────────────────────────────────────

def generate_dynamic_narrative(symbol, position, watchlist_data, signal_data, risk_config, risk_state):
    _infer_pead(signal_data)
    pl_percent = position.get("unrealized_plpc", 0)
    price = position.get("current", 0)
    avg_entry = position.get("avg_entry", 0)
    qty = position.get("qty", 0)
    market_value = position.get("market_value", 0)

    total_score = signal_data.get("total_score", 0)
    momentum_score = signal_data.get("momentum_score", 0)
    quality_score = signal_data.get("quality_score", 0)
    risk_score = signal_data.get("risk_score", 0)
    regime_score_val = signal_data.get("regime_score", 0)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or COMPANY_NAMES.get(symbol, symbol)
    drivers = signal_data.get("drivers", [])

    # Load thesis data for entry confirmations
    thesis_data = {}
    try:
        with open(BOT_DIR / "position_theses.json") as f:
            theses = json.load(f)
            thesis_data = theses.get(symbol, {})
    except Exception:
        pass

    stops = get_stop_levels(symbol, position, risk_config, risk_state, signal_data)

    # Build dynamic narratives
    what_it_is = _what_it_is(symbol, signal_data, sector, company)
    why_owned = _why_bot_bought(signal_data, position, thesis_data)
    how_doing = _how_its_doing(position, signal_data, watchlist_data)
    catalyst = _what_moves_it(signal_data)
    risk = _what_kills_it(symbol, position, signal_data, watchlist_data, stops)
    confidence = _confidence_level(position, signal_data, watchlist_data)

    readiness = signal_data.get("readiness_score", 0)
    entry_eligible = signal_data.get("entry_eligible", False)
    confirmation_count = signal_data.get("confirmation_count", 0)
    tier_reason = signal_data.get("tier_reason", "")
    confirmations = signal_data.get("confirmations", {})
    tier = signal_data.get("tier", "MONITOR")
    signal_tier = watchlist_data.get("signal_tier") or tier
    display_tier = watchlist_data.get("display_tier") or signal_tier
    signal = signal_label(pl_percent, total_score, tier)

    result = {
        "whatItIs": what_it_is,
        "whyWeOwnIt": why_owned,
        "howItsDoing": how_doing,
        "catalyst": catalyst,
        "risk": risk,
        "confidence": confidence,
        "signal": signal,
        "tier": display_tier,
        "signal_tier": signal_tier,
        "display_tier": display_tier,
        "backend_tier": tier,
        "readiness_score": round(readiness, 1) if readiness else None,
        "entry_eligible": entry_eligible,
        "confirmation_count": confirmation_count,
        "tier_reason": tier_reason,
        "confirmations": confirmations,
        "company": company,
        "entryReason": why_owned,
        "stopReason": f"Hard stop ${stops['hard_stop']:.2f} (-10%); trailing ${stops['trailing_stop']:.2f}",
        "totalScore": round(total_score, 1) if total_score > 0 else None,
        "momentumScore": round(momentum_score, 1) if momentum_score > 0 else None,
        "qualityScore": round(quality_score, 1) if quality_score > 0 else None,
        "riskScore": round(risk_score, 1) if risk_score > 0 else None,
        "regimeScore": round(regime_score_val, 1) if regime_score_val > 0 else None,
        "plPercent": pl_percent,
        "price": price,
        "qty": qty,
        "marketValue": market_value,
        "avgEntry": avg_entry,
        "hardStop": stops["hard_stop"],
        "trailingStop": stops["trailing_stop"],
        "vwapStop": stops.get("vwap_stop"),
        "lastUpdated": now().isoformat().replace("+00:00", "Z"),
        "drivers": drivers,
        "alpacaNewsHeadline": signal_data.get("news", {}).get("alpaca_headline") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSentiment": signal_data.get("news", {}).get("alpaca_sentiment") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsUrl": signal_data.get("news", {}).get("alpaca_url") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSource": signal_data.get("news", {}).get("alpaca_source") if isinstance(signal_data.get("news"), dict) else None,
        "optionsImpliedVol": _iv_scalar(signal_data.get("options_implied_vol")),
        "momentum20d": signal_data.get("momentum_20d"),
        "momentum50d": signal_data.get("momentum_50d"),
        "strategyType": signal_data.get("strategy_type", "momentum"),
        "volatility20d": signal_data.get("volatility_20d"),
        "spyCorr20d": signal_data.get("spy_corr_20d"),
        "atr14": signal_data.get("atr14"),
        "dailyVwap": signal_data.get("daily_vwap"),
        "prevClose": signal_data.get("prev_close"),
        "intradayVwap": signal_data.get("intraday_vwap"),
        "intradayVolRatio": signal_data.get("intraday_vol_ratio"),
        "vwapDeviation": round((price - signal_data.get("daily_vwap", price)) / signal_data.get("daily_vwap", price) * 100, 2) if signal_data.get("daily_vwap") and price else None,
        "rsi": signal_data.get("rsi14", 50),
        "aiScore": int(min(100, max(30, total_score))) if total_score > 0 else None,
        "isScored": total_score > 0,
        "sources": {
            "whatItIs": "Company profile (internal) | Alpaca ticker lookup",
            "whyWeOwnIt": "StonkBOT signal engine | Alpaca bars, options, news",
            "howItsDoing": "StonkBOT signal engine | Alpaca positions + bars",
            "catalyst": "Alpaca newsfeed + Alpaca bars",
            "risk": "StonkBOT risk engine | Alpaca ATR, IV, vol, correlation",
            "confidence": "StonkBOT signal engine | Alpaca bars, options, IV",
            "confirmations": "StonkBOT signal engine | Alpaca bars, options, news, IV",
            "momentumScore": "Alpaca bars API (20d/50d returns)",
            "price": "Alpaca latest quote",
            "avgEntry": "Alpaca positions API",
            "alpacaNewsHeadline": "Alpaca news API",
            "alpacaNewsSentiment": "Alpaca news API",
            "rsi": "Alpaca bars API (14d)",
            "volatility20d": "Alpaca bars API",
            "spyCorr20d": "Alpaca bars API",
            "atr14": "Alpaca bars API",
            "hardStop": "StonkBOT risk engine (Alpaca ATR)",
            "trailingStop": "StonkBOT risk engine (Alpaca ATR)",
            "vwapStop": "StonkBOT risk engine (Alpaca VWAP)",
            "dailyVwap": "Alpaca bars API",
            "prevClose": "Alpaca bars API",
            "intradayVwap": "Alpaca bars API",
            "intradayVolRatio": "Alpaca bars API",
            "vwapDeviation": "Alpaca bars API",
            "optionsImpliedVol": "Alpaca options API",
            "drivers": "StonkBOT signal engine (Alpaca bars, IV, news)",
            "aiScore": "StonkBOT engine (Alpaca-derived composite)",
            "momentum20d": "Alpaca bars API",
            "momentum50d": "Alpaca bars API",
            "totalScore": "StonkBOT engine (Alpaca bars)",
            "qualityScore": "StonkBOT engine (Alpaca bars)",
            "riskScore": "StonkBOT engine (Alpaca bars)",
            "regimeScore": "StonkBOT engine (Alpaca bars)",
            "sector": "Alpaca assets API",
            "company": "Alpaca assets API",
            "strategyType": "StonkBOT engine",
        },
    }

    # Extended hours from watchlist live feed
    result["premarket_change_pct"] = watchlist_data.get("premarket_change_pct")
    result["premarket_volume"] = watchlist_data.get("premarket_volume")
    result["afterhours_change_pct"] = watchlist_data.get("afterhours_change_pct")
    result["afterhours_volume"] = watchlist_data.get("afterhours_volume")

    return result


# ─────────────────────────────────────────────────────────────────────
# WATCHLIST narrative (replaces generate_watchlist_narrative)
# ─────────────────────────────────────────────────────────────────────

def _missing_factors(signal_data):
    """List which confirmation factors are NOT green, for gap diagnosis."""
    conf = signal_data.get("confirmations", {})
    mom_score = conf.get("momentum_score", signal_data.get("momentum_score", 0))
    missing = []
    if mom_score < 50:
        missing.append("momentum")
    rsi = conf.get("rsi_signal", "")
    if rsi not in ("bullish", "overbought"):
        missing.append("RSI")
    if not conf.get("volume_confirmed"):
        missing.append("volume")
    if not conf.get("macd_turning"):
        missing.append("MACD")
    if not conf.get("above_ema"):
        missing.append("EMA")
    if not conf.get("sector_strong"):
        missing.append("sector")
    if not conf.get("intraday_confirmed"):
        missing.append("intraday")
    if not conf.get("options_confirmed"):
        missing.append("options")
    if not conf.get("earnings_confirmed"):
        missing.append("PEAD")
    return missing


def _why_on_watchlist(signal_data, watchlist_data):
    """Why this name is on the list. Punchy, data-first, human."""
    r = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")
    entry = watchlist_data.get("entry_eligible") or signal_data.get("entry_eligible", False)
    c = _visible_confirmation_count(signal_data)

    if tier == "STRONG_NOW" and entry:
        return f"Locked and loaded. Readiness at {r:.0f} with {c} green lights firing. Highest-conviction tier — bot deploys 1.5x size the second cash clears."
    elif tier == "NOW" and entry:
        return f"Entry-ready. Readiness at {r:.0f}, {c} confirmations in the green. Bot will buy as soon as portfolio cash frees up."
    elif tier == "WATCH" and entry:
        return f"Mean reversion play. Readiness at {r:.0f}, {c} lights green. Momentum is below the 72 gate but the setup is mathematically valid."
    elif tier == "WATCH":
        gap = max(0, 72 - r)
        missing = _missing_factors(signal_data)
        missing_text = ", ".join(missing[:3]) + (" and others" if len(missing) > 3 else "") if missing else "supporting factors"
        if gap > 5 and c < 2:
            return f"Watching from the sidelines. Readiness at {r:.0f} — {gap:.0f} points short of the 72 gate. Only {c} confirmation(s). Needs both momentum and confirmations."
        elif gap > 5:
            return f"Watching from the sidelines. Readiness at {r:.0f} — {gap:.0f} points short of the 72 gate. Already has {c} confirmations green but needs more {missing_text}."
        elif gap > 0 and c < 2:
            return f"Close. Readiness at {r:.0f} — only {gap:.0f} shy of the gate. Only {c} confirmation(s). Needs 2+ green lights to fire."
        elif gap > 0:
            return f"Close. Readiness at {r:.0f} — just {gap:.0f} shy of the 72 entry gate. Already has {c} confirmations green. Missing: {missing_text}."
        elif c < 2:
            return f"At the gate. Readiness at {r:.0f} clears the 72 gate but only {c} confirmation firing. Needs 2+ green lights to pull the trigger."
        else:
            return f"Close. Readiness at {r:.0f} clears the gate with {c} confirmations but tracking as WATCH."
    elif tier == "MONITOR":
        return f"Tracking only. Readiness at {r:.0f} — nowhere near the entry zone. Waiting for a signal revival."
    else:
        return f"Quiet in the tape. Readiness at {r:.0f}. No trade today."

def _what_triggers_buy(signal_data, watchlist_data):
    """What is missing to trigger a buy. No corporate jargon."""
    r = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)
    c = _visible_confirmation_count(signal_data)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "MONITOR")

    if tier in ("STRONG_NOW", "NOW") and watchlist_data.get("entry_eligible"):
        return "Gate is open. All systems go — just waiting for cash to clear."

    gaps = []
    if r < 72:
        gaps.append(f"readiness {r:.0f} → 75")
    if c < 2:
        gaps.append(f"{c} confirmation firing (need 2+)" if c > 0 else "zero confirmations (need 2+)")

    missing = _missing_factors(signal_data)
    if missing:
        shown = nice_join(missing[:3]) + (" and others" if len(missing) > 3 else "")
        gaps.append(f"missing: {shown}")

    if not gaps:
        return "Everything lined up. Should trigger any minute."
    return "Gate is shut. Still needs " + "; ".join(gaps) + "."

def _watchlist_risk(signal_data, watchlist_data):
    """Watchlist risk — same surgical tone as holdings."""
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    vol = signal_data.get("volatility_20d")
    iv  = _iv_scalar(signal_data.get("options_implied_vol"))
    rsi = signal_data.get("rsi14", 50)
    symbol = signal_data.get("symbol", "") or watchlist_data.get("symbol", "")

    risks = []
    cr = _COMPANY_RISKS.get(symbol)
    if cr:
        risks.append(cr)
    else:
        map_ = {
            "Semiconductors":    "chip cycle and capex volatility",
            "AI/Growth":        "AI sentiment shifts and rate sensitivity",
            "Tech Giants":      "antitrust and growth deceleration",
            "Fintech":          "regulation and credit losses",
            "Consumer/Platform": "consumer spending cyclicality",
            "Cloud/Data":       "enterprise IT budgets",
            "EV/Mobility":      "EV price wars and demand",
            "Retail/Lifestyle":  "discretionary spending",
            "Cybersecurity":    "competitive pricing pressure",
            "Healthcare":      "drug pricing policy",
            "Energy":          "oil price swings",
            "Industrials":      "cyclical demand",
            "Financials":       "credit and rate cycles",
            "Communications":   "advertising and cord-cutting",
            "Tech Expansion":   "legacy decline and execution",
        }
        sr = map_.get(sector)
        if sr:
            risks.append(sr)

    if vol and vol > 0.45:
        risks.append(f"wild volatility ({vol*100:.0f}%)")
    elif vol and vol > 0.30:
        risks.append(f"elevated volatility ({vol*100:.0f}%)")
    if iv and iv > 0.6:
        risks.append(f"options pricing fear (IV {iv*100:.0f}%)")
    if rsi and rsi > 75:
        risks.append("RSI overheated — pullback risk")

    if not risks:
        risks.append("standard market risk")
    return "The bear case: " + ", ".join(risks) + "."

def generate_watchlist_narrative(symbol, signal_data, watchlist_data):
    _infer_pead(signal_data)
    total_score = signal_data.get("total_score", 0)
    sector = signal_data.get("sector") or watchlist_data.get("sector", "Other")
    company = signal_data.get("company") or COMPANY_NAMES.get(symbol, symbol)
    price = watchlist_data.get("price") or signal_data.get("price", 0)
    tier = watchlist_data.get("signal_tier") or signal_data.get("tier", "TRACKING")
    readiness = signal_data.get("readiness_score", 0) or watchlist_data.get("readiness_score", 0)

    return {
        "symbol": symbol,
        "company": company,
        "whatItIs": _what_it_is(symbol, signal_data, sector, company),
        "whyOnWatchlist": _why_on_watchlist(signal_data, watchlist_data),
        "whatTriggersBuy": _what_triggers_buy(signal_data, watchlist_data),
        "catalyst": _what_moves_it(signal_data),
        "risk": _watchlist_risk(signal_data, watchlist_data),
        "total_score": round(total_score, 1) if total_score else None,
        "readiness_score": round(readiness, 1) if readiness else None,
        "tier": tier,
        "confirmations": signal_data.get("confirmations", {}),
        "confirmation_count": signal_data.get("confirmation_count", 0),
        "price": price,
        "sector": sector,
        "last_updated": now().isoformat().replace("+00:00", "Z"),
        "alpacaNewsHeadline": signal_data.get("news", {}).get("alpaca_headline") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSentiment": signal_data.get("news", {}).get("alpaca_sentiment") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsUrl": signal_data.get("news", {}).get("alpaca_url") if isinstance(signal_data.get("news"), dict) else None,
        "alpacaNewsSource": signal_data.get("news", {}).get("alpaca_source") if isinstance(signal_data.get("news"), dict) else None,
        "sources": {
            "whatItIs": "Company profile (internal) | Alpaca ticker lookup",
            "whyOnWatchlist": "StonkBOT signal engine | Alpaca bars, options, news",
            "whatTriggersBuy": "StonkBOT signal engine | Alpaca bars, options, news",
            "catalyst": "Alpaca newsfeed + Alpaca bars",
            "risk": "StonkBOT risk engine | Alpaca IV, vol, correlation",
            "readiness": "StonkBOT signal engine | Alpaca bars, options, IV",
            "confirmations": "StonkBOT signal engine | Alpaca bars, options, news, IV",
            "total_score": "StonkBOT engine (Alpaca bars)",
            "tier": "StonkBOT engine (Alpaca bars)",
            "price": "Alpaca latest quote",
            "sector": "Alpaca assets API",
            "company": "Alpaca assets API",
            "alpacaNewsHeadline": "Alpaca news API",
            "alpacaNewsSentiment": "Alpaca news API",
        },
    }


def signal_tier(total_score):
    if total_score >= 55:
        return "NOW"
    if total_score >= 45:
        return "WATCH"
    if total_score > 0:
        return "MONITOR"
    return "TRACKING"


def generate_popup_content():
    _market_open = is_market_open()
    if not _market_open:
        logger.info("Markets closed — generating with available data")

    portfolio = load_json(PORTFOLIO_FILE)
    watchlist = load_json(WATCHLIST_FILE).get("prices", {})
    signals_map = load_signals_map()
    risk_config = load_risk_config()
    risk_state = load_risk_state()

    positions = portfolio.get("positions", [])
    if not positions:
        logger.warning("No positions in portfolio")
        return None

    popup_data = {
        "timestamp": now().isoformat().replace("+00:00", "Z"),
        "holdings": {},
    }

    watchlist_narratives = {
        "timestamp": now().isoformat().replace("+00:00", "Z"),
        "narratives": {},
    }
    for symbol, wdata in watchlist.items():
        signal_data = signals_map.get(symbol, {})
        try:
            narrative = generate_watchlist_narrative(symbol, signal_data, wdata)
            # Enrich narrative with confirmation data for monitor/frontend parity
            conf = signal_data.get("confirmations", {})
            narrative["confirmations"] = conf
            narrative["confirmation_count"] = signal_data.get("confirmation_count") or (sum(1 for k, v in conf.items() if v) if conf else 0)
            narrative["readiness_score"] = signal_data.get("readiness_score")
            narrative["signal_tier"] = signal_data.get("tier")
            narrative["entry_eligible"] = signal_data.get("entry_eligible", False)
            watchlist_narratives["narratives"][symbol] = narrative
        except Exception as e:
            logger.error(f"Failed to generate watchlist narrative for {symbol}: {e}")

    try:
        WATCHLIST_NARRATIVES_FILE.write_text(json.dumps(watchlist_narratives, indent=2))
        logger.info(f"Saved watchlist narratives for {len(watchlist_narratives['narratives'])} symbols")
    except Exception as e:
        logger.error(f"Failed to save watchlist narratives: {e}")

    for position in positions:
        symbol = position.get("symbol")
        if not symbol:
            continue
        watchlist_data = watchlist.get(symbol, {})
        signal_data = signals_map.get(symbol, {})
        try:
            narrative = generate_dynamic_narrative(
                symbol, position, watchlist_data, signal_data, risk_config, risk_state
            )
            popup_data["holdings"][symbol] = narrative
            logger.info(f"Generated popup content for {symbol}: {narrative['signal']}")
        except Exception as e:
            logger.error(f"Failed to generate narrative for {symbol}: {e}")

    try:
        POPUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        POPUP_FILE.write_text(json.dumps(popup_data, indent=2))
        logger.info(f"Saved popup content for {len(popup_data['holdings'])} holdings")
    except Exception as e:
        logger.error(f"Failed to save popup content: {e}")
        return None

    return popup_data


if __name__ == "__main__":
    logger.info("=== STONK.AI Popup Content Generator v3 Starting ===")
    result = generate_popup_content()
    if result:
        logger.info(f"Successfully generated content for {len(result['holdings'])} positions")
    else:
        logger.info("No popup data generated")