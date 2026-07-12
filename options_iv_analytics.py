"""
options_iv_analytics.py - IV term structure, IV rank, and IV skew from Alpaca options snapshots.

Premium Data subscription with OPRA feed required for greeks/IV.
Outputs:
  - iv_term_structure(symbol): {30d, 60d, 90d, 120d} implied vols.
  - iv_rank(symbol, lookback_days=252): percentile of current 30d IV vs history.
  - iv_skew(symbol): 25-delta put IV / 25-delta call IV.
All data sourced from Alpaca v1beta1/options/snapshots/{symbol}?feed=opra.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import time
import threading

logger = logging.getLogger(__name__)

# Simple TTL cache for option snapshots (parsing is expensive; data changes slowly)
_CACHE_LOCK = threading.Lock()
_OPTIONS_SNAPSHOT_CACHE: Dict[str, Tuple[float, Dict[str, Dict]]] = {}
_IV_SUMMARY_CACHE: Dict[str, Tuple[float, Dict]] = {}
_SNAPSHOT_TTL = 300  # 5 minutes
_IV_SUMMARY_TTL = 60  # 1 minute


def _load_config() -> Dict:
    paths = [
        Path("/opt/stonk-ai/alpaca_config.json"),
        Path(__file__).parent / "alpaca_config.json",
        Path("/var/www/hedge-fund-website/alpaca_config.json"),
    ]
    for p in paths:
        if p.exists():
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                continue
    return {}


def _headers(cfg: Optional[Dict] = None) -> Dict:
    cfg = cfg or _load_config()
    return {
        "APCA-API-KEY-ID": cfg["api_key"],
        "APCA-API-SECRET-KEY": cfg["api_secret"],
        "Accept": "application/json",
    }


def _parse_option_contract(contract: str) -> Optional[Tuple[str, datetime, str, float]]:
    """Parse OCC-style option symbol. Returns (underlying, expiration, type, strike)."""
    # Format: UNDERLYING + YYMMDD + C/P + strike*1000 (8 digits)
    m = re.match(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", contract)
    if not m:
        return None
    try:
        exp = datetime.strptime(f"20{m.group(2)}-{m.group(3)}-{m.group(4)}", "%Y-%m-%d")
        opt_type = "call" if m.group(5) == "C" else "put"
        strike = int(m.group(6)) / 1000.0
        return m.group(1), exp, opt_type, strike
    except Exception:
        return None


def _fetch_all_options_snapshots(symbol: str, cfg: Optional[Dict] = None, max_pages: int = 20) -> Dict[str, Dict]:
    """Fetch all option snapshots with 5-minute TTL cache."""
    now = time.time()
    key = f"{symbol}:{id(cfg) if cfg else 'default'}"
    with _CACHE_LOCK:
        entry = _OPTIONS_SNAPSHOT_CACHE.get(key)
        if entry and (now - entry[0]) < _SNAPSHOT_TTL:
            return entry[1]
    snaps = _fetch_all_options_snapshots_uncached(symbol, cfg, max_pages)
    with _CACHE_LOCK:
        _OPTIONS_SNAPSHOT_CACHE[key] = (now, snaps)
    return snaps


def _fetch_all_options_snapshots_uncached(symbol: str, cfg: Optional[Dict] = None, max_pages: int = 20) -> Dict[str, Dict]:
    """Fetch all option snapshots for an underlying, paginating through Alpaca's response."""
    cfg = cfg or _load_config()
    data_url = cfg.get("data_url", "https://data.alpaca.markets")
    url_base = f"{data_url}/v1beta1/options/snapshots/{symbol}?feed=opra"
    token = None
    all_snaps = {}
    for page in range(max_pages):
        url = url_base + (f"&page_token={token}" if token else "")
        try:
            resp = requests.get(url, headers=_headers(cfg), timeout=15)
            if resp.status_code != 200:
                logger.debug(f"Options snapshot for {symbol} page {page}: {resp.status_code}")
                break
            data = resp.json()
            snaps = data.get("snapshots", {})
            if not snaps:
                break
            all_snaps.update(snaps)
            token = data.get("next_page_token")
            if not token:
                break
        except Exception as e:
            logger.debug(f"Options snapshot failed for {symbol} page {page}: {e}")
            break
    return all_snaps


def _days_to_expiration(exp: datetime) -> int:
    now = datetime.now()
    return max(1, (exp.replace(hour=16, minute=0) - now).days)


def _atm_iv(chain: List[Tuple[int, Dict]]) -> Optional[float]:
    """Pick the IV of the option whose |delta| is closest to 0.50."""
    candidates = []
    for dte, opt in chain:
        iv = opt.get("impliedVolatility")
        delta = opt.get("greeks", {}).get("delta")
        if iv is None or delta is None:
            continue
        candidates.append((abs(abs(delta) - 0.50), iv))
    if not candidates:
        return None
    return min(candidates)[1]


