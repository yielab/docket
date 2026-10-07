"""`docket notify` -- only an explicit `flush` delivers."""

from __future__ import annotations

from typing import Any

import pytest

from docket.cli import _notify

SUBJECT = "docket.cli._notify"


@pytest.fixture
def flushed(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def _record(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        raise AssertionError("flush must not run")

    monkeypatch.setattr(_notify._notify, "flush", _record)
    return calls


def test_bare_notify_is_usage_and_delivers_nothing(flushed: list[Any]) -> None:
    assert _notify.run_notify("", []) == 2
    assert flushed == []


def test_an_unknown_action_is_usage_and_delivers_nothing(flushed: list[Any]) -> None:
    assert _notify.run_notify("sendall", []) == 2
    assert flushed == []
