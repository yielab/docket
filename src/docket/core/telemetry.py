"""Neutral span model over the trace vocabulary, and the policy that reduces a payload
before export. ``Span``/``SpanEvent``/``project``/``flush_open``/``ExportPolicy`` are pure: no
socket, no queue, no vendor knowledge -- ``project`` turns ``core/trace.py`` records into spans
deterministically, so a retried record never produces a duplicate one. ``Pipeline`` and the
module-level registry below them are the one impure part of this module: a bounded queue and a
background sender per enabled exporter, wired to ``core.trace.add_subscriber``."""

from __future__ import annotations

import contextlib
import hashlib
import json
import queue
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import docket.config as _cfg
from docket.core import exporter as _exporter
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


@dataclass(frozen=True)
class ExportPolicy:
    """What one exporter's pipeline admits and may share. ``admit`` filters by event type
    only; content reduction happens later, at projection, through an allowlist. ``classes``
    is the granted content classes beyond bare structure; ``label`` names the level shown."""

    events: frozenset[str] | None = None
    classes: frozenset[str] = frozenset()
    label: str = "minimal"
    content_max_chars: int = 4000

    def admit(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """``None`` when this record's event type is not admitted; otherwise the record,
        unmodified -- content reduction is `project`'s job, not this gate's."""
        event_type = record.get("event_type", "")
        if self.events is not None and event_type not in self.events:
            return None
        return record


MINIMAL_POLICY = ExportPolicy()


def _granted(policy: ExportPolicy, cls: str) -> bool:
    """The one function that decides whether a content attribute of class *cls* may be
    set -- nothing else in this module checks ``policy.classes`` directly."""
    return cls in policy.classes


def _truncate(text: str, max_chars: int) -> str:
    """Cut *text* to *max_chars*, appending a marker naming how many characters were cut.
    Never silently drops content, and the result is always a valid string to embed in a
    JSON attribute (ADR 0015 §2 rule 5)."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = len(text) - max_chars
    return f"{text[:max_chars]}…[truncated {cut} chars]"


# Every attribute a handler can emit that is NOT bare structure, mapped to its content
# class. An attribute absent from this table is structure -- always sent, never gated by
# `_granted`. `gen_ai.input.messages` is deliberately absent: it mixes classes per message
# part (ADR 0015 §2 rule 3), enforced by `_input_part_class`/`_filter_part`, not by a single
# whole-attribute class.
ATTRIBUTE_CLASSES: dict[str, str] = {
    "gen_ai.tool.call.arguments": "toolArguments",
    "docket.approval.action": "toolArguments",
    "docket.error.message": "errors",
    "gen_ai.tool.call.result": "toolResults",
    "gen_ai.output.messages": "completions",
    "gen_ai.system_instructions": "instructions",
}

# Per generic event type, the payload keys forwarded as `docket.<key>` structural
# attributes (never gated -- structure is always sent). Derived from every real
# `trace_event(`/`_emit_trace(`/`_trace_locked(` call site's payload as of this card; an
# unlisted key drops rather than forwarding by default (ADR 0015 §2 rule 2). Only
# scalar (str/int/bool) values are ever forwarded, whether listed here or not -- a list or
# dict payload value (e.g. `step_skipped`'s `when`) is dropped by that check regardless.
_STRUCTURAL_KEYS: dict[str, tuple[str, ...]] = {
    "context_composed": ("hop", "description_bytes", "total_bytes", "truncated"),
    "prompt_composed": ("budgetTokens", "budgetSource"),
    "session_compaction": (
        "status",
        "beforeMessageCount",
        "afterMessageCount",
        "beforeEstimatedTokens",
        "afterEstimatedTokens",
        "groupsSummarized",
        "summaryRounds",
        "maxSummaryPromptEstimatedTokens",
    ),
    "request_fit": (
        "purpose",
        "status",
        "estimatedInputTokens",
        "outputReserveTokens",
        "contextWindowTokens",
        "estimate",
    ),
    "guardrail_check": ("hook", "policy", "action"),
    "guardrail_block": ("hook", "policy", "action"),
    "approval_requested": ("token",),
    "approval_granted": ("token",),
    "approval_denied": ("token",),
    "cost_charged": ("role",),
    "budget_warning": (
        "action",
        "status",
        "reason",
        "tokenBudget",
        "measuredTokensUsed",
        "remainingMeasuredTokens",
        "normalEstimatedInputTokens",
        "finalizationEstimatedInputTokens",
        "outputReserveTokens",
        "normalProspectiveTokens",
        "finalizationProspectiveTokens",
        "estimate",
    ),
    "budget_exceeded": ("spent", "cap", "role", "estimated"),
    "drift_alert": (),
    "stale_claim": ("task", "claimedAt"),
    "paused_refused": ("reason",),
    "approval_required": ("role", "token", "pipelineIndex", "policy"),
    "approval_resumed": ("task", "token"),
    "approval_task_denied": ("task", "token"),
    "run_cancellation_observed": ("run", "source"),
    "run_cancelled": ("run", "source"),
    "step_skipped": ("step",),
    "error": ("run", "source"),
}

# Per generic event type, the one payload key that carries free-text content instead of
# structure: (payload key, attribute name, content class). Closes the two leaks ADR 0015
# names by name: `approval_requested.action` is the command line waiting for a human
# (toolArguments, like a tool call's own arguments); `error.error` is a run's free-text
# failure message (errors). `guardrail_*`'s `action` is a verdict, not this -- it stays in
# `_STRUCTURAL_KEYS` above under the same key name; the two are told apart by event type,
# never by key name (ADR 0015's "action" collision).
_GENERIC_CONTENT_ATTRS: dict[str, tuple[str, str, str]] = {
    "approval_requested": ("action", "docket.approval.action", "toolArguments"),
    "error": ("error", "docket.error.message", "errors"),
}


def _input_part_class(role: str, part: dict[str, Any]) -> str:
    """One conversation turn mixes classes (ADR 0015 §2 rule 3): a `tool` role turn is a
    tool result, an assistant `tool_call` part carries arguments, a `system` turn is
    instructions -- everything else (user text, assistant text) is a prompt."""
    if role == "system":
        return "instructions"
    if role == "tool":
        return "toolResults"
    if role == "assistant" and part.get("type") == "tool_call":
        return "toolArguments"
    return "prompts"


def _filter_part(part: dict[str, Any], cls: str, policy: ExportPolicy) -> dict[str, Any]:
    """*part* verbatim (its ``content`` truncated) when *cls* is granted; otherwise a
    withheld marker naming the class that would have carried it."""
    if not _granted(policy, cls):
        return {"type": "withheld", "class": cls}
    out = dict(part)
    content = out.get("content")
    if isinstance(content, str):
        out["content"] = _truncate(content, policy.content_max_chars)
    return out


def _filter_input_messages(messages: Any, policy: ExportPolicy) -> list[dict[str, Any]] | None:
    """The conversation sent to the model, one turn per message, each part kept or
    withheld per its own class (`_input_part_class`). ``None`` when *messages* is not a
    list, so a caller whose payload never carries one must not assume a list back."""
    if not isinstance(messages, list):
        return None
    filtered: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", ""))
        parts = message.get("parts")
        parts = parts if isinstance(parts, list) else []
        filtered.append(
            {
                "role": role,
                "parts": [
                    _filter_part(part, _input_part_class(role, part), policy)
                    for part in parts
                    if isinstance(part, dict)
                ],
            }
        )
    return filtered


def _filter_output_messages(messages: Any, policy: ExportPolicy) -> list[dict[str, Any]] | None:
    """What the model wrote, whole (text and the tool calls it requested are one class,
    ``completions`` -- ADR 0015 §1). ``None`` when not granted or *messages* is not a list,
    so the attribute is omitted entirely rather than emitted empty or part-withheld."""
    if not isinstance(messages, list) or not _granted(policy, "completions"):
        return None
    out: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        parts = message.get("parts")
        parts = parts if isinstance(parts, list) else []
        kept: list[dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            item = dict(part)
            content = item.get("content")
            if isinstance(content, str):
                item["content"] = _truncate(content, policy.content_max_chars)
            kept.append(item)
        out.append({"role": str(message.get("role", "")), "parts": kept})
    return out


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
            attributes["gen_ai.system_instructions"] = _truncate(
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


def _handle_tool_call(
    state: ProjectionState, record: dict[str, Any], policy: ExportPolicy
) -> list[Span]:
    session_id = str(record.get("session_id", ""))
    root = _ensure_root(state, session_id, record, policy)
    payload = record.get("payload") or {}
    tool = str(payload.get("tool", ""))
    call_id = str(payload.get("callId", ""))
    attributes: Attributes = {"gen_ai.tool.name": tool, "gen_ai.tool.call.id": call_id}
    arguments = payload.get("arguments")
    if _granted(policy, "toolArguments") and isinstance(arguments, str) and arguments:
        attributes["gen_ai.tool.call.arguments"] = _truncate(arguments, policy.content_max_chars)
    state.stacks[session_id].append(
        _OpenSpan(
            span_id=_span_id(session_id, "tool_call", call_id),
            parent_id=root.span_id,
            name=f"execute_tool {tool}" if tool else "execute_tool",
            start_ts=str(record.get("ts", "")),
            kind="tool_call",
            key=call_id,
            attributes=attributes,
        )
    )
    return []


def _pop_open_tool(state: ProjectionState, session_id: str, call_id: str) -> _OpenSpan | None:
    stack = state.stacks.get(session_id, [])
    for i in range(len(stack) - 1, 0, -1):
        if stack[i].kind == "tool_call" and stack[i].key == call_id:
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
    result_text = payload.get("text")
    if not isinstance(result_text, str):
        result_text = payload.get("output")
    if _granted(policy, "toolResults") and isinstance(result_text, str) and result_text:
        attributes["gen_ai.tool.call.result"] = _truncate(result_text, policy.content_max_chars)
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
            attributes[attr_name] = _truncate(value, policy.content_max_chars)
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


# ── Export pipeline: bounded queue, background sender, module registry ──
#
# Everything below is deliberately impure -- a queue, a thread, a module-level registry -- unlike
# the projection/policy above it. `Pipeline` never imports `edges/`: it receives an already-built
# `SpanSink` object and never constructs one itself (`edges/adapters/exporters` does that).


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Matched structurally against edges/adapters/exporters/otlp_http.py::SinkResult's field names,
# never imported by name, so this module still never imports anything from edges/. Declared as
# read-only properties, not plain attributes: a frozen dataclass only satisfies a Protocol that
# asks for a get, never one that also demands a set.
class SinkOutcome(Protocol):
    """The shape `Pipeline` reads off whatever `SpanSink.emit` returns."""

    @property
    def accepted(self) -> int: ...
    @property
    def status(self) -> int | None: ...
    @property
    def error(self) -> str: ...
    @property
    def retry_after_s(self) -> float | None: ...


class SpanSink(Protocol):
    """What a wire adapter must supply for `Pipeline` to drain into it. One instance per enabled
    exporter, built by `edges/adapters/exporters` from an `ExporterSpec` -- this module never
    builds one itself."""

    def emit(self, spans: Sequence[Span]) -> SinkOutcome: ...
    def close(self) -> None: ...


@dataclass
class PipelineStats:
    """One exporter's delivery counters -- the exact per-name shape
    `config.EXPORTERS_HEALTH_FILE` holds (observability-export.spec.md requirement 32)."""

    exported: int = 0
    dropped: int = 0
    failed: int = 0
    last_ok: str = ""
    last_error: str = ""
    last_error_at: str = ""


class _FlushMarker:
    """Sentinel pushed onto a `Pipeline`'s queue: the drain thread sends whatever batch is
    already forming, then sets this event. Never mistaken for a real span -- checked with
    `isinstance` before anything treats a queued item as one."""

    __slots__ = ("event",)

    def __init__(self) -> None:
        self.event = threading.Event()


_STOP = object()


# `offer` runs `policy.admit` and `project` in the caller's thread (whichever thread
# `core.trace.trace_event` runs on) and enqueues the spans it closes with `put_nowait`; a full
# queue increments `dropped` and returns rather than blocking the caller. One daemon thread
# drains the queue in batches (up to `batch_max` items, or `batch_wait_s` since the first item
# in a forming batch) and calls `sink.emit`, folding the result into `PipelineStats`.
class Pipeline:
    """One exporter's bounded queue and background sender. Never raises out of `offer`,
    `flush`, or `close`."""

    def __init__(
        self,
        sink: SpanSink,
        policy: ExportPolicy,
        *,
        queue_max: int,
        batch_max: int = 100,
        batch_wait_s: float = 1.0,
        clock: Callable[[], float],
    ) -> None:
        self._sink = sink
        self._policy = policy
        self._batch_max = batch_max
        self._batch_wait_s = batch_wait_s
        self._clock = clock
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=queue_max)
        self._state = ProjectionState()
        self._project_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._stats = PipelineStats()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def offer(self, record: dict[str, Any]) -> None:
        """Admit *record* through `policy`, project it, and enqueue any spans it closes."""
        try:
            admitted = self._policy.admit(record)
            if admitted is None:
                return
            with self._project_lock:
                spans = project(admitted, self._state, self._policy)
        except Exception:
            return
        for span in spans:
            self._enqueue(span)

    def _enqueue(self, item: Any) -> None:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._stats_lock:
                self._stats.dropped += 1

    def flush(self, timeout_s: float) -> None:
        """Force-close every span still open, enqueue it, then wait at most *timeout_s* for the
        drain thread to have sent everything queued as of this call -- never longer."""
        try:
            with self._project_lock:
                closed = flush_open(self._state)
            for span in closed:
                self._enqueue(span)
            marker = _FlushMarker()
            try:
                self._queue.put_nowait(marker)
            except queue.Full:
                return
            marker.event.wait(timeout_s)
        except Exception:
            return

    def close(self) -> None:
        """Flush, then stop the drain thread and release the sink."""
        with contextlib.suppress(Exception):
            self.flush(_cfg.EXPORT_FLUSH_TIMEOUT_S)
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_STOP)
        self._thread.join(timeout=_cfg.EXPORT_FLUSH_TIMEOUT_S)
        with contextlib.suppress(Exception):
            self._sink.close()

    def stats(self) -> PipelineStats:
        with self._stats_lock:
            return replace(self._stats)

    @property
    def policy(self) -> ExportPolicy:
        return self._policy

    def _drain(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is _STOP:
                return
            batch: list[Span] = []
            markers: list[_FlushMarker] = []
            if isinstance(item, _FlushMarker):
                markers.append(item)
            else:
                batch.append(item)
                deadline = self._clock() + self._batch_wait_s
                while len(batch) < self._batch_max:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        break
                    try:
                        item = self._queue.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if item is _STOP:
                        if batch:
                            self._send(batch)
                        return
                    if isinstance(item, _FlushMarker):
                        markers.append(item)
                        break
                    batch.append(item)
            if batch:
                self._send(batch)
            for marker in markers:
                marker.event.set()

    def _send(self, batch: list[Span]) -> None:
        try:
            result = self._sink.emit(batch)
        except Exception as exc:
            with self._stats_lock:
                self._stats.failed += len(batch)
                self._stats.last_error = str(exc)
                self._stats.last_error_at = _now_iso()
            return
        accepted = max(0, min(int(result.accepted), len(batch)))
        with self._stats_lock:
            self._stats.exported += accepted
            if accepted < len(batch):
                self._stats.failed += len(batch) - accepted
            if result.error:
                self._stats.last_error = result.error
                self._stats.last_error_at = _now_iso()
            elif accepted:
                self._stats.last_ok = _now_iso()


SinkFactory = Callable[[Any, list[str]], SpanSink]

_REGISTRY: dict[str, Pipeline] = {}
_REGISTRY_LOCK = threading.Lock()
_UNSUBSCRIBE: Callable[[], None] | None = None


def _events_for(spec: Any) -> frozenset[str] | None:
    if spec.events == "all":
        return None
    if spec.events == "default":
        return DEFAULT_EVENTS
    return frozenset(spec.events)


def load_enabled_exporters() -> list[Any]:
    """Every entry in the exporter catalog (`core.exporter.load_catalog`) with `enabled: true`
    -- credential resolution is `start`'s job, not this loader's, so a caller can hand this
    straight to `start` every turn without duplicating that check."""
    return [spec for spec in _exporter.load_catalog().entries.values() if spec.enabled]


def _fan_out(record: dict[str, Any]) -> None:
    with _REGISTRY_LOCK:
        pipelines = list(_REGISTRY.values())
    for pipeline in pipelines:
        with contextlib.suppress(Exception):
            pipeline.offer(record)


# A no-op (returns 0) under `DOCKET_NO_EXPORT=1`, when *specs* has nothing enabled, or when the
# registry is already started -- this registry starts at most once per process.
def start(specs: Sequence[Any], sink_for: SinkFactory) -> int:
    """Build one `Pipeline` per *specs* entry that is enabled and whose credentials all resolve,
    subscribing one fan-out sink through `core.trace.add_subscriber`. Returns the count of
    pipelines actually started."""
    global _UNSUBSCRIBE
    if _cfg.no_export():
        return 0
    with _REGISTRY_LOCK:
        if _REGISTRY or _UNSUBSCRIBE is not None:
            return 0
        started = 0
        for spec in specs:
            if not spec.enabled:
                continue
            values, _source = _exporter.resolve_credentials(spec)
            if spec.auth.credentials and any(not value for value in values):
                continue
            sink = sink_for(spec, values)
            # Every started pipeline shares nothing beyond structure until an exporter
            # document's own privacy fields are wired through here -- a default only narrows.
            policy = ExportPolicy(events=_events_for(spec), classes=frozenset(), label="minimal")
            _REGISTRY[spec.name] = Pipeline(
                sink, policy, queue_max=_cfg.EXPORT_QUEUE_MAX, clock=time.monotonic
            )
            started += 1
        if started:
            _UNSUBSCRIBE = trace.add_subscriber(_fan_out)
        return started


def flush(timeout_s: float) -> None:
    """Flush every started `Pipeline`, each bounded to at most *timeout_s*. Never raises."""
    with _REGISTRY_LOCK:
        pipelines = list(_REGISTRY.values())
    for pipeline in pipelines:
        with contextlib.suppress(Exception):
            pipeline.flush(timeout_s)


def close() -> None:
    """Flush and stop every started `Pipeline`, and unsubscribe the fan-out sink. Safe to call
    when nothing was ever started (a plain no-op), and safe to call more than once."""
    global _UNSUBSCRIBE
    with _REGISTRY_LOCK:
        unsubscribe = _UNSUBSCRIBE
        _UNSUBSCRIBE = None
        pipelines = list(_REGISTRY.values())
        _REGISTRY.clear()
    if unsubscribe is not None:
        with contextlib.suppress(Exception):
            unsubscribe()
    for pipeline in pipelines:
        with contextlib.suppress(Exception):
            pipeline.close()


def capture_classes() -> frozenset[str]:
    """Union of the content classes every started pipeline's policy grants -- empty when
    none is started. A caller uses this to decide what to capture, only on demand, so with
    every exporter at `minimal` the local trace stays exactly what it is today."""
    with _REGISTRY_LOCK:
        pipelines = list(_REGISTRY.values())
    classes: set[str] = set()
    for pipeline in pipelines:
        classes |= pipeline.policy.classes
    return frozenset(classes)


def health() -> dict[str, dict[str, Any]]:
    """Every started exporter's current counters, in `config.EXPORTERS_HEALTH_FILE`'s shape --
    the caller (`edges/adapters/docket_runtime.py::run_turn`) writes this through
    `edges/store.py`; this function itself performs no I/O."""
    with _REGISTRY_LOCK:
        items = list(_REGISTRY.items())
    out: dict[str, dict[str, Any]] = {}
    for name, pipeline in items:
        stats = pipeline.stats()
        out[name] = {
            "exported": stats.exported,
            "dropped": stats.dropped,
            "failed": stats.failed,
            "lastOk": stats.last_ok,
            "lastError": stats.last_error,
            "lastErrorAt": stats.last_error_at,
        }
    return out
