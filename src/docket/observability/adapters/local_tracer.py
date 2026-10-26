"""The local adapter of the kernel ``Tracer`` port: the JSONL trace store and the exporter pipeline.

Each call looks the function up at call time, so a patch on ``observability.trace`` or
``observability.telemetry`` lands here too.
"""

from __future__ import annotations

from docket.observability import telemetry as _telemetry
from docket.observability import trace as _trace


class LocalTracer:
    def trace_event(
        self,
        project: str,
        session_id: str,
        agent_role: str,
        event_type: str,
        payload: str,
        cost_usd: float | str | None = None,
        duration_ms: int | str | None = None,
        *,
        task_id: str = "",
    ) -> str:
        return _trace.trace_event(
            project,
            session_id,
            agent_role,
            event_type,
            payload,
            cost_usd,
            duration_ms,
            task_id=task_id,
        )

    def capture_classes(self) -> frozenset[str]:
        return _telemetry.capture_classes()
