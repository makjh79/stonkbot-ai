"""
VPS-based memory maintenance for Jeeves.

Reads daily memory files and MEMORY.md synced from the Mac,
analyzes them with a local LLM, and writes a maintenance report
(DREAMS.md) with suggested additions, removals, and contradictions.

Does NOT modify MEMORY.md unless run with --apply, and even then
it creates a backup first.

Runs on the VPS as root because OpenClaw auth profiles live under
/root/.openclaw/.

NOTE: This is an independent, report-only maintenance loop for Jeeves.
It does NOT use OpenClaw's memory-core dreaming plugin and does NOT touch
Einstein's memory directory or OpenClaw's internal .dreams/ store. It only
reads from /opt/stonk-ai/jeeves-memory/ and writes DREAMS.md there.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path("/opt/stonk-ai/jeeves-memory")
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"
DAILY_DIR = MEMORY_DIR / "memory"
DREAMS_FILE = MEMORY_DIR / "DREAMS.md"


def run_llm(prompt: str, model: str = "openrouter/moonshotai/kimi-k2.6", timeout: int = 180) -> str:
    """Call openclaw infer model run and return the model text content."""
    cmd = [
        "timeout", "-s", "KILL", str(timeout),
        "openclaw", "infer", "model", "run",
        "--model", model,
        "--json",
        "--prompt", prompt,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if result.returncode != 0:
            print(f"[WARN] LLM call failed: {result.stderr[:500]}", file=sys.stderr)
            return ""
        envelope = json.loads(result.stdout)
        outputs = envelope.get("outputs", [])
        if outputs and isinstance(outputs, list):
            return outputs[0].get("text", "")
        return ""
    except Exception as exc:
        print(f"[WARN] LLM call exception: {exc}", file=sys.stderr)
        return ""


def load_recent_daily_files(days: int = 14) -> list[tuple[str, str]]:
    """Load daily memory files from the last N days, newest first."""
    files = []
    if not DAILY_DIR.exists():
        return files
    for path in sorted(DAILY_DIR.glob("*.md"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
            files.append((path.name, text))
        except Exception as exc:
            print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        if len(files) >= days:
            break
    return files


def load_memory_md() -> str:
    if not MEMORY_FILE.exists():
        return ""
    return MEMORY_FILE.read_text(encoding="utf-8")


def extract_json(text: str) -> dict:
    """Extract JSON from LLM output, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    try:
        return json.loads(text)
    except Exception as exc:
        print(f"[WARN] JSON parse failed: {exc}\n{text[:500]}", file=sys.stderr)
        return {}


def analyze_memory(daily_files: list[tuple[str, str]], memory_md: str) -> dict:
    """Use LLM to compare recent daily notes against MEMORY.md."""
    daily_blob = "\n\n---\n\n".join([f"## {name}\n\n{text}" for name, text in daily_files])
    prompt = f"""You are maintaining a long-term memory file (MEMORY.md) for an AI assistant.

Below is the current MEMORY.md, followed by recent daily memory files.

TASK: Produce a JSON object with exactly these keys:
- "summary": one-sentence summary of memory health
- "suggested_additions": list of memory entries that should be added to MEMORY.md, each with "entry" (the concise text) and "reason"
- "suggested_removals": list of entries currently in MEMORY.md that seem outdated, each with "entry" (first 120 chars) and "reason"
- "contradictions": list of pairs of old vs new information that conflict, each with "old", "new", and "resolution"
- "low_priority": list of items that are true but not worth adding yet

Be conservative. Only suggest adding things that are durable preferences, decisions, infrastructure facts, or lessons. Do not suggest adding ephemeral status updates.

=== MEMORY.md ===
{memory_md[:8000]}

=== RECENT DAILY FILES ===
{daily_blob[:12000]}

Return JSON only."""

    raw = run_llm(prompt)
    return extract_json(raw)


def render_report(analysis: dict) -> str:
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lines = [
        f"# Memory Maintenance Report — {ts}",
        "",
        f"**Summary:** {analysis.get('summary', 'No summary generated.')}",
        "",
        "## Suggested Additions",
        "",
    ]
    for item in analysis.get("suggested_additions", []):
        lines.append(f"- **Add:** {item.get('entry', '')}")
        lines.append(f"  - Reason: {item.get('reason', '')}")
        lines.append("")
    if not analysis.get("suggested_additions"):
        lines.append("_None._")
        lines.append("")

    lines.extend(["## Suggested Removals", ""])
    for item in analysis.get("suggested_removals", []):
        lines.append(f"- **Remove:** {item.get('entry', '')}")
        lines.append(f"  - Reason: {item.get('reason', '')}")
        lines.append("")
    if not analysis.get("suggested_removals"):
        lines.append("_None._")
        lines.append("")

    lines.extend(["## Contradictions", ""])
    for item in analysis.get("contradictions", []):
        lines.append(f"- **Old:** {item.get('old', '')}")
        lines.append(f"  **New:** {item.get('new', '')}")
        lines.append(f"  **Resolution:** {item.get('resolution', '')}")
        lines.append("")
    if not analysis.get("contradictions"):
        lines.append("_None._")
        lines.append("")

    lines.extend(["## Low Priority", ""])
    for item in analysis.get("low_priority", []):
        if isinstance(item, dict):
            entry = item.get("entry", item.get("item", ""))
            reason = item.get("reason", "")
            lines.append(f"- {entry}")
            if reason:
                lines.append(f"  - {reason}")
        else:
            lines.append(f"- {item}")
    if not analysis.get("low_priority"):
        lines.append("_None._")
        lines.append("")

    lines.extend(["", "---", "", "This report was generated by the VPS memory maintenance script. It does not modify MEMORY.md unless explicitly applied."])
    return "\n".join(lines)


def apply_changes(analysis: dict, memory_md: str) -> str:
    """Naive apply: append additions, comment out removals. Very conservative."""
    lines = memory_md.splitlines()
    # Append additions under a new section
    additions = analysis.get("suggested_additions", [])
    if additions:
        lines.append("")
        lines.append(f"## Auto-added {datetime.now(timezone.utc).strftime('%Y-%m-%d')}")
        for item in additions:
            lines.append(f"- {item.get('entry', '')}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="VPS memory maintenance for Jeeves")
    parser.add_argument("--apply", action="store_true", help="Apply suggested additions to MEMORY.md (creates backup)")
    parser.add_argument("--days", type=int, default=14, help="Number of recent daily files to analyze")
    args = parser.parse_args()

    print(f"[INFO] Loading MEMORY.md and last {args.days} daily files...")
    memory_md = load_memory_md()
    daily_files = load_recent_daily_files(args.days)
    if not memory_md and not daily_files:
        print("[ERROR] No memory files found. Exiting.")
        sys.exit(1)

    print(f"[INFO] Analyzing with LLM...")
    analysis = analyze_memory(daily_files, memory_md)

    if not analysis:
        print("[ERROR] LLM analysis returned empty. Exiting.")
        sys.exit(1)

    report = render_report(analysis)
    DREAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DREAMS_FILE.write_text(report, encoding="utf-8")
    print(f"[INFO] Report written to {DREAMS_FILE}")

    if args.apply:
        backup = MEMORY_FILE.with_suffix(f".md.bak.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        backup.write_text(memory_md, encoding="utf-8")
        new_md = apply_changes(analysis, memory_md)
        MEMORY_FILE.write_text(new_md, encoding="utf-8")
        print(f"[INFO] Applied changes to {MEMORY_FILE}; backup at {backup}")
    else:
        print("[INFO] Report-only mode. Run with --apply to modify MEMORY.md.")


if __name__ == "__main__":
    main()
