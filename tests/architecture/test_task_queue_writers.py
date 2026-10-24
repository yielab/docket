"""Architecture: only the repository reads and writes a pod's task queue.

A pod's queue is ``TASK_LIST.json`` in its Lead's workspace. Every module that reaches it with
``pod_task_list_path(`` and a store call (``read_modify_write(`` or ``read_json(``) is a second
door beside ``TaskRepository``, and every module that defines the dict helpers
(``_normalize_task``, ``hop_record``, ``hop_from_record``) keeps the dict shape alive. Each is
listed in ``task_queue_writers_baseline.txt``. The list only shrinks: a module not listed fails
here, and a listed module that no longer matches must be deleted from the file (one path per
line) in the commit that moves its last caller.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "docket"
BASELINE = Path(__file__).with_name("task_queue_writers_baseline.txt")
QUEUE_PATH = "pod_task_list_path"
STORE_CALLS = frozenset({"read_modify_write", "read_json"})
DICT_HELPERS = frozenset({"_normalize_task", "hop_record", "hop_from_record"})


def reasons(source: str) -> list[str]:
    """Why *source* is a task queue writer: the dict helpers it defines, and the queue path it
    names beside a store call. Empty when it is neither."""
    called: set[str] = set()
    defined: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            defined.add(node.name)
    found = sorted(f"defines {name}" for name in defined & DICT_HELPERS)
    if QUEUE_PATH in called and called & STORE_CALLS:
        found.append(f"{QUEUE_PATH} with {sorted(called & STORE_CALLS)[0]}")
    return found


def writers_in_tree() -> set[str]:
    return {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if reasons(path.read_text(encoding="utf-8"))
    }


def baseline() -> set[str]:
    return {
        line
        for line in BASELINE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


def test_no_new_module_reaches_the_task_queue_beside_the_repository() -> None:
    new = sorted(writers_in_tree() - baseline())
    assert not new, (
        f"{new} reach the task queue without TaskRepository: use "
        "tasks/application/repository.py (the list only shrinks)"
    )


def test_every_listed_module_still_reaches_the_task_queue() -> None:
    gone = sorted(baseline() - writers_in_tree())
    assert not gone, f"{gone} no longer match: delete them from {BASELINE.name}"


def test_the_baseline_is_sorted_and_has_no_duplicates() -> None:
    lines = [
        line
        for line in BASELINE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert lines == sorted(set(lines))


def test_the_scan_sees_a_planted_writer() -> None:
    # A guard is not evidence until it has seen a violation.
    planted = (
        "from docket.platform import read_modify_write\n"
        "from docket.teams.settings import pod_task_list_path\n"
        "def f(project):\n"
        "    read_modify_write(pod_task_list_path(project), lambda doc: doc)\n"
    )
    assert reasons(planted) == ["pod_task_list_path with read_modify_write"]
    assert reasons("import m\ndef f(p):\n    m.read_json(m.pod_task_list_path(p))\n") == [
        "pod_task_list_path with read_json"
    ]
    assert reasons("def _normalize_task(t):\n    return t\n") == ["defines _normalize_task"]
    assert reasons("def hop_record(h):\n    return {}\n") == ["defines hop_record"]
    assert reasons("def f(p):\n    return pod_task_list_path(p)\n") == []
    assert reasons("def f(p):\n    return read_json(p)\n") == []
