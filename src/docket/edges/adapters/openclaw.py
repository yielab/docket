"""Anti-Corruption Layer: the single Python module that knows OpenClaw.

INVARIANT: No other Python module in this codebase may import or reference
openclaw.json, auth-profiles.json, or any other OpenClaw-owned file format.
All knowledge of those formats lives here and nowhere else.

Inventory of all Bash operations this module replaces
(cross-reference with the grep census in MIGRATION-PLAN-PYTHON.md):

  openclaw.json
    [oc-01]  list all agents                        cmd_list, cmd_info, cmd_team
    [oc-02]  get one agent by id                    cmd_info, cost, doctor
    [oc-03]  agent_registered check                 cmd_add, cmd_delete, cmd_doctor
    [oc-04]  write agent.model                      cmd_profile, cmd_models
    [oc-05]  write agent.metadata.sessionKey        cmd_scope
    [oc-06]  write agent.metadata.projectKey        cmd_scope
    [oc-07]  read defaults.model                    cmd_install bootstrap
    [oc-08]  write defaults.model                   cmd_models set default
    [oc-09]  upsert binding                         cmd_wire
    [oc-10]  remove binding                         cmd_unwire, cmd_delete
    [oc-11]  read binding by agent + channel        cmd_info, cmd_wire
    [oc-12]  remove agent from agents.list          cmd_delete
    [oc-13]  add agent to agents.list               cmd_add
    [oc-14]  read security.gates.enabled            cmd_doctor, cmd_gates
    [oc-15]  write security.gates.enabled           cmd_gates enable/disable
    [oc-16]  read security.isolation.enabled        cmd_doctor, cmd_gates
    [oc-17]  write security.isolation.enabled       cmd_gates isolate

  .docket-meta.json (per-workspace)
    [dm-01]  read one field                         meta_get (all commands)
    [dm-02]  write one field                        meta_set (profile, scope, add...)
    [dm-03]  read full record                       cmd_info, cmd_list, sync

  auth-profiles.json
    [ap-01]  list profiles + disabled state         cmd_auth, cmd_doctor
    [ap-02]  has_usable_profile check               cmd_add, cmd_install

  Provider config (future / T5.6 — stub only)
    [pc-01]  add local provider                     models provider add
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from docket.config import (
    CONFIG_FILE,
    auth_profiles_path,
    meta_path,
)
from docket.core.models import AgentMeta
from docket.core.oc_models import (
    AuthProfiles,
    OcAgent,
    OcAgentMetadata,
    OcBinding,
    OcMatch,
    OcPeer,
    OpenClawConfig,
)
from docket.edges import store

# ── helpers ────────────────────────────────────────────────────────────────────


def load_config() -> OpenClawConfig:
    """Return the full openclaw.json as a validated model (public entry point)."""
    return _load_oc()


def _load_oc() -> OpenClawConfig:
    raw = store.read_json(CONFIG_FILE)
    return OpenClawConfig.model_validate(raw)


def _save_oc(cfg: OpenClawConfig) -> None:
    store.write_json(CONFIG_FILE, cfg.model_dump(by_alias=True, exclude_none=False))


# ── .docket-meta.json operations [dm-*] ───────────────────────────────────────


def meta_read(agent_id: str) -> AgentMeta:
    """[dm-03] Read and validate the full .docket-meta.json for an agent."""
    path = meta_path(agent_id)
    raw = store.read_json(path)
    return AgentMeta.model_validate(raw)


def meta_get(agent_id: str, field: str, default: str = "") -> str:
    """[dm-01] Read a single string field from .docket-meta.json."""
    path = meta_path(agent_id)
    if not path.exists():
        return default
    raw = store.read_json(path)
    val = raw.get(field)
    return str(val) if val is not None else default


def meta_set(agent_id: str, field: str, value: Any) -> None:
    """[dm-02] Write a single field to .docket-meta.json (validated, atomic)."""
    path = meta_path(agent_id)
    raw = store.read_json(path)
    raw[field] = value
    # Validate the whole record after mutation so we never write garbage.
    AgentMeta.model_validate(raw)
    store.write_json(path, raw)


def meta_write(agent_id: str, meta: AgentMeta) -> None:
    """[dm-02] Replace the full .docket-meta.json for an agent."""
    path = meta_path(agent_id)
    store.write_json(path, meta.model_dump(by_alias=True, exclude_none=False))


# ── agents.list operations [oc-01 … oc-08] ────────────────────────────────────


def list_agents(cfg: OpenClawConfig | None = None) -> list[OcAgent]:
    """[oc-01] Return the full agents.list from openclaw.json."""
    return (cfg or _load_oc()).agents.items


def get_agent(agent_id: str, cfg: OpenClawConfig | None = None) -> OcAgent | None:
    """[oc-02] Return one agent entry by id, or None if not registered."""
    for agent in (cfg or _load_oc()).agents.items:
        if agent.id == agent_id:
            return agent
    return None


def agent_registered(agent_id: str, cfg: OpenClawConfig | None = None) -> bool:
    """[oc-03] Return True if agent_id is in openclaw.json agents.list."""
    return get_agent(agent_id, cfg) is not None


def set_agent_model(agent_id: str, model: str) -> None:
    """[oc-04] Update the model field for one agent in agents.list."""
    cfg = _load_oc()
    for agent in cfg.agents.items:
        if agent.id == agent_id:
            agent.model = model
            _save_oc(cfg)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def set_agent_session_key(agent_id: str, session_key: str) -> None:
    """[oc-05] Update metadata.sessionKey for one agent."""
    oc = _load_oc()
    for agent in oc.agents.items:
        if agent.id == agent_id:
            agent.metadata.session_key = session_key
            _save_oc(oc)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def set_agent_project_key(agent_id: str, project_key: str) -> None:
    """[oc-06] Update metadata.projectKey for one agent."""
    oc = _load_oc()
    for agent in oc.agents.items:
        if agent.id == agent_id:
            agent.metadata.project_key = project_key
            _save_oc(oc)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def sync_session_key(agent_id: str, session_key: str, project_key: str) -> None:
    """[oc-05,oc-06] Write both sessionKey and projectKey in one round-trip.

    Mirrors sync_session_key() in session.sh (avoids two separate read-write cycles).
    """
    oc = _load_oc()
    for agent in oc.agents.items:
        if agent.id == agent_id:
            agent.metadata.session_key = session_key
            agent.metadata.project_key = project_key
            _save_oc(oc)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def get_default_model(cfg: OpenClawConfig | None = None) -> str:
    """[oc-07] Return agents.defaults.model."""
    return (cfg or _load_oc()).agents.defaults.model


def set_default_model(model: str) -> None:
    """[oc-08] Write agents.defaults.model."""
    cfg = _load_oc()
    cfg.agents.defaults.model = model
    _save_oc(cfg)


def add_agent(
    agent_id: str,
    model: str,
    session_key: str = "",
    project_key: str = "",
) -> None:
    """[oc-13] Append an agent to agents.list (no-op if already present)."""
    cfg = _load_oc()
    if not agent_registered(agent_id, cfg):
        cfg.agents.items.append(
            OcAgent(
                id=agent_id,
                model=model,
                metadata=OcAgentMetadata(
                    session_key=session_key, project_key=project_key
                ),
            )
        )
        _save_oc(cfg)


def remove_agent(agent_id: str) -> None:
    """[oc-12] Remove agent from agents.list."""
    cfg = _load_oc()
    cfg.agents.items = [a for a in cfg.agents.items if a.id != agent_id]
    _save_oc(cfg)


# ── binding operations [oc-09 … oc-11] ────────────────────────────────────────


def get_binding(
    agent_id: str, channel: str = "telegram", cfg: OpenClawConfig | None = None
) -> str:
    """[oc-11] Return the peer id for a channel binding, or '' if none."""
    for b in (cfg or _load_oc()).bindings:
        if b.agent_id == agent_id and b.match.channel == channel:
            return b.match.peer.id
    return ""


def upsert_binding(
    agent_id: str,
    peer_id: str,
    channel: str = "telegram",
    peer_kind: str = "group",
) -> None:
    """[oc-09] Add or replace a channel binding for an agent."""
    cfg = _load_oc()
    cfg.bindings = [
        b
        for b in cfg.bindings
        if not (b.agent_id == agent_id and b.match.channel == channel)
    ]
    cfg.bindings.append(
        OcBinding(
            agent_id=agent_id,
            match=OcMatch(
                channel=channel,
                peer=OcPeer(kind=peer_kind, id=peer_id),
            ),
        )
    )
    _save_oc(cfg)


def remove_binding(agent_id: str, channel: str | None = None) -> None:
    """[oc-10] Remove one or all channel bindings for an agent."""
    cfg = _load_oc()
    if channel is None:
        cfg.bindings = [b for b in cfg.bindings if b.agent_id != agent_id]
    else:
        cfg.bindings = [
            b
            for b in cfg.bindings
            if not (b.agent_id == agent_id and b.match.channel == channel)
        ]
    _save_oc(cfg)


# ── security config [oc-14 … oc-17] ───────────────────────────────────────────


def get_gates_enabled(cfg: OpenClawConfig | None = None) -> bool:
    """[oc-14]"""
    return (cfg or _load_oc()).security.gates.enabled


def set_gates_enabled(enabled: bool) -> None:
    """[oc-15]"""
    cfg = _load_oc()
    cfg.security.gates.enabled = enabled
    _save_oc(cfg)


def get_isolation_enabled(cfg: OpenClawConfig | None = None) -> bool:
    """[oc-16]"""
    return (cfg or _load_oc()).security.isolation.enabled


def set_isolation_enabled(enabled: bool) -> None:
    """[oc-17]"""
    cfg = _load_oc()
    cfg.security.isolation.enabled = enabled
    _save_oc(cfg)


# ── auth-profiles.json operations [ap-*] ──────────────────────────────────────


@dataclass
class ProfileSummary:
    id: str
    provider: str
    type: str
    disabled: bool
    disabled_reason: str


def auth_profiles_summary(agent: str = "main") -> list[ProfileSummary]:
    """[ap-01] Return profile list with disabled state.

    Mirrors the Bash auth_profiles_summary() pipe in lib/helpers/auth.sh.
    """
    path = auth_profiles_path(agent)
    if not path.exists():
        return []
    raw = store.read_json(path)
    data = AuthProfiles.model_validate(raw)
    now_ms = time.time() * 1000
    result: list[ProfileSummary] = []
    for pid, prof in data.profiles.items():
        usage = data.usage_stats.get(pid)
        disabled_until = usage.disabled_until if usage else 0.0
        disabled = disabled_until > now_ms
        disabled_reason = (usage.disabled_reason if usage else "") if disabled else ""
        result.append(
            ProfileSummary(
                id=pid,
                provider=prof.provider,
                type=prof.type,
                disabled=disabled,
                disabled_reason=disabled_reason,
            )
        )
    return result


def has_usable_profile(agent: str = "main") -> bool:
    """[ap-02] True if at least one non-disabled auth profile exists."""
    return any(not p.disabled for p in auth_profiles_summary(agent))


# ── provider config [pc-*] — stub, T5.6 ───────────────────────────────────────


def add_local_provider(
    name: str,
    base_url: str,
    model_id: str,
    api_key: str = "",
) -> None:
    """[pc-01] Register a local (Ollama / LM Studio / vLLM) provider.

    Full implementation: T5.6 (wire-local-provider → docket models provider add).
    Placeholder raises so callers know this surface is not yet wired.
    """
    raise NotImplementedError(
        "Local provider registration is not yet implemented (T5.6). "
        "Use `openclaw models provider add` directly for now."
    )


# ── telegram channel status ───────────────────────────────────────────────────


def get_telegram_enabled() -> bool:
    """Read channels.telegram.enabled from openclaw.json.

    Not modelled in OpenClawConfig (OpenClaw-internal); read via raw dict.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    channels = raw.get("channels")
    if not isinstance(channels, dict):
        return False
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return False
    return bool(telegram.get("enabled", False))


