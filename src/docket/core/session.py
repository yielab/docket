"""Durable turn history + compaction.

Persists message history *inside* a turn, keyed on ``agent:<id>:<project>``; loaded by
``core/agent_loop.py`` before each turn and appended after. Full contract, storage layout, and
wire format: ``specs/functional/session-history.spec.md``.

Load-bearing facts kept here: an assistant message's ``tool_calls`` and every answering
``tool``-role reply are one atomic unit ``compact_session`` never splits, drops, or partially
summarises. If summarisation fails or returns nothing usable, the stored history is left
unchanged and ``ok=False`` is reported. ``plan_compaction`` budgets against the *estimate*
(``core.context.estimate_tokens``), never against ``MeasuredUsage``'s *measured* counts.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote as _urlquote

from pydantic import BaseModel, ConfigDict, Field

import docket.config as _cfg
from docket.core import context as _context
from docket.core.llm import ChatMessage, Role, TokenUsage, ToolCall
from docket.core.runtime_driver import FailureKind, TurnResult
from docket.edges import store as _store

__all__ = [
    "CompactionPlan",
    "CompactionResult",
    "MeasuredUsage",
    "SessionRecord",
    "SessionSummaryRunner",
    "StoredMessage",
    "StoredToolCall",
    "append_messages",
    "compact_session",
    "find_orphaned_tool_messages",
    "find_unanswered_tool_calls",
    "group_atomic_units",
    "load_messages",
    "load_session",
    "plan_compaction",
]

#: The shape `compact_session` needs from a driver -- identical to
#: `core.memory.DistillRunner`/`core.dispatch.Runner`: `RuntimeDriver.run_turn`'s
#: core 5-arg call, nothing more. A separate alias (not an import of either)
#: because this module must not depend on `core/memory.py` or `core/dispatch.py`
#: for a plain structural type -- see the module docstring's fail-closed section.
SessionSummaryRunner = Callable[[str, str, str, int, dict[str, str] | None], TurnResult]

_SESSION_FILENAME = "session.json"
_COMPACTED_SUMMARY_PREFIX = "[compacted summary of "
_COMPACTION_ACTIVE: ContextVar[bool] = ContextVar("docket_session_compaction_active", default=False)


# ── storage models ────────────────────────────────────────────────────────────


class StoredToolCall(BaseModel):
    """Wire/storage twin of ``core.llm.ToolCall`` -- same three fields, no more."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    arguments: str = "{}"


class StoredMessage(BaseModel):
    """Wire/storage twin of ``core.llm.ChatMessage``, field-for-field so ``_encode``/``_decode``
    are the only translation needed (round-trip contract: session-history.spec.md req 6)."""

    model_config = ConfigDict(populate_by_name=True)

    role: Role
    content: str = ""
    tool_calls: list[StoredToolCall] = Field(default_factory=list, alias="toolCalls")
    tool_call_id: str = Field("", alias="toolCallId")
    name: str = ""


class MeasuredUsage(BaseModel):
    """Cumulative **measured** token counts (real, from the completion endpoint) across a
    session's turns. Distinct from the estimate ``plan_compaction`` budgets against -- never
    conflate the two. Display/reporting only; never read by compaction."""

    model_config = ConfigDict(populate_by_name=True)

    input_tokens: int = Field(0, alias="inputTokens")
    output_tokens: int = Field(0, alias="outputTokens")
    cached_tokens: int = Field(0, alias="cachedTokens")
    turns: int = 0


def _add_usage(current: MeasuredUsage, delta: TokenUsage) -> MeasuredUsage:
    """Fold one exchange's real ``TokenUsage`` into a session's running total."""
    return MeasuredUsage(
        input_tokens=current.input_tokens + delta.input_tokens,
        output_tokens=current.output_tokens + delta.output_tokens,
        cached_tokens=current.cached_tokens + delta.cached_tokens,
        turns=current.turns + 1,
    )


