"""Guard: core/ and edges/ must never call print() directly.

``core/``/``edges/`` must never print or import ``docket.ui``; only
``cli/`` renders output, so a bare ``print()`` can never quietly regress
back into either layer.

AST-based rather than a plain text grep: a naive substring search for
``"print("`` false-positives on identifiers merely ending in those
letters (e.g. ``PodBlueprint(...)`` contains ``"eprint("``) -- this walks
real ``ast.Call`` nodes instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent


def _python_files(subdir: str) -> list[Path]:
    return sorted((_SRC_ROOT / subdir).rglob("*.py"))


def _calls_print(path: Path) -> bool:
    """True if *path* contains a real call to the builtin ``print``."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            return True
    return False


def test_core_never_calls_print() -> None:
    offenders = [str(p) for p in _python_files("core") if _calls_print(p)]
    assert not offenders, (
        "core/ must never print() directly — return a typed result and let "
        f"cli/ render it: {offenders}"
    )


def test_edges_never_calls_print() -> None:
    offenders = [str(p) for p in _python_files("edges") if _calls_print(p)]
    assert not offenders, (
        "edges/ must never print() directly — return a typed result and let "
        f"cli/ render it: {offenders}"
    )
