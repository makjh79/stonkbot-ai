#!/usr/bin/env python3
"""
Compare backtest performance of current readiness weights vs.
a baseline where the newest confirmation-chip weights are zero.

This helps assess whether adding 5M/OF/SPR/CA/QBI chips has
shifted the PRIME/NOW tiering scale in a harmful way.
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from backtest import BacktestEngine  # noqa: E402
import readiness_score as rs  # noqa: E402


NEW_CHIP_WEIGHTS = {
    "WEIGHT_5M_MOMENTUM": 0.03,
    "WEIGHT_5M_VOLUME_SURGE": 0.01,
    "WEIGHT_5M_VWAP": 0.01,
    "WEIGHT_OPTIONS_FLOW": 0.02,
    "WEIGHT_SPREAD_OK": 0.02,
    "WEIGHT_NO_CORPORATE_ACTION": 0.02,
    "WEIGHT_BID_ASK_IMBALANCE": 0.02,
}


def run_backtest(label: str, weight_overrides: dict) -> dict:
    print(f"\n=== Running backtest: {label} ===")
    # Apply overrides
    originals = {}
    for name, value in weight_overrides.items():
        originals[name] = getattr(rs, name)
        setattr(rs, name, value)

    try:
        engine = BacktestEngine(
            start_date="2026-01-01",
            end_date="2026-06-27",
            initial_cash=100_000,
        )
        result = engine.run(max_positions=10, verbose=False)
        result["label"] = label
        return result
    finally:
        for name, value in originals.items():
            setattr(rs, name, value)


def main():
    current = run_backtest("current_weights", {})
    baseline = run_backtest(
        "baseline_no_new_chips",
        {name: 0.0 for name in NEW_CHIP_WEIGHTS},
    )

    print("\n=== Comparison ===")
    for r in [current, baseline]:
        print(f"\n{r['label']}:")
        print(f"  Total return:        {r['total_return']*100:.2f}%")
        print(f"  Sharpe:              {r['sharpe_ratio']:.2f}")
        print(f"  Max drawdown:        {r['max_drawdown']*100:.2f}%")
        print(f"  Win rate:            {r['win_rate']*100:.2f}%")
        print(f"  Alpha:               {r['alpha']:.4f}")
        print(f"  Beta:                {r['beta']:.4f}")
        print(f"  # Trades:            {r['trades']}")

    # Compare PRIME/NOW tier distribution (approximate from signals)
    print("\n=== Tier threshold sanity ===")
    print("PRIME threshold >=78 used by readiness_score.py")
    print("If baseline outperforms current, the new weights likely need recalibration.")

    # Save detailed reports
    out = {
        "current_weights": current,
        "baseline_no_new_chips": baseline,
    }
    out_path = BASE / "backtest_weight_comparison.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nDetailed report: {out_path}")


if __name__ == "__main__":
    main()