class SessionRecord(BaseModel):
    """One session's durable turn history, as persisted to ``session.json``."""

    model_config = ConfigDict(populate_by_name=True)

    session_key: str = Field("", alias="sessionKey")
    created: str = ""
    updated: str = ""
    messages: list[StoredMessage] = Field(default_factory=list)
    usage: MeasuredUsage = Field(default_factory=MeasuredUsage)


def _encode(msg: ChatMessage) -> StoredMessage:
    return StoredMessage(
        role=msg.role,
        content=msg.content,
        tool_calls=[
            StoredToolCall(id=c.id, name=c.name, arguments=c.arguments) for c in msg.tool_calls
        ],
        tool_call_id=msg.tool_call_id,
        name=msg.name,
    )


def _decode(sm: StoredMessage) -> ChatMessage:
    return ChatMessage(
        role=sm.role,
        content=sm.content,
        tool_calls=[ToolCall(id=c.id, name=c.name, arguments=c.arguments) for c in sm.tool_calls],
        tool_call_id=sm.tool_call_id,
        name=sm.name,
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── storage paths ─────────────────────────────────────────────────────────────


def _session_dir(session_key: str, sessions_dir: Path | None = None) -> Path:
    root = sessions_dir if sessions_dir is not None else _cfg.SESSIONS_DIR
    return root / _urlquote(session_key, safe="")


def _session_path(session_key: str, sessions_dir: Path | None = None) -> Path:
    return _session_dir(session_key, sessions_dir) / _SESSION_FILENAME


def _ensure_session_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)


# ── load ──────────────────────────────────────────────────────────────────────


def load_session(session_key: str, *, sessions_dir: Path | None = None) -> SessionRecord:
    """Load *session_key*'s durable record, or empty if absent/corrupt -- scoped to *this session
    only*, never touching another's file. ``edges/store.py`` keeps a ``.bak``; no auto-recovery."""
    path = _session_path(session_key, sessions_dir)
    if not path.exists():
        return SessionRecord(session_key=session_key)
    try:
        return SessionRecord.model_validate(_store.read_json(path))
    except Exception:
        return SessionRecord(session_key=session_key)


def load_messages(session_key: str, *, sessions_dir: Path | None = None) -> list[ChatMessage]:
    """Convenience: *session_key*'s durable history, decoded to ``ChatMessage``."""
    return [_decode(m) for m in load_session(session_key, sessions_dir=sessions_dir).messages]


# ── append ────────────────────────────────────────────────────────────────────


def append_messages(
    session_key: str,
    messages: Sequence[ChatMessage],
    *,
    usage: TokenUsage | None = None,
    now: str | None = None,
    sessions_dir: Path | None = None,
) -> SessionRecord:
    """Atomically append *messages* (and optional measured *usage*) to *session_key*'s durable
    history, creating the session if absent. One locked ``read_modify_write``, so two concurrent
    appends to the *same* key can never interleave and drop messages."""
    stamp = now or _utc_now()
    path = _session_path(session_key, sessions_dir)
    _ensure_session_dir(path)

    def _mutate(current: dict[str, Any]) -> dict[str, Any]:
        record = (
            SessionRecord.model_validate(current)
            if current
            else SessionRecord(session_key=session_key, created=stamp)
        )
        new_usage = _add_usage(record.usage, usage) if usage is not None else record.usage
        updated = record.model_copy(
            update={
                "session_key": session_key,
                "messages": [*record.messages, *(_encode(m) for m in messages)],
                "usage": new_usage,
                "updated": stamp,
            }
        )
        return updated.model_dump(by_alias=True)

    result = _store.read_modify_write(path, _mutate)
    return SessionRecord.model_validate(result)


# ── atomic grouping ───────────────────────────────────────────────────────────


