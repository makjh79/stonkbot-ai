#!/usr/bin/env bash
set -euo pipefail

# Verify that website/index.html contains the required features of the current Bot sleeve design.
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

# Core tabs
check "TAB PANEL: Overview"        "Overview tab"
check "TAB PANEL: Holdings"        "Holdings tab"
check "TAB PANEL: Watchlist"        "Watchlist tab"
check "id=\"tab-about\""           "About tab"

# Bot sleeve copy
check "Bot vs. Market"             "Bot vs Market header"
check "Bot Thinking Log"            "Bot Thinking Log link"
check "dm_paper/sleeve_state.json"  "Sleeve state data source"
check "monthly-rebalanced"          "Monthly rebalanced description"
check "Not investment advice"       "Disclaimer"

# Watchlist UI
check "id=\"watchlist-content\""    "Watchlist content container"
check "currentWatchlistSort"        "Watchlist sort state"

# Holdings UI
check "id=\"holdingsCards\""         "Holdings cards container"

# Race / performance
check "sleeve_equity.csv"           "Sleeve equity CSV"

# Layout
check "Updated: "                   "Freshness timestamp"

echo "All checks passed."
