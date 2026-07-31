"""Durable turn history + compaction (ROADMAP Phase 19 P19-4 / decision D-19).

docket already owns the durable state that survives *between* turns: the
``HEARTBEAT.md`` task ledger (``core/memory.py``), the conversation registry
(``core/conversations.py``), memory logs, traces. What it has never owned is
the message history *inside* a turn, because the OpenClaw daemon owned the
loop. Phase 19 takes the loop back (P19-5); this module is the durable store
that loop replays on every model call, keyed on docket's existing session
coordinate (``agent:<id>:<project>``, see ``specs/functional/session-scoping.spec.md``).

**Not yet wired to a live path.** Like ``core/llm.py`` (P19-1) and
``core/tools.py`` (P19-2) before it, this module ships fully tested and
unused until ``core/agent_loop.py`` (P19-5) exists to call it — there is no
speculative API surface here beyond what that loop demonstrably needs: load a
session's history, append new turns to it, and compact it when it grows past
budget.

## Storage layout

One JSON file per session key, each in its *own* subdirectory:

    $SESSIONS_DIR/<percent-encoded session key>/session.json

Percent-encoding (``urllib.parse.quote``, ``safe=""``) is a deterministic,
collision-free map from an arbitrary session-key string (``agent:<id>:<project>``
today, but this module treats it as an opaque string) to a filesystem-safe
name — two distinct keys can never collide onto the same file. Giving each
session its **own** subdirectory (rather than one shared registry file, the
shape ``core/conversations.py``/``core/runs.py`` use for their much smaller
records) matters for two reasons docket has stated as hard requirements:

1. **Isolation.** ``edges/store.py``'s filelock is scoped per *directory*
   (``_lock_path`` = ``target.parent / ".docket.lock"``). Sessions sharing one
   directory would serialize their writes against each other for no reason;
   giving each session its own directory means one session's write — even a
   slow one, like the compaction summarisation call below, held under lock —
   can never block another session's.
2. **Blast radius.** A read-modify-write mistake or an on-disk corruption is
   scoped to the one file whose lock is being held. A shared registry (as
   ``core/conversations.py`` uses) would put every session's history behind
   one lock and one JSON blob, so a validation failure on load would either
   wipe every session's data (matching ``load()``'s fail-open-to-empty
   convention elsewhere in this codebase) or need a more complex per-key
   partial-recovery scheme this card has no evidence it needs yet.

All reads/writes of the per-session JSON go through ``edges/store.py`` (D-12's
single-writer chokepoint) — this module never opens the file itself.

## Round-trip serialisation

``StoredMessage``/``StoredToolCall`` mirror ``core.llm.ChatMessage``/
``ToolCall`` field-for-field (camelCase aliases on the wire, matching every
other docket-owned JSON shape). ``tool_calls``, ``tool_call_id`` and ``name``
all round-trip losslessly — ``edges/adapters/llm.py``'s ``_encode_message`` is
the wire contract this exists to satisfy: a history that has lost a
``tool_call_id`` produces a request every OpenAI-compatible endpoint rejects.

## Compaction: the atomic tool-call/tool-result unit

An assistant message that requests ``tool_calls`` and the ``tool``-role
messages answering each one are **one atomic unit** — split them, and the
next request either carries a ``tool_call_id`` with no preceding call, or a
call with no result, and every endpoint rejects it outright. ``compact_session``
never drops or summarises part of a group: ``group_atomic_units`` partitions
history into whole units first, and every later stage (``plan_compaction``,
the driver-backed summarisation) operates on whole units only — a unit is
either entirely kept or entirely folded into the summary, by construction,
never split. ``find_orphaned_tool_messages``/``find_unanswered_tool_calls`` are
the explicit post-condition checks ``compact_session`` runs on its own output
before ever persisting it, so a bug in the grouping logic fails the
compaction (nothing written) rather than silently writing a broken history.

## Budgeting honesty

Two numbers live on a session and must never be conflated:

- **Estimated** — ``core.context.estimate_tokens``'s existing bytes/divisor
  approximation (``config.CONTEXT_BYTES_PER_TOKEN``), reused here rather than
  a second, independently-tunable estimator. This is what ``plan_compaction``
  measures against a budget to decide *whether* to compact. It is an honest
  approximation, never billed against, never claimed as an exact count.
- **Measured** — ``core.llm.TokenUsage``, real counts reported by the
  completion endpoint. ``MeasuredUsage`` accumulates these on a
  ``SessionRecord`` across every appended turn. This is docket's first
  non-estimated token number (P19-1) and retires the daemon's session JSONL
  as the source of usage data — but it plays **no role** in compaction's
  budget math, which stays on the estimate. Do not let the two merge into one
  field or one docstring claim.

The compaction budget itself is resolved via ``core.context.budget_for_role``
— the same per-role token-budget compiler ROADMAP Phase 17 C-1 built for
hop-to-hop handoff artifacts — rather than a second, parallel per-role budget
table. Session compaction does not reuse ``compile_artifact``/``DROP_ORDER``
directly: those shed a single ``HandoffArtifact``'s *fields*, a shape that
does not apply to a list of chat messages. The analogous "shed the
cheapest content first" idea for a message history is summarisation (below),
which serves the same purpose for a different data shape.

## Fail-closed summarisation (decision D-18)

Compacting away old units never bare-deletes them: the units being replaced
are summarised in one call through the injected ``SessionSummaryRunner`` —
the same ``RuntimeDriver.run_turn`` call shape ``core/memory.py``'s
``distill_memory`` already uses for docket's first self-originated LLM call.
Per D-18 this is never a hand-rolled per-vendor client. If that call fails, or
replies with nothing usable, ``compact_session`` leaves the session's stored
history **completely unchanged** and reports ``ok=False`` — the same
fail-closed contract ``distill_memory``'s ``DistillResult`` gives
``maintain clean``/``reset --distill-first``. Losing an agent's context to a
summariser error is exactly the durability failure this phase exists to
prevent, so a failed compaction is a no-op, never a silent truncation.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


# ── storage models ────────────────────────────────────────────────────────────


class StoredToolCall(BaseModel):
    """Wire/storage twin of ``core.llm.ToolCall`` -- same three fields, no more."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    arguments: str = "{}"


