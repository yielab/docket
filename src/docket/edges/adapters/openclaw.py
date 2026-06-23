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

  Provider config
    [pc-01]  add local provider                     models provider add
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
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
    """[oc-07] Return agents.defaults.model (normalised to a bare id string).

    OpenClaw may store this as a string or a {"primary": "<id>"} object; both
    are accepted and reduced to the model id here.
    """
    model = (cfg or _load_oc()).agents.defaults.model
    if isinstance(model, dict):
        return str(model.get("primary", ""))
    return model


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
                metadata=OcAgentMetadata(session_key=session_key, project_key=project_key),
            )
        )
        _save_oc(cfg)


def remove_agent(agent_id: str) -> None:
    """[oc-12] Remove agent from agents.list."""
    cfg = _load_oc()
    cfg.agents.items = [a for a in cfg.agents.items if a.id != agent_id]
    _save_oc(cfg)


# ── binding operations [oc-09 … oc-11] ────────────────────────────────────────


def get_binding(agent_id: str, channel: str = "telegram", cfg: OpenClawConfig | None = None) -> str:
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
        b for b in cfg.bindings if not (b.agent_id == agent_id and b.match.channel == channel)
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
            b for b in cfg.bindings if not (b.agent_id == agent_id and b.match.channel == channel)
        ]
    _save_oc(cfg)


def wire_group(
    agent_id: str,
    peer_id: str,
    channel: str = "telegram",
    peer_kind: str = "group",
) -> bool:
    """Wire an agent to a channel peer: allowlist entry + binding upsert.

    Returns True if the openclaw allowlist step succeeded, False if unavailable.
    The binding is always written regardless of the allowlist result.
    Mirrors _wire_group() in workspace.sh.
    """
    import subprocess as _sp

    allowlist_ok = False
    try:
        result = _sp.run(
            [
                "openclaw",
                "config",
                "set",
                f"channels.{channel}.groups.{peer_id}",
                '{"requireMention": false}',
            ],
            capture_output=True,
            timeout=10,
        )
        allowlist_ok = result.returncode == 0
    except (FileNotFoundError, OSError, _sp.TimeoutExpired):
        pass

    upsert_binding(agent_id, peer_id, channel, peer_kind)
    return allowlist_ok


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


# ── provider config [pc-*] ─────────────────────────────────────────────────────
#
# OpenClaw stores provider definitions under models.providers.<name>. That block
# is OpenClaw-internal (not modelled in OpenClawConfig), so — like the sandbox /
# approvals / channels reads above — it is accessed via the raw dict here, and
# ONLY here. No other module may touch models.providers.*.


def local_provider_config(
    base_url: str,
    model_id: str,
    model_name: str,
    ctx: int,
    max_tokens: int,
) -> dict[str, Any]:
    """Build the provider definition for a local OpenAI-compatible endpoint.

    Mirrors the PROVIDER_JSON Python heredoc in scripts/wire-local-provider.sh.
    apiKey is a literal dummy ("local") — llama.cpp ignores it but OpenClaw
    requires the field present. Cost is zero (local/free).
    """
    return {
        "baseUrl": base_url,
        "apiKey": "local",
        "api": "openai-completions",
        "models": [
            {
                "id": model_id,
                "name": model_name,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": int(ctx),
                "maxTokens": int(max_tokens),
            }
        ],
    }


def get_local_provider(name: str) -> dict[str, Any] | None:
    """[pc-01] Return the stored models.providers.<name> block, or None if absent."""
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    providers = (raw.get("models") or {}).get("providers")
    if not isinstance(providers, dict):
        return None
    entry = providers.get(name)
    return entry if isinstance(entry, dict) else None


def add_local_provider(
    name: str,
    base_url: str,
    model_id: str,
    model_name: str,
    ctx: int,
    max_tokens: int,
) -> bool:
    """[pc-01] Register a local (llama.cpp / LM Studio / vLLM) provider.

    Writes models.providers.<name> in openclaw.json. Idempotent: returns False
    (and writes nothing) when the existing block already matches the desired
    definition, True when it created or updated the entry.

    Mirrors `openclaw config set models.providers.<name> <json>` in
    scripts/wire-local-provider.sh (written directly so no openclaw CLI is
    required and the operation is transactional with docket's other writes).
    """
    desired = local_provider_config(base_url, model_id, model_name, ctx, max_tokens)

    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    models = raw.get("models")
    if not isinstance(models, dict):
        models = {}
        raw["models"] = models
    providers = models.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        models["providers"] = providers

    if providers.get(name) == desired:
        return False

    providers[name] = desired
    store.write_json(CONFIG_FILE, raw)
    return True


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


