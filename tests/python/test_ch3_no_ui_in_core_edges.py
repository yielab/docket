"""CH-3 guard: core/ and edges/ must never import docket.ui.

ROADMAP §2 states "core has no knowledge of terminals" — core/edges are pure
domain + I/O layers; only cli/ renders output. Two modules used to violate
this (core/provider.py, edges/adapters/system.py); both were split so the
Rich console.print calls live in cli/. This test scans the source tree so the
invariant can never silently regress.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent


def _python_files(subdir: str) -> list[Path]:
    return sorted((_SRC_ROOT / subdir).rglob("*.py"))


def _imports_ui(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name in ("docket.ui", "docket.ui.py") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            # `from docket import ui` (module == "docket", name "ui") or
            # `from docket.ui import ...` (module == "docket.ui").
            if node.module == "docket" and any(alias.name == "ui" for alias in node.names):
                return True
            if node.module == "docket.ui":
                return True
    return False


def test_core_has_no_ui_imports() -> None:
    offenders = [str(p) for p in _python_files("core") if _imports_ui(p)]
    assert not offenders, f"core/ must not import docket.ui: {offenders}"


def test_edges_has_no_ui_imports() -> None:
    offenders = [str(p) for p in _python_files("edges") if _imports_ui(p)]
    assert not offenders, f"edges/ must not import docket.ui: {offenders}"
