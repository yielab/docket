"""fleet.json — docket's own agent-fleet registry (models + read/write API).

Agent registration, channel bindings, gates/isolation flags, and the
org-wide default model are read/written **only** by docket, through
``edges/store.py`` — nothing else ever writes ``fleet.json``. This state used
to live in ``openclaw.json``, a file that could be mutated by more than one
writer (the daemon, a raw ``openclaw`` CLI call, or a hand edit) independently
of docket — exactly the kind of drift a single-writer file makes
structurally impossible rather than merely harder: with one writer, "an
older docket version partially wrote this" is still possible in principle,
but "a different program touched this file" is not.

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
for fleet and agent-metadata state. None of these ever touched an OpenClaw
file format — they are, and always were, docket-owned state read through
``edges/store.py``, so they live as a plain ``core/`` module rather than
needing an anti-corruption layer of their own.
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


class FleetDefaults(BaseModel):
    """Org-wide defaults. Today: the default model new agents provision with."""

    model_config = _LENIENT

    model: str = ""


class FleetSecurity(BaseModel):
    """Gates/isolation/approval-routing flags (see security-gates.spec.md)."""

    model_config = _LENIENT

    gates_enabled: bool = Field(False, alias="gatesEnabled")
    isolation_enabled: bool = Field(False, alias="isolationEnabled")
    # 'unset' | 'off' | a sandbox mode string (e.g. 'non-main').
    isolation_mode: str = Field("unset", alias="isolationMode")
    # 'unset' | 'on' | 'off' — a real tri-state, not a bool, so "never
    # configured" and "explicitly turned off" stay distinguishable (the same
    # shape as isolation_mode above; a bare `enabled: bool` cannot tell those
    # two apart).
    approval_routing_state: str = Field("unset", alias="approvalRoutingState")
    approval_routing_mode: str = Field("", alias="approvalRoutingMode")


class FleetConfig(BaseModel):
    """Top-level shape of fleet.json."""

    model_config = _LENIENT

    agents: list[FleetAgent] = Field(default_factory=list)
    bindings: list[FleetBinding] = Field(default_factory=list)
    security: FleetSecurity = Field(default_factory=lambda: FleetSecurity())
    defaults: FleetDefaults = Field(default_factory=lambda: FleetDefaults())
    # Local OpenAI-compatible model endpoints (llama.cpp / LM Studio / vLLM),
    # registered by `docket models provider` (core/provider.py) and read by
    # `edges/adapters/llm.py`'s `resolve_endpoint`. Kept as a loose dict (not
    # a typed sub-model) since its shape is dictated by `core.provider`'s
    # `local_provider_config` producer and `edges/adapters/llm.py`'s consumer,
    # not by anything fleet-registry-specific.
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Read/write API. Every function below is docket-owned state — fleet.json
# and .docket-meta.json — never an OpenClaw file format, so this is a plain
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


def get_default_model(cfg: FleetConfig | None = None) -> str:
    """Return the fleet's org-wide default model id."""
    return (cfg or load_fleet()).defaults.model


def set_default_model(model: str) -> None:
    """Write the fleet's org-wide default model id."""
    cfg = load_fleet()
    cfg.defaults.model = model
    _save_fleet(cfg)


def add_agent(
    agent_id: str,
    model: str = "",
    session_key: str = "",
    project_key: str = "",
) -> None:
    """Register agent_id in the fleet (no-op if already present).

    ``model``/``session_key``/``project_key`` are accepted for call-site
    compatibility (callers historically pass all four) but are not stored
    here — ``.docket-meta.json`` (``AgentMeta``) is their one real home;
    duplicating them in the fleet registry would recreate the drift this
    module's docstring describes.
    """
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


def get_gates_enabled(cfg: FleetConfig | None = None) -> bool:
    return (cfg or load_fleet()).security.gates_enabled


def set_gates_enabled(enabled: bool) -> None:
    cfg = load_fleet()
    cfg.security.gates_enabled = enabled
    _save_fleet(cfg)


def get_isolation_enabled(cfg: FleetConfig | None = None) -> bool:
    return (cfg or load_fleet()).security.isolation_enabled


def set_isolation_enabled(enabled: bool) -> None:
    cfg = load_fleet()
    cfg.security.isolation_enabled = enabled
    _save_fleet(cfg)


def get_isolation_mode() -> str:
    """Return the fleet's sandbox isolation mode ('unset' if never configured)."""
    return load_fleet().security.isolation_mode


def set_sandbox_isolation(mode: str = "non-main") -> None:
    """Write the fleet's sandbox isolation mode."""
    cfg = load_fleet()
    cfg.security.isolation_mode = mode
    cfg.security.isolation_enabled = mode not in ("off", "unset")
    _save_fleet(cfg)


def disable_sandbox_isolation() -> None:
    """Set the fleet's sandbox isolation mode to 'off'."""
    cfg = load_fleet()
    cfg.security.isolation_mode = "off"
    cfg.security.isolation_enabled = False
    _save_fleet(cfg)


def get_approval_routing() -> tuple[str, str]:
    """Return (state, mode) for exec-approval routing; state is 'on' | 'off' | 'unset'."""
    sec = load_fleet().security
    return (sec.approval_routing_state, sec.approval_routing_mode)


def set_approval_routing(enabled: bool, mode: str = "session") -> None:
    """Write the fleet's exec-approval routing state."""
    cfg = load_fleet()
    cfg.security.approval_routing_state = "on" if enabled else "off"
    cfg.security.approval_routing_mode = mode
    _save_fleet(cfg)


def disable_approval_routing() -> None:
    """Turn exec-approval routing off."""
    cfg = load_fleet()
    cfg.security.approval_routing_state = "off"
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


def get_local_provider(name: str, cfg: FleetConfig | None = None) -> dict[str, Any] | None:
    """Return the stored local-provider definition for *name*, or None if absent."""
    return (cfg or load_fleet()).providers.get(name)


def add_local_provider(
    name: str,
    base_url: str,
    model_id: str,
    model_name: str,
    ctx: int,
    max_tokens: int,
) -> bool:
    """Register a local (llama.cpp / LM Studio / vLLM) provider in fleet.json.

    Idempotent: returns False when the existing entry already matches.
    """
    from docket.core.provider import local_provider_config

    desired = local_provider_config(base_url, model_id, model_name, ctx, max_tokens)
    cfg = load_fleet()
    if cfg.providers.get(name) == desired:
        return False
    cfg.providers[name] = desired
    _save_fleet(cfg)
    return True
