"""Conversation registry — docket's durable index of channel conversations.

Option B from ``internal-docs/telegram-conversation-memory.md``. No agent runtime
docket has driven persists a durable conversation transcript (see
``internal-docs/POD-DAEMON-NOTES.md``): a per-agent recall index is at best a
rebuildable RAG index over workspace files, and live conversation context is lost
on reset/compaction. So docket owns a small registry
mapping each channel thread → the agent handling it, its topic, status, and a resume
pointer — deterministic resume that does **not** depend on the runtime's ephemeral
session.

Layering: this module holds the domain models + **pure** operations on an in-memory
registry, plus thin load/save helpers over ``edges/store.py`` (the same shape
``core/models_policy.py`` uses). Timestamps are passed in by the caller so the pure
ops stay testable; the ``cli`` layer stamps ``datetime.now(UTC)``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import docket.config as _cfg
from docket.edges import store as _store


class ConversationStatus(StrEnum):
    """Where a conversation stands. ``in_progress`` = an accepted task is being worked."""

    active = "active"
    in_progress = "in_progress"
    waiting = "waiting"
    done = "done"


class Conversation(BaseModel):
    """One channel thread docket is tracking. ``id`` is stable per (agent, peer)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    agent_id: str = Field("", alias="agentId")
    channel: str = "telegram"
    peer_id: str = Field("", alias="peerId")
    peer_kind: str = Field("group", alias="peerKind")
    topic: str = ""
    status: ConversationStatus = ConversationStatus.active
    created: str = ""
    updated: str = ""
    last_message: str = Field("", alias="lastMessage")
    task_ref: str = Field("", alias="taskRef")


class ConversationRegistry(BaseModel):
    # Preserve forward-compatible registry fields during a durable mutation.
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    conversations: list[Conversation] = Field(default_factory=list)


# --- pure operations ----------------------------------------------------------


def make_id(agent_id: str, peer_id: str, channel: str = "telegram") -> str:
    """Stable conversation id for an (agent, peer) pair on a channel."""
    return f"{channel}:{agent_id}:{peer_id}"


def get(reg: ConversationRegistry, cid: str) -> Conversation | None:
    return next((c for c in reg.conversations if c.id == cid), None)


def by_agent(reg: ConversationRegistry, agent_id: str) -> list[Conversation]:
    return [c for c in reg.conversations if c.agent_id == agent_id]


def ordered(reg: ConversationRegistry) -> list[Conversation]:
    """Conversations most-recently-updated first (stable for equal timestamps)."""
    return sorted(reg.conversations, key=lambda c: (c.updated, c.id), reverse=True)


def upsert(reg: ConversationRegistry, conv: Conversation) -> ConversationRegistry:
    """Insert *conv*, or replace the existing entry with the same id. Pure."""
    kept = [c for c in reg.conversations if c.id != conv.id]
    return reg.model_copy(update={"conversations": [*kept, conv]})


def record(
    reg: ConversationRegistry,
    *,
    agent_id: str,
    peer_id: str,
    now: str,
    channel: str = "telegram",
    peer_kind: str = "group",
    topic: str | None = None,
    status: ConversationStatus | None = None,
    last_message: str | None = None,
    task_ref: str | None = None,
) -> tuple[Conversation, ConversationRegistry]:
    """Create or update the conversation for (agent, peer), returning it + the registry.

    Only provided fields overwrite; ``created`` is set once. ``updated`` is always
    bumped to *now*. Idempotent seeding: calling with no topic/status just refreshes
    ``updated`` (used by ``docket wire`` to register a binding).
    """
    cid = make_id(agent_id, peer_id, channel)
    existing = get(reg, cid)
    if existing is not None:
        conv = existing.model_copy(
            update={
                "agent_id": agent_id,
                "channel": channel,
                "peer_id": peer_id,
                "peer_kind": peer_kind,
                "topic": topic if topic is not None else existing.topic,
                "status": status if status is not None else existing.status,
                "created": existing.created or now,
                "updated": now,
                "last_message": last_message if last_message is not None else existing.last_message,
                "task_ref": task_ref if task_ref is not None else existing.task_ref,
            }
        )
    else:
        conv = Conversation(
            id=cid,
            agent_id=agent_id,
            channel=channel,
            peer_id=peer_id,
            peer_kind=peer_kind,
            topic=topic or "",
            status=status or ConversationStatus.active,
            created=now,
            updated=now,
            last_message=last_message or "",
            task_ref=task_ref or "",
        )
    return conv, upsert(reg, conv)


def resume(
    reg: ConversationRegistry, cid: str, now: str
) -> tuple[Conversation | None, ConversationRegistry]:
    """Mark a conversation ``in_progress`` and bump ``updated``. No-op if unknown."""
    conv = get(reg, cid)
    if conv is None:
        return None, reg
    resumed = conv.model_copy(update={"status": ConversationStatus.in_progress, "updated": now})
    return resumed, upsert(reg, resumed)


