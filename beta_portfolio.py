#!/usr/bin/env python3
"""
High-Beta Portfolio to Beat S&P 500
$10,000 allocation with speculative growth focus
"""

PORTFOLIO = {
    # AI/Growth (60% = $6,000) - High conviction
    "NVDA": {"shares": 12, "theme": "AI chips", "conviction": "high"},
    "PLTR": {"shares": 25, "theme": "AI/Gov tech", "conviction": "high"},
    "CRWD": {"shares": 3, "theme": "Cybersecurity", "conviction": "high"},
    "APP": {"shares": 8, "theme": "AI ad tech", "conviction": "speculative"},
    "SOFI": {"shares": 100, "theme": "Fintech/AI", "conviction": "medium"},
    
    # Tech/Balance (25% = $2,500)
    "AVGO": {"shares": 5, "theme": "AI dividend", "conviction": "medium"},
    "META": {"shares": 3, "theme": "AI/Ads", "conviction": "medium"},
    "HOOD": {"shares": 25, "theme": "Fintech", "conviction": "speculative"},
    
    # Defensive/Cash (15% = $1,500)
    "SCHD": {"shares": 30, "theme": "Dividend ETF", "conviction": "defensive"},
    "SGOV": {"shares": 15, "theme": "Cash buffer", "conviction": "cash"},
}

ALLOCATION = {
    "growth": 0.60,
    "tech": 0.25,
    "defensive": 0.15
}

THESIS = """
PORTFOLIO THESIS - Beat S&P 500

1. AI INFRASTRUCTURE (60%)
   - NVDA: Core AI play, data center demand
   - PLTR: Government/enterprise AI, fits small-cap rotation
   - CRWD: Cybersecurity, defensive growth
   - APP: AI-driven ad tech, 500% YTD momentum
   - SOFI: AI lending, rate cut beneficiary

2. QUALITY TECH (25%)
   - AVGO: AI chips + 3% dividend
   - META: AI/VR, advertising recovery
   - HOOD: Crypto trading volume, retail comeback

3. DEFENSIVE ANCHOR (15%)
   - SCHD: Dividend aristocrats
   - SGOV: Cash for opportunities

RISK FACTORS:
- High volatility (70% growth = big swings)
- APP is speculative (could drop 30% fast)
- Fed policy changes impact SOFI/HOOD

TARGET: Beat S&P 500 by 10%+ over 3-6 months
"""