def group_atomic_units(messages: Sequence[ChatMessage]) -> list[list[ChatMessage]]:
    """Partition *messages* into the atomic units compaction must never split: an assistant
    message's ``tool_calls`` plus every contiguous ``tool`` reply answering one, matched by
    ``tool_call_id`` (unanswered ids just close the group; ``find_unanswered_tool_calls`` checks that)."""
    groups: list[list[ChatMessage]] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if msg.role == "assistant" and msg.tool_calls:
            pending_ids = {c.id for c in msg.tool_calls}
            unit = [msg]
            j = i + 1
            while j < n and pending_ids:
                nxt = messages[j]
                if nxt.role == "tool" and nxt.tool_call_id in pending_ids:
                    unit.append(nxt)
                    pending_ids.discard(nxt.tool_call_id)
                    j += 1
                else:
                    break
            groups.append(unit)
            i = j
        else:
            groups.append([msg])
            i += 1
    return groups


def find_orphaned_tool_messages(messages: Sequence[ChatMessage]) -> list[int]:
    """Indices of ``tool``-role messages whose ``tool_call_id`` answers no still-open, preceding
    assistant ``tool_calls`` entry -- the post-condition check run on ``compact_session``'s
    candidate output before it is ever persisted."""
    open_ids: set[str] = set()
    orphans: list[int] = []
    for idx, m in enumerate(messages):
        if m.role == "assistant" and m.tool_calls:
            open_ids.update(c.id for c in m.tool_calls)
        elif m.role == "tool":
            if m.tool_call_id in open_ids:
                open_ids.discard(m.tool_call_id)
            else:
                orphans.append(idx)
    return orphans


def find_unanswered_tool_calls(messages: Sequence[ChatMessage]) -> list[str]:
    """Tool-call ids requested by an assistant message that no later ``tool``
    message in *messages* ever answers. The other half of the atomicity
    guarantee, alongside ``find_orphaned_tool_messages``."""
    open_ids: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            open_ids.update(c.id for c in m.tool_calls)
        elif m.role == "tool" and m.tool_call_id in open_ids:
            open_ids.discard(m.tool_call_id)
    return sorted(open_ids)


# ── compaction planning (pure) ─────────────────────────────────────────────────


def _render_message_for_estimate(msg: ChatMessage) -> str:
    """Cheap text approximation of one message, for ``estimate_tokens``."""
    parts = [msg.role, msg.content]
    for call in msg.tool_calls:
        parts.append(call.name)
        parts.append(call.arguments)
    if msg.tool_call_id:
        parts.append(msg.tool_call_id)
    return "\n".join(p for p in parts if p)


def _unit_text(unit: Sequence[ChatMessage]) -> str:
    return "\n".join(_render_message_for_estimate(m) for m in unit)


def _unit_tokens(unit: Sequence[ChatMessage]) -> int:
    return _context.estimate_tokens(_unit_text(unit))


def _messages_estimated_tokens(messages: Sequence[ChatMessage]) -> int:
    return _context.estimate_tokens(_unit_text(messages))


@dataclass(frozen=True)
class CompactionPlan:
    """Pure plan for one compaction pass -- no I/O, no driver call. ``keep_head``: leading
    ``system`` messages kept verbatim. ``keep_tail``: newest atomic units that already fit
    ``budget_tokens``. ``to_summarize``: the whole atomic units in between, oldest first."""

    keep_head: list[ChatMessage]
    to_summarize: list[list[ChatMessage]]
    keep_tail: list[ChatMessage]

    @property
    def needed(self) -> bool:
        return bool(self.to_summarize)


