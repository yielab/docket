"""Architecture: only ``bootstrap.py`` imports the SQLite records adapter.

A pod's records sit behind the ``RecordStore`` port. The concrete adapter is chosen in one place,
the factory ``bootstrap.bind_adapters`` binds, so a module that imports ``platform.records_sqlite``
any other way has made a second place to choose a backend.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "docket"
ADAPTER = "docket.platform.records_sqlite"
ALLOWED = "bootstrap.py"


def names_the_adapter(source: str) -> bool:
    """Whether *source* imports the adapter module, by any spelling or by name."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(a.name == ADAPTER for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == ADAPTER or any(f"{module}.{a.name}" == ADAPTER for a in node.names):
                return True
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if name in {"import_module", "__import__"} and ADAPTER in args:
                return True
    return False


def importers() -> set[str]:
    return {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if names_the_adapter(path.read_text(encoding="utf-8"))
    }


def test_only_bootstrap_imports_the_sqlite_adapter() -> None:
    assert importers() == {ALLOWED}, (
        f"{sorted(importers())} import {ADAPTER}; only {ALLOWED} binds the records factory"
    )


def test_the_scan_sees_a_planted_second_chooser() -> None:
    # A guard is not evidence until it has seen a violation.
    assert names_the_adapter("import docket.platform.records_sqlite\n")
    assert names_the_adapter("from docket.platform.records_sqlite import SqliteRecordStore\n")
    assert names_the_adapter("from docket.platform import records_sqlite\n")
    assert names_the_adapter(
        "import importlib\nimportlib.import_module('docket.platform.records_sqlite')\n"
    )
    assert not names_the_adapter("from docket.platform import store\nx = 'records_sqlite'\n")
