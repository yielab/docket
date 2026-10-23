"""Dispatch tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.tasks.claim import claim_next

SUBJECT = "docket.tasks.claim"


@pytest.fixture
def task_file(tmp_path: Path) -> Path:
    return tmp_path / "task.json"


def test_claim_returns_the_path(task_file: Path) -> None:
    assert claim_next(str(task_file)) == str(task_file)
