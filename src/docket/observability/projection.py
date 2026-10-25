from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from docket.kernel import clock as _clock
from docket.kernel import text as _text
from docket.observability import trace
from docket.observability.spans import (
    _GENERIC_CONTENT_ATTRS,
    _STRUCTURAL_KEYS,
    MINIMAL_POLICY,
    Attributes,
    ExportPolicy,
    ProjectionState,
    Span,
    SpanEvent,
    _filter_input_messages,
    _filter_output_messages,
    _filter_part,
    _granted,
    _OpenSpan,
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
        "verdict_reasked",
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
        "verdict_reasked",
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


def _format_ts(moment: datetime) -> str:
    text = moment.isoformat()
    return text[:-6] + "Z" if text.endswith("+00:00") else text


def _shift_ts(ts: str, delta_ms: int) -> str:
    return _format_ts((_clock.parse_iso(ts) or _clock.now()) + timedelta(milliseconds=delta_ms))


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


def _new_root(session_id: str, record: dict[str, Any], policy: ExportPolicy) -> _OpenSpan:
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
            "docket.privacy": policy.label,
            "docket.privacy.classes": ",".join(sorted(policy.classes)),
        },
    )


def _ensure_root(
    state: ProjectionState, session_id: str, record: dict[str, Any], policy: ExportPolicy
) -> _OpenSpan:
    stack = state.stacks.setdefault(session_id, [])
    if not stack:
        stack.append(_new_root(session_id, record, policy))
    return stack[0]


def _handle_session_start(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    _ensure_root(state, session_id, record, policy)
    return []


def _text_parts(messages: Any, role: str) -> list[str]:
    """Every non-empty ``text`` part's content, in order, across *messages* of *role*."""
    if not isinstance(messages, list):
        return []
    return [
        part["content"]
        for message in messages
        if isinstance(message, dict) and message.get("role") == role
        for part in message.get("parts") or ()
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("content"), str)
        and part["content"]
    ]


def _fold_session_content(root: _OpenSpan, payload: dict[str, Any], policy: ExportPolicy) -> None:
    """Give the session root what the session was asked and what it last answered, for a
    destination that shows a trace's own input and output (Langfuse reads the root's)."""
    if _granted(policy, "prompts") and "docket.session.input" not in root.attributes:
        asked = _text_parts(payload.get("inputMessages"), "user")
        if asked:
            root.attributes["docket.session.input"] = _text.cut_chars(
                asked[0], policy.content_max_chars
            )
    if _granted(policy, "completions"):
        answered = _text_parts(payload.get("outputMessages"), "assistant")
        if answered:
            root.attributes["docket.session.output"] = _text.cut_chars(
                answered[-1], policy.content_max_chars
            )


def _handle_llm_call(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record, policy)
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
    input_messages = _filter_input_messages(payload.get("inputMessages"), policy)
    if input_messages is not None:
        attributes["gen_ai.input.messages"] = json.dumps(input_messages)
    output_messages = _filter_output_messages(payload.get("outputMessages"), policy)
    if output_messages is not None:
        attributes["gen_ai.output.messages"] = json.dumps(output_messages)
    if _granted(policy, "instructions"):
        instructions = payload.get("systemInstructions")
        if isinstance(instructions, str) and instructions:
            attributes["gen_ai.system_instructions"] = _text.cut_chars(
                instructions, policy.content_max_chars
            )
        elif isinstance(instructions, list):
            kept_instructions = [
                _filter_part(part, "instructions", policy)
                for part in instructions
                if isinstance(part, dict)
            ]
            if kept_instructions:
                attributes["gen_ai.system_instructions"] = json.dumps(kept_instructions)
    instructions_sha = payload.get("systemInstructionsSha256")
    if instructions_sha:
        attributes["docket.instructions.sha256"] = str(instructions_sha)
    _fold_session_content(root, payload, policy)
    # Every hop of a pod dispatch restarts at iteration 1 under one session, so the iteration
    # alone would give four hops one span id and a destination that upserts would keep one.
    key = "|".join(
        (
            str(record.get("agent_role", "")),
            str(payload.get("purpose") or "task"),
            str(iteration),
            ts,
        )
    )
    return [
        Span(
            trace_id=_trace_id(session_id),
            span_id=_span_id(session_id, "llm_call", key),
            parent_id=root.span_id,
            name="gen_ai.chat",
            start_ts=_shift_ts(ts, -duration_ms),
            end_ts=ts,
            status="error" if ok is False else "ok",
            attributes=attributes,
        )
    ]


def _handle_tool_call(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record, policy)
    payload = record.get("payload") or {}
    tool = str(payload.get("tool", ""))
    call_id = str(payload.get("callId", ""))
    key = call_id or f"{record.get('agent_role', '')}|{record.get('ts', '')}"
    attributes: Attributes = {"gen_ai.tool.name": tool, "gen_ai.tool.call.id": call_id}
    arguments = payload.get("arguments")
    if _granted(policy, "toolArguments") and isinstance(arguments, str) and arguments:
        attributes["gen_ai.tool.call.arguments"] = _text.cut_chars(
            arguments, policy.content_max_chars
        )
    state.stacks[session_id].append(
        _OpenSpan(
            span_id=_span_id(session_id, "tool_call", key),
            parent_id=root.span_id,
            name=f"execute_tool {tool}" if tool else "execute_tool",
            start_ts=str(record.get("ts", "")),
            kind="tool_call",
            key=key,
            attributes=attributes,
        )
    )
    return []