def plan_compaction(
    messages: Sequence[ChatMessage],
    budget_tokens: int,
    *,
    keep_latest_unit: bool = True,
) -> CompactionPlan:
    """Decide what a compaction pass would summarize, without calling anything. Never splits an
    atomic unit (session-history.spec.md reqs 9-13); by default keeps at least the newest unit.
    ``keep_latest_unit=False`` is for the ranged caller when an anchor remains outside the range."""
    groups = group_atomic_units(messages)
    if not groups:
        return CompactionPlan([], [], [])

    idx = 0
    head: list[ChatMessage] = []
    while (
        idx < len(groups)
        and len(groups[idx]) == 1
        and groups[idx][0].role == "system"
        and not groups[idx][0].content.startswith(_COMPACTED_SUMMARY_PREFIX)
    ):
        head.append(groups[idx][0])
        idx += 1
    body = groups[idx:]

    if not body:
        return CompactionPlan(head, [], [])

    used = _context.estimate_tokens(_unit_text(head)) if head else 0
    kept: list[list[ChatMessage]] = []
    for pos in range(len(body) - 1, -1, -1):
        unit = body[pos]
        cost = _unit_tokens(unit)
        if used + cost > budget_tokens and (kept or not keep_latest_unit):
            break
        used += cost
        kept.append(unit)
    kept.reverse()

    boundary = len(body) - len(kept)
    to_summarize = body[:boundary]
    keep_tail = [m for unit in kept for m in unit]
    return CompactionPlan(head, to_summarize, keep_tail)


# ── compaction (I/O + driver) ──────────────────────────────────────────────────


def _summarization_message(label: str, units: Sequence[Sequence[ChatMessage]]) -> str:
    """Build the compaction summarisation prompt from the units being replaced -- a self-contained
    prompt over chat-message units, mirroring ``core.memory._distillation_message``'s shape but
    never re-reading anything from disk."""
    header = (
        f"You are compacting durable turn history for '{label}'. Below are "
        "older turns from this session, oldest first. Write a concise summary "
        "that preserves any decision, fact, or unresolved action a later turn "
        "would need -- including the outcome of any tool call, not just that "
        "one was made. Reply with the summary text only -- no preamble, no "
        "repeating the raw turns verbatim.\n"
    )

    def _render_unit(unit: Sequence[ChatMessage]) -> str:
        lines: list[str] = []
        for m in unit:
            if m.role == "tool":
                lines.append(f"[tool result for {m.name or m.tool_call_id}]\n{m.content}")
            elif m.tool_calls:
                calls = ", ".join(f"{c.name}({c.arguments})" for c in m.tool_calls)
                text = f"[assistant] {m.content}".rstrip()
                lines.append(f"{text}\n[requested tool calls] {calls}")
            else:
                lines.append(f"[{m.role}] {m.content}")
        return "\n".join(lines)

    body = "\n\n".join(_render_unit(u) for u in units)
    return f"{header}\n{body}"


def _bounded_summary_batch(
    label: str,
    units: Sequence[Sequence[ChatMessage]],
    input_budget_tokens: int,
) -> tuple[list[list[ChatMessage]], str, int]:
    """Largest oldest prefix whose complete summary prompt fits the estimate."""
    selected: list[list[ChatMessage]] = []
    prompt = ""
    estimated = 0
    for unit in units:
        candidate = [*selected, list(unit)]
        candidate_prompt = _summarization_message(label, candidate)
        candidate_estimated = _context.estimate_tokens(candidate_prompt)
        if candidate_estimated > input_budget_tokens:
            break
        selected = candidate
        prompt = candidate_prompt
        estimated = candidate_estimated
    return selected, prompt, estimated


def _is_compacted_summary_unit(unit: Sequence[ChatMessage]) -> bool:
    return (
        len(unit) == 1
        and unit[0].role == "system"
        and unit[0].content.startswith(_COMPACTED_SUMMARY_PREFIX)
    )


@dataclass
class CompactionResult:
    """Outcome of one ``compact_session`` call. ``ok=False`` means the stored history was left
    **completely untouched** (same fail-closed contract as ``core.memory.DistillResult``).
    ``compacted`` (only True alongside ``ok=True``) means summarisation actually ran."""

    ok: bool
    compacted: bool = False
    groups_summarized: int = 0
    summary_rounds: int = 0
    max_summary_prompt_estimated_tokens: int = 0
    before_message_count: int = 0
    after_message_count: int = 0
    before_estimated_tokens: int = 0
    after_estimated_tokens: int = 0
    error: str = ""
    failure_kind: FailureKind | None = None