def touch_for_hop(
    reg: ConversationRegistry, *, agent_id: str, task_ref: str, last_message: str, now: str
) -> ConversationRegistry:
    """Refresh every tracked conversation for *agent_id* with real dispatch activity.

    A pod dispatch hop is real, observable work — a human
    watching a wired channel thread should see the task it's actually on and a
    preview of what it last said, not just whatever ``docket wire`` seeded once
    at binding time. Pure: ``touch_for_hop_durable`` owns its locked
    read-modify-write round-trip, while this helper remains usable in tests and
    other in-memory transforms.

    A no-op — returns *reg* unchanged — when *agent_id* has no tracked
    conversation at all, so a hop for an unwired pod member never fabricates
    one out of thin air; topic/status are left exactly as they were (only
    ``last_message``/``task_ref``/``updated`` move). *last_message* is
    collapsed to a single line and trimmed to a short preview — the full text
    already lives in the trace log and the task's own persisted hop record, so
    the registry only ever needs to answer "what is this thread on right now".
    """
    matches = by_agent(reg, agent_id)
    if not matches:
        return reg
    preview = " ".join(last_message.split())
    if len(preview) > 300:
        preview = preview[:299] + "…"
    for conv in matches:
        _, reg = record(
            reg,
            agent_id=conv.agent_id,
            peer_id=conv.peer_id,
            now=now,
            channel=conv.channel,
            peer_kind=conv.peer_kind,
            last_message=preview,
            task_ref=task_ref,
        )
    return reg


def remove_agent(reg: ConversationRegistry, agent_id: str) -> ConversationRegistry:
    """Drop all conversations for *agent_id* (used on agent/pod teardown)."""
    kept = [c for c in reg.conversations if c.agent_id != agent_id]
    return (
        reg
        if len(kept) == len(reg.conversations)
        else reg.model_copy(update={"conversations": kept})
    )


# --- load / save (I/O via edges/store.py) -------------------------------------


def load(path: Path | None = None) -> ConversationRegistry:
    """Load the registry, or an empty one if the file is absent/unreadable."""
    p = path or _cfg.CONVERSATIONS_FILE
    if not p.exists():
        return ConversationRegistry()
    try:
        return ConversationRegistry.model_validate(_store.read_json(p))
    except Exception:
        return ConversationRegistry()


def save(reg: ConversationRegistry, path: Path | None = None) -> None:
    """Persist the registry atomically via edges/store.py."""
    p = path or _cfg.CONVERSATIONS_FILE
    _store.write_json(p, reg.model_dump(by_alias=True))


# --- durable mutations --------------------------------------------------------


class ConversationRegistryError(RuntimeError):
    """The existing registry cannot safely be transformed."""


_MutationResult = TypeVar("_MutationResult")


def mutate(
    fn: Callable[[ConversationRegistry], tuple[_MutationResult, ConversationRegistry]],
    path: Path | None = None,
) -> _MutationResult:
    """Run one conversation transformation under the registry's file lock.

    ``fn`` receives the latest validated registry while the lock is held. Returning the
    same registry object means no durable mutation, which deliberately leaves the input
    byte-identical. Malformed data is not treated as an empty registry here: that forgiving
    read behavior belongs to ``load`` for inspection, while a write must fail closed.
    """
    p = path or _cfg.CONVERSATIONS_FILE
    result: _MutationResult

    def _apply(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal result
        try:
            current = ConversationRegistry.model_validate(doc)
        except ValidationError as exc:
            raise ConversationRegistryError(
                f"Cannot mutate malformed conversation registry: {p}"
            ) from exc
        result, updated = fn(current)
        if updated is current:
            return None
        return updated.model_dump(by_alias=True)

    try:
        _store.read_modify_write(p, _apply)
    except json.JSONDecodeError as exc:
        raise ConversationRegistryError(
            f"Cannot mutate malformed conversation registry: {p}"
        ) from exc
    return result


def record_durable(
    *,
    agent_id: str,
    peer_id: str,
    now: str,
    channel: str = "telegram",
    peer_kind: str = "group",
    topic: str | None = None,
    status: ConversationStatus | None = None,
    last_message: str | None = None,
    task_ref: str | None = None,
    path: Path | None = None,
) -> Conversation:
    """Record a conversation in one locked read-modify-write operation."""
    return mutate(
        lambda reg: record(
            reg,
            agent_id=agent_id,
            peer_id=peer_id,
            now=now,
            channel=channel,
            peer_kind=peer_kind,
            topic=topic,
            status=status,
            last_message=last_message,
            task_ref=task_ref,
        ),
        path,
    )


def resume_durable(cid: str, now: str, path: Path | None = None) -> Conversation | None:
    """Resume a known conversation atomically; unknown ids leave the file untouched."""
    return mutate(lambda reg: resume(reg, cid, now), path)


def remove_agent_durable(agent_id: str, path: Path | None = None) -> bool:
    """Remove one agent's tracked conversations atomically."""

    def _remove(reg: ConversationRegistry) -> tuple[bool, ConversationRegistry]:
        updated = remove_agent(reg, agent_id)
        return updated is not reg, updated

    return mutate(_remove, path)


def touch_for_hop_durable(
    *, agent_id: str, task_ref: str, last_message: str, now: str, path: Path | None = None
) -> bool:
    """Persist one wired agent's bounded hop preview without a stale-registry race."""

    def _touch(reg: ConversationRegistry) -> tuple[bool, ConversationRegistry]:
        updated = touch_for_hop(
            reg, agent_id=agent_id, task_ref=task_ref, last_message=last_message, now=now
        )
        return updated is not reg, updated

    return mutate(_touch, path)
