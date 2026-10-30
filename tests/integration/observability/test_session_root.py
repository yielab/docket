"""A process that joins a session after it began sends that session's root from its real start."""

from __future__ import annotations

import json
import time
from typing import Any

from docket.kernel.home import current_home
from docket.observability import spans as observability_spans
from docket.observability import telemetry, trace
from docket.observability.adapters import otlp_http

SUBJECT = "docket.observability.telemetry"

_SESSION = "agent:demo:task-1"


class _CollectingSink:
    def __init__(self) -> None:
        self.spans: list[observability_spans.Span] = []

    def emit(self, spans: Any) -> Any:
        self.spans.extend(spans)
        return otlp_http.SinkResult(accepted=len(spans), status=200, error="")

    def close(self) -> None:
        return None


def test_the_answering_process_sends_the_root_from_the_session_s_first_record() -> None:
    earlier = {
        "ts": "2026-10-29T09:00:00Z",
        "project": "demo",
        "session_id": _SESSION,
        "agent_role": "lead",
        "event_type": "session_start",
        "payload": {"source": "dispatch"},
    }
    trace_dir = current_home().traces_dir / "demo"
    trace_dir.mkdir(parents=True)
    (trace_dir / f"{_SESSION}.jsonl").write_text(json.dumps(earlier) + "\n")
    sink = _CollectingSink()
    pipeline = telemetry.Pipeline(
        sink,
        observability_spans.MINIMAL_POLICY,
        queue_max=100,
        batch_wait_s=0.01,
        clock=time.monotonic,
    )

    with trace.subscribe(pipeline.offer):
        trace.trace_event("demo", _SESSION, "lead", "approval_resumed", "{}")
    pipeline.close()

    (root,) = [span for span in sink.spans if span.name == "docket.session"]
    assert root.start_ts == "2026-10-29T09:00:00Z"
