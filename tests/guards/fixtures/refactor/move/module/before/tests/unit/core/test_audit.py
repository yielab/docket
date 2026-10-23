"""Audit tests."""

from __future__ import annotations

from docket.core import audit, trace

from .test_trace import SUBJECT as TRACE_SUBJECT

SUBJECT = "docket.core.audit"


def test_log_records() -> None:
    audit.log("a")
    assert "a" in trace.EVENTS
    assert TRACE_SUBJECT.endswith("trace")
