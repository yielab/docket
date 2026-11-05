from __future__ import annotations

from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

from docket.agent import ports as _ports
from docket.agent.ports import ChatMessage, FailureKind
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
from docket.platform import mkdir_private, read_modify_write, write_json

_COMPACTION_ACTIVE: ContextVar[bool] = ContextVar("docket_session_compaction_active", default=False)

_COMPACTIONS_DIRNAME = "compactions"


# ── compaction (I/O + driver) ──────────────────────────────────────────────────


_NOT_SHOWN_MARKER = "[... {n} characters of this tool result not shown to the summarizer ...]"


def _render_unit(unit: Sequence[ChatMessage], tool_result_cap: int | None = None) -> str:
    """One atomic unit as the summarizer reads it. With *tool_result_cap*, each tool result is
    cut to it and followed by the visible marker."""
    lines: list[str] = []
    for m in unit:
        if m.role == "tool":
            content = m.content
            if tool_result_cap is not None and len(content) > tool_result_cap:
                marker = _NOT_SHOWN_MARKER.format(n=len(content) - tool_result_cap)
                content = f"{content[:tool_result_cap]}\n{marker}"
            lines.append(f"[tool result for {m.name or m.tool_call_id}]\n{content}")
        elif m.tool_calls:
            calls = ", ".join(f"{c.name}({c.arguments})" for c in m.tool_calls)
            text = f"[assistant] {m.content}".rstrip()
            lines.append(f"{text}\n[requested tool calls] {calls}")
        else:
            lines.append(f"[{m.role}] {m.content}")
    return "\n".join(lines)


def _summarization_message(
    prompt_text: str,
    label: str,
    units: Sequence[Sequence[ChatMessage]],
    tool_result_cap: int | None = None,
) -> str:
    """The summarizer prompt: the caller's resolved *prompt_text* with ``${label}`` and ``${turns}``
    (the *units* being replaced, oldest first) substituted. Nothing is read from disk."""
    turns = "\n\n".join(_render_unit(u, tool_result_cap) for u in units)
    return Template(prompt_text).safe_substitute(label=label, turns=turns)


def _is_compacted_summary_unit(unit: Sequence[ChatMessage]) -> bool:
    return (
        len(unit) == 1
        and unit[0].role == "user"
        and unit[0].content.startswith(_COMPACTED_SUMMARY_PREFIX)
    )


def _projected_prompt(
    prompt_text: str,
    label: str,
    summaries: Sequence[Sequence[ChatMessage]],
    unit: Sequence[ChatMessage],
    input_budget_tokens: int,
) -> tuple[str, int] | None:
    """Prompt for *unit* with each tool result cut to the largest share that still fits, or
    ``None`` when even cutting every tool result to nothing does not fit."""
    batch = [*summaries, list(unit)]

    def _fits(cap: int) -> tuple[str, int] | None:
        prompt = _summarization_message(prompt_text, label, batch, tool_result_cap=cap)
        estimated = _ports.estimate_tokens(prompt)
        return (prompt, estimated) if estimated <= input_budget_tokens else None

    low, high = 0, max((len(m.content) for m in unit if m.role == "tool"), default=0)
    best = _fits(low)
    if best is None:
        return None
    while low < high:
        mid = (low + high + 1) // 2
        fitted = _fits(mid)
        if fitted is None:
            high = mid - 1
        else:
            low, best = mid, fitted
    return best