def channel_names() -> list[str]:
    """Return the configured channel keys from openclaw.json `channels`.

    Mirrors the `list(c.get('channels', {}).keys())` read in cmd_snapshot.
    Not modelled in OpenClawConfig (OpenClaw-internal); read via raw dict.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    channels = raw.get("channels")
    if not isinstance(channels, dict):
        return []
    return list(channels.keys())


def agent_bindings(agent_id: str, cfg: OpenClawConfig | None = None) -> list[dict[str, str]]:
    """Return [{channel, peerId}, ...] for one agent's bindings.

    Mirrors the agent_bindings() helper inside cmd_snapshot.
    """
    return [
        {"channel": b.match.channel, "peerId": b.match.peer.id}
        for b in (cfg or _load_oc()).bindings
        if b.agent_id == agent_id
    ]


# ── doctor: read-only posture reads ───────────────────────────────────────────


def get_config_perms() -> str:
    """Return the octal permission string of openclaw.json (e.g. '600'), or ''.

    Mirrors the `stat -c '%a'` call in cmd_doctor's config-hardening check.
    """
    import os as _os
    import stat as _stat

    if not CONFIG_FILE.exists():
        return ""
    try:
        mode = _stat.S_IMODE(_os.stat(CONFIG_FILE).st_mode)
    except OSError:
        return ""
    return format(mode, "o")


def get_isolation_mode() -> str:
    """Return agents.defaults.sandbox.mode from openclaw.json ('unset' if absent).

    Mirrors _isolation_status() in security.sh. The sandbox block is
    OpenClaw-internal and not modelled, so this reads the raw dict.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    defaults = agents.get("defaults") if isinstance(agents, dict) else None
    sandbox = defaults.get("sandbox") if isinstance(defaults, dict) else None
    if not isinstance(sandbox, dict):
        return "unset"
    mode = sandbox.get("mode")
    return str(mode) if mode else "unset"


def get_approval_routing() -> tuple[str, str]:
    """Return (state, mode) for approvals.exec routing.

    state is 'on' | 'off' | 'unset'. Mirrors _approval_routing_status() in
    security.sh. approvals is OpenClaw-internal; read from the raw dict.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    approvals = raw.get("approvals")
    exec_cfg = approvals.get("exec") if isinstance(approvals, dict) else None
    if not isinstance(exec_cfg, dict) or not exec_cfg:
        return ("unset", "")
    state = "on" if exec_cfg.get("enabled") else "off"
    return (state, str(exec_cfg.get("mode") or ""))


def secrets_keys() -> set[str]:
    """Return the set of key names stored in secrets.json (empty if absent)."""
    path = CONFIG_FILE.parent / "secrets.json"
    raw = store.read_json(path)
    return set(raw.keys())


def secrets_meta() -> dict[str, Any]:
    """Return the raw secrets.meta.json contents (empty if absent)."""
    path = CONFIG_FILE.parent / "secrets.meta.json"
    return store.read_json(path)


def security_gate_report() -> tuple[str, str, str]:
    """Return (state, policy, counts) for the daemon exec-approval policy.

    state: OK | OPEN | UNSET | NA. Mirrors _security_gate_report() in
    security.sh — shells out to `openclaw approvals get --json`.
    """
    import json as _json
    import shutil as _shutil
    import subprocess as _sp

    if not _shutil.which("openclaw"):
        return ("NA", "openclaw CLI not found", "")
    try:
        res = _sp.run(
            ["openclaw", "approvals", "get", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, _sp.TimeoutExpired):
        return ("NA", "approvals snapshot unavailable", "")
    out = res.stdout.strip()
    if not out:
        return ("NA", "approvals snapshot unavailable", "")
    try:
        d: dict[str, Any] = _json.loads(out)
    except Exception:
        return ("NA", "approvals snapshot unparseable", "")
    f = d.get("file") or {}
    defaults = (f.get("defaults") or {}) if isinstance(f, dict) else {}
    agents = (f.get("agents") or {}) if isinstance(f, dict) else {}
    sec = defaults.get("security") or "unset"
    ask = defaults.get("ask") or "unset"
    fb = defaults.get("askFallback") or "unset"
    allow_total = 0
    if isinstance(agents, dict):
        for a in agents.values():
            allow_total += len((a or {}).get("allowlist", []) or [])
    state = "OK" if sec in ("deny", "allowlist") else ("OPEN" if sec == "full" else "UNSET")
    policy = f"security={sec} ask={ask} askFallback={fb}"
    counts = f"agents={len(agents)} allowlisted={allow_total}"
    return (state, policy, counts)


@dataclass
class AuditFinding:
    title: str
    remediation: str


@dataclass
class SecurityAudit:
    available: bool
    critical: int
    warn: int
    info: int
    findings: list[AuditFinding]


def security_audit_report() -> SecurityAudit:
    """Summarise `openclaw security audit --json` (config-perms finding excluded).

    Mirrors _security_audit_report() in security.sh. Returns available=False
    when the audit cannot be run/parsed.
    """
    import json as _json
    import shutil as _shutil
    import subprocess as _sp

    none = SecurityAudit(False, 0, 0, 0, [])
    if not _shutil.which("openclaw"):
        return none
    try:
        res = _sp.run(
            ["openclaw", "security", "audit", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, _sp.TimeoutExpired):
        return none
    out = res.stdout.strip()
    if not out:
        return none
    try:
        d: dict[str, Any] = _json.loads(out)
    except Exception:
        return none
    owned = {"fs.config.perms_writable"}
    ext = [f for f in (d.get("findings") or []) if f.get("checkId") not in owned]
    crit = sum(1 for f in ext if f.get("severity") == "critical")
    warn = sum(1 for f in ext if f.get("severity") == "warn")
    info = sum(1 for f in ext if f.get("severity") == "info")
    findings: list[AuditFinding] = []
    for f in ext:
        if f.get("severity") == "critical" and len(findings) < 5:
            findings.append(AuditFinding(str(f.get("title", "?")), str(f.get("remediation", ""))))
    return SecurityAudit(True, crit, warn, info, findings)


# ── install bootstrap (cmd_install) ───────────────────────────────────────────


def config_exists() -> bool:
    """True if openclaw.json is present (the Bash `[[ -f $CONFIG_FILE ]]` gate)."""
    return CONFIG_FILE.is_file()


def has_agent_defaults() -> bool:
    """True if openclaw.json already carries agents.defaults.

    Mirrors the inline `'agents' in c and 'defaults' in c['agents']` probe in
    cmd_install (Step: detect-existing). Tolerant of a malformed/absent file.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    return isinstance(agents, dict) and "defaults" in agents


