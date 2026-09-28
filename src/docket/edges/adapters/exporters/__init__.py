"""Wire adapters for observability export.

Each module here is the only place in docket that knows one destination's wire
format; ``core/telemetry.py``'s ``Span``/``SpanEvent`` model stays vendor-free.

``sink_for`` is the one factory `core/telemetry.py::start` calls to turn a resolved
`ExporterSpec` plus its already-resolved credential values into a `SpanSink` -- dispatching on
`spec.dialect` through `_DIALECTS`. Today only `otlp-http` is registered.
"""

from __future__ import annotations

import base64
from collections.abc import Callable

from docket.core.exporter import ExporterSpec
from docket.core.telemetry import SpanSink
from docket.edges.adapters.exporters.otlp_http import AuthHeader, OtlpHttpSink


def _auth_header(spec: ExporterSpec, values: list[str]) -> AuthHeader:
    """Build the resolved auth header pair for *spec*'s ``auth.type`` from its already-resolved
    credential *values* (`core.exporter.resolve_credentials`) -- this module never reads a
    credential by name, only what the caller already resolved."""
    auth_type = spec.auth.type
    if auth_type == "none":
        return None
    if auth_type == "bearer":
        return ("Authorization", f"Bearer {values[0]}")
    if auth_type == "basic":
        pair = f"{values[0]}:{values[1]}".encode()
        return ("Authorization", f"Basic {base64.b64encode(pair).decode('ascii')}")
    if auth_type == "header":
        return (spec.auth.header, values[0])
    raise ValueError(f"unknown auth type: {auth_type!r}")  # pragma: no cover - closed by pydantic


def _otlp_sink(spec: ExporterSpec, auth_header: AuthHeader) -> SpanSink:
    return OtlpHttpSink(
        endpoint=spec.endpoint,
        auth_header=auth_header,
        headers=spec.headers,
        resource=spec.resource,
        aliases=spec.aliases,
    )


_DIALECTS: dict[str, Callable[[ExporterSpec, AuthHeader], SpanSink]] = {"otlp-http": _otlp_sink}


def sink_for(spec: ExporterSpec, values: list[str]) -> SpanSink:
    """Build the wire sink for *spec*'s ``dialect``, wired with its already-resolved auth header
    and static config. Raises ``ValueError`` for an unknown dialect -- unreachable today since
    `ExporterSpec.dialect` is a closed `Literal`, but the check is not conditioned on that."""
    factory = _DIALECTS.get(spec.dialect)
    if factory is None:
        raise ValueError(f"unknown exporter dialect: {spec.dialect!r}")
    return factory(spec, _auth_header(spec, values))
