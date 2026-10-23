"""Dispatch tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.core import dispatch as _dispatch
from docket.core.dispatch import claim_next

SUBJECT = "docket.core.dispatch"


@pytest.fixture
def task_file(tmp_path: Path) -> Path:
    return tmp_path / "task.json"


@pytest.fixture
def unused_fixture() -> int:
    return 1


def _name(path: Path) -> str:
    return path.name


def test_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("docket.core.dispatch.ping", lambda: "pong")
    assert _dispatch.ping() == "pong"


def test_claim_returns_the_path(task_file: Path) -> None:
    assert claim_next(str(task_file)) == str(task_file)


class TestRunHop:
    def test_marks_the_hop(self, task_file: Path) -> None:
        assert _dispatch.run_hop(str(task_file)) == f"{task_file}!"

    def test_names_the_file(self, task_file: Path) -> None:
        assert _name(Path(_dispatch.run_hop(str(task_file)))) == "task.json!"
