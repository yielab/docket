"""Durable turn history + compaction.

Persists message history *inside* a turn, keyed on ``agent:<id>:<project>``; loaded by
``agent/loop.py`` before each turn and appended after. Full contract, storage layout, and
wire format: ``specs/functional/session-history.spec.md``.

Load-bearing facts kept here: an assistant message's ``tool_calls`` and every answering
``tool``-role reply are one atomic unit ``compact_session`` never splits, drops, or partially
summarises. If summarisation fails or returns nothing usable, the stored history is left
unchanged and ``ok=False`` is reported. ``plan_compaction`` budgets against the *estimate*
(``agent.context.estimate_tokens``), never against ``MeasuredUsage``'s *measured* counts.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote as _urlquote

from pydantic import BaseModel, ConfigDict, Field

from docket.agent.llm import ChatMessage, Role, TokenUsage, ToolCall
from docket.agent.ports import TurnResult
from docket.agent.session_units import (
    find_orphaned_tool_messages,
    find_unanswered_tool_calls,
    group_atomic_units,
    plan_compaction,
)
from docket.kernel import clock as _clock
from docket.kernel import text as _text
from docket.kernel.home import current_home
from docket.platform import store as _store

__all__ = [
    "HISTORY_FULL_RESULTS_CHARS",
    "HISTORY_KEEP_FULL_RESULTS",
    "HISTORY_LOW_WATER_CHARS",
    "MeasuredUsage",
    "SessionRecord",
    "SessionSummaryRunner",
    "StoredMessage",
    "StoredToolCall",
    "append_messages",
    "condense_history",
    "find_orphaned_tool_messages",
    "find_unanswered_tool_calls",
    "group_atomic_units",
    "load_messages",
    "load_session",
    "plan_compaction",
]

#: The shape `compact_session` needs from a driver -- identical to
#: `agent.memory.DistillRunner`/`core.dispatch.Runner`: `RuntimeDriver.run_turn`'s
#: core 5-arg call, nothing more. A separate alias (not an import of either)
#: because this module must not depend on `agent/memory.py` or `core/dispatch.py`
#: for a plain structural type -- see the module docstring's fail-closed section.
SessionSummaryRunner = Callable[[str, str, str, int, dict[str, str] | None], TurnResult]

#: Tool results newer than this many stay whole in a built request.
HISTORY_KEEP_FULL_RESULTS = 2
#: Older results also stay whole while all whole results fit in this many characters.
HISTORY_FULL_RESULTS_CHARS = 6_000
#: Once whole results exceed the budget, condensing leaves at most this many characters whole.
HISTORY_LOW_WATER_CHARS = 3_000

_SESSION_FILENAME = "session.json"


# ── storage models ────────────────────────────────────────────────────────────


class StoredToolCall(BaseModel):
    """Wire/storage twin of ``agent.llm.ToolCall`` -- same three fields, no more."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    arguments: str = "{}"


class StoredMessage(BaseModel):
    """Wire/storage twin of ``agent.llm.ChatMessage``, field-for-field so ``_encode``/``_decode``
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
    cache_write_tokens: int = Field(0, alias="cacheWriteTokens")
    turns: int = 0


def _add_usage(current: MeasuredUsage, delta: TokenUsage) -> MeasuredUsage:
    """Fold one exchange's real ``TokenUsage`` into a session's running total."""
    return MeasuredUsage(
        input_tokens=current.input_tokens + delta.input_tokens,
        output_tokens=current.output_tokens + delta.output_tokens,
        cached_tokens=current.cached_tokens + delta.cached_tokens,
        cache_write_tokens=current.cache_write_tokens + delta.cache_write_tokens,
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


# ── storage paths ─────────────────────────────────────────────────────────────


def _session_dir(session_key: str, sessions_dir: Path | None = None) -> Path:
    root = sessions_dir if sessions_dir is not None else current_home().sessions_dir
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
    only*, never touching another's file. ``platform/store.py`` keeps a ``.bak``; no auto-recovery."""
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
    stamp = now or _clock.stamp()
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


# ── request projection ────────────────────────────────────────────────────────

_ERROR_PREFIXES = ("ERROR:", "REFUSED [", "AWAITING APPROVAL:")
_ERROR_KEEP_CHARS = 400
_TARGET_CHARS = 80
_BODY_ARGUMENTS = {
    "write": {"content": "wrote"},
    "edit": {"new_string": "wrote", "old_string": "replaced"},
}


