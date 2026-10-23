"""Guard: ``kernel/`` imports nothing from docket.

The kernel is what every layer stands on. If it imported ``core`` or ``edges`` the layers would
form a cycle, and a module needing a clock or an id could not be imported on its own.
"""

from __future__ import annotations

import ast
from pathlib import Path

import docket

SUBJECT = "docket.kernel"

_KERNEL = Path(docket.__file__).resolve().parent / "kernel"


def _docket_imports(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "docket"]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                found.append("." * node.level + (node.module or ""))
            elif (node.module or "").split(".")[0] == "docket":
                found.append(node.module or "")
    return found


def test_kernel_imports_nothing_from_docket() -> None:
    offenders = {
        p.name: imports for p in sorted(_KERNEL.glob("*.py")) if (imports := _docket_imports(p))
    }
    assert not offenders, f"kernel/ must not import docket: {offenders}"
