from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docket.kernel import text as _text

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
    "docket.session.input": "prompts",
    "docket.session.output": "completions",
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
    "stale_claim": ("task", "claimedAt"),
    "paused_refused": ("reason",),
    "approval_required": ("role", "token", "pipelineIndex", "policy"),
    "approval_resumed": ("task", "token"),
    "approval_task_denied": ("task", "token"),
    "run_cancellation_observed": ("run", "source"),
    "run_cancelled": ("run", "source"),
    "step_skipped": ("step",),
    "input_requested": ("task", "step", "questionId"),
    "question_asked": ("questionId", "kind", "mode"),
    "input_answered": ("task", "step", "questionId", "action"),
    "process_started": ("pgid", "tool"),
    "process_exited": ("pgid", "tool", "exitCode", "signal"),
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


# The part fields that carry free text in the OTel GenAI message shape: a text part's
# `content`, a `tool_call` part's `arguments`, a `tool_call_response` part's `response`.
_PART_TEXT_FIELDS: tuple[str, ...] = ("content", "arguments", "response")


def _bound_part(part: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """A copy of *part* with every free-text field cut to *max_chars*."""
    out = dict(part)
    for key in _PART_TEXT_FIELDS:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = _text.cut_chars(value, max_chars)
    return out


def _filter_part(part: dict[str, Any], cls: str, policy: ExportPolicy) -> dict[str, Any]:
    """*part* with its text fields truncated when *cls* is granted; otherwise a withheld
    marker naming the class that would have carried it."""
    if not _granted(policy, cls):
        return {"type": "withheld", "class": cls}
    return _bound_part(part, policy.content_max_chars)


def _filter_input_messages(messages: Any, policy: ExportPolicy) -> list[dict[str, Any]] | None:
    """The conversation sent to the model, one turn per message, each part kept or
    withheld per its own class (`_input_part_class`). ``None`` when *messages* is not a
    list or no part is granted, so nothing but withheld markers is never exported."""
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
    kept = any(part.get("type") != "withheld" for turn in filtered for part in turn["parts"])
    return filtered if kept else None


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
        kept = [
            _bound_part(part, policy.content_max_chars) for part in parts if isinstance(part, dict)
        ]
        out.append({"role": str(message.get("role", "")), "parts": kept})
    return out