def _bounded_summary_batch(
    prompt_text: str,
    label: str,
    units: Sequence[Sequence[ChatMessage]],
    input_budget_tokens: int,
) -> tuple[list[list[ChatMessage]], str, int]:
    """Largest oldest prefix whose complete summary prompt fits the estimate. A batch holds at
    least one raw unit: when the first raw unit does not fit behind the summaries, it is
    projected; a batch of summaries alone is returned empty."""
    selected: list[list[ChatMessage]] = []
    prompt = ""
    estimated = 0
    for unit in units:
        candidate = [*selected, list(unit)]
        candidate_prompt = _summarization_message(prompt_text, label, candidate)
        candidate_estimated = _ports.estimate_tokens(candidate_prompt)
        if candidate_estimated <= input_budget_tokens:
            selected, prompt, estimated = candidate, candidate_prompt, candidate_estimated
            continue
        if not _is_compacted_summary_unit(unit) and all(
            _is_compacted_summary_unit(u) for u in selected
        ):
            projected = _projected_prompt(prompt_text, label, selected, unit, input_budget_tokens)
            if projected is not None:
                selected, (prompt, estimated) = candidate, projected
        break
    if all(_is_compacted_summary_unit(u) for u in selected):
        return [], "", 0
    return selected, prompt, estimated


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
    #: Hash of the prompt text the summarisation rounds were built from; ``""`` when none ran.
    prompt_sha256: str = ""
    #: The compaction record, relative to the session directory; ``""`` when none was written.
    record: str = ""
    #: ``(start, end)`` of the replaced messages in the history before the call; ``None`` when none.
    summarized_range: tuple[int, int] | None = None
    before_message_count: int = 0
    after_message_count: int = 0
    before_estimated_tokens: int = 0
    after_estimated_tokens: int = 0
    error: str = ""
    failure_kind: FailureKind | None = None
    refused_by_guard: bool = False


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
    #: The input messages the summaries replaced, oldest first, and where the first one stood
    #: in *working* (the head the plan keeps comes before it).
    replaced: list[ChatMessage] = field(default_factory=list)
    replaced_offset: int = 0
    summary: str = ""
    rounds: int = 0
    groups_summarized: int = 0
    max_prompt_estimated: int = 0
    error: str = ""
    failure_kind: FailureKind | None = None
    refused_by_guard: bool = False


def _untouched(
    before_count: int,
    before_estimated: int,
    *,
    ok: bool,
    rounds: _RoundOutcome | None = None,
    prompt_sha256: str = "",
    error: str = "",
    failure_kind: FailureKind | None = None,
) -> CompactionResult:
    """A result whose history is as it was: a no-op (``ok``) or a fail-closed refusal, with the
    figures of the *rounds* that ran before it, when any did."""
    return CompactionResult(
        ok=ok,
        groups_summarized=rounds.groups_summarized if rounds else 0,
        summary_rounds=rounds.rounds if rounds else 0,
        max_summary_prompt_estimated_tokens=rounds.max_prompt_estimated if rounds else 0,
        prompt_sha256=prompt_sha256,
        before_message_count=before_count,
        after_message_count=before_count,
        before_estimated_tokens=before_estimated,
        after_estimated_tokens=before_estimated,
        error=error,
        failure_kind=failure_kind,
        refused_by_guard=rounds.refused_by_guard if rounds else False,
    )


def _candidate_refusal(
    candidate: Sequence[ChatMessage], current: Sequence[ChatMessage]
) -> tuple[str, bool] | None:
    """Why *candidate* must not replace *current*, as ``(error, refused_by_guard)``, or ``None``:
    it would orphan a tool call or result, or it is not smaller."""
    if find_orphaned_tool_messages(candidate) or find_unanswered_tool_calls(candidate):
        return "compaction produced an orphaned tool call or result -- refusing to persist", False
    current_estimated = _messages_estimated_tokens(current)
    candidate_estimated = _messages_estimated_tokens(candidate)
    if candidate_estimated >= current_estimated:
        return (
            "compaction summary did not reduce estimated history size "
            f"({current_estimated} -> {candidate_estimated})",
            True,
        )
    return None


