"""Neutral span model, incremental projection and export policy (observability/telemetry.py)."""

from __future__ import annotations

import pytest

from docket.observability import projection, trace
from docket.observability import spans as observability_spans

SUBJECT = "docket.observability.projection"


class TestEventTypeCoverage:
    @pytest.mark.parametrize("event_type", sorted(trace.EVENT_TYPES))
    def test_every_event_type_produces_no_exception(self, event_type: str) -> None:
        record = {
            "ts": "2026-09-27T10:00:00Z",
            "project": "p",
            "session_id": "cover",
            "agent_role": "lead",
            "event_type": event_type,
            "payload": {},
        }
        state = observability_spans.ProjectionState()
        spans = projection.project(record, state)
        spans += projection.flush_open(state)
        assert spans, f"{event_type} produced neither a span nor a recorded span event"
