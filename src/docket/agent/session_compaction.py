from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docket.agent import context as _context
from docket.agent.llm import ChatMessage
from docket.agent.ports import FailureKind
from docket.agent.session import (
    SessionRecord,
    SessionSummaryRunner,
    _decode,
    _encode,
    _ensure_session_dir,
    _session_path,
)
from docket.agent.session_units import (
    _COMPACTED_SUMMARY_PREFIX,
    _messages_estimated_tokens,
    find_orphaned_tool_messages,
    find_unanswered_tool_calls,
    group_atomic_units,
    plan_compaction,
)
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.platform import store as _store

_COMPACTION_ACTIVE: ContextVar[bool] = ContextVar("docket_session_compaction_active", default=False)


# ── compaction (I/O + driver) ──────────────────────────────────────────────────


def _summarization_message(label: str, units: Sequence[Sequence[ChatMessage]]) -> str:
    """Build the compaction summarisation prompt from the units being replaced -- a self-contained
    prompt over chat-message units, mirroring ``agent.memory._distillation_message``'s shape but
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
    **completely untouched** (same fail-closed contract as ``agent.memory.DistillResult``).
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
    project: str = "",
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

    role_budget = _context.budget_for_role(role, project=project)
    budget = budget_tokens if budget_tokens is not None else role_budget
    summary_input_budget = (
        summary_input_budget_tokens if summary_input_budget_tokens is not None else role_budget
    )
    turn_timeout = timeout if timeout is not None else current_home().distill_timeout_s
    stamp = now or _clock.stamp()
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
