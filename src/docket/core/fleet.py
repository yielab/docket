"""fleet.json — docket's own agent-fleet registry (models + read/write API).

Agent registration, channel bindings, and isolation flags are read/written
**only** by docket, through
``edges/store.py`` — nothing else ever writes ``fleet.json``. The single-writer
contract makes cross-runtime configuration drift structurally impossible:
with one writer, "an older docket version partially wrote this" is still
possible in principle, but "a different program touched this file" is not.

**Deliberately not duplicated:** a registered agent's ``model``, ``sessionKey``
and ``projectKey`` remain ``.docket-meta.json``'s job (see ``core/models.py``'s
``AgentMeta``) and are NOT tracked here. ``FleetAgent`` records only the bare
fact of registration (its id) — carrying a second copy of fields
``.docket-meta.json`` already owns would just recreate the same kind of
drift.

Lenient by design (``extra="allow"``) so a future field added by one docket
version round-trips through an older one instead of being silently dropped.

This module also carries the read/write functions
(``meta_get``/``meta_set``/``list_agents``/``add_agent``/``get_binding``/…)
for fleet and agent-metadata state. These are docket-owned formats read through
``edges/store.py``, so they live as a plain ``core/`` module.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import docket.config as _cfg
from docket.core.models import AgentMeta
from docket.edges import store

_LENIENT = ConfigDict(extra="allow", populate_by_name=True)


class FleetAgent(BaseModel):
    """One registered agent — presence only; model/session live in AgentMeta."""

    model_config = _LENIENT

    id: str = ""


class FleetBinding(BaseModel):
    """One channel binding: which peer (e.g. a Telegram group) routes to an agent."""

    model_config = _LENIENT

    agent_id: str = Field("", alias="agentId")
    channel: str = "telegram"
    peer_kind: str = Field("group", alias="peerKind")
    peer_id: str = Field("", alias="peerId")


class FleetSecurity(BaseModel):
    """Workspace-isolation flags (see security-gates.spec.md)."""

    model_config = _LENIENT

    # 'unset' (no recorded choice: isolated by default) | 'off' | a sandbox mode string.
    isolation_mode: str = Field("unset", alias="isolationMode")


class FleetConfig(BaseModel):
    """Top-level shape of fleet.json."""

    model_config = _LENIENT

    agents: list[FleetAgent] = Field(default_factory=list)
    bindings: list[FleetBinding] = Field(default_factory=list)
    security: FleetSecurity = Field(default_factory=lambda: FleetSecurity())


# ─────────────────────────────────────────────────────────────────────────────
# Read/write API. Every function below is docket-owned state — fleet.json
# and .docket-meta.json — both Docket-owned formats, so this is a plain
# core/ module (imports only edges/store.py for I/O).
# ─────────────────────────────────────────────────────────────────────────────


def load_fleet() -> FleetConfig:
    """Return the full fleet registry as a validated model."""
    raw = store.read_json(_cfg.FLEET_FILE)
    return FleetConfig.model_validate(raw)


def _save_fleet(cfg: FleetConfig) -> None:
    store.write_json(_cfg.FLEET_FILE, cfg)


def meta_read(agent_id: str) -> AgentMeta:
    """Read and validate the full .docket-meta.json for an agent."""
    path = _cfg.meta_path(agent_id)
    raw = store.read_json(path)
    return AgentMeta.model_validate(raw)


def meta_get(agent_id: str, field: str, default: str = "") -> str:
    """Read a single string field from .docket-meta.json."""
    path = _cfg.meta_path(agent_id)
    if not path.exists():
        return default
    raw = store.read_json(path)
    val = raw.get(field)
    return str(val) if val is not None else default


def meta_set(agent_id: str, field: str, value: Any) -> None:
    """Write a single field to .docket-meta.json; validates the full record before writing."""
    path = _cfg.meta_path(agent_id)
    raw = store.read_json(path)
    raw[field] = value
    AgentMeta.model_validate(raw)
    store.write_json(path, raw)


def list_agents(cfg: FleetConfig | None = None) -> list[FleetAgent]:
    """Return the fleet's registered-agent list."""
    return (cfg or load_fleet()).agents


def get_agent(agent_id: str, cfg: FleetConfig | None = None) -> FleetAgent | None:
    """Return one agent entry by id, or None if not registered."""
    for agent in (cfg or load_fleet()).agents:
        if agent.id == agent_id:
            return agent
    return None


def agent_registered(agent_id: str, cfg: FleetConfig | None = None) -> bool:
    """Return True if agent_id is registered in the fleet."""
    return get_agent(agent_id, cfg) is not None


def agent_count() -> int:
    """Return the number of agents registered in the fleet."""
    return len(load_fleet().agents)


def add_agent(agent_id: str) -> None:
    """Register agent_id in the fleet (no-op if already present). Model and session keys live
    in ``.docket-meta.json`` (``AgentMeta``), never here."""
    cfg = load_fleet()
    if not agent_registered(agent_id, cfg):
        cfg.agents.append(FleetAgent(id=agent_id))
        _save_fleet(cfg)


