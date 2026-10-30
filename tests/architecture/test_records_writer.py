"""Architecture: only ``platform/records_store.py`` imports ``sqlite3``.

A pod's records live in one SQLite file. ``RecordsStore`` is the one module that opens it, so every
other module reaches the records through that class. A module is a second door when it imports
``sqlite3`` by any spelling, or loads it by name with ``import_module`` or ``__import__``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "docket"
STORE_MODULE = "platform/records_store.py"
DRIVER = "sqlite3"
LOADERS = frozenset({"import_module", "__import__"})


def reasons(source: str) -> list[str]:
    """Why *source* is a second door to the records file; empty when it is not."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [f"imports {a.name}" for a in node.names if a.name.split(".")[0] == DRIVER]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == DRIVER:
                found.append(f"imports from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if name in LOADERS and DRIVER in args:
                found.append(f"loads {DRIVER} with {name}")
    return found


def modules_reaching_the_records() -> dict[str, list[str]]:
    reached = {
        path.relative_to(SRC).as_posix(): reasons(path.read_text(encoding="utf-8"))
        for path in SRC.rglob("*.py")
    }
    return {module: why for module, why in reached.items() if why}


def test_only_the_records_store_imports_sqlite() -> None:
    outside = {m: why for m, why in modules_reaching_the_records().items() if m != STORE_MODULE}
    assert not outside, f"{outside} reach SQLite without RecordsStore: use {STORE_MODULE}"


def test_the_allowed_module_exists_and_is_the_door() -> None:
    assert (SRC / STORE_MODULE).is_file(), f"{STORE_MODULE} moved: update the guard"
    assert STORE_MODULE in modules_reaching_the_records()


def test_the_scan_sees_a_planted_second_door() -> None:
    # A guard is not evidence until it has seen a violation.
    assert reasons("import sqlite3\n") == ["imports sqlite3"]
    assert reasons("import os, sqlite3 as db\n") == ["imports sqlite3"]
    assert reasons("from sqlite3 import connect\n") == ["imports from sqlite3"]
    assert reasons("import importlib\nimportlib.import_module('sqlite3')\n") == [
        "loads sqlite3 with import_module"
    ]
    assert reasons("m = __import__('sqlite3')\n") == ["loads sqlite3 with __import__"]
    assert reasons("import sqlite_utils_not_it\nx = 'sqlite3'\n") == []
