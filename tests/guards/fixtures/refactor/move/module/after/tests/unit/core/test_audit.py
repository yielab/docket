"""Audit tests."""

from __future__ import annotations

from tests.unit.observe.test_trace import SUBJECT as TRACE_SUBJECT

from docket.core import audit
from docket.observe import trace

SUBJECT = "docket.core.audit"


def test_log_records() -> None:
    audit.log("a")
    assert "a" in trace.EVENTS
    assert TRACE_SUBJECT.endswith("trace")