def _run_compaction_rounds(
    working: list[ChatMessage],
    *,
    preserved_prefix: Sequence[ChatMessage],
    preserved_suffix: Sequence[ChatMessage],
    budget: int,
    keep_latest_unit: bool,
    prompt_text: str,
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
    replaced: list[ChatMessage] = []
    produced: list[ChatMessage] = []
    replaced_offset = 0

    while True:
        plan = plan_compaction(working, budget, keep_latest_unit=keep_latest_unit)
        if not plan.needed:
            break
        if all(_is_compacted_summary_unit(unit) for unit in plan.to_summarize):
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
                refused_by_guard=True,
            )

        batch, prompt, prompt_estimated = _bounded_summary_batch(
            prompt_text,
            display_label,
            plan.to_summarize,
            summary_input_budget,
        )
        if not batch:
            blocking = next(
                (u for u in plan.to_summarize if not _is_compacted_summary_unit(u)),
                plan.to_summarize[0],
            )
            required = _ports.estimate_tokens(
                _summarization_message(prompt_text, display_label, [blocking], tool_result_cap=0)
            )
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error=(
                    "one compaction atomic unit exceeds the summary input budget "
                    f"even with its tool results cut (estimated {required} tokens > "
                    f"{summary_input_budget})"
                ),
                failure_kind="invalid_output",
                refused_by_guard=True,
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
            role="user",
            content=(
                f"{_COMPACTED_SUMMARY_PREFIX}{len(batch)} earlier turn(s), "
                f"{summarized_count} message(s)]\n{summary}"
            ),
        )
        remaining_old = [message for unit in plan.to_summarize[len(batch) :] for message in unit]
        candidate = [*plan.keep_head, summary_message, *remaining_old, *plan.keep_tail]
        full_candidate = [*preserved_prefix, *candidate, *preserved_suffix]

        refusal = _candidate_refusal(
            full_candidate, [*preserved_prefix, *working, *preserved_suffix]
        )
        if refusal is not None:
            return _RoundOutcome(
                ok=False,
                rounds=rounds,
                groups_summarized=groups_summarized,
                max_prompt_estimated=max_prompt_estimated,
                error=refusal[0],
                failure_kind="invalid_output",
                refused_by_guard=refusal[1],
            )

        if not produced:
            replaced_offset = len(plan.keep_head)
        replaced += [m for unit in batch for m in unit if all(m is not p for p in produced)]
        produced.append(summary_message)
        working = candidate
        rounds += 1
        groups_summarized += len(batch)

    return _RoundOutcome(
        ok=True,
        working=working,
        replaced=replaced,
        replaced_offset=replaced_offset,
        summary=produced[-1].content if produced else "",
        rounds=rounds,
        groups_summarized=groups_summarized,
        max_prompt_estimated=max_prompt_estimated,
    )


def _write_compaction_record(
    session_dir: Path,
    *,
    session_key: str,
    stamp: str,
    span: tuple[int, int],
    replaced: Sequence[ChatMessage],
    summary: str,
    prompt_sha256: str,
) -> str:
    """Write the next ``compactions/<seq>.json`` of *session_dir* and return its path relative to
    it. ``seq`` is the count of records present plus one; the caller holds the session lock."""
    directory = session_dir / _COMPACTIONS_DIRNAME
    mkdir_private(directory)
    seq = 1 + sum(1 for entry in directory.glob("*.json") if entry.stem.isdigit())
    relative = f"{_COMPACTIONS_DIRNAME}/{seq}.json"
    write_json(
        session_dir / relative,
        {
            "sessionKey": session_key,
            "at": stamp,
            "range": list(span),
            "replaced": [_encode(m).model_dump(by_alias=True) for m in replaced],
            "summary": summary,
            "promptSha256": prompt_sha256,
        },
    )
    return relative


