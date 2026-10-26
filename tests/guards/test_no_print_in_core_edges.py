"""Guard: nothing outside ``interfaces/`` calls print() directly.

The contexts and ``platform/`` must never print or import the CLI's ``ui`` module; only
``interfaces/`` renders output, so a bare ``print()`` can never quietly regress back into
them. ``sandbox/jail.py`` is the one exemption: it is the jail's own command-line entry
(``python -m docket.sandbox.jail``), which reports its usage errors on the terminal itself.

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


_EXEMPT = {"sandbox/jail.py"}


def _python_files() -> list[Path]:
    """Every module outside ``interfaces/`` except the exemptions above."""
    return sorted(
        p
        for p in _SRC_ROOT.rglob("*.py")
        if p.relative_to(_SRC_ROOT).parts[0] != "interfaces"
        and p.relative_to(_SRC_ROOT).as_posix() not in _EXEMPT
    )


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


def test_nothing_outside_interfaces_calls_print() -> None:
    files = _python_files()
    assert files, "the scan found no modules: the layout moved and this guard went vacuous"
    offenders = [str(p) for p in files if _calls_print(p)]
    assert not offenders, (
        "only interfaces/ may print() -- return a typed result and let the CLI render it: "
        f"{offenders}"
    )
