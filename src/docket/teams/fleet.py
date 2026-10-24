"""fleet.json — docket's own agent-fleet registry (models + read/write API).

Agent registration, channel bindings, and isolation flags are read/written
**only** by docket, through
``platform/store.py`` — nothing else ever writes ``fleet.json``. The single-writer
contract makes cross-runtime configuration drift structurally impossible:
with one writer, "an older docket version partially wrote this" is still
possible in principle, but "a different program touched this file" is not.

**Deliberately not duplicated:** a registered agent's ``model``, ``sessionKey``
and ``projectKey`` remain ``.docket-meta.json``'s job (see ``teams/models.py``'s
``AgentMeta``) and are NOT tracked here. ``FleetAgent`` records only the bare
fact of registration (its id) — carrying a second copy of fields
``.docket-meta.json`` already owns would just recreate the same kind of
drift.

Lenient by design (``extra="allow"``) so a future field added by one docket
version round-trips through an older one instead of being silently dropped.

This module also carries the read/write functions
(``meta_get``/``meta_set``/``list_agents``/``add_agent``/``get_binding``/…)
for fleet and agent-metadata state. These are docket-owned formats read through
``platform/store.py``, so they live as a plain ``teams/`` module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.platform import read_json, write_json
from docket.teams import fleet as _fleet
from docket.teams.models import AgentMeta

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

    # 'unset' (no recorded choice: not isolated, opt-in) | 'off' | a sandbox mode string.
    isolation_mode: str = Field("unset", alias="isolationMode")
    # 'unset' (reads as 'none') | 'none' | 'open': whether a jailed tool call may reach the network.
    network_mode: str = Field("unset", alias="networkMode")
    # 'auto' (landlock on Linux, seatbelt on macOS) | 'docker' (docker only, once chosen).
    sandbox_backend: str = Field("auto", alias="sandboxBackend")
    # 'unset' (attended: nothing recorded) | 'lights-out' (ADR 0025 D2; hops/gates/profile.py).
    profile: str = Field("unset", alias="profile")
    # Resolved absolute paths every jail reads and executes, never writes (the toolchain).
    read_only: list[str] = Field(default_factory=list, alias="readOnly")


class FleetConfig(BaseModel):
    """Top-level shape of fleet.json."""

    model_config = _LENIENT

    agents: list[FleetAgent] = Field(default_factory=list)
    bindings: list[FleetBinding] = Field(default_factory=list)
    security: FleetSecurity = Field(default_factory=lambda: FleetSecurity())


# ─────────────────────────────────────────────────────────────────────────────
# Read/write API. Every function below is docket-owned state — fleet.json
# and .docket-meta.json — both Docket-owned formats, so this is a plain
# teams/ module (imports only platform/store.py for I/O).
# ─────────────────────────────────────────────────────────────────────────────


def load_fleet() -> FleetConfig:
    """Return the full fleet registry as a validated model."""
    raw = read_json(current_home().fleet_file)
    return FleetConfig.model_validate(raw)


def _save_fleet(cfg: FleetConfig) -> None:
    write_json(current_home().fleet_file, cfg)


def meta_get(agent_id: str, field: str, default: str = "") -> str:
    """Read a single string field from .docket-meta.json."""
    path = current_home().meta_path(agent_id)
    if not path.exists():
        return default
    raw = read_json(path)
    val = raw.get(field)
    return str(val) if val is not None else default


def meta_set(agent_id: str, field: str, value: Any) -> None:
    """Write a single field to .docket-meta.json; validates the full record before writing."""
    path = current_home().meta_path(agent_id)
    raw = read_json(path)
    raw[field] = value
    AgentMeta.model_validate(raw)
    write_json(path, raw)


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
    """True only once the operator recorded `gates isolate on`; isolation is opt-in."""
    mode = (cfg or load_fleet()).security.isolation_mode
    return mode not in ("unset", "off")


def get_isolation_state(cfg: FleetConfig | None = None) -> str:
    """'off (default)' with no recorded choice, 'on' once recorded, 'off' once recorded off."""
    mode = (cfg or load_fleet()).security.isolation_mode
    if mode == "unset":
        return "off (default)"
    return "off" if mode == "off" else "on"


def get_network_mode(cfg: FleetConfig | None = None) -> str:
    """'open' only when the operator recorded it; unset or a stray value reads as 'none'."""
    mode = (cfg or load_fleet()).security.network_mode
    return "open" if mode == "open" else "none"


def network_mode_recorded(cfg: FleetConfig | None = None) -> bool:
    """True when the operator recorded a network mode (so 'none' is a choice, not the default)."""
    return (cfg or load_fleet()).security.network_mode in ("none", "open")


def set_network_mode(mode: str) -> None:
    """Record the fleet's network mode: 'none' or 'open'."""
    if mode not in ("none", "open"):
        raise InvalidInput(f"network mode must be 'none' or 'open', not {mode!r}")
    cfg = load_fleet()
    cfg.security.network_mode = mode
    _save_fleet(cfg)