def _validate_compaction_range(
    original_messages: Sequence[ChatMessage],
    compact_range: tuple[int, int] | None,
    keep_latest_unit: bool,
) -> tuple[int, int] | None:
    """Resolve *compact_range* (or the whole history) to ``(start_index, end_index)``, or
    ``None`` if it does not land on atomic-unit boundaries or would strip the verbatim anchor
    a ranged, non-latest-keeping caller must leave outside the range."""
    start_index, end_index = compact_range or (0, len(original_messages))
    boundaries = {0}
    cursor = 0
    for unit in group_atomic_units(original_messages):
        cursor += len(unit)
        boundaries.add(cursor)
    if (
        start_index < 0
        or end_index < start_index
        or end_index > len(original_messages)
        or start_index not in boundaries
        or end_index not in boundaries
        or (
            not keep_latest_unit
            and (
                compact_range is None or (start_index == 0 and end_index == len(original_messages))
            )
        )
    ):
        return None
    return start_index, end_index


@dataclass
class _RoundOutcome:
    """Internal result of the summarisation-round loop -- never persisted or returned to a
    ``compact_session`` caller directly; ``_plan_and_apply_compaction`` folds it into a
    ``CompactionResult``."""

    ok: bool
    working: list[ChatMessage] = field(default_factory=list)
    rounds: int = 0
    groups_summarized: int = 0
    max_prompt_estimated: int = 0
    error: str = ""
    failure_kind: FailureKind | None = None


def _run_compaction_rounds(
    working: list[ChatMessage],
    *,
    preserved_prefix: Sequence[ChatMessage],
    preserved_suffix: Sequence[ChatMessage],
    budget: int,
    keep_latest_unit: bool,
    display_label: str,
    summary_input_budget: int,
    agent_id: str,
    summary_session_key: str,
    turn_timeout: int,
    summarizer: SessionSummaryRunner,
) -> _RoundOutcome:
    """Repeatedly summarize *working*'s oldest atomic units until it fits *budget* or a round
    fails, bounded by a deterministic round cap. Never mutates *preserved_prefix*/*_suffix* --
    they are only consulted to validate each candidate's atomic-unit integrity."""
    rounds = 0
    groups_summarized = 0
    max_prompt_estimated = 0
    round_cap = max(1, len(group_atomic_units(working)) + 1)

    while True:
        plan = plan_compaction(working, budget, keep_latest_unit=keep_latest_unit)
        if not plan.needed:
            break
        if rounds and all(_is_compacted_summary_unit(unit) for unit in plan.to_summarize):
            # The target can be smaller than the irreducible summary
            # marker + mandatory newest unit (common in tiny tests). All
            # raw old units are already represented, so re-summarizing
            # the same summary alone would spend tokens without adding
            # information or guaranteeing further progress.
            break
        if rounds >= round_cap:
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error=f"compaction exceeded its deterministic round cap ({round_cap})",
                failure_kind="invalid_output",
            )

        batch, prompt, prompt_estimated = _bounded_summary_batch(
            display_label,
            plan.to_summarize,
            summary_input_budget,
        )
        if not batch:
            first_prompt = _summarization_message(display_label, plan.to_summarize[:1])
            required = _context.estimate_tokens(first_prompt)
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error=(
                    "one compaction atomic unit exceeds the summary input budget "
                    f"(estimated {required} tokens > {summary_input_budget})"
                ),
                failure_kind="invalid_output",
            )

        max_prompt_estimated = max(max_prompt_estimated, prompt_estimated)
        result = summarizer(agent_id, summary_session_key, prompt, turn_timeout, None)
        if not result.ok:
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error=result.error or "compaction summarisation turn failed",
                failure_kind=result.failure_kind or "daemon_error",
            )

        summary = result.output.strip()
        if not summary:
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error="compaction summarisation turn returned an empty summary",
                failure_kind="invalid_output",
            )

        summarized_count = sum(len(unit) for unit in batch)
        summary_message = ChatMessage(
            role="system",
            content=(
                f"{_COMPACTED_SUMMARY_PREFIX}{len(batch)} earlier turn(s), "
                f"{summarized_count} message(s)]\n{summary}"
            ),
        )
        remaining_old = [message for unit in plan.to_summarize[len(batch) :] for message in unit]
        candidate = [*plan.keep_head, summary_message, *remaining_old, *plan.keep_tail]
        full_candidate = [*preserved_prefix, *candidate, *preserved_suffix]

        if find_orphaned_tool_messages(full_candidate) or find_unanswered_tool_calls(
            full_candidate
        ):
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error="compaction produced an orphaned tool call or result -- refusing to persist",
                failure_kind="invalid_output",
            )

        current_full = [*preserved_prefix, *working, *preserved_suffix]
        current_estimated = _messages_estimated_tokens(current_full)
        candidate_estimated = _messages_estimated_tokens(full_candidate)
        if candidate_estimated >= current_estimated:
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error=(
                    "compaction summary did not reduce estimated history size "
                    f"({current_estimated} -> {candidate_estimated})"
                ),
                failure_kind="invalid_output",
            )

        working = candidate
        rounds += 1
        groups_summarized += len(batch)

    return _RoundOutcome(
        ok=True,
        working=working,
        rounds=rounds,
        groups_summarized=groups_summarized,
        max_prompt_estimated=max_prompt_estimated,
    )


