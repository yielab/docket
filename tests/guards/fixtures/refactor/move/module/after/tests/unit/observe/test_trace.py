"""Trace tests."""

from __future__ import annotations

import pytest

from docket.observe import trace

SUBJECT = "docket.observe.trace"


def test_record_appends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("docket.observe.trace.EVENTS", [])
    trace.record("x")
    assert trace.EVENTS == ["x"]