def get_profile(cfg: FleetConfig | None = None) -> str:
    """'lights-out' only when the operator recorded it; unset or a stray value reads as 'attended'."""
    mode = (cfg or load_fleet()).security.profile
    return "lights-out" if mode == "lights-out" else "attended"


def set_profile(profile: str) -> None:
    """Record the fleet's profile: 'lights-out', or 'attended' (which clears the record)."""
    if profile not in ("lights-out", "attended"):
        raise InvalidInput(f"profile must be 'lights-out' or 'attended', not {profile!r}")
    cfg = load_fleet()
    cfg.security.profile = "lights-out" if profile == "lights-out" else "unset"
    _save_fleet(cfg)


def get_sandbox_backend(cfg: FleetConfig | None = None) -> str:
    """'docker' only when the operator recorded it; anything else reads as 'auto'."""
    mode = (cfg or load_fleet()).security.sandbox_backend
    return "docker" if mode == "docker" else "auto"


def set_sandbox_backend(choice: str) -> None:
    """Record the sandbox backend choice: 'auto' or 'docker'."""
    if choice not in ("auto", "docker"):
        raise InvalidInput(f"sandbox backend must be 'auto' or 'docker', not {choice!r}")
    cfg = load_fleet()
    cfg.security.sandbox_backend = choice
    _save_fleet(cfg)


def get_read_only_paths(cfg: FleetConfig | None = None) -> tuple[Path, ...]:
    """The operator's read-only jail grants, as recorded (a grant gone from disk is kept)."""
    return tuple(Path(p) for p in (cfg or load_fleet()).security.read_only)


def _read_only_refusal(path: Path) -> str | None:
    if not path.is_absolute():
        return "is not an absolute path"
    if not path.exists():
        return "does not exist"
    resolved = path.resolve()
    docket_home = current_home().root.resolve()
    if resolved == docket_home or resolved.is_relative_to(docket_home):
        return "is docket's home or inside it"
    for guarded in (Path.home().resolve(), docket_home):
        if guarded.is_relative_to(resolved):
            return f"would expose {guarded}"
    return None


def add_read_only(path: str) -> Path:
    """Record *path* (resolved) as a read-only jail grant; ``ValueError`` names a refusal."""
    candidate = Path(path)
    refusal = _read_only_refusal(candidate)
    if refusal is not None:
        raise InvalidInput(f"{path} {refusal}")
    resolved = candidate.resolve()
    cfg = load_fleet()
    if str(resolved) not in cfg.security.read_only:
        cfg.security.read_only.append(str(resolved))
        _save_fleet(cfg)
    return resolved


def remove_read_only(path: str) -> str:
    """Drop a recorded grant, matched as given or resolved; ``ValueError`` when not recorded."""
    cfg = load_fleet()
    for candidate in dict.fromkeys((path, str(Path(path).resolve()))):
        if candidate in cfg.security.read_only:
            cfg.security.read_only.remove(candidate)
            _save_fleet(cfg)
            return candidate
    raise InvalidInput(f"{path} is not a recorded read-only grant")


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
    if not current_home().fleet_file.exists():
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
    ``docket setup model set`` calls. This writes only
    ``.docket-meta.json`` today — the fleet registry never tracked an
    agent's model, so despite the name there is only one write to make.
    """
    meta_set(agent_id, "model", model)


def apply_workspace_isolation() -> None:
    """Record that per-agent Docker sandbox isolation is desired.

    The Docker capability check at ``docket setup sandbox on`` time is the
    caller's responsibility. Writes fleet.json's isolation mode, read by
    ``DocketDriver`` on every turn to decide real landlock, seatbelt or docker containment
    when a backend is usable, or an audited refusal instead of an
    unsandboxed run when none is.
    """
    _fleet.set_sandbox_isolation(mode="non-main")


def disable_workspace_isolation() -> None:
    """Turn the recorded sandbox-isolation mode off (mode: off)."""
    _fleet.disable_sandbox_isolation()