class StoredMessage(BaseModel):
    """Wire/storage twin of ``core.llm.ChatMessage``.

    Field-for-field with the in-memory type so ``_encode``/``_decode`` are
    the only translation this module needs -- see the module docstring's
    round-trip contract.
    """

    model_config = ConfigDict(populate_by_name=True)

    role: Role
    content: str = ""
    tool_calls: list[StoredToolCall] = Field(default_factory=list, alias="toolCalls")
    tool_call_id: str = Field("", alias="toolCallId")
    name: str = ""


class MeasuredUsage(BaseModel):
    """Cumulative token counts **measured** by the completion endpoint across a
    session's turns (``core.llm.TokenUsage``, real per-call counts).

    Never to be confused with ``core.context.estimate_tokens``'s bytes/divisor
    *approximation*, which ``plan_compaction`` uses to decide when to act --
    see the module docstring's "Budgeting honesty" section. This is purely a
    running total for display/reporting; it is never read by compaction.
    """

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
    """Load *session_key*'s durable record, or a fresh empty one if absent.

    A corrupt/unparseable file degrades to a fresh empty record for *this
    session only* -- the per-session storage layout (see module docstring)
    means that never touches any other session's file. ``edges/store.py``'s
    ``write_json`` keeps a ``.bak`` of the previous write, so a corrupt
    current file is not the only copy on disk, even though this function
    does not attempt automatic recovery from it (out of scope for this card).
    """
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
    """Atomically append *messages* (and optional measured *usage*) to
    *session_key*'s durable history, creating the session if it doesn't exist.

    Goes through ``edges/store.py``'s ``read_modify_write`` -- the whole
    read-append-write is one locked operation, so two concurrent appends to
    the *same* session key can never interleave and drop one's messages.
    """
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
    """Partition *messages* into the atomic units compaction must never split.

    An assistant message carrying ``tool_calls`` and every contiguous
    ``tool``-role message answering one of those calls (matched by
    ``tool_call_id``) form one group. Every other message is its own
    single-message group. A tool-call id that is never answered inside
    *messages* still closes its group at the point the matching results run
    out -- this function only ever *groups* what is there; it does not
    invent or require an answer to exist (``find_unanswered_tool_calls``
    checks that separately).
    """
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
    """Indices of ``tool``-role messages whose ``tool_call_id`` answers no
    still-open, preceding assistant ``tool_calls`` entry.

    The post-condition half of the atomicity guarantee: run on
    ``compact_session``'s own candidate output before it is ever persisted.
    """
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


@dataclass(frozen=True)
class CompactionPlan:
    """Pure plan for one compaction pass -- no I/O, no driver call.

    ``keep_head``: leading messages preserved verbatim (any run of leading
    ``system``-role messages). ``keep_tail``: the most-recent atomic units
    that already fit ``budget_tokens``, flattened back into a plain message
    list. ``to_summarize``: the atomic units in between, oldest first --
    always whole units, never a partial one.
    """

    keep_head: list[ChatMessage]
    to_summarize: list[list[ChatMessage]]
    keep_tail: list[ChatMessage]

    @property
    def needed(self) -> bool:
        return bool(self.to_summarize)


def plan_compaction(messages: Sequence[ChatMessage], budget_tokens: int) -> CompactionPlan:
    """Decide what a compaction pass would summarize, without calling anything.

    Never splits a tool-call/tool-result atomic unit (``group_atomic_units``
    produces whole units; this function only ever assigns a whole unit to
    ``keep_tail`` or ``to_summarize``, never both). Leading ``system``
    messages are always kept and are counted against the same budget, so the
    plan cannot claim to fit while quietly excluding them from the count.
    Units are walked newest-first and kept while they still fit; **at least
    the single most recent unit is always kept**, even if it alone exceeds
    ``budget_tokens`` -- there must always be something to answer with, and a
    compactor cannot shrink one message below itself.
    """
    groups = group_atomic_units(messages)
    if not groups:
        return CompactionPlan([], [], [])

    idx = 0
    head: list[ChatMessage] = []
    while idx < len(groups) and len(groups[idx]) == 1 and groups[idx][0].role == "system":
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
        if kept and used + cost > budget_tokens:
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
    """Build the compaction summarisation prompt from the units being replaced.

    Mirrors ``core.memory._distillation_message``'s shape (a self-contained
    prompt built from the caller's own data, not a re-read of anything from
    disk) but over chat-message units instead of daily log files.
    """
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