def _plan_and_apply_compaction(
    current: dict[str, Any],
    *,
    session_key: str,
    stamp: str,
    compact_range: tuple[int, int] | None,
    keep_latest_unit: bool,
    budget: int,
    summary_input_budget: int,
    turn_timeout: int,
    display_label: str,
    agent_id: str,
    summary_session_key: str,
    summarizer: SessionSummaryRunner,
) -> tuple[dict[str, Any] | None, CompactionResult]:
    """The whole read-modify-write body: decode, validate the range, run the summarisation
    rounds, then build the payload to persist or a fail-closed ``CompactionResult``. ``payload``
    is ``None`` whenever nothing should be written (no compaction needed, or any failure)."""
    record = (
        SessionRecord.model_validate(current)
        if current
        else SessionRecord(session_key=session_key, created=stamp)
    )
    original_messages = [_decode(m) for m in record.messages]
    before_count = len(original_messages)
    before_estimated = _messages_estimated_tokens(original_messages)

    range_bounds = _validate_compaction_range(original_messages, compact_range, keep_latest_unit)
    if range_bounds is None:
        return None, CompactionResult(
            ok=False,
            before_message_count=before_count,
            after_message_count=before_count,
            before_estimated_tokens=before_estimated,
            after_estimated_tokens=before_estimated,
            error="compaction range must be atomic and leave a verbatim message anchor",
            failure_kind="invalid_output",
        )
    start_index, end_index = range_bounds
    preserved_prefix = original_messages[:start_index]
    preserved_suffix = original_messages[end_index:]
    working = original_messages[start_index:end_index]

    initial_plan = plan_compaction(working, budget, keep_latest_unit=keep_latest_unit)
    if not initial_plan.needed:
        return None, CompactionResult(
            ok=True,
            compacted=False,
            before_message_count=before_count,
            after_message_count=before_count,
            before_estimated_tokens=before_estimated,
            after_estimated_tokens=before_estimated,
        )

    round_result = _run_compaction_rounds(
        working,
        preserved_prefix=preserved_prefix,
        preserved_suffix=preserved_suffix,
        budget=budget,
        keep_latest_unit=keep_latest_unit,
        display_label=display_label,
        summary_input_budget=summary_input_budget,
        agent_id=agent_id,
        summary_session_key=summary_session_key,
        turn_timeout=turn_timeout,
        summarizer=summarizer,
    )
    if not round_result.ok:
        return None, CompactionResult(
            ok=False,
            groups_summarized=round_result.groups_summarized,
            summary_rounds=round_result.rounds,
            max_summary_prompt_estimated_tokens=round_result.max_prompt_estimated,
            before_message_count=before_count,
            after_message_count=before_count,
            before_estimated_tokens=before_estimated,
            after_estimated_tokens=before_estimated,
            error=round_result.error,
            failure_kind=round_result.failure_kind,
        )

    final_messages = [*preserved_prefix, *round_result.working, *preserved_suffix]
    updated = record.model_copy(
        update={
            "session_key": session_key,
            "messages": [_encode(m) for m in final_messages],
            "updated": stamp,
        }
    )
    result = CompactionResult(
        ok=True,
        compacted=True,
        groups_summarized=round_result.groups_summarized,
        summary_rounds=round_result.rounds,
        max_summary_prompt_estimated_tokens=round_result.max_prompt_estimated,
        before_message_count=before_count,
        after_message_count=len(final_messages),
        before_estimated_tokens=before_estimated,
        after_estimated_tokens=_messages_estimated_tokens(final_messages),
    )
    return updated.model_dump(by_alias=True), result


