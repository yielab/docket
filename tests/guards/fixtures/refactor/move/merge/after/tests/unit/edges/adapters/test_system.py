"""System tests."""

from __future__ import annotations

import pytest

from docket.edges.adapters import system

SUBJECT = "docket.edges.adapters.system"


@pytest.fixture
def cmd() -> list[str]:
    return ["true"]


def test_run(cmd: list[str]) -> None:
    assert system.run(cmd) == cmd
