"""Conversation registry — docket's durable index of channel conversations.

Option B from ``internal-docs/telegram-conversation-memory.md``. OpenClaw persists
**no** durable conversation transcript (TC-3 in ``internal-docs/POD-DAEMON-NOTES.md``):
its per-agent sqlite is only a rebuildable RAG index over workspace files, and live
conversation context is lost on reset/compaction. So docket owns a small registry
mapping each channel thread → the agent handling it, its topic, status, and a resume
pointer — deterministic resume that does **not** depend on the runtime's ephemeral
session.

Layering: this module holds the domain models + **pure** operations on an in-memory
registry, plus thin load/save helpers over ``edges/store.py`` (the same shape
``core/models_policy.py`` uses). Timestamps are passed in by the caller so the pure
ops stay testable; the ``cli`` layer stamps ``datetime.now(UTC)``.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(populate_by_name=True)

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
    return ConversationRegistry(conversations=[*kept, conv])


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
    conv = Conversation(
        id=cid,
        agent_id=agent_id,
        channel=channel,
        peer_id=peer_id,
        peer_kind=peer_kind,
        topic=topic if topic is not None else (existing.topic if existing else ""),
        status=status
        if status is not None
        else (existing.status if existing else ConversationStatus.active),
        created=existing.created if existing and existing.created else now,
        updated=now,
        last_message=last_message
        if last_message is not None
        else (existing.last_message if existing else ""),
        task_ref=task_ref if task_ref is not None else (existing.task_ref if existing else ""),
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


def remove_agent(reg: ConversationRegistry, agent_id: str) -> ConversationRegistry:
    """Drop all conversations for *agent_id* (used on agent/pod teardown)."""
    return ConversationRegistry(
        conversations=[c for c in reg.conversations if c.agent_id != agent_id]
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
