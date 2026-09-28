"""Neutral span model over the trace vocabulary, and the policy that reduces a payload
before export. Pure: no socket, no queue, no vendor knowledge -- ``project`` and
``flush_open`` turn ``core/trace.py`` records into ``Span``/``SpanEvent``, deterministically,
so a retried record never produces a duplicate span."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from docket.core import trace

AttrValue = str | int | bool
Attributes = dict[str, AttrValue]


@dataclass(frozen=True)
class SpanEvent:
    name: str
    ts: str
    attributes: Attributes = field(default_factory=dict)


@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start_ts: str
    end_ts: str
    status: str
    attributes: Attributes
    events: tuple[SpanEvent, ...] = ()


@dataclass
class _OpenSpan:
    span_id: str
    parent_id: str | None
    name: str
    start_ts: str
    kind: str
    key: str
    attributes: Attributes
    events: list[SpanEvent] = field(default_factory=list)


@dataclass
class ProjectionState:
    stacks: dict[str, list[_OpenSpan]] = field(default_factory=dict)
    last_ts: dict[str, str] = field(default_factory=dict)


_CONTENT_KEYS = frozenset(
    {"arguments", "text", "content", "output", "result", "prompt", "messages", "summary"}
)

DEFAULT_EVENTS: frozenset[str] = frozenset(
    {
        "session_start",
        "session_end",
        "llm_call",
        "tool_call",
        "tool_result",
        "guardrail_check",
        "guardrail_block",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "approval_required",
        "approval_resumed",
        "approval_task_denied",
        "budget_warning",
        "budget_exceeded",
        "error",
        "hop_retry",
        "verdict_rework_started",
        "verdict_rejected",
        "verdict_unparseable",
        "rework_started",
        "review_rejected",
        "route_taken",
        "command_step",
        "verification_failed",
        "tester_verdict_failed",
        "reviewer_verdict_unparseable",
        "stale_claim",
        "paused_refused",
        "run_cancelled",
    }
)

_ROOT_EVENTS = frozenset(
    {
        "hop_retry",
        "rework_started",
        "verdict_rework_started",
        "verdict_rejected",
        "verdict_unparseable",
        "route_taken",
        "command_step",
        "review_rejected",
        "tester_verdict_failed",
        "verification_failed",
    }
)


def _trace_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:32]


def _span_id(session_id: str, kind: str, key: str) -> str:
    return hashlib.sha256(f"{session_id}|{kind}|{key}".encode()).hexdigest()[:16]


def _parse_ts(ts: str) -> datetime:
    text = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)


def _format_ts(moment: datetime) -> str:
    text = moment.isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


def _shift_ts(ts: str, delta_ms: int) -> str:
    return _format_ts(_parse_ts(ts) + timedelta(milliseconds=delta_ms))


def _close(open_span: _OpenSpan, trace_id: str, end_ts: str, status: str) -> Span:
    return Span(
        trace_id=trace_id,
        span_id=open_span.span_id,
        parent_id=open_span.parent_id,
        name=open_span.name,
        start_ts=open_span.start_ts,
        end_ts=end_ts,
        status=status,
        attributes=dict(open_span.attributes),
        events=tuple(open_span.events),
    )


def _new_root(session_id: str, record: dict[str, Any]) -> _OpenSpan:
    return _OpenSpan(
        span_id=_span_id(session_id, "session", "root"),
        parent_id=None,
        name="docket.session",
        start_ts=str(record.get("ts", "")),
        kind="session",
        key="root",
        attributes={
            "docket.project": str(record.get("project", "")),
            "docket.role": str(record.get("agent_role", "")),
            "docket.session_id": session_id,
            "session.id": session_id,
        },
    )


def _ensure_root(state: ProjectionState, session_id: str, record: dict[str, Any]) -> _OpenSpan:
    stack = state.stacks.setdefault(session_id, [])
    if not stack:
        stack.append(_new_root(session_id, record))
    return stack[0]


def _handle_session_start(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    _ensure_root(state, session_id, record)
    return []


def _handle_llm_call(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record)
    payload = record.get("payload") or {}
    ts = str(record.get("ts", ""))
    duration_ms = int(record.get("duration_ms") or 0)
    ok = payload.get("ok", True)
    iteration = payload.get("iteration", "")
    attributes: Attributes = {
        "gen_ai.system": str(payload.get("provider", "")),
        "gen_ai.request.model": str(payload.get("model", "")),
        "gen_ai.usage.input_tokens": int(payload.get("inputTokens") or 0),
        "gen_ai.usage.output_tokens": int(payload.get("outputTokens") or 0),
        "gen_ai.response.finish_reasons": str(payload.get("finishReason", "")),
        "docket.iteration": iteration if isinstance(iteration, int) else str(iteration),
    }
    return [
        Span(
            trace_id=_trace_id(session_id),
            span_id=_span_id(session_id, "llm_call", str(iteration)),
            parent_id=root.span_id,
            name="gen_ai.chat",
            start_ts=_shift_ts(ts, -duration_ms),
            end_ts=ts,
            status="error" if ok is False else "ok",
            attributes=attributes,
        )
    ]


def _handle_tool_call(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record)
    payload = record.get("payload") or {}
    tool = str(payload.get("tool", ""))
    call_id = str(payload.get("callId", ""))
    state.stacks[session_id].append(
        _OpenSpan(
            span_id=_span_id(session_id, "tool_call", call_id),
            parent_id=root.span_id,
            name=f"execute_tool {tool}" if tool else "execute_tool",
            start_ts=str(record.get("ts", "")),
            kind="tool_call",
            key=call_id,
            attributes={"gen_ai.tool.name": tool, "gen_ai.tool.call.id": call_id},
        )
    )
    return []


def _pop_open_tool(state: ProjectionState, session_id: str, call_id: str) -> _OpenSpan | None:
    stack = state.stacks.get(session_id, [])
    for i in range(len(stack) - 1, 0, -1):
        if stack[i].kind == "tool_call" and stack[i].key == call_id:
            return stack.pop(i)
    return None


def _handle_tool_result(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record)
    payload = record.get("payload") or {}
    tool = str(payload.get("tool", ""))
    call_id = str(payload.get("callId", ""))
    ts = str(record.get("ts", ""))
    open_span = _pop_open_tool(state, session_id, call_id)
    if open_span is None:
        open_span = _OpenSpan(
            span_id=_span_id(session_id, "tool_call", call_id),
            parent_id=root.span_id,
            name=f"execute_tool {tool}" if tool else "execute_tool",
            start_ts=ts,
            kind="tool_call",
            key=call_id,
            attributes={"gen_ai.tool.name": tool, "gen_ai.tool.call.id": call_id},
        )
    attributes = dict(open_span.attributes)
    if "ok" in payload:
        attributes["docket.tool.ok"] = bool(payload["ok"])
    policy_id = payload.get("policyId")
    if policy_id:
        attributes["docket.tool.blocked_by"] = str(policy_id)
    return [
        Span(
            trace_id=_trace_id(session_id),
            span_id=open_span.span_id,
            parent_id=open_span.parent_id,
            name=open_span.name,
            start_ts=open_span.start_ts,
            end_ts=ts,
            status="unset",
            attributes=attributes,
            events=tuple(open_span.events),
        )
    ]


def _handle_session_end(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    _ensure_root(state, session_id, record)
    ts = str(record.get("ts", ""))
    stack = state.stacks.pop(session_id, [])
    state.last_ts.pop(session_id, None)
    trace_id = _trace_id(session_id)
    closed = [_close(open_span, trace_id, ts, "unset") for open_span in reversed(stack[1:])]
    if stack:
        closed.append(_close(stack[0], trace_id, ts, "unset"))
    return closed


def _root_attributes(payload: dict[str, Any], record: dict[str, Any]) -> Attributes:
    attributes: Attributes = {}
    hop = payload.get("hop")
    if hop:
        attributes["docket.hop"] = str(hop)
    task_id = record.get("task_id")
    if task_id:
        attributes["docket.task_id"] = str(task_id)
    return attributes


def _handle_root_event(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record)
    payload = record.get("payload") or {}
    root.events.append(
        SpanEvent(
            name=str(record.get("event_type", "")),
            ts=str(record.get("ts", "")),
            attributes=_root_attributes(payload, record),
        )
    )
    return []


def _handle_generic_event(state: ProjectionState, record: dict[str, Any]) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    _ensure_root(state, session_id, record)
    target = state.stacks[session_id][-1]
    payload = record.get("payload") or {}
    attributes: Attributes = {
        f"docket.{key}": value
        for key, value in payload.items()
        if isinstance(value, str | int | bool)
    }
    target.events.append(
        SpanEvent(
            name=str(record.get("event_type", "")),
            ts=str(record.get("ts", "")),
            attributes=attributes,
        )
    )
    return []


_Handler = Callable[[ProjectionState, dict[str, Any]], list[Span]]

_SPECIAL: dict[str, _Handler] = {
    "session_start": _handle_session_start,
    "llm_call": _handle_llm_call,
    "tool_call": _handle_tool_call,
    "tool_result": _handle_tool_result,
    "session_end": _handle_session_end,
}


def _build_handlers() -> dict[str, _Handler]:
    handlers = dict(_SPECIAL)
    for event_type in _ROOT_EVENTS:
        handlers[event_type] = _handle_root_event
    for event_type in trace.EVENT_TYPES | {"llm_call"}:
        handlers.setdefault(event_type, _handle_generic_event)
    return handlers


_HANDLERS: dict[str, _Handler] = _build_handlers()


def project(record: dict[str, Any], state: ProjectionState) -> list[Span]:
    """Incrementally fold one trace record into ``state``, returning the spans it closes.
    A record whose ``event_type`` is unknown is ignored, never raised on."""
    event_type = str(record.get("event_type", ""))
    handler = _HANDLERS.get(event_type)
    if handler is None:
        return []
    session_id = str(record.get("session_id", ""))
    ts = record.get("ts")
    if ts:
        state.last_ts[session_id] = str(ts)
    return handler(state, record)


def flush_open(state: ProjectionState) -> list[Span]:
    """Force-close every span still open in ``state`` (children before their root),
    at each session's last-seen timestamp, and clear that session's state."""
    closed: list[Span] = []
    for session_id in list(state.stacks):
        stack = state.stacks.pop(session_id)
        ts = state.last_ts.pop(session_id, None) or (stack[0].start_ts if stack else "")
        trace_id = _trace_id(session_id)
        closed.extend(_close(open_span, trace_id, ts, "unset") for open_span in reversed(stack[1:]))
        if stack:
            closed.append(_close(stack[0], trace_id, ts, "unset"))
    return closed


def _reduce_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _CONTENT_KEYS}


def _reduce_full(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
    reduced: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _CONTENT_KEYS:
            text = value if isinstance(value, str) else json.dumps(value)
            reduced[key] = text[:max_chars]
        else:
            reduced[key] = value
    return reduced


@dataclass(frozen=True)
class ExportPolicy:
    events: frozenset[str] | None = None
    payload: str = "metadata"
    payload_max_chars: int = 4000

    def admit(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """``None`` when this record's event type is not admitted; otherwise the record
        with its payload reduced per ``self.payload`` -- never mutates the input."""
        event_type = record.get("event_type", "")
        if self.events is not None and event_type not in self.events:
            return None
        raw_payload = record.get("payload")
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        reduced = (
            _reduce_full(payload, self.payload_max_chars)
            if self.payload == "full"
            else _reduce_metadata(payload)
        )
        out = dict(record)
        out["payload"] = reduced
        return out
