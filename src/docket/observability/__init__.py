"""Public surface of the ``observability`` context (ADR 0030).

Exactly the names other contexts import; the modules behind them stay internal.
"""

from __future__ import annotations

from docket.observability.exporter import (
    ExporterError,
    ExporterSpec,
    ProbeResult,
    activation_state,
    delete_exporter,
    disable_exporter,
    enable_exporter,
    export_exporter,
    is_widening,
    load_catalog,
    load_exporter_document,
    read_health,
    resolve_credentials,
    save_exporter,
    set_privacy,
    verify_endpoint,
)
from docket.observability.projection import DEFAULT_EVENTS, flush_open, project
from docket.observability.spans import ATTRIBUTE_CLASSES, ExportPolicy, ProjectionState, Span
from docket.observability.trace import (
    TraceStatus,
    expire_old_traces,
    export_lines,
    find_trace,
    project_trace_dir,
    read_trace,
    redact,
    subscribe,
    sweep_all,
    terminal_outcomes,
    trace_event,
)

__all__ = [
    "ATTRIBUTE_CLASSES",
    "DEFAULT_EVENTS",
    "ExportPolicy",
    "ExporterError",
    "ExporterSpec",
    "ProbeResult",
    "ProjectionState",
    "Span",
    "TraceStatus",
    "activation_state",
    "delete_exporter",
    "disable_exporter",
    "enable_exporter",
    "expire_old_traces",
    "export_exporter",
    "export_lines",
    "find_trace",
    "flush_open",
    "is_widening",
    "load_catalog",
    "load_exporter_document",
    "project",
    "project_trace_dir",
    "read_health",
    "read_trace",
    "redact",
    "resolve_credentials",
    "save_exporter",
    "set_privacy",
    "subscribe",
    "sweep_all",
    "terminal_outcomes",
    "trace_event",
    "verify_endpoint",
]
