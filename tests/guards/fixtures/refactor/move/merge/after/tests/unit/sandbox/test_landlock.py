"""Landlock tests."""

from __future__ import annotations

import pytest

from docket.sandbox import landlock
from docket.sandbox.landlock import landlock_argv

SUBJECT = "docket.sandbox.landlock"


@pytest.fixture
def cmd() -> list[str]:
    return ["true"]


def test_ok(cmd: list[str]) -> None:
    assert landlock.landlock_ok() and cmd


def test_argv(cmd: list[str]) -> None:
    assert landlock_argv(cmd) == cmd