def _select_delta_iv(chain: List[Tuple[int, Dict]], delta_target: float, option_type: str) -> Optional[float]:
    """Pick the IV of the option of given type closest to target delta."""
    candidates = []
    for dte, opt in chain:
        if opt.get("_type") != option_type:
            continue
        iv = opt.get("impliedVolatility")
        delta = opt.get("greeks", {}).get("delta")
        if iv is None or delta is None:
            continue
        candidates.append((abs(abs(delta) - abs(delta_target)), iv))
    if not candidates:
        return None
    return min(candidates)[1]


def iv_term_structure(symbol: str, cfg: Optional[Dict] = None) -> Optional[Dict[str, float]]:
    """Return interpolated ATM IV at 30, 60, 90, 120 days."""
    snaps = _fetch_all_options_snapshots(symbol, cfg)
    if not snaps:
        return None

    buckets = {30: [], 60: [], 90: [], 120: []}
    for contract, opt in snaps.items():
        parsed = _parse_option_contract(contract)
        if not parsed:
            continue
        _, exp, opt_type, strike = parsed
        opt["_type"] = opt_type
        opt["_strike"] = strike
        dte = _days_to_expiration(exp)
        iv = opt.get("impliedVolatility")
        if iv is None:
            continue
        for target in buckets:
            buckets[target].append((dte, opt))

    result = {}
    for target, chain in buckets.items():
        # Pick ATM IV for points near target (within +/- target/2 days)
        window = target // 2
        nearby = [(dte, opt) for dte, opt in chain if target - window <= dte <= target + window]
        if not nearby:
            nearby = chain
        iv = _atm_iv(nearby)
        if iv is None:
            result[target] = None
        else:
            result[target] = round(iv, 4)

    return result


def iv_skew(symbol: str, cfg: Optional[Dict] = None) -> Optional[float]:
    """25-delta put IV / 25-delta call IV from nearest 20-50 DTE expiration."""
    snaps = _fetch_all_options_snapshots(symbol, cfg)
    if not snaps:
        return None

    # Group by expiration, find nearest to 30 DTE
    by_exp = {}
    for contract, opt in snaps.items():
        parsed = _parse_option_contract(contract)
        if not parsed:
            continue
        _, exp, opt_type, strike = parsed
        opt["_type"] = opt_type
        dte = _days_to_expiration(exp)
        if 20 <= dte <= 50:
            by_exp.setdefault(exp, []).append((dte, opt))

    if not by_exp:
        return None

    best_exp = min(by_exp.keys(), key=lambda e: abs(_days_to_expiration(e) - 30))
    chain = by_exp[best_exp]

    put_iv = _select_delta_iv(chain, -0.25, "put")
    call_iv = _select_delta_iv(chain, 0.25, "call")
    if not put_iv or not call_iv or call_iv == 0:
        return None

    return round(put_iv / call_iv, 3)


def _iv_history_path(symbol: str) -> Path:
    return Path(f"/opt/stonk-ai/iv_history/{symbol}.json")


def _load_iv_history(symbol: str) -> List[Dict]:
    p = _iv_history_path(symbol)
    if not p.exists():
        return []
    try:
        return json.load(open(p))
    except Exception:
        return []