def _call_arguments(call: ToolCall) -> dict[str, Any] | None:
    try:
        decoded = json.loads(call.arguments)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _call_target(args: dict[str, Any] | None) -> str:
    """The path, command, pattern or url a call named, on one bounded line."""
    for key in ("path", "file_path", "command", "pattern", "url", "query"):
        value = (args or {}).get(key)
        if isinstance(value, str) and value.strip():
            line = value.strip().splitlines()[0]
            return _text.ellipsize(line, _TARGET_CHARS, "...")
    return ""


def _result_notice(call: ToolCall | None, message: ChatMessage) -> str:
    name = call.name if call else message.name or "tool"
    target = _call_target(_call_arguments(call) if call else None)
    lines = message.content.count("\n") + 1 if message.content else 0
    head = f"{name} {target}" if target else name
    return (
        f"[{head}: {lines} lines, {len(message.content):,} characters, already seen and "
        f"omitted; call {name} again only for exact text you still need]"
    )


def _condense_result(call: ToolCall | None, message: ChatMessage) -> ChatMessage:
    content = message.content
    if content.startswith(_ERROR_PREFIXES):
        if len(content) <= _ERROR_KEEP_CHARS:
            return message
        rest = len(content) - _ERROR_KEEP_CHARS
        content = f"{content[:_ERROR_KEEP_CHARS]}\n[{rest:,} more characters omitted]"
        return ChatMessage(message.role, content, [], message.tool_call_id, message.name)
    notice = _result_notice(call, message)
    if len(notice) >= len(content):
        return message
    return ChatMessage(message.role, notice, [], message.tool_call_id, message.name)


def _condense_call(call: ToolCall) -> ToolCall:
    """Replace a large ``write``/``edit`` body with its size, keeping the arguments valid JSON."""
    fields = _BODY_ARGUMENTS.get(call.name)
    args = _call_arguments(call) if fields else None
    if not fields or args is None:
        return call
    path = args.get("path") if isinstance(args.get("path"), str) else ""
    changed = False
    for key, verb in fields.items():
        value = args.get(key)
        if not isinstance(value, str):
            continue
        notice = (
            f"[{verb} {path}: {len(value):,} characters]"
            if path
            else f"[{verb}: {len(value):,} characters]"
        )
        if len(notice) < len(value):
            args[key], changed = notice, True
    if not changed:
        return call
    return ToolCall(call.id, call.name, json.dumps(args, ensure_ascii=False, separators=(",", ":")))


def _batch_cut(sizes: Sequence[int], keep: int, budget: int) -> int:
    """How many of the oldest results are condensed: it moves only when the whole ones outgrow
    *budget*, and then down to the low-water mark. A function of *sizes* alone."""
    low = min(HISTORY_LOW_WATER_CHARS, budget // 2)
    cut = 0
    for end in range(1, len(sizes) + 1):
        if sum(sizes[cut:end]) <= budget:
            continue
        start = max(cut, end - keep)
        whole = sum(sizes[start:end])
        while start > cut and whole + sizes[start - 1] <= low:
            start -= 1
            whole += sizes[start]
        cut = start
    return cut


def condense_history(
    messages: Sequence[ChatMessage],
    keep: int = HISTORY_KEEP_FULL_RESULTS,
    budget: int = HISTORY_FULL_RESULTS_CHARS,
) -> list[ChatMessage]:
    """The request projection: the last *keep* tool results and older ones that still fit
    *budget* characters stay whole, with the cut moving in batches; the rest become notices and
    their large ``write``/``edit`` arguments counts. Pure and deterministic; the stored history
    is never changed."""
    results = [m for m in messages if m.role == "tool"]
    cut = _batch_cut([len(m.content) for m in results], max(1, keep), budget)
    old = {m.tool_call_id for m in results[:cut]}
    calls = {c.id: c for m in messages for c in m.tool_calls}
    out: list[ChatMessage] = []
    for m in messages:
        if m.role == "tool" and m.tool_call_id in old:
            out.append(_condense_result(calls.get(m.tool_call_id), m))
        elif m.role == "assistant" and any(c.id in old for c in m.tool_calls):
            condensed = [_condense_call(c) if c.id in old else c for c in m.tool_calls]
            out.append(ChatMessage(m.role, m.content, condensed, m.tool_call_id, m.name))
        else:
            out.append(m)
    return out
