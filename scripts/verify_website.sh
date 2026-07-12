#!/usr/bin/env bash
set -euo pipefail

# Verify that website/index.html contains the required features.
# Used locally and in CI.

FILE="${1:-website/index.html}"

if [ ! -f "$FILE" ]; then
    echo "FAIL: $FILE not found"
    exit 1
fi

check() {
    if grep -q "$1" "$FILE"; then
        echo "PASS: $2"
    else
        echo "FAIL: $2"
        exit 1
    fi
}

check "TAB PANEL: Orders"        "Orders tab"
check "Watchlist Tiers"          "About tab tiers"
check "'5M'"                    "5-minute momentum chip"
check "'OF'"                    "Options flow chip"
check "'SPR'"                   "Spread chip"
check "'CA'"                    "Corporate action chip"
check "Updated: "               "Freshness timestamp"
check "flex-wrap: wrap"          "Two-row chip layout"

echo "All checks passed."
