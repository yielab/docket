from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

_CANCELLATION_REASON = "operator request"
_CANCELLATION_SOURCE = "cli"
_CANCELLATION_REASON_CHARS = 200
_CANCELLATION_SOURCE_CHARS = 32


@dataclass(frozen=True, slots=True)
class CancellationLifecycle:
    """Typed view of one run record's persisted cancellation lifecycle."""

    requested_at: str | None = None
    observed_at: str | None = None
    stopped_at: str | None = None
    reason: str = ""
    source: str = ""

    @property
    def requested(self) -> bool:
        return self.requested_at is not None

    def to_record(self) -> dict[str, str | None]:
        return {
            "requestedAt": self.requested_at,
            "observedAt": self.observed_at,
            "stoppedAt": self.stopped_at,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class CancelOutcome:
    """Result of :func:`cancel_run` — what a ``docket task cancel <ref>`` call
    found and did. ``core/`` returns typed results; ``cli/`` renders them."""

    ok: bool
    message: str
    killed_pids: list[int] = field(default_factory=list)


def _valid_timestamp(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = _dt.datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _cancellation_lifecycle(
    rec: dict[str, Any],
) -> tuple[CancellationLifecycle, bool]:
    """Parse a record's cancellation lifecycle; ``False`` when it is missing or malformed."""
    raw = rec.get("cancellation")
    if not isinstance(raw, dict):
        return CancellationLifecycle(), False
    required = {"requestedAt", "observedAt", "stoppedAt", "reason", "source"}
    if not required.issubset(raw):
        return CancellationLifecycle(), False
    requested_at = raw.get("requestedAt")
    observed_at = raw.get("observedAt")
    stopped_at = raw.get("stoppedAt")
    reason = raw.get("reason")
    source = raw.get("source")
    if not all(_valid_timestamp(value) for value in (requested_at, observed_at, stopped_at)):
        return CancellationLifecycle(), False
    if not isinstance(reason, str) or len(reason) > _CANCELLATION_REASON_CHARS:
        return CancellationLifecycle(), False
    if not isinstance(source, str) or len(source) > _CANCELLATION_SOURCE_CHARS:
        return CancellationLifecycle(), False
    if requested_at is None and (observed_at is not None or stopped_at is not None):
        return CancellationLifecycle(), False
    if observed_at is None and stopped_at is not None:
        return CancellationLifecycle(), False
    timestamps = [
        _dt.datetime.fromisoformat(value)
        for value in (requested_at, observed_at, stopped_at)
        if isinstance(value, str)
    ]
    if timestamps != sorted(timestamps):
        return CancellationLifecycle(), False
    return (
        CancellationLifecycle(
            requested_at=requested_at if isinstance(requested_at, str) else None,
            observed_at=observed_at if isinstance(observed_at, str) else None,
            stopped_at=stopped_at if isinstance(stopped_at, str) else None,
            reason=reason,
            source=source,
        ),
        True,
    )


def _set_cancellation_lifecycle(rec: dict[str, Any], lifecycle: CancellationLifecycle) -> None:
    """Update known lifecycle fields while preserving forward-compatible keys."""
    raw = rec.get("cancellation")
    cancellation = dict(raw) if isinstance(raw, dict) else {}
    cancellation.update(lifecycle.to_record())
    rec["cancellation"] = cancellation


def _emit_cancellation_trace(project: str, run_id: str, source: str, event_type: str) -> None:
    """Best-effort bounded trace for one monotonic cancellation lifecycle edge."""
    try:
        import json as _json

        from docket.observability import trace as _trace

        _trace.trace_event(
            project,
            f"agent:{project}:dispatch",
            "lead",
            event_type,
            _json.dumps({"run": run_id, "source": source}),
        )
    except Exception:
        return None