def agent_count() -> int:
    """Return the number of registered agents (len of agents.list).

    Mirrors the `len(c.get('agents', {}).get('list', []))` read in cmd_install.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    items = agents.get("list") if isinstance(agents, dict) else None
    return len(items) if isinstance(items, list) else 0


def configure_agent_defaults(default_model: str) -> None:
    """Write agents.defaults + ensure channels.telegram (cmd_install Step 4).

    Faithful port of the embedded Python heredoc in install.sh: sets the default
    model, workspace, safeguard compaction, concurrency caps, and an enabled
    Telegram channel with an empty groups map. These blocks are OpenClaw-internal
    (not modelled in OpenClawConfig), so they are written via the raw dict here.
    """
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)

    agents = raw.get("agents")
    if not isinstance(agents, dict):
        agents = {}
        raw["agents"] = agents

    workspace = raw.get("workspacesDir", "~/.openclaw/workspace")
    agents["defaults"] = {
        "model": {"primary": default_model},
        "workspace": workspace,
        "compaction": {"mode": "safeguard"},
        "maxConcurrent": 4,
        "subagents": {"maxConcurrent": 8},
    }

    channels = raw.get("channels")
    if not isinstance(channels, dict):
        channels = {}
        raw["channels"] = channels
    if "telegram" not in channels:
        channels["telegram"] = {"enabled": True, "groups": {}}

    store.write_json(CONFIG_FILE, raw)


def register_agent_cli(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
    """Register an agent via `openclaw agents add` (cmd_install Step 5).

    Shells out to the OpenClaw CLI — the daemon owns agent registration, so this
    lives behind the ACL. Returns (ok, message): ok is False with a reason when
    the CLI is missing or the command fails. Mirrors the `openclaw agents add`
    invocation in install.sh.
    """
    import shutil as _shutil
    import subprocess as _sp

    if not _shutil.which("openclaw"):
        return (False, "openclaw CLI not found")
    try:
        res = _sp.run(
            [
                "openclaw",
                "agents",
                "add",
                agent_id,
                "--workspace",
                workspace,
                "--model",
                model,
                "--non-interactive",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, _sp.TimeoutExpired) as ex:
        return (False, str(ex))
    if res.returncode != 0:
        return (False, (res.stderr or res.stdout or f"exit {res.returncode}").strip())
    return (True, "")


def harden_config_perms() -> list[str]:
    """chmod 600 openclaw.json / secrets.json if group/other-accessible (G2).

    Returns the list of paths it tightened (empty if all were already owner-only).
    Only tightens, never loosens. Mirrors secure_config_perms() in security.sh.
    """
    import os as _os
    import stat as _stat

    hardened: list[str] = []
    for path in (CONFIG_FILE, CONFIG_FILE.parent / "secrets.json"):
        if not path.is_file():
            continue
        try:
            mode = _stat.S_IMODE(_os.stat(path).st_mode)
        except OSError:
            continue
        # Any group/other bit set => the low 6 mode bits are non-zero.
        if mode & 0o077:
            try:
                _os.chmod(path, 0o600)
            except OSError:
                continue
            hardened.append(str(path))
    return hardened


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


# ── exec-approval gates (G3) — exec-approvals.json + daemon apply ──────────────


def exec_approvals_path() -> Path:
    """Path to the daemon's exec-approvals.json (OpenClaw-owned)."""
    return CONFIG_FILE.parent / "exec-approvals.json"