def _save_iv_history(symbol: str, record: Dict):
    p = _iv_history_path(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    hist = _load_iv_history(symbol)
    hist.append(record)
    cutoff = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    hist = [h for h in hist if h.get("date", "") >= cutoff]
    try:
        json.dump(hist, open(p, "w"), indent=2)
    except Exception as e:
        logger.debug(f"Failed to save IV history for {symbol}: {e}")


def record_iv_snapshot(symbol: str, cfg: Optional[Dict] = None) -> Optional[Dict]:
    """Record today's 30d IV for rank calculation. Call once per day."""
    term = iv_term_structure(symbol, cfg)
    if not term or term.get(30) is None:
        return None
    record = {"date": datetime.now().strftime("%Y-%m-%d"), "iv_30d": term[30]}
    _save_iv_history(symbol, record)
    return record


def iv_rank(symbol: str, lookback_days: int = 252, cfg: Optional[Dict] = None) -> Optional[float]:
    """Percentile of current 30d IV over lookback_days of history."""
    hist = _load_iv_history(symbol)
    if not hist:
        record_iv_snapshot(symbol, cfg)
        return None

    current = iv_term_structure(symbol, cfg)
    if not current or current.get(30) is None:
        return None

    current_iv = current[30]
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    samples = [h["iv_30d"] for h in hist if h.get("date", "") >= cutoff]
    if len(samples) < 20:
        return None

    below = sum(1 for s in samples if s < current_iv)
    return round(below / len(samples), 3)


def iv_summary(symbol: str, cfg: Optional[Dict] = None) -> Dict:
    """Convenience dict with 1-minute TTL cache."""
    now = time.time()
    key = f"{symbol}:{id(cfg) if cfg else 'default'}"
    with _CACHE_LOCK:
        entry = _IV_SUMMARY_CACHE.get(key)
        if entry and (now - entry[0]) < _IV_SUMMARY_TTL:
            return entry[1]
    result = _iv_summary_uncached(symbol, cfg)
    with _CACHE_LOCK:
        _IV_SUMMARY_CACHE[key] = (now, result)
    return result


def _iv_summary_uncached(symbol: str, cfg: Optional[Dict] = None) -> Dict:
    """Convenience dict for readiness_score.py and popups."""
    term = iv_term_structure(symbol, cfg)
    return {
        "iv_30d": term.get(30) if term else None,
        "iv_60d": term.get(60) if term else None,
        "iv_90d": term.get(90) if term else None,
        "iv_120d": term.get(120) if term else None,
        "iv_rank": iv_rank(symbol, cfg=cfg),
        "iv_skew": iv_skew(symbol, cfg=cfg),
    }


def options_flow_signals(symbol: str, cfg: Optional[Dict] = None) -> Dict:
    """
    Compute options flow signals from Alpaca options snapshots.

    Returns
    -------
    dict with keys:
        total_options_volume: int
        call_volume: int
        put_volume: int
        put_call_ratio: float
        near_term_call_volume: int (0-30 DTE)
        near_term_put_volume: int (0-30 DTE)
        near_term_put_call_ratio: float
        avg_implied_vol: Optional[float]
        options_unusual_volume: bool (True if total volume is in top ~20% of observed)
        near_term_bullish_flow: bool (True if near-term call volume > put volume)
        top_call_strikes: List[Dict] (strike, volume)
        top_put_strikes: List[Dict] (strike, volume)
    """
    snaps = _fetch_all_options_snapshots(symbol, cfg)
    if not snaps:
        return {
            "total_options_volume": 0,
            "call_volume": 0,
            "put_volume": 0,
            "put_call_ratio": None,
            "near_term_call_volume": 0,
            "near_term_put_volume": 0,
            "near_term_put_call_ratio": None,
            "avg_implied_vol": None,
            "options_unusual_volume": False,
            "near_term_bullish_flow": False,
            "top_call_strikes": [],
            "top_put_strikes": [],
        }

    today = datetime.now()
    call_volume = 0
    put_volume = 0
    near_term_call_volume = 0
    near_term_put_volume = 0
    iv_values = []
    call_strikes: Dict[float, int] = {}
    put_strikes: Dict[float, int] = {}

    for contract, snap in snaps.items():
        parsed = _parse_option_contract(contract)
        if not parsed:
            continue
        _, exp, opt_type, strike = parsed
        dte = max(1, (exp.replace(hour=16, minute=0) - today).days)

        daily = snap.get("dailyBar", {})
        vol = daily.get("v", 0) or 0
        iv = snap.get("impliedVolatility")

        if vol <= 0:
            continue

        if iv is not None and 0 < iv < 10:
            iv_values.append(iv)

        if opt_type == "call":
            call_volume += vol
            call_strikes[strike] = call_strikes.get(strike, 0) + vol
        else:
            put_volume += vol
            put_strikes[strike] = put_strikes.get(strike, 0) + vol

        if dte <= 30:
            if opt_type == "call":
                near_term_call_volume += vol
            else:
                near_term_put_volume += vol

    total_options_volume = call_volume + put_volume

    # Top 3 strikes by volume
    top_call = sorted(call_strikes.items(), key=lambda x: -x[1])[:3]
    top_put = sorted(put_strikes.items(), key=lambda x: -x[1])[:3]

    # Heuristic unusual volume: total options volume above this threshold
    OPTIONS_UNUSUAL_VOLUME_THRESHOLD = 5000
    options_unusual_volume = total_options_volume > OPTIONS_UNUSUAL_VOLUME_THRESHOLD

    # Near-term bullish flow: near-term calls > puts
    near_term_bullish_flow = near_term_call_volume > near_term_put_volume

    put_call_ratio = round(put_volume / call_volume, 3) if call_volume > 0 else None
    near_term_pcr = round(near_term_put_volume / near_term_call_volume, 3) if near_term_call_volume > 0 else None

    # Simple flow score: 0-100
    if put_call_ratio is not None and put_call_ratio < 0.5 and near_term_bullish_flow:
        options_flow_score = 80.0
    elif put_call_ratio is not None and put_call_ratio < 1.0 and near_term_bullish_flow:
        options_flow_score = 65.0
    elif put_call_ratio is not None and put_call_ratio > 1.5:
        options_flow_score = 30.0
    else:
        options_flow_score = 50.0

    return {
        "total_options_volume": total_options_volume,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "put_call_ratio": put_call_ratio,
        "options_volume": total_options_volume,
        "near_term_call_volume": near_term_call_volume,
        "near_term_put_volume": near_term_put_volume,
        "near_term_put_call_ratio": near_term_pcr,
        "avg_implied_vol": round(sum(iv_values) / len(iv_values), 4) if iv_values else None,
        "options_unusual_volume": options_unusual_volume,
        "near_term_bullish_flow": near_term_bullish_flow,
        "options_flow_score": options_flow_score,
        "top_call_strikes": [{"strike": k, "volume": v} for k, v in top_call],
        "top_put_strikes": [{"strike": k, "volume": v} for k, v in top_put],
    }


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(iv_summary(sym), indent=2, default=str))
    print("---")
    print(json.dumps(options_flow_signals(sym), indent=2, default=str))
