"""
Correlate existing options IV/skew metrics with trade outcomes.

Reads:
- /opt/stonk-ai/performance_attribution.json (trade journal)
- /opt/stonk-ai/iv_summaries.json (current IV summary)
- /opt/stonk-ai/iv_history/*.json (historical IV records)

Outputs:
- /opt/stonk-ai/options_skew_correlation_report.json

Internal analysis only. No website or trading logic changes.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PERF_FILE = Path("/opt/stonk-ai/performance_attribution.json")
IV_SUMMARY_FILE = Path("/opt/stonk-ai/iv_summaries.json")
IV_HISTORY_DIR = Path("/opt/stonk-ai/iv_history")
OUTPUT_FILE = Path("/opt/stonk-ai/options_skew_correlation_report.json")


def load_trade_journal() -> list[dict]:
    try:
        data = json.loads(PERF_FILE.read_text())
        return data.get("trade_journal", [])
    except Exception as exc:
        print(f"[WARN] Could not load performance_attribution.json: {exc}", file=sys.stderr)
        return []


def load_iv_history(symbol: str) -> list[dict]:
    p = IV_HISTORY_DIR / f"{symbol}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def load_iv_summaries() -> dict:
    try:
        return json.loads(IV_SUMMARY_FILE.read_text())
    except Exception:
        return {}


def get_iv_as_of(symbol: str, date_str: str) -> dict:
    """Get IV metrics for symbol as of a specific date."""
    # Try history first
    hist = load_iv_history(symbol)
    for rec in sorted(hist, key=lambda x: x.get("date", ""), reverse=True):
        if rec.get("date", "") <= date_str:
            return rec
    # Fallback to current summary
    summary = load_iv_summaries().get(symbol, {})
    if summary.get("iv_30d") is not None:
        return {
            "iv_30d": summary.get("iv_30d"),
            "iv_skew": summary.get("iv_skew"),
            "iv_rank": summary.get("iv_rank"),
        }
    return {}


def correlation(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    if var_x == 0 or var_y == 0:
        return 0.0
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    return cov / (var_x * var_y) ** 0.5


def main():
    journal = load_trade_journal()
    if not journal:
        print("[ERROR] No trade journal found. Exiting.")
        sys.exit(1)

    records = []
    for trade in journal:
        symbol = trade.get("symbol")
        entry_date = trade.get("entry_date", "")[:10]
        pnl_pct = trade.get("pnl_pct")
        if not symbol or not entry_date or pnl_pct is None:
            continue
        iv = get_iv_as_of(symbol, entry_date)
        if iv.get("iv_30d") is None and iv.get("iv_skew") is None:
            continue
        records.append({
            "symbol": symbol,
            "entry_date": entry_date,
            "pnl_pct": pnl_pct,
            "result": trade.get("result"),
            "iv_30d": iv.get("iv_30d"),
            "iv_skew": iv.get("iv_skew"),
            "iv_rank": iv.get("iv_rank"),
            "entry_readiness": trade.get("entry_readiness"),
        })

    if not records:
        print("[WARN] No records with both trade outcome and IV data. Exiting.")
        sys.exit(0)

    # Overall correlations
    iv30d_vals = [r["iv_30d"] for r in records if r["iv_30d"] is not None]
    skew_vals = [r["iv_skew"] for r in records if r["iv_skew"] is not None]
    rank_vals = [r["iv_rank"] for r in records if r["iv_rank"] is not None]
    pnl_for_iv30d = [r["pnl_pct"] for r in records if r["iv_30d"] is not None]
    pnl_for_skew = [r["pnl_pct"] for r in records if r["iv_skew"] is not None]
    pnl_for_rank = [r["pnl_pct"] for r in records if r["iv_rank"] is not None]

    corr_iv30d = correlation(iv30d_vals, pnl_for_iv30d) if len(iv30d_vals) >= 2 else None
    corr_skew = correlation(skew_vals, pnl_for_skew) if len(skew_vals) >= 2 else None
    corr_rank = correlation(rank_vals, pnl_for_rank) if len(rank_vals) >= 2 else None

    # Win rate by skew buckets
    wins_high_skew = sum(1 for r in records if r["iv_skew"] and r["iv_skew"] >= 1.1 and r["result"] == "win")
    total_high_skew = sum(1 for r in records if r["iv_skew"] and r["iv_skew"] >= 1.1)
    wins_low_skew = sum(1 for r in records if r["iv_skew"] and r["iv_skew"] <= 1.0 and r["result"] == "win")
    total_low_skew = sum(1 for r in records if r["iv_skew"] and r["iv_skew"] <= 1.0)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sample_size": len(records),
        "correlations": {
            "iv_30d_vs_pnl": round(corr_iv30d, 4) if corr_iv30d is not None else None,
            "iv_skew_vs_pnl": round(corr_skew, 4) if corr_skew is not None else None,
            "iv_rank_vs_pnl": round(corr_rank, 4) if corr_rank is not None else None,
        },
        "win_rate_by_skew": {
            "high_skew_ge_1.1": {
                "wins": wins_high_skew,
                "total": total_high_skew,
                "win_rate": round(wins_high_skew / total_high_skew, 4) if total_high_skew else None,
                "avg_pnl_pct": round(sum(r["pnl_pct"] for r in records if r["iv_skew"] and r["iv_skew"] >= 1.1) / total_high_skew, 4) if total_high_skew else None,
            },
            "low_skew_le_1.0": {
                "wins": wins_low_skew,
                "total": total_low_skew,
                "win_rate": round(wins_low_skew / total_low_skew, 4) if total_low_skew else None,
                "avg_pnl_pct": round(sum(r["pnl_pct"] for r in records if r["iv_skew"] and r["iv_skew"] <= 1.0) / total_low_skew, 4) if total_low_skew else None,
            },
        },
        "records": records,
        "interpretation": {
            "iv_skew": "Put IV / call IV. >1.0 means puts are relatively expensive (fear/hedging).",
            "iv_rank": "Percentile of current 30d IV vs last ~252 days. High = expensive options.",
            "iv_30d": "Absolute 30-day ATM implied volatility.",
        },
    }

    OUTPUT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[DONE] Wrote correlation report for {len(records)} trades to {OUTPUT_FILE}")
    print(json.dumps(report["correlations"], indent=2))
    print(json.dumps(report["win_rate_by_skew"], indent=2))


if __name__ == "__main__":
    main()
