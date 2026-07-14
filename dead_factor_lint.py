#!/usr/bin/env python3
"""Dead-factor lint for StonkBOT.AI.

Scans active Python source under /opt/stonk-ai and the live web frontend for
*active* references to data sources/features that were intentionally removed.
Bare comments that say "PEAD removed" are ignored; imports, function calls,
and dict keys that still use dead factors are reported.

Exit codes:
    0 = clean
    1 = zombie references found
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ACTIVE_SOURCE = Path("/opt/stonk-ai")
WEB_ROOT = Path("/var/www/hedge-fund-website")

# Scan active Python source in /opt/stonk-ai and a few live web artifacts.
# Skip memory, backups, agent messages, generated data caches, stale versioned HTML,
# and the web-tree copy of source files (those are deployed from /opt/stonk-ai).
SKIP_DIRS: Set[str] = {
    "backups",
    "logs",
    "__pycache__",
    "node_modules",
    "einstein-memory",
    "jeeves-memory",
    "agent-messages",
    "backup-sqlite-migration-20260706_041612",
    "website",  # duplicate of /var/www/hedge-fund-website; deployed separately
    "sentiment",
}
SKIP_FILE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^rsi_cache\.json$", re.I),
    re.compile(r"^signal_enrichment\.json$", re.I),
    re.compile(r"^trending_sentiment_cache\.json$", re.I),
    re.compile(r"\.v\d+\.html$", re.I),  # versioned old HTML
    re.compile(r"^index\.(v\d+|\d{6,})\.html$", re.I),
    re.compile(r"\.bak-.*$", re.I),
    re.compile(r"\.disabled$", re.I),  # explicitly disabled scripts
]

# Only these files in the web root are considered "active" enough to scan.
WEB_FILES_TO_SCAN: Set[str] = {
    "index.html",
    "ai_watchlist_live.json",
    "signals.json",
    "popup_content.json",
    "watchlist_narratives.json",
}

# Patterns target active usage, not explanatory comments or disabled scripts.
# Each entry: (name, [regexes])
DEAD_FACTORS: List[Tuple[str, List[str]]] = [
    (
        "pead",
        [
            # importing or calling pead_factor / _infer_pead
            r"\bpead_factor\b",
            r"\b_infer_pead\b",
            r"\bpead_score\b",
            r"\bpead_signal\b",
            r"\bpost_earnings_drift\b",
            r"\bearnings_drift\b",
        ],
    ),
    (
        "earnings_confirmed confirmation",
        [
            # dict key usage (not the narrative regex that merely matches the word "earnings")
            r'[\"\']earnings_confirmed[\"\']',
        ],
    ),
    (
        "external news API",
        [
            # actual import/call patterns of the removed external news provider (FH)
            r"\bfrom\s+finnhub\b",
            r"\bimport\s+finnhub\b",
            r"\bfinnhub_client\b",
            r"\.finnhub\b",
            r"finnhub_get\(",
            r"load_finnhub_key\(",
            r"refresh_news_for_symbols\(",
            r"finnhub_news\(",
        ],
    ),
    (
        "yahoo finance data",
        [
            r"\byfinance\b",
            r"\byf\.Ticker\b",
            r"\byf\.download\b",
            r"\byf\b",  # catches some module usage
        ],
    ),
    (
        "polygon data",
        [
            r"\bpolygon\.io\b",
            r"\bpolygon\s*api\b",
            r"\bfrom polygon\b",
            r"\bimport polygon\b",
        ],
    ),
]

# Paths/files that are allowed to mention dead factors (e.g. this script, docs, disabled modules).
ALLOWLIST: Set[Path] = {Path(__file__).resolve()}

# Comment-only matches are ignored if the whole line is a comment or the match
# is inside a trailing comment.
COMMENT_RE = re.compile(r"^\s*#|#\s*.*$")


def _path_is_allowed(path: Path) -> bool:
    return path.resolve() in ALLOWLIST


def _should_scan(path: Path) -> bool:
    if _path_is_allowed(path):
        return False

    if path.suffix not in {".py", ".js", ".html", ".json", ".md"}:
        return False

    if any(part in SKIP_DIRS for part in path.parts):
        return False

    for pat in SKIP_FILE_PATTERNS:
        if pat.search(path.name):
            return False

    return True


def _iter_scan_paths() -> Iterable[Path]:
    """Yield active-source .py files and the live web frontend files."""
    if ACTIVE_SOURCE.exists():
        for dirpath, dirs, files in os.walk(ACTIVE_SOURCE):
            # Prune noisy directories inline
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                p = Path(dirpath) / fname
                if _should_scan(p):
                    yield p

    if WEB_ROOT.exists():
        for fname in WEB_FILES_TO_SCAN:
            p = WEB_ROOT / fname
            if p.is_file() and _should_scan(p):
                yield p


def _is_comment_only(line: str) -> bool:
    """Return True if the line is nothing but whitespace + a comment."""
    return bool(COMMENT_RE.match(line.lstrip()))


def _line_without_trailing_comment(line: str) -> str:
    """Strip trailing # comment from a line (rough)."""
    # Simple approach: find first '#' that is not inside a string is tricky;
    # we just split on the last '#' if it looks like a comment.
    if "#" not in line:
        return line
    # Heuristic: if # is preceded by whitespace and followed by space, treat as comment
    m = re.search(r"\s+#\s", line)
    if m:
        return line[: m.start()]
    return line


def _find_survivors() -> List[Tuple[Path, int, str, str]]:
    survivors: List[Tuple[Path, int, str, str]] = []
    for p in _iter_scan_paths():
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = text.splitlines()
        for factor_name, patterns in DEAD_FACTORS:
            for pat in patterns:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    line_no = text[: m.start()].count("\n") + 1
                    line = lines[line_no - 1] if line_no <= len(lines) else ""
                    # Skip if match is only inside a comment-only line.
                    if _is_comment_only(line):
                        continue
                    # Skip if match is only in a trailing comment.
                    code_part = _line_without_trailing_comment(line)
                    match_in_code = re.search(pat, code_part, re.IGNORECASE)
                    if not match_in_code:
                        continue
                    survivors.append((p, line_no, factor_name, m.group(0)))
    return survivors


def find_survivors() -> List[Tuple[str, str, int, str]]:
    """Return a flat list of (category, path, line, match_text)."""
    survivors: List[Tuple[Path, int, str, str]] = _find_survivors()
    return [(factor, str(path), line, match) for path, line, factor, match in survivors]


def main() -> int:
    survivors = find_survivors()

    if not survivors:
        print("No dead-factor references found in active code.")
        return 0

    grouped: Dict[str, List[Tuple[str, int, str]]] = {}
    for category, path, line, match in survivors:
        grouped.setdefault(category, []).append((path, line, match))

    print(f"Found {len(survivors)} dead-factor reference(s) in active code:\n")
    for category in sorted(grouped):
        print(f"  {category}:")
        for path, line, match in grouped[category]:
            print(f"    {path}:{line}  ({match})")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
