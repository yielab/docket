"""Trace tests."""

from __future__ import annotations

import pytest

from docket.core import trace

SUBJECT = "docket.core.trace"


def test_record_appends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("docket.core.trace.EVENTS", [])
    trace.record("x")
    assert trace.EVENTS == ["x"]