def _plan_and_apply_compaction(
    current: dict[str, Any],
    *,
    session_dir: Path,
    session_key: str,
    stamp: str,
    compact_range: tuple[int, int] | None,
    keep_latest_unit: bool,
    budget: int,
    summary_input_budget: int,
    turn_timeout: int,
    prompt_text: str,
    prompt_sha256: str,
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
        return None, _untouched(
            before_count,
            before_estimated,
            ok=False,
            error="compaction range must be atomic and leave a verbatim message anchor",
            failure_kind="invalid_output",
        )
    start_index, end_index = range_bounds
    preserved_prefix = original_messages[:start_index]
    preserved_suffix = original_messages[end_index:]
    working = original_messages[start_index:end_index]

    initial_plan = plan_compaction(working, budget, keep_latest_unit=keep_latest_unit)
    if not initial_plan.needed:
        return None, _untouched(before_count, before_estimated, ok=True)

    round_result = _run_compaction_rounds(
        working,
        preserved_prefix=preserved_prefix,
        preserved_suffix=preserved_suffix,
        budget=budget,
        keep_latest_unit=keep_latest_unit,
        prompt_text=prompt_text,
        display_label=display_label,
        summary_input_budget=summary_input_budget,
        agent_id=agent_id,
        summary_session_key=summary_session_key,
        turn_timeout=turn_timeout,
        summarizer=summarizer,
    )
    if not round_result.ok:
        return None, _untouched(
            before_count,
            before_estimated,
            ok=False,
            rounds=round_result,
            prompt_sha256=prompt_sha256,
            error=round_result.error,
            failure_kind=round_result.failure_kind,
        )

    span: tuple[int, int] | None = None
    record_path = ""
    if round_result.replaced:
        first = start_index + round_result.replaced_offset
        span = (first, first + len(round_result.replaced))
        try:
            record_path = _write_compaction_record(
                session_dir,
                session_key=session_key,
                stamp=stamp,
                span=span,
                replaced=round_result.replaced,
                summary=round_result.summary,
                prompt_sha256=prompt_sha256,
            )
        except (OSError, RuntimeError) as exc:
            return None, _untouched(
                before_count,
                before_estimated,
                ok=False,
                rounds=round_result,
                prompt_sha256=prompt_sha256,
                error=f"could not write the compaction record: {exc}",
                failure_kind="daemon_error",
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
        prompt_sha256=prompt_sha256,
        record=record_path,
        summarized_range=span,
        before_message_count=before_count,
        after_message_count=len(final_messages),
        before_estimated_tokens=before_estimated,
        after_estimated_tokens=_messages_estimated_tokens(final_messages),
    )
    return updated.model_dump(by_alias=True), result


def compact_session(
    session_key: str,
    *,
    agent_id: str,
    summarizer: SessionSummaryRunner,
    prompt_text: str,
    prompt_sha256: str,
    budget_tokens: int,
    summary_input_budget_tokens: int,
    summarizer_session_key: str | None = None,
    compact_range: tuple[int, int] | None = None,
    keep_latest_unit: bool = True,
    timeout: int | None = None,
    label: str = "",
    now: str | None = None,
    sessions_dir: Path | None = None,
) -> CompactionResult:
    """Compact *session_key*'s history in place to *budget_tokens* (``0`` on a range: the whole
    range), each summarizer prompt within *summary_input_budget_tokens* (session-history.spec.md).
    Fail-closed: any failure leaves the record unchanged and returns ``ok=False``."""
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
    if "turns" not in Template(prompt_text).get_identifiers():
        return CompactionResult(
            ok=False,
            error="compaction prompt does not place ${turns}; nothing would be summarized",
            failure_kind="invalid_output",
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
            session_dir=path.parent,
            session_key=session_key,
            stamp=stamp,
            compact_range=compact_range,
            keep_latest_unit=keep_latest_unit,
            budget=budget_tokens,
            summary_input_budget=summary_input_budget_tokens,
            turn_timeout=turn_timeout,
            prompt_text=prompt_text,
            prompt_sha256=prompt_sha256,
            display_label=display_label,
            agent_id=agent_id,
            summary_session_key=summary_session_key,
            summarizer=summarizer,
        )
        return payload

    guard_token = _COMPACTION_ACTIVE.set(True)
    try:
        read_modify_write(path, _mutate)
    finally:
        _COMPACTION_ACTIVE.reset(guard_token)
    return outcome