# ── generic dotted-path access (escape hatch for Bash bridge) ─────────────────


def oc_get_path(dotpath: str, default: str = "") -> str:
    """Read an arbitrary dotted path from openclaw.json.

    Used by the _json bridge for oc-get; prefer the typed methods above
    for all ported Python commands.
    """
    import json as _json  # local import to avoid polluting module namespace

    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    obj: Any = raw
    for part in dotpath.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return default
        if obj is None:
            return default
    if obj is None:
        return default
    # Serialise non-string values the same way json.dumps would in Bash.
    if isinstance(obj, (dict, list)):
        return _json.dumps(obj)
    return str(obj)


def oc_set_path(dotpath: str, json_value: str) -> None:
    """Write an arbitrary dotted path in openclaw.json (value must be valid JSON).

    Used by the _json bridge for oc-set; prefer the typed methods above
    for all ported Python commands.
    """
    import json as _json

    value: Any = _json.loads(json_value)
    raw = store.read_json(CONFIG_FILE)
    parts = dotpath.split(".")
    obj: Any = raw
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    obj[parts[-1]] = value
    store.write_json(CONFIG_FILE, raw)


# ── convenience: set model in BOTH stores atomically ──────────────────────────


def set_model_both(agent_id: str, model: str) -> None:
    """Update model in openclaw.json agents.list AND .docket-meta.json.

    The two writes are NOT in a single transaction; openclaw.json is updated
    first. If the second write fails, docket doctor will detect the drift.
    """
    set_agent_model(agent_id, model)
    meta_set(agent_id, "model", model)
