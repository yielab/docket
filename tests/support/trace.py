"""Shared trace helpers and fixtures for the docket suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docket.governance import audit as _audit
from docket.kernel.home import current_home
from docket.observability import projection
from docket.observability import spans as observability_spans
from docket.observability import trace as _trace


def trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = current_home().traces_dir / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


def audit_actions() -> list[str]:
    return [e["action"] for e in _audit.read_audit()]


def audit_actions_2(action: str) -> list[dict[str, Any]]:
    return [e for e in _audit.read_audit() if e["action"] == action]


def trace_events_2(project: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    traces_dir = current_home().traces_dir / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


def write_trace(pdir: Path, name: str, lines: list[dict[str, object]]) -> Path:
    pdir.mkdir(parents=True, exist_ok=True)
    tf = pdir / f"{name}.jsonl"
    tf.write_text("\n".join(json.dumps(r) for r in lines) + "\n", encoding="utf-8")
    return tf


def project_all(records: list[dict[str, Any]]) -> list[observability_spans.Span]:
    state = observability_spans.ProjectionState()
    spans: list[observability_spans.Span] = []
    for record in records:
        spans.extend(projection.project(record, state))
    spans.extend(projection.flush_open(state))
    return spans
