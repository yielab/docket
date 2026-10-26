"""Helpers shared by the split halves of one test file."""

from __future__ import annotations

import json
from pathlib import Path

from docket.observability import projection
from docket.observability import spans as observability_spans

_TRACE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "traces" / "dispatch-3-hops.jsonl"
)


def _projected_spans() -> list[observability_spans.Span]:
    records = [json.loads(line) for line in _TRACE_FIXTURE.read_text().splitlines() if line.strip()]
    state = observability_spans.ProjectionState()
    spans: list[observability_spans.Span] = []
    for record in records:
        spans.extend(projection.project(record, state))
    spans.extend(projection.flush_open(state))
    return spans
