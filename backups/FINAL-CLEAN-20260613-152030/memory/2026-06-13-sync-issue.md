# Watchlist Sync Issue - Resolution

## Problem
User reported: "I don't see all these stocks you mentioned in the watchlist"

## Root Cause
The watchlist manager dynamically rotates stocks based on RSI thresholds, but the website's HTML had a **hardcoded** `companyInfo` object with old stock symbols. When the manager rotated to new stocks (AMZN, NFLX, SOFI, etc.), the website still showed company info for old stocks (ORCL, IBM, CSCO, etc.).

## Solution Implemented

### 1. Created Dynamic Company Info System
- **File**: `/var/www/hedge-fund-website/company_info.json`
- **Purpose**: Single source of truth for company information
- **Auto-updates**: Watchlist manager updates this file when stocks rotate

### 2. Updated Watchlist Manager
- **File**: `/opt/stonk-ai/dynamic_watchlist_manager.py`
- **Change**: Added code to update `company_info.json` when watchlist rotates
- **Logic**: Keep only current symbols, add placeholders for new ones

### 3. Updated Website
- **File**: `/var/www/hedge-fund-website/index.html`
- **Change**: 
  - Replaced hardcoded `companyInfo` object with dynamic loader
  - Added `fetchCompanyInfo()` function that loads from JSON
  - Falls back to hardcoded values if JSON fails
  - Loads on startup before rendering watchlist

### 4. Added Safeguards
- Manager maintains `company_info.json` alongside `ai_watchlist_live.json`
- JSON file has timestamp for debugging
- Fallback ensures website never breaks completely

## Files Modified
1. `/var/www/hedge-fund-website/company_info.json` (NEW)
2. `/opt/stonk-ai/dynamic_watchlist_manager.py` (UPDATED)
3. `/var/www/hedge-fund-website/index.html` (UPDATED)

## Prevention
This prevents future mismatches because:
- Manager updates both price data AND company info atomically
- Website always loads current data from JSON
- No hardcoded symbol lists to get out of sync

## Cache Buster
`v=20260613-1415-DYNAMIC-COMPANY-INFO`
