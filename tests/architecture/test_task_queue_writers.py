"""Architecture: only ``tasks/application/json_store.py`` touches a pod's task file.

A pod's queue is ``TASK_LIST.json`` in its Lead's workspace. ``JsonTaskStore`` (``json_store.py``)
is the one module that reads and writes it, and ``TaskRepository`` (``repository.py``) is the one
module that builds a store, so every other module reaches the queue through the repository. A
module is a second door when it names ``JsonTaskStore``, or when it passes ``pod_task_list_path(``
to a store call (``read_modify_write(`` or ``read_json(``).
"""

from __future__ import annotations

import ast
from pathlib import Path

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "docket"
STORE_MODULE = "tasks/application/json_store.py"
REPOSITORY_MODULE = "tasks/application/repository.py"
QUEUE_PATH = "pod_task_list_path"
STORE_CLASS = "JsonTaskStore"
STORE_CALLS = frozenset({"read_modify_write", "read_json"})


def reasons(source: str) -> list[str]:
    """Why *source* is a second door to the task queue; empty when it is not."""
    called: set[str] = set()
    named: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
        elif isinstance(node, ast.Name | ast.Attribute):
            named.add(node.id if isinstance(node, ast.Name) else node.attr)
        elif isinstance(node, ast.ImportFrom):
            named.update(alias.name for alias in node.names)
    found: list[str] = []
    if QUEUE_PATH in called and called & STORE_CALLS:
        found.append(f"{QUEUE_PATH} with {sorted(called & STORE_CALLS)[0]}")
    if STORE_CLASS in named:
        found.append(f"names {STORE_CLASS}")
    return found


def modules_reaching_the_queue() -> dict[str, list[str]]:
    reached = {
        path.relative_to(SRC).as_posix(): reasons(path.read_text(encoding="utf-8"))
        for path in SRC.rglob("*.py")
    }
    return {module: why for module, why in reached.items() if why}


def test_only_the_store_and_the_repository_reach_the_task_queue() -> None:
    reached = modules_reaching_the_queue()
    outside = {m: why for m, why in reached.items() if m not in {STORE_MODULE, REPOSITORY_MODULE}}
    assert not outside, (
        f"{outside} reach the task queue without TaskRepository: "
        "use tasks/application/repository.py"
    )


def test_the_allowed_modules_exist() -> None:
    for module in (STORE_MODULE, REPOSITORY_MODULE):
        assert (SRC / module).is_file(), f"{module} moved: update the guard"
    assert REPOSITORY_MODULE in modules_reaching_the_queue()


def test_the_scan_sees_a_planted_second_door() -> None:
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
    assert reasons("from m import JsonTaskStore\ndef f(p):\n    return JsonTaskStore(p)\n") == [
        "names JsonTaskStore"
    ]
    assert reasons("import m\ndef f(p):\n    return m.JsonTaskStore(p)\n") == [
        "names JsonTaskStore"
    ]
    assert reasons("def f(p):\n    return pod_task_list_path(p)\n") == []
    assert reasons("def f(p):\n    return read_json(p)\n") == []