def remove_agent(agent_id: str) -> None:
    """Remove agent_id from the fleet registry."""
    cfg = load_fleet()
    cfg.agents = [a for a in cfg.agents if a.id != agent_id]
    _save_fleet(cfg)


def get_binding(agent_id: str, channel: str = "telegram", cfg: FleetConfig | None = None) -> str:
    """Return the peer id for a channel binding, or '' if none."""
    for b in (cfg or load_fleet()).bindings:
        if b.agent_id == agent_id and b.channel == channel:
            return b.peer_id
    return ""


def upsert_binding(
    agent_id: str,
    peer_id: str,
    channel: str = "telegram",
    peer_kind: str = "group",
) -> None:
    """Add or replace a channel binding for an agent."""
    cfg = load_fleet()
    cfg.bindings = [
        b for b in cfg.bindings if not (b.agent_id == agent_id and b.channel == channel)
    ]
    cfg.bindings.append(
        FleetBinding(agent_id=agent_id, channel=channel, peer_kind=peer_kind, peer_id=peer_id)
    )
    _save_fleet(cfg)


def remove_binding(agent_id: str, channel: str | None = None) -> None:
    """Remove one or all channel bindings for an agent."""
    cfg = load_fleet()
    if channel is None:
        cfg.bindings = [b for b in cfg.bindings if b.agent_id != agent_id]
    else:
        cfg.bindings = [
            b for b in cfg.bindings if not (b.agent_id == agent_id and b.channel == channel)
        ]
    _save_fleet(cfg)


def find_binding(channel: str, peer_id: str, cfg: FleetConfig | None = None) -> FleetBinding | None:
    """Reverse lookup: the binding (if any) a channel peer is wired to.

    The authorization primitive docket's Telegram channel is built on --
    ``get_binding``/``agent_bindings`` above answer "what peer is *this
    agent* bound to"; an inbound channel message needs the opposite
    direction, "what agent (if any) is *this peer* bound to". A peer maps to
    at most one agent per channel (``upsert_binding`` replaces, never
    appends, for a given (agent_id, channel) pair), so the first match is the
    only match.
    """
    for b in (cfg or load_fleet()).bindings:
        if b.channel == channel and b.peer_id == peer_id:
            return b
    return None


def agent_bindings(agent_id: str, cfg: FleetConfig | None = None) -> list[dict[str, str]]:
    """Return [{channel, peerId}, ...] for one agent's bindings."""
    return [
        {"channel": b.channel, "peerId": b.peer_id}
        for b in (cfg or load_fleet()).bindings
        if b.agent_id == agent_id
    ]


def channel_names(cfg: FleetConfig | None = None) -> list[str]:
    """Return the distinct channel names any binding currently uses.

    fleet.json has no "configured but unused" concept — a channel exists
    here only once something is bound to it.
    """
    seen: list[str] = []
    for b in (cfg or load_fleet()).bindings:
        if b.channel not in seen:
            seen.append(b.channel)
    return seen


def get_isolation_enabled(cfg: FleetConfig | None = None) -> bool:
    """True unless the operator recorded an explicit off; no recorded choice is isolated."""
    mode = (cfg or load_fleet()).security.isolation_mode
    return mode != "off"


def get_isolation_state(cfg: FleetConfig | None = None) -> str:
    """'on (default)' with no recorded choice, 'on' once recorded, 'off' once recorded off."""
    mode = (cfg or load_fleet()).security.isolation_mode
    if mode == "unset":
        return "on (default)"
    return "off" if mode == "off" else "on"


def set_sandbox_isolation(mode: str = "non-main") -> None:
    """Write the fleet's sandbox isolation mode."""
    cfg = load_fleet()
    cfg.security.isolation_mode = mode
    _save_fleet(cfg)


def disable_sandbox_isolation() -> None:
    """Set the fleet's sandbox isolation mode to 'off'."""
    cfg = load_fleet()
    cfg.security.isolation_mode = "off"
    _save_fleet(cfg)


def all_agent_ids() -> list[str]:
    """Return agent ids registered in the fleet; 'main' is always included."""
    if not _cfg.FLEET_FILE.exists():
        return ["main"]
    try:
        ids = [a.id for a in list_agents() if a.id]
    except Exception:
        return []
    return ids


def set_model_both(agent_id: str, model: str) -> None:
    """Update an agent's model in .docket-meta.json (the one home for it).

    Named (rather than inlining ``meta_set`` at every call site) because
    "update an agent's model" is a meaningful operation on its own — what
    ``docket profile``/``docket models set`` call. This writes only
    ``.docket-meta.json`` today — the fleet registry never tracked an
    agent's model, so despite the name there is only one write to make.
    """
    meta_set(agent_id, "model", model)
