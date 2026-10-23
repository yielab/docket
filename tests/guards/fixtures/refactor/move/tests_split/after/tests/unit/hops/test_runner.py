"""Dispatch tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.hops import runner as _runner

SUBJECT = "docket.hops.runner"


@pytest.fixture
def task_file(tmp_path: Path) -> Path:
    return tmp_path / "task.json"


def _name(path: Path) -> str:
    return path.name


class TestRunHop:
    def test_marks_the_hop(self, task_file: Path) -> None:
        assert _runner.run_hop(str(task_file)) == f"{task_file}!"

    def test_names_the_file(self, task_file: Path) -> None:
        assert _name(Path(_runner.run_hop(str(task_file)))) == "task.json!"
