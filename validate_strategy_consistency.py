"""validate_strategy_consistency.py

Cross-module consistency check for StonkBOT.AI strategy parameters.
Ensures that the config-of-truth in strategy_config.py is actually what other
modules enforce.  Run this after any strategy change, before restart.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _read(path: Path) -> str:
    return path.read_text()


def _find_gate_expression(module_text: str, required_keys: set) -> list:
    """Return a list of (file, line, snippet) for hardcoded entry gates."""
    tree = ast.parse(module_text)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "vwap_confirmed" in names and "options_confirmed" in names:
                hits.append((node.lineno, ast.unparse(node)[:200]))
        if isinstance(node, ast.Call):
            func = getattr(node.func, "id", "")
            if func in ("all", "any"):
                names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                if names & required_keys:
                    hits.append((node.lineno, ast.unparse(node)[:200]))
    return hits


def main() -> int:
    from strategy_config import REQUIRED_POSITIVE_HARD_KEYS, HARD_CONFIRMATION_KEYS, ENTRY_READINESS_MIN

    errors = []

    # 1. Config self-consistency
    if not REQUIRED_POSITIVE_HARD_KEYS.issubset(HARD_CONFIRMATION_KEYS):
        errors.append(
            f"REQUIRED_POSITIVE_HARD_KEYS {REQUIRED_POSITIVE_HARD_KEYS} not subset of "
            f"HARD_CONFIRMATION_KEYS {HARD_CONFIRMATION_KEYS}"
        )

    # 2. signal_engine.py must not hardcode a gate different from strategy_config
    se_text = _read(ROOT / "signal_engine.py")
    se_hits = _find_gate_expression(se_text, REQUIRED_POSITIVE_HARD_KEYS)
    for lineno, snippet in se_hits:
        if "REQUIRED_POSITIVE_HARD_KEYS" not in snippet:
            errors.append(
                f"signal_engine.py:{lineno} hardcodes entry gate: {snippet!r} "
                f"(should derive from strategy_config.REQUIRED_POSITIVE_HARD_KEYS)"
            )

    # 3. signal_rules.py and readiness_score.py must use all() over V3_REQUIRED_POSITIVE_KEYS
    for fname in ("signal_rules.py", "readiness_score.py"):
        text = _read(ROOT / fname)
        if "REQUIRED_POSITIVE_HARD_KEYS" in text or "V3_REQUIRED_POSITIVE_KEYS" in text:
            if "all(" not in text or "any(" in text:
                # naive check: if both any and all appear, flag for manual review
                if "any(" in text:
                    errors.append(
                        f"{fname}: contains both 'any(' and hard-confirmation logic; "
                        "verify it uses 'all(' for REQUIRED_POSITIVE_HARD_KEYS"
                    )
        else:
            errors.append(f"{fname}: does not reference REQUIRED_POSITIVE_HARD_KEYS")

    # 4. trading_bot.py fallback must reference REQUIRED_POSITIVE_HARD_KEYS
    tb_text = _read(ROOT / "trading_bot.py")
    if "REQUIRED_POSITIVE_HARD_KEYS" not in tb_text:
        errors.append("trading_bot.py paper fallback does not use REQUIRED_POSITIVE_HARD_KEYS")
    if "any(" in tb_text and "REQUIRED_POSITIVE_HARD_KEYS" in tb_text:
        # allow any() for hard count, but the positive-edge check should ideally be all()
        if "all(" not in tb_text.split("REQUIRED_POSITIVE_HARD_KEYS")[1].split("\n")[0]:
            errors.append("trading_bot.py: positive-edge check should use all() for REQUIRED_POSITIVE_HARD_KEYS")

    # 5. strategy_config.validate() must pass
    import strategy_config
    issues = strategy_config.validate()
    if issues:
        errors.extend([f"strategy_config.validate(): {i}" for i in issues])

    if errors:
        print("STRATEGY CONSISTENCY ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("STRATEGY CONSISTENCY OK")
    print(f"  Entry readiness min: {ENTRY_READINESS_MIN}")
    print(f"  Required positive hard keys: {sorted(REQUIRED_POSITIVE_HARD_KEYS)}")
    print(f"  All hard keys: {sorted(HARD_CONFIRMATION_KEYS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
