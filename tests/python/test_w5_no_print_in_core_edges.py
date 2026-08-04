"""Guard: core/ and edges/ must never call print() directly.

``core/dispatch.py`` once had ``print(f"[dispatch] verification skipped...")``
— a layering violation of the standing rule (CLAUDE.md, ROADMAP §4.5) that
``core/``/``edges/`` never print or import ``docket.ui``; only ``cli/``
renders output. That call is now a typed ``HopResult.verification_skipped``
flag plus a trace event, rendered by ``cli/_pod.py``. This is an AST-based
guard (sibling of ``test_ch3_no_ui_in_core_edges.py``'s no-``ui``-import
check and ``test_ch4_no_subprocess_in_core.py``'s no-shell-out check) so a
bare ``print()`` can never quietly regress back into either layer.

AST-based rather than a plain text grep: a naive substring search for
``"print("`` false-positives on identifiers merely ending in those letters
(e.g. ``PodBlueprint(...)`` in ``core/blueprints.py`` contains the literal
substring ``"eprint("``) — this walks real ``ast.Call`` nodes instead.
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
