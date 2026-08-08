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


def _find_positive_edge_check(module_text: str, required_keys: set) -> tuple[str, str]:
    """Find the expression where REQUIRED_POSITIVE_HARD_KEYS is used as a positive-edge gate.

    Returns (filename-style location, expression source) or ('', '') if not found.
    Specifically looks for all()/any() calls iterating over REQUIRED_POSITIVE_HARD_KEYS.
    """
    tree = ast.parse(module_text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Call, ast.BoolOp)):
            continue
        # Candidate: a call to all()/any() or a bool-and expression
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        if "REQUIRED_POSITIVE_HARD_KEYS" in names or "V3_REQUIRED_POSITIVE_KEYS" in names:
            return (f"line {node.lineno}", ast.unparse(node))
        # Also detect explicit symbol checks like conf.get("vwap_confirmed") and conf.get("options_confirmed")
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            checked = {n.s for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.s, str)}
            if required_keys.issubset(checked):
                return (f"line {node.lineno}", ast.unparse(node))
    return ("", "")


def _gate_uses_all(module_text: str, required_keys: set) -> bool:
    """Return True if the positive-edge gate uses all() (or explicit And with all required keys)."""
    loc, expr = _find_positive_edge_check(module_text, required_keys)
    if not expr:
        return False
    # Accept all() or explicit And with every required key present
    if "all(" in expr:
        return True
    if isinstance(ast.parse(expr).body[0].value, ast.BoolOp):
        return True
    return False


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
    loc, expr = _find_positive_edge_check(se_text, REQUIRED_POSITIVE_HARD_KEYS)
    if loc:
        if "REQUIRED_POSITIVE_HARD_KEYS" not in expr:
            errors.append(
                f"signal_engine.py:{loc} hardcodes entry gate: {expr[:200]!r} "
                f"(should derive from strategy_config.REQUIRED_POSITIVE_HARD_KEYS)"
            )
        elif not _gate_uses_all(se_text, REQUIRED_POSITIVE_HARD_KEYS):
            errors.append(
                f"signal_engine.py:{loc} positive-edge gate does not use all(): {expr[:200]!r}"
            )
    else:
        errors.append("signal_engine.py: no REQUIRED_POSITIVE_HARD_KEYS gate found")

    # 3. signal_rules.py and readiness_score.py must use all() over V3_REQUIRED_POSITIVE_KEYS
    for fname in ("signal_rules.py", "readiness_score.py"):
        text = _read(ROOT / fname)
        loc, expr = _find_positive_edge_check(text, REQUIRED_POSITIVE_HARD_KEYS)
        if not loc:
            errors.append(f"{fname}: does not reference REQUIRED_POSITIVE_HARD_KEYS or V3_REQUIRED_POSITIVE_KEYS")
        elif not _gate_uses_all(text, REQUIRED_POSITIVE_HARD_KEYS):
            errors.append(f"{fname}:{loc} positive-edge gate should use all(), found: {expr[:200]!r}")

    # 4. trading_bot.py fallback must reference REQUIRED_POSITIVE_HARD_KEYS and use all()
    tb_text = _read(ROOT / "trading_bot.py")
    loc, expr = _find_positive_edge_check(tb_text, REQUIRED_POSITIVE_HARD_KEYS)
    if not loc:
        errors.append("trading_bot.py paper fallback does not use REQUIRED_POSITIVE_HARD_KEYS")
    elif not _gate_uses_all(tb_text, REQUIRED_POSITIVE_HARD_KEYS):
        errors.append(f"trading_bot.py:{loc} positive-edge gate should use all(), found: {expr[:200]!r}")

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
