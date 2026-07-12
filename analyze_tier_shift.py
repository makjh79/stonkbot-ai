#!/usr/bin/env python3
"""
Quick analysis of how new chip weights shifted the readiness distribution.
Uses current signals.json and recomputes readiness with new chip weights = 0.
"""

import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import readiness_score as rs  # noqa: E402

NEW_CHIP_WEIGHTS = [
    "WEIGHT_5M_MOMENTUM",
    "WEIGHT_5M_VOLUME_SURGE",
    "WEIGHT_5M_VWAP",
    "WEIGHT_OPTIONS_FLOW",
    "WEIGHT_SPREAD_OK",
    "WEIGHT_NO_CORPORATE_ACTION",
    "WEIGHT_BID_ASK_IMBALANCE",
]


def compute_old_readiness(signal: dict) -> float:
    """Recompute readiness as if new chip weights were zero."""
    conf = signal.get("confirmations", {})
    # Map signal keys to readiness factors values.
    # We approximate using the already computed readiness and strip new chip effects.
    # Old total weight = current total weight - new chip weight sum.
    new_weight_sum = sum(getattr(rs, w) for w in NEW_CHIP_WEIGHTS)
    current_total_weight = (
        rs.WEIGHT_SIGNAL + rs.WEIGHT_RSI + rs.WEIGHT_VOLUME + rs.WEIGHT_MACD + rs.WEIGHT_EMA
        + rs.WEIGHT_SECTOR + rs.WEIGHT_INTRADAY + rs.WEIGHT_OPTIONS
        + rs.WEIGHT_REL_VOLUME + rs.WEIGHT_VWAP_DEV + rs.WEIGHT_RELATIVE_STRENGTH
        + new_weight_sum
    )
    old_total_weight = current_total_weight - new_weight_sum

    # Weighted contribution of new chips to current weighted sum.
    new_contribution = 0.0
    new_contribution += rs.WEIGHT_5M_MOMENTUM * (100 if conf.get("momentum_5m_up") else 0)
    new_contribution += rs.WEIGHT_5M_VOLUME_SURGE * (100 if conf.get("volume_5m_surge") else 0)
    new_contribution += rs.WEIGHT_5M_VWAP * (100 if conf.get("price_above_5m_vwap") else 0)
    new_contribution += rs.WEIGHT_OPTIONS_FLOW * (100 if conf.get("options_flow_score") else 0)
    new_contribution += rs.WEIGHT_SPREAD_OK * (100 if conf.get("spread_ok") else 0)
    new_contribution += rs.WEIGHT_NO_CORPORATE_ACTION * (100 if conf.get("no_corporate_action_risk") else 0)
    new_contribution += rs.WEIGHT_BID_ASK_IMBALANCE * (100 if conf.get("bid_ask_bullish") else 0)

    current_weighted_sum = signal["readiness_score"] * current_total_weight
    old_weighted_sum = current_weighted_sum - new_contribution
    return old_weighted_sum / old_total_weight


def tier(r: float) -> str:
    if r >= 78:
        return "STRONG_NOW"
    if r >= 72:
        return "NOW"
    if r >= 55:
        return "WATCH"
    return "MONITOR"


def main():
    signals = json.loads((BASE / "signals.json").read_text())["signals"]
    current_tiers = Counter()
    old_tiers = Counter()
    changed = 0
    demoted_from_prime = 0
    promoted_to_prime = 0

    for s in signals:
        cur = s["readiness_score"]
        old = compute_old_readiness(s)
        cur_tier = tier(cur)
        old_tier = tier(old)
        current_tiers[cur_tier] += 1
        old_tiers[old_tier] += 1
        if cur_tier != old_tier:
            changed += 1
            if old_tier == "STRONG_NOW" and cur_tier != "STRONG_NOW":
                demoted_from_prime += 1
            if cur_tier == "STRONG_NOW" and old_tier != "STRONG_NOW":
                promoted_to_prime += 1

    print("=== Tier distribution (current weights) ===")
    for t in ["STRONG_NOW", "NOW", "WATCH", "MONITOR"]:
        print(f"  {t}: {current_tiers[t]}")

    print("\n=== Tier distribution (new chips removed) ===")
    for t in ["STRONG_NOW", "NOW", "WATCH", "MONITOR"]:
        print(f"  {t}: {old_tiers[t]}")

    print("\n=== Old-weight top readiness scores ===")
    old_scores = []
    for s in signals:
        cur = s["readiness_score"]
        old = compute_old_readiness(s)
        old_scores.append(old)
    old_scores_sorted = sorted(old_scores, reverse=True)
    print("Top 10 old-weight scores:", [round(x, 1) for x in old_scores_sorted[:10]])
    print("Old-weight # >= 78:", len([x for x in old_scores if x >= 78]))
    print("Old-weight # >= 77:", len([x for x in old_scores if x >= 77]))
    print("Old-weight # >= 76:", len([x for x in old_scores if x >= 76]))
    print("Old-weight # >= 75:", len([x for x in old_scores if x >= 75]))

    print(f"\nSymbols with tier change: {changed} / {len(signals)}")
    print(f"Demoted from STRONG_NOW: {demoted_from_prime}")
    print(f"Promoted to STRONG_NOW:  {promoted_to_prime}")


if __name__ == "__main__":
    main()
