from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from docket.agent import context as _context
from docket.agent.llm import ChatMessage

_COMPACTED_SUMMARY_PREFIX = "[compacted summary of "


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
