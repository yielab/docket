"""Landlock tests."""

from __future__ import annotations

import pytest

from docket.edges.adapters import landlock

SUBJECT = "docket.edges.adapters.landlock"


@pytest.fixture
def cmd() -> list[str]:
    return ["true"]


def test_ok(cmd: list[str]) -> None:
    assert landlock.landlock_ok() and cmd
