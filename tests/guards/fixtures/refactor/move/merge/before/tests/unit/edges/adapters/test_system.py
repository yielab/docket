"""System tests."""

from __future__ import annotations

import pytest

from docket.edges.adapters import system
from docket.edges.adapters.system import landlock_argv

SUBJECT = "docket.edges.adapters.system"


@pytest.fixture
def cmd() -> list[str]:
    return ["true"]


def test_argv(cmd: list[str]) -> None:
    assert landlock_argv(cmd) == cmd


def test_run(cmd: list[str]) -> None:
    assert system.run(cmd) == cmd