def compact_session(
    session_key: str,
    *,
    role: str,
    agent_id: str,
    summarizer: SessionSummaryRunner,
    summarizer_session_key: str | None = None,
    budget_tokens: int | None = None,
    summary_input_budget_tokens: int | None = None,
    compact_range: tuple[int, int] | None = None,
    keep_latest_unit: bool = True,
    timeout: int | None = None,
    label: str = "",
    now: str | None = None,
    sessions_dir: Path | None = None,
) -> CompactionResult:
    """Compact *session_key*'s history in place if over budget (locking/range/nesting rules:
    session-history.spec.md). Fail-closed: any summarisation failure, or an orphaned tool
    call/result, leaves the record unchanged and returns ``ok=False`` -- never a partial write."""
    summary_session_key = summarizer_session_key or f"{session_key}:compaction"
    if summary_session_key == session_key:
        return CompactionResult(
            ok=False,
            error="compaction summarizer session key must differ from the target session key",
            failure_kind="invalid_output",
        )
    if _COMPACTION_ACTIVE.get():
        return CompactionResult(
            ok=False,
            error="nested session compaction is not allowed",
            failure_kind="invalid_output",
        )

    role_budget = _context.budget_for_role(role)
    budget = budget_tokens if budget_tokens is not None else role_budget
    summary_input_budget = (
        summary_input_budget_tokens if summary_input_budget_tokens is not None else role_budget
    )
    turn_timeout = timeout if timeout is not None else _cfg.DISTILL_TIMEOUT_S
    stamp = now or _utc_now()
    display_label = label or session_key
    path = _session_path(session_key, sessions_dir)
    _ensure_session_dir(path)

    outcome = CompactionResult(ok=True, compacted=False)

    def _mutate(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal outcome
        payload, outcome = _plan_and_apply_compaction(
            current,
            session_key=session_key,
            stamp=stamp,
            compact_range=compact_range,
            keep_latest_unit=keep_latest_unit,
            budget=budget,
            summary_input_budget=summary_input_budget,
            turn_timeout=turn_timeout,
            display_label=display_label,
            agent_id=agent_id,
            summary_session_key=summary_session_key,
            summarizer=summarizer,
        )
        return payload

    guard_token = _COMPACTION_ACTIVE.set(True)
    try:
        _store.read_modify_write(path, _mutate)
    finally:
        _COMPACTION_ACTIVE.reset(guard_token)
    return outcome
