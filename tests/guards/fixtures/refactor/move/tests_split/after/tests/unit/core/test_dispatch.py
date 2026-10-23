"""Dispatch tests."""

from __future__ import annotations

import pytest

from docket.core import dispatch as _dispatch

SUBJECT = "docket.core.dispatch"


@pytest.fixture
def unused_fixture() -> int:
    return 1


def test_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("docket.core.dispatch.ping", lambda: "pong")
    assert _dispatch.ping() == "pong"
