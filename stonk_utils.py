"""Shared utilities for StonkBOT.AI pipeline scripts.

Goals:
- Atomic JSON writes with correct permissions
- Single-writer enforcement for critical files
- Consistent logging/behaviour across scripts
- Post-write assertions to catch stale mtime / immutable flag / permission drift
"""

import json
import os
import stat
import tempfile
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Canonical single-writer ownership.
# File path (str) -> dict with expected owner and allowed writer scripts.
# Writers are basename patterns; e.g. "run_signal_engine.py" or "*" for any.
CRITICAL_FILES = {
    "/opt/stonk-ai/signals.json": {"owner": "stonkai", "allowed_writers": ["signal_engine.py", "run_signal_engine.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/signals.json": {"owner": "stonkai", "allowed_writers": ["signal_engine.py", "run_signal_engine.py"], "mode": 0o644},
    "/opt/stonk-ai/ai_watchlist_live.json": {"owner": "stonkai", "allowed_writers": ["dynamic_watchlist_manager.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/ai_watchlist_live.json": {"owner": "stonkai", "allowed_writers": ["dynamic_watchlist_manager.py"], "mode": 0o644},
    "/opt/stonk-ai/portfolio_data.json": {"owner": "stonkai", "allowed_writers": ["trading_bot.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/portfolio_data.json": {"owner": "stonkai", "allowed_writers": ["trading_bot.py"], "mode": 0o644},
    "/opt/stonk-ai/portfolio_history.json": {"owner": "stonkai", "allowed_writers": ["reconstruct_portfolio_history.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/portfolio_history.json": {"owner": "stonkai", "allowed_writers": ["reconstruct_portfolio_history.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/popup_content.json": {"owner": "stonkai", "allowed_writers": ["generate_popup_content_narrative_v6_server.py", "generate_popup_content.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/watchlist_narratives.json": {"owner": "stonkai", "allowed_writers": ["generate_narratives_llm_batched.py", "generate_popup_content_narrative_v6_server.py"], "mode": 0o644},
    "/opt/stonk-ai/signal_outcomes.json": {"owner": "stonkai", "allowed_writers": ["outcome_tracker.py"], "mode": 0o644},
    "/var/www/hedge-fund-website/signal_accuracy.json": {"owner": "stonkai", "allowed_writers": ["outcome_tracker.py"], "mode": 0o644},
}


def _caller_script_name() -> str:
    """Best-effort caller script basename (skip stonk_utils.py itself)."""
    import inspect
    for frame in inspect.stack()[1:]:
        # Try frame filename first (most reliable)
        frame_file = frame.filename
        if frame_file:
            base = os.path.basename(frame_file)
            if base != "stonk_utils.py":
                return base
        # Fallback to module.__file__
        module = inspect.getmodule(frame[0])
        if module is None:
            continue
        fname = getattr(module, "__file__", None)
        if not fname:
            continue
        if os.path.basename(fname) == "stonk_utils.py":
            continue
        return os.path.basename(fname)
    return ""


def _file_attrs(path: Union[str, Path]) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Return (file_mode, immutable_flag?, owner_name) for a path, or None on error."""
    try:
        st = os.lstat(path)
        mode = stat.S_IMODE(st.st_mode)
        owner = _uid_to_name(st.st_uid)
        # Check immutable flag (requires reading ext attributes; non-root may fail)
        immutable = None
        try:
            import subprocess
            result = subprocess.run(
                ["lsattr", str(path)], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # lsattr output: "---- filename"; 'i' in attrs means immutable
                attrs = result.stdout.split()[0] if result.stdout.split() else ""
                immutable = "i" in attrs
        except Exception:
            immutable = None
        return mode, immutable, owner
    except OSError:
        return None, None, None


def _uid_to_name(uid: int) -> str:
    import pwd
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _is_writable_now(path: Union[str, Path]) -> Tuple[bool, str]:
    """Check whether the current non-root process can overwrite this path.

    Returns (ok, reason). Does not attempt to fix anything.
    """
    path = Path(path)
    if not path.exists():
        # Writable if parent directory is writable
        if not os.access(path.parent, os.W_OK):
            return False, f"parent directory {path.parent} is not writable by current user"
        return True, ""

    if not os.access(path, os.W_OK):
        mode, immutable, owner = _file_attrs(path)
        hint = f"sudo chown stonkai:stonkai {path} && sudo chmod 0644 {path}"
        if immutable:
            hint += f" && sudo chattr -i {path}"
        return False, f"not writable (owner={owner}, mode={oct(mode) if mode else '?'}, immutable={immutable}); run: {hint}"

    mode, immutable, owner = _file_attrs(path)
    if immutable:
        return False, f"immutable flag (+i) is set on {path} (owner={owner}); run: sudo chattr -i {path}"

    return True, ""


def _is_allowed_writer(path: Union[str, Path], caller: str) -> bool:
    """Check if caller script is in the allowed-writer list for this path."""
    path_str = str(path)
    config = CRITICAL_FILES.get(path_str)
    if not config:
        return True  # Non-critical files pass through
    if "*" in config["allowed_writers"]:
        return True
    return caller in config["allowed_writers"]


def _assert_write_ok(
    path: Union[str, Path],
    expected_owner: Optional[str] = None,
    expected_mode: int = 0o644,
    max_age_seconds: float = 120.0,
) -> None:
    """Assert that a file was just written and is in good shape.

    Raises RuntimeError if any check fails so callers cannot silently emit stale data.
    """
    path = Path(path)
    now = time.time()
    st = path.stat()

    if st.st_size == 0:
        raise RuntimeError(f"{path} was written with zero bytes")

    age = now - st.st_mtime
    if age > max_age_seconds or age < -1:
        raise RuntimeError(
            f"{path} mtime is stale or clock-skewed (age={age:.1f}s, max={max_age_seconds:.0f}s); "
            "atomic rename may have failed to update mtime"
        )

    actual_mode = stat.S_IMODE(st.st_mode)
    if actual_mode != expected_mode:
        raise RuntimeError(f"{path} mode is {oct(actual_mode)} (expected {oct(expected_mode)})")

    if expected_owner:
        actual_owner = _uid_to_name(st.st_uid)
        if actual_owner != expected_owner:
            raise RuntimeError(f"{path} owner is {actual_owner} (expected {expected_owner})")

    # Immutable flag would block the *next* write; surface it now if we can detect it.
    mode_bits, immutable, _ = _file_attrs(path)
    if immutable:
        raise RuntimeError(f"{path} has immutable flag (+i) set; run: sudo chattr -i {path}")


def atomic_write_json(
    path: Union[str, Path],
    data: Any,
    *,
    mode: int = 0o644,
    owner: Optional[str] = None,
    allowed_writers: Optional[list] = None,
    check_ownership: bool = True,
) -> None:
    """
    Atomically write a JSON file with the right permissions.

    - Writes to a temp file in the same directory
    - Renames into place
    - chmods to `mode`
    - If the file is registered as critical, enforces single-writer rules
    """
    path = Path(path)
    caller = _caller_script_name()

    if not _is_allowed_writer(path, caller):
        raise RuntimeError(
            f"{caller} is not allowed to write {path}; "
            f"allowed writers: {CRITICAL_FILES[str(path)]['allowed_writers']}"
        )

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix='.json.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.rename(tmp_path, str(path))
        os.chmod(str(path), mode)
        # Update mtime so freshness checks reflect the actual write, not the temp file's birth time
        os.utime(str(path), None)
        if owner:
            shutil.chown(str(path), user=owner, group=owner)
        _assert_write_ok(path, expected_owner=owner, expected_mode=mode)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def validate_critical_files() -> list:
    """
    Return a list of issues for any critical file that has wrong owner/mode
    or was written by an non-allowed process.
    """
    import pwd
    issues = []
    for path_str, config in CRITICAL_FILES.items():
        try:
            p = Path(path_str)
            if not p.exists():
                continue
            st = p.stat()
            expected_owner = config["owner"]
            expected_mode = config["mode"]
            actual_owner = pwd.getpwuid(st.st_uid).pw_name
            actual_mode = stat.S_IMODE(st.st_mode)
            if actual_owner != expected_owner or actual_mode != expected_mode:
                issues.append(
                    f"{path_str} is {actual_owner}:{oct(actual_mode)} "
                    f"(expected {expected_owner}:{oct(expected_mode)})"
                )
        except Exception as e:
            issues.append(f"Could not validate {path_str}: {e}")
    return issues
