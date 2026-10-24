"""Architecture: a task record's ``status`` is assigned in exactly one place.

``tasks/domain/state.py`` decides every move and ``tasks/application/transitions.py::apply_to_task``
performs it. A second ``task["status"] = ...`` is a second way to move a task that the transition
table does not know about. The scan reads
subscript assignments on the receiver names the task code uses for a record (``task``, ``t``,
``claimed``), the shape a status assignment takes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUBJECT = "docket"

SRC = Path(__file__).resolve().parents[2] / "src" / "docket"
RECEIVERS = frozenset({"task", "t", "claimed"})
WRITER = ("tasks/application/transitions.py", "apply_to_task")
BASELINE = 1


def status_writes(source: str) -> list[tuple[int, str]]:
    """``(line, enclosing function)`` of every ``<task receiver>["status"] = ...`` in *source*."""
    found: list[tuple[int, str]] = []

    def walk(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else function
            )
            if isinstance(child, ast.Assign) and any(_is_status_target(t) for t in child.targets):
                found.append((child.lineno, inner))
            walk(child, inner)

    walk(ast.parse(source), "")
    return found


def _is_status_target(target: ast.expr) -> bool:
    return (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and target.value.id in RECEIVERS
        and isinstance(target.slice, ast.Constant)
        and target.slice.value == "status"
    )


def _writes_in_tree() -> list[tuple[str, str]]:
    return [
        (path.relative_to(SRC).as_posix(), function)
        for path in sorted(SRC.rglob("*.py"))
        for _line, function in status_writes(path.read_text(encoding="utf-8"))
    ]


def test_status_is_written_only_by_apply_to_task() -> None:
    assert _writes_in_tree() == [WRITER] * BASELINE


def test_the_scan_sees_a_stray_writer() -> None:
    # A guard is not evidence until it has seen a violation.
    stray = 'def reopen(t):\n    t["status"] = "pending"\n'
    assert status_writes(stray) == [(2, "reopen")]
    assert status_writes('def f(doc):\n    doc["status"] = 1\n') == []
