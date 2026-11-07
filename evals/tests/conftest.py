"""Builders for fixture tasks, written into a temporary tree so pytest never collects `hidden/`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
HIDDEN_TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
PATCH = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"

TaskBuilder = Callable[..., Path]


def task_yaml(task_id: str, suite: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": task_id,
        "version": 1,
        "suite": suite,
        "shape": "build",
        "origin": "a fixture bug: add subtracts",
        "instruction": "Fix add() in calc.py so that it adds.",
        "pod": {"blueprint": "build", "isolation": False},
        "operator": {"approval": "approve_once"},
        "graders": {"required": ["outcome.hidden_tests"], "report": ["process.tokens"]},
        "limits": {"wall_seconds": 60},
    }
    data.update(overrides)
    return data


@pytest.fixture
def make_task(tmp_path: Path) -> TaskBuilder:
    """Build `tmp_path/tasks/<suite>/<id>/`; `solution` is `fixed`, `buggy`, `patch` or `none`."""

    def build(
        task_id: str = "fix-add",
        suite: str = "regression",
        *,
        solution: str = "fixed",
        hidden: bool = True,
        **overrides: Any,
    ) -> Path:
        task = tmp_path / "tasks" / suite / task_id
        (task / "repo").mkdir(parents=True)
        (task / "repo" / "calc.py").write_text(BUGGY, encoding="utf-8")
        (task / "task.yaml").write_text(
            yaml.safe_dump(task_yaml(task_id, suite, **overrides)), encoding="utf-8"
        )
        if hidden:
            (task / "hidden").mkdir()
            (task / "hidden" / "test_add.py").write_text(HIDDEN_TEST, encoding="utf-8")
        if solution != "none":
            (task / "solution").mkdir()
            if solution == "patch":
                (task / "solution" / "fix.patch").write_text(PATCH, encoding="utf-8")
            else:
                text = FIXED if solution == "fixed" else BUGGY
                (task / "solution" / "calc.py").write_text(text, encoding="utf-8")
        return task

    return build
