"""Guard: nothing outside ``interfaces/`` imports ``docket.interfaces.cli.render.ui``.

"The domain has no knowledge of terminals" -- the contexts and ``platform/`` are pure domain
plus I/O; only ``interfaces/`` renders output. ``models/catalog.py`` and the git/process
wrappers once violated this; both were split so the Rich console.print calls live in the CLI.
This test scans the source tree so the invariant can never silently regress.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

_SRC_ROOT = Path(docket.__file__).resolve().parent
_UI = "docket.interfaces.cli.render.ui"


def _python_files() -> list[Path]:
    """Every module outside ``interfaces/`` (the only package that renders output)."""
    return sorted(
        p for p in _SRC_ROOT.rglob("*.py") if p.relative_to(_SRC_ROOT).parts[0] != "interfaces"
    )


def _imports_ui(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == _UI for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            # `from docket.interfaces.cli.render import ui` or `from ...render.ui import x`.
            if node.module == _UI:
                return True
            if node.module == _UI.rpartition(".")[0] and any(a.name == "ui" for a in node.names):
                return True
    return False


def test_nothing_outside_interfaces_imports_ui() -> None:
    files = _python_files()
    assert files, "the scan found no modules: the layout moved and this guard went vacuous"
    offenders = [str(p) for p in files if _imports_ui(p)]
    assert not offenders, f"only interfaces/ may import {_UI}: {offenders}"
