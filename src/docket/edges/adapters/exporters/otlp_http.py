"""OTLP/HTTP JSON wire encoding and transport.

The only module in docket that knows the OTLP JSON shape: ``encode`` turns
``core.telemetry`` spans into a ``resourceSpans`` document, ``OtlpHttpSink``
POSTs it (one retry on 429/502/503/504, honouring ``Retry-After``), and
``probe`` answers ``docket setup export enable``'s reachability check. Stdlib
``urllib``/``json`` only, modelled on ``edges/adapters/llm.py``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docket import __version__
from docket.config import DISPATCH_RETRY_MAX_WAIT_S
from docket.core.telemetry import AttrValue, Span, SpanEvent

_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
_STATUS_CODES: dict[str, int] = {"ok": 1, "error": 2}
_DEFAULT_RETRY_WAIT_S = 1.0

AuthHeader = tuple[str, str] | None


def _encode_value(value: AttrValue) -> dict[str, Any]:
    """One OTLP attribute value: bool/str stay themselves, int becomes a decimal string."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    return {"stringValue": str(value)}


def _encode_attributes(
    attrs: Mapping[str, AttrValue], aliases: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Sorted ``{"key", "value"}`` pairs; an aliased key is duplicated, never renamed."""
    combined = dict(attrs)
    for source, alias in aliases.items():
        if source in attrs:
            combined[alias] = attrs[source]
    return [{"key": key, "value": _encode_value(val)} for key, val in sorted(combined.items())]


def _to_nanos(ts: str) -> str:
    return str(int(datetime.fromisoformat(ts).timestamp() * 1e9))


def _encode_event(event: SpanEvent, aliases: Mapping[str, str]) -> dict[str, Any]:
    return {
        "timeUnixNano": _to_nanos(event.ts),
        "name": event.name,
        "attributes": _encode_attributes(event.attributes, aliases),
    }


def _encode_span(span: Span, aliases: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "parentSpanId": span.parent_id or "",
        "name": span.name,
        "kind": 3 if span.name == "gen_ai.chat" else 1,
        "startTimeUnixNano": _to_nanos(span.start_ts),
        "endTimeUnixNano": _to_nanos(span.end_ts),
        "attributes": _encode_attributes(span.attributes, aliases),
    }
    status_code = _STATUS_CODES.get(span.status)
    if status_code is not None:
        out["status"] = {"code": status_code}
    if span.events:
        out["events"] = [_encode_event(e, aliases) for e in span.events]
    return out


def encode(
    spans: Sequence[Span],
    *,
    resource: Mapping[str, str],
    aliases: Mapping[str, str],
) -> dict[str, Any]:
    """One ``resourceSpans`` document over every span in *spans*, deterministically ordered."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _encode_attributes(resource, aliases)},
                "scopeSpans": [
                    {
                        "scope": {"name": "docket", "version": __version__},
                        "spans": [_encode_span(span, aliases) for span in spans],
                    }
                ],
            }
        ]
    }


def _retry_after_seconds(headers: Any) -> float | None:
    """``Retry-After`` in integer-seconds form only; anything else is "named no wait"."""
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(int(value.strip())))
    except (TypeError, ValueError):
        return None


def _build_headers(auth_header: AuthHeader, headers: Mapping[str, str]) -> dict[str, str]:
    out = {"Content-Type": "application/json"}
    out.update(headers)
    if auth_header is not None:
        name, value = auth_header
        out[name] = value
    return out


def _post(
    opener: Callable[..., Any],
    endpoint: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_s: float,
) -> tuple[int | None, str, float | None]:
    """POST *body*; never raises. Returns ``(status, error, retry_after_s)``;
    ``status`` is ``None`` only for a transport failure."""
    request = urllib.request.Request(endpoint, data=body, headers=dict(headers), method="POST")
    try:
        with opener(request, timeout=timeout_s) as resp:
            resp.read()
            return int(resp.status), "", None
    except urllib.error.HTTPError as ex:
        try:
            detail = ex.read().decode("utf-8", errors="replace").strip()
        except OSError:
            detail = ""
        retry_after = _retry_after_seconds(ex.headers) if ex.code in _RETRYABLE_STATUS else None
        return ex.code, detail or ex.reason, retry_after
    except urllib.error.URLError as ex:
        return None, f"cannot reach {endpoint}: {ex.reason}", None
    except OSError as ex:
        return None, f"cannot reach {endpoint}: {ex}", None


@dataclass(frozen=True)
class SinkResult:
    """The outcome of one ``OtlpHttpSink.emit`` call. ``status`` is ``None`` only for a
    transport failure; a non-2xx response reports ``accepted=0`` with the response detail."""

    accepted: int
    status: int | None
    error: str = ""
    retry_after_s: float | None = None


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of one ``probe`` call. ``status`` is ``None`` only for a transport
    failure; classification into an enable/refuse decision belongs to the caller."""

    status: int | None
    error: str = ""


class OtlpHttpSink:
    """POSTs encoded spans to one OTLP/HTTP JSON endpoint, stateless apart from its
    configuration. ``clock``/``sleep``/``opener`` are injectable so a retry test never
    sleeps or reaches a socket for real."""

    def __init__(
        self,
        endpoint: str,
        auth_header: AuthHeader,
        headers: Mapping[str, str] | None = None,
        resource: Mapping[str, str] | None = None,
        aliases: Mapping[str, str] | None = None,
        timeout_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._endpoint = endpoint
        self._auth_header = auth_header
        self._headers = dict(headers or {})
        self._resource = dict(resource or {})
        self._aliases = dict(aliases or {})
        self._timeout_s = timeout_s
        self._clock = clock
        self._sleep = sleep
        self._opener = opener

    def emit(self, spans: Sequence[Span]) -> SinkResult:
        """POST *spans*, retrying once on a retryable status. Never raises."""
        if not spans:
            return SinkResult(accepted=0, status=None, error="")
        body = json.dumps(encode(spans, resource=self._resource, aliases=self._aliases)).encode()
        wire_headers = _build_headers(self._auth_header, self._headers)
        status, error, retry_after = _post(
            self._opener, self._endpoint, body, wire_headers, self._timeout_s
        )
        if status is not None and 200 <= status < 300:
            return SinkResult(accepted=len(spans), status=status, error="")
        if status in _RETRYABLE_STATUS:
            wait = min(retry_after or _DEFAULT_RETRY_WAIT_S, DISPATCH_RETRY_MAX_WAIT_S)
            self._sleep(wait)
            status, error, retry_after = _post(
                self._opener, self._endpoint, body, wire_headers, self._timeout_s
            )
            if status is not None and 200 <= status < 300:
                return SinkResult(accepted=len(spans), status=status, error="")
        return SinkResult(accepted=0, status=status, error=error, retry_after_s=retry_after)

    def close(self) -> None:
        """No persistent connection to release; present for the ``SpanSink`` protocol."""
        return None


def probe(
    endpoint: str,
    auth_header: AuthHeader,
    headers: Mapping[str, str],
    timeout_s: float = 5.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> ProbeResult:
    """POST an empty ``resourceSpans`` document; never raises."""
    body = json.dumps({"resourceSpans": []}).encode()
    wire_headers = _build_headers(auth_header, headers)
    status, error, _retry_after = _post(opener, endpoint, body, wire_headers, timeout_s)
    return ProbeResult(status=status, error=error)