def read_exec_approvals() -> dict[str, Any]:
    """Return the parsed exec-approvals.json ({} if absent/malformed)."""
    raw = store.read_json(exec_approvals_path())
    return raw if isinstance(raw, dict) else {}


def write_exec_approvals(data: dict[str, Any]) -> bool:
    """Write exec-approvals.json, preferring the validated daemon path.

    Tries ``openclaw approvals set <tmp>`` first; on success returns True
    (applied-via-daemon). If the CLI is absent or fails, writes the file
    directly (0600) and returns False (applied-direct). Mirrors the
    daemon-vs-direct branch in apply_exec_approval_gates().
    """
    import json as _json
    import os as _os
    import shutil as _shutil
    import subprocess as _sp
    import tempfile as _tempfile

    path = exec_approvals_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    serialised = _json.dumps(data, indent=2) + "\n"

    if _shutil.which("openclaw"):
        fd, tmp_name = _tempfile.mkstemp(suffix=".json")
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialised)
            try:
                res = _sp.run(
                    ["openclaw", "approvals", "set", tmp_name],
                    capture_output=True,
                    timeout=10,
                )
            except (OSError, _sp.TimeoutExpired):
                res = None
            if res is not None and res.returncode == 0:
                return True
        finally:
            with contextlib.suppress(OSError):
                _os.unlink(tmp_name)

    # Direct write (gateway not reached).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(serialised, encoding="utf-8")
    _os.chmod(tmp, 0o600)
    _os.replace(tmp, path)
    return False


# ── approval routing + sandbox isolation (G4 / G5) — openclaw.json writes ──────


def set_approval_routing(enabled: bool, mode: str = "session") -> None:
    """Write approvals.exec = {enabled, mode} in openclaw.json (G4)."""
    raw = store.read_json(CONFIG_FILE)
    approvals = raw.setdefault("approvals", {})
    if not isinstance(approvals, dict):
        approvals = {}
        raw["approvals"] = approvals
    approvals["exec"] = {"enabled": enabled, "mode": mode}
    store.write_json(CONFIG_FILE, raw)


def disable_approval_routing() -> None:
    """Set approvals.exec.enabled = false (escape hatch, G4)."""
    if not CONFIG_FILE.exists():
        return
    raw = store.read_json(CONFIG_FILE)
    approvals = raw.get("approvals")
    exec_cfg = approvals.get("exec") if isinstance(approvals, dict) else None
    if not isinstance(exec_cfg, dict):
        return
    exec_cfg["enabled"] = False
    store.write_json(CONFIG_FILE, raw)


def set_sandbox_isolation(
    mode: str = "non-main",
    scope: str = "agent",
    workspace_access: str = "rw",
) -> None:
    """Write agents.defaults.sandbox = {mode, scope, workspaceAccess} (G5)."""
    raw = store.read_json(CONFIG_FILE)
    agents = raw.setdefault("agents", {})
    if not isinstance(agents, dict):
        agents = {}
        raw["agents"] = agents
    defaults = agents.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        defaults = {}
        agents["defaults"] = defaults
    defaults["sandbox"] = {
        "mode": mode,
        "scope": scope,
        "workspaceAccess": workspace_access,
    }
    store.write_json(CONFIG_FILE, raw)


def disable_sandbox_isolation() -> None:
    """Set agents.defaults.sandbox.mode = "off" (escape hatch, G5)."""
    if not CONFIG_FILE.exists():
        return
    raw = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    defaults = agents.get("defaults") if isinstance(agents, dict) else None
    sandbox = defaults.get("sandbox") if isinstance(defaults, dict) else None
    if not isinstance(sandbox, dict):
        return
    sandbox["mode"] = "off"
    store.write_json(CONFIG_FILE, raw)


def all_agent_ids() -> list[str]:
    """Return agent ids registered in openclaw.json (always including 'main').

    Mirrors _all_agent_ids() in security.sh: the explicit 'main' agent is
    appended so the curated allowlist is always seeded for it.
    """
    if not CONFIG_FILE.exists():
        return ["main"]
    try:
        ids = [a.id for a in list_agents() if a.id]
    except Exception:
        return []
    return ids