def _pop_open_tool(
    state: ProjectionState, session_id: str, call_id: str, role: str
) -> _OpenSpan | None:
    stack = state.stacks.get(session_id, [])
    for i in range(len(stack) - 1, 0, -1):
        span = stack[i]
        if span.kind != "tool_call":
            continue
        if call_id and span.key == call_id:
            return stack.pop(i)
        unkeyed = not call_id and not span.attributes.get("gen_ai.tool.call.id")
        if unkeyed and span.key.startswith(f"{role}|"):
            return stack.pop(i)
    return None


def _handle_tool_result(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record, policy)
    payload = record.get("payload") or {}
    tool = str(payload.get("tool", ""))
    call_id = str(payload.get("callId", ""))
    ts = str(record.get("ts", ""))
    role = str(record.get("agent_role", ""))
    open_span = _pop_open_tool(state, session_id, call_id, role)
    if open_span is None:
        key = call_id or f"{role}|{ts}|result"
        open_span = _OpenSpan(
            span_id=_span_id(session_id, "tool_call", key),
            parent_id=root.span_id,
            name=f"execute_tool {tool}" if tool else "execute_tool",
            start_ts=ts,
            kind="tool_call",
            key=key,
            attributes={"gen_ai.tool.name": tool, "gen_ai.tool.call.id": call_id},
        )
    attributes = dict(open_span.attributes)
    if "ok" in payload:
        attributes["docket.tool.ok"] = bool(payload["ok"])
    policy_id = payload.get("policyId")
    if policy_id:
        attributes["docket.tool.blocked_by"] = str(policy_id)
    result_text = payload.get("text")
    if not isinstance(result_text, str):
        result_text = payload.get("output")
    if _granted(policy, "toolResults") and isinstance(result_text, str) and result_text:
        attributes["gen_ai.tool.call.result"] = _text.cut_chars(
            result_text, policy.content_max_chars
        )
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


def _handle_session_end(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    _ensure_root(state, session_id, record, policy)
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


def _handle_root_event(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record, policy)
    payload = record.get("payload") or {}
    root.events.append(
        SpanEvent(
            name=str(record.get("event_type", "")),
            ts=str(record.get("ts", "")),
            attributes=_root_attributes(payload, record),
        )
    )
    return []


def _handle_generic_event(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    _ensure_root(state, session_id, record, policy)
    target = state.stacks[session_id][-1]
    payload = record.get("payload") or {}
    event_type = str(record.get("event_type", ""))
    allowed = _STRUCTURAL_KEYS.get(event_type, ())
    attributes: Attributes = {
        f"docket.{key}": value
        for key, value in payload.items()
        if key in allowed and isinstance(value, str | int | bool)
    }
    content = _GENERIC_CONTENT_ATTRS.get(event_type)
    if content is not None:
        payload_key, attr_name, cls = content
        value = payload.get(payload_key)
        if _granted(policy, cls) and isinstance(value, str) and value:
            attributes[attr_name] = _text.cut_chars(value, policy.content_max_chars)
    target.events.append(
        SpanEvent(
            name=event_type,
            ts=str(record.get("ts", "")),
            attributes=attributes,
        )
    )
    return []


_Handler = Callable[[ProjectionState, dict[str, Any], ExportPolicy], list[Span]]

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


def project(
    record: dict[str, Any], state: ProjectionState, policy: ExportPolicy = MINIMAL_POLICY
) -> list[Span]:
    """Incrementally fold one trace record into ``state`` under *policy*'s granted content
    classes, returning the spans it closes. A record whose ``event_type`` is unknown is
    ignored, never raised on. *policy* defaults to sharing nothing beyond structure."""
    event_type = str(record.get("event_type", ""))
    handler = _HANDLERS.get(event_type)
    if handler is None:
        return []
    session_id = str(record.get("session_id", ""))
    ts = record.get("ts")
    if ts:
        state.last_ts[session_id] = str(ts)
    return handler(state, record, policy)


def _is_hop_span(span: _OpenSpan) -> bool:
    return span.kind == "tool_call" and not span.attributes.get("gen_ai.tool.call.id")


def flush_turn(state: ProjectionState) -> list[Span]:
    """Close every open span a turn owns; keep each session root and hop span open and unsent,
    since both wrap the turn (Langfuse keeps a trace's Input/Output from the first root it
    receives). `session_end`, the hop's own reply, or `flush_open` closes them."""
    closed: list[Span] = []
    for session_id, stack in state.stacks.items():
        if len(stack) < 2:
            continue
        ts = state.last_ts.get(session_id) or stack[0].start_ts
        trace_id = _trace_id(session_id)
        owned = [span for span in stack[1:] if not _is_hop_span(span)]
        closed.extend(_close(open_span, trace_id, ts, "unset") for open_span in reversed(owned))
        stack[1:] = [span for span in stack[1:] if _is_hop_span(span)]
    return closed


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