@dataclass
class CompactionResult:
    """Outcome of one ``compact_session`` call.

    ``ok=False`` means the session's stored history was left **completely
    untouched** -- the same fail-closed contract ``core.memory.DistillResult``
    gives ``maintain clean``/``reset`` (ROADMAP Phase 17 C-2). ``compacted``
    (only ever True alongside ``ok=True``) distinguishes "nothing needed
    compacting" from "compaction ran".
    """

    ok: bool
    compacted: bool = False
    groups_summarized: int = 0
    error: str = ""
    failure_kind: FailureKind | None = None


def compact_session(
    session_key: str,
    *,
    role: str,
    agent_id: str,
    summarizer: SessionSummaryRunner,
    budget_tokens: int | None = None,
    timeout: int | None = None,
    label: str = "",
    now: str | None = None,
    sessions_dir: Path | None = None,
) -> CompactionResult:
    """Compact *session_key*'s stored history in place, if it is over budget.

    ``budget_tokens`` defaults to ``core.context.budget_for_role(role)`` --
    the same per-role token-budget compiler C-1 built for hop-to-hop handoff
    artifacts, reused here rather than a second table (see module docstring).
    Nothing needing compaction is a no-op: ``ok=True, compacted=False``, no
    driver call made.

    The whole operation (load, plan, driver call, write) runs inside one
    ``edges/store.py`` locked read-modify-write on this session's own file, so
    a concurrent ``append_messages`` for the *same* session key can never
    interleave with it and get silently discarded; a different session's file
    is never touched, let alone blocked (see module docstring's storage
    layout section).

    Fails closed (ROADMAP Phase 17 C-2 / decision D-18): if the summarisation
    call fails, or replies with nothing usable, or the candidate compacted
    history would contain an orphaned tool call/result (``find_orphaned_tool_messages``/
    ``find_unanswered_tool_calls`` -- should be structurally impossible given
    ``plan_compaction``'s whole-unit guarantee, checked anyway as the explicit
    post-condition this card calls for), nothing is written and
    ``CompactionResult.ok`` is False.
    """
    budget = budget_tokens if budget_tokens is not None else _context.budget_for_role(role)
    turn_timeout = timeout if timeout is not None else _cfg.DISTILL_TIMEOUT_S
    stamp = now or _utc_now()
    display_label = label or session_key
    path = _session_path(session_key, sessions_dir)
    _ensure_session_dir(path)

    outcome = CompactionResult(ok=True, compacted=False)

    def _mutate(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal outcome
        record = (
            SessionRecord.model_validate(current)
            if current
            else SessionRecord(session_key=session_key, created=stamp)
        )
        messages = [_decode(m) for m in record.messages]
        plan = plan_compaction(messages, budget)
        if not plan.needed:
            outcome = CompactionResult(ok=True, compacted=False)
            return None

        prompt = _summarization_message(display_label, plan.to_summarize)
        result = summarizer(agent_id, session_key, prompt, turn_timeout, None)
        if not result.ok:
            outcome = CompactionResult(
                ok=False,
                error=result.error or "compaction summarisation turn failed",
                failure_kind=result.failure_kind,
            )
            return None

        summary = result.output.strip()
        if not summary:
            outcome = CompactionResult(
                ok=False,
                error="compaction summarisation turn returned an empty summary",
                failure_kind="invalid_output",
            )
            return None

        summarized_count = sum(len(u) for u in plan.to_summarize)
        summary_message = ChatMessage(
            role="system",
            content=(
                f"[compacted summary of {len(plan.to_summarize)} earlier turn(s), "
                f"{summarized_count} message(s)]\n{summary}"
            ),
        )
        new_messages = [*plan.keep_head, summary_message, *plan.keep_tail]

        # Post-condition checks (see module docstring): should be structurally
        # impossible given plan_compaction's whole-unit guarantee, verified
        # here so a bug in the grouping logic fails the compaction instead of
        # ever persisting a broken history.
        if find_orphaned_tool_messages(new_messages) or find_unanswered_tool_calls(new_messages):
            outcome = CompactionResult(
                ok=False,
                error="compaction produced an orphaned tool call or result -- refusing to persist",
                failure_kind="invalid_output",
            )
            return None

        updated = record.model_copy(
            update={
                "session_key": session_key,
                "messages": [_encode(m) for m in new_messages],
                "updated": stamp,
            }
        )
        outcome = CompactionResult(
            ok=True, compacted=True, groups_summarized=len(plan.to_summarize)
        )
        return updated.model_dump(by_alias=True)

    _store.read_modify_write(path, _mutate)
    return outcome
