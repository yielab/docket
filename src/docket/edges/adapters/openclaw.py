"""Anti-Corruption Layer: the single Python module that knows OpenClaw.

INVARIANT: No other Python module in this codebase may import or reference
openclaw.json, auth-profiles.json, or any other OpenClaw-owned file format.
All knowledge of those formats lives here and nowhere else.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import subprocess

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


def load_config() -> OpenClawConfig:
    """Return the full openclaw.json as a validated model (public entry point)."""
    return _load_oc()


def _load_oc() -> OpenClawConfig:
    raw = store.read_json(CONFIG_FILE)
    return OpenClawConfig.model_validate(raw)


def _strip_empty_modeled_keys(data: dict[str, Any]) -> None:
    """Drop the modeled `metadata` block and an empty `security` block before writing.

    docket models a per-agent `metadata` object (sessionKey/projectKey) so its
    in-memory model round-trips, but current OpenClaw versions REJECT an
    unrecognised `metadata` key on an agent entry and refuse to start (verified
    against 2026.2.23: ``agents.list.N: Unrecognized key: "metadata"``). docket's
    source of truth for sessionKey/projectKey is `.docket-meta.json`, so the
    `metadata` block is **never persisted to openclaw.json** — it is stripped
    unconditionally here (a real sessionKey is not "synced" into openclaw.json;
    that was an unfulfillable contract given the daemon schema). The default
    (all-off) `security` block is likewise stripped when empty. Other empty
    defaults (e.g. an empty `bindings` list) are untouched.
    """
    for agent in data.get("agents", {}).get("list", []):
        agent.pop("metadata", None)
    sec = data.get("security")
    if (
        isinstance(sec, dict)
        and set(sec) <= {"gates", "isolation"}
        and not sec.get("gates", {}).get("enabled")
        and not sec.get("isolation", {}).get("enabled")
    ):
        data.pop("security", None)


def _save_oc(cfg: OpenClawConfig) -> None:
    data = cfg.model_dump(by_alias=True, exclude_none=False)
    _strip_empty_modeled_keys(data)
    store.write_json(CONFIG_FILE, data)


def meta_read(agent_id: str) -> AgentMeta:
    """Read and validate the full .docket-meta.json for an agent."""
    path = meta_path(agent_id)
    raw = store.read_json(path)
    return AgentMeta.model_validate(raw)


def meta_get(agent_id: str, field: str, default: str = "") -> str:
    """Read a single string field from .docket-meta.json."""
    path = meta_path(agent_id)
    if not path.exists():
        return default
    raw = store.read_json(path)
    val = raw.get(field)
    return str(val) if val is not None else default


def meta_set(agent_id: str, field: str, value: Any) -> None:
    """Write a single field to .docket-meta.json; validates the full record before writing."""
    path = meta_path(agent_id)
    raw = store.read_json(path)
    raw[field] = value
    AgentMeta.model_validate(raw)
    store.write_json(path, raw)


def meta_write(agent_id: str, meta: AgentMeta) -> None:
    """Replace the full .docket-meta.json for an agent."""
    path = meta_path(agent_id)
    store.write_json(path, meta.model_dump(by_alias=True, exclude_none=False))


def list_agents(cfg: OpenClawConfig | None = None) -> list[OcAgent]:
    """Return the full agents.list from openclaw.json."""
    return (cfg or _load_oc()).agents.items


def get_agent(agent_id: str, cfg: OpenClawConfig | None = None) -> OcAgent | None:
    """Return one agent entry by id, or None if not registered."""
    for agent in (cfg or _load_oc()).agents.items:
        if agent.id == agent_id:
            return agent
    return None


def agent_registered(agent_id: str, cfg: OpenClawConfig | None = None) -> bool:
    """Return True if agent_id is in openclaw.json agents.list."""
    return get_agent(agent_id, cfg) is not None


def set_agent_model(agent_id: str, model: str) -> None:
    """Update the model field for one agent in agents.list."""
    cfg = _load_oc()
    for agent in cfg.agents.items:
        if agent.id == agent_id:
            agent.model = model
            _save_oc(cfg)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def set_agent_session_key(agent_id: str, session_key: str) -> None:
    """Update metadata.sessionKey for one agent."""
    oc = _load_oc()
    for agent in oc.agents.items:
        if agent.id == agent_id:
            agent.metadata.session_key = session_key
            _save_oc(oc)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def set_agent_project_key(agent_id: str, project_key: str) -> None:
    """Update metadata.projectKey for one agent."""
    oc = _load_oc()
    for agent in oc.agents.items:
        if agent.id == agent_id:
            agent.metadata.project_key = project_key
            _save_oc(oc)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def sync_session_key(agent_id: str, session_key: str, project_key: str) -> None:
    """Write both sessionKey and projectKey in one round-trip."""
    oc = _load_oc()
    for agent in oc.agents.items:
        if agent.id == agent_id:
            agent.metadata.session_key = session_key
            agent.metadata.project_key = project_key
            _save_oc(oc)
            return
    raise KeyError(f"Agent '{agent_id}' not found in openclaw.json")


def get_default_model(cfg: OpenClawConfig | None = None) -> str:
    """Return agents.defaults.model as a bare id string.

    OpenClaw stores this as either a string or {"primary": "<id>"}; both are
    normalised to the id here.
    """
    model = (cfg or _load_oc()).agents.defaults.model
    if isinstance(model, dict):
        return str(model.get("primary", ""))
    return model


def set_default_model(model: str) -> None:
    """Write agents.defaults.model."""
    cfg = _load_oc()
    cfg.agents.defaults.model = model
    _save_oc(cfg)


def add_agent(
    agent_id: str,
    model: str,
    session_key: str = "",
    project_key: str = "",
) -> None:
    """Append an agent to agents.list (no-op if already present)."""
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
    """Remove agent from agents.list."""
    cfg = _load_oc()
    cfg.agents.items = [a for a in cfg.agents.items if a.id != agent_id]
    _save_oc(cfg)


def get_binding(agent_id: str, channel: str = "telegram", cfg: OpenClawConfig | None = None) -> str:
    """Return the peer id for a channel binding, or '' if none."""
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
    """Add or replace a channel binding for an agent."""
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
    """Remove one or all channel bindings for an agent."""
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


def get_gates_enabled(cfg: OpenClawConfig | None = None) -> bool:
    return (cfg or _load_oc()).security.gates.enabled


def set_gates_enabled(enabled: bool) -> None:
    cfg = _load_oc()
    cfg.security.gates.enabled = enabled
    _save_oc(cfg)


def get_isolation_enabled(cfg: OpenClawConfig | None = None) -> bool:
    return (cfg or _load_oc()).security.isolation.enabled


def set_isolation_enabled(enabled: bool) -> None:
    cfg = _load_oc()
    cfg.security.isolation.enabled = enabled
    _save_oc(cfg)


@dataclass
class ProfileSummary:
    id: str
    provider: str
    type: str
    disabled: bool
    disabled_reason: str


def auth_profiles_summary(agent: str = "main") -> list[ProfileSummary]:
    """Return profile list with disabled state."""
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
    """True if at least one non-disabled auth profile exists."""
    return any(not p.disabled for p in auth_profiles_summary(agent))


def local_provider_config(
    base_url: str,
    model_id: str,
    model_name: str,
    ctx: int,
    max_tokens: int,
) -> dict[str, Any]:
    """Build the provider definition for a local OpenAI-compatible endpoint.

    apiKey is a literal dummy ("local") — llama.cpp ignores it but OpenClaw
    requires the field to be present. Cost is zero (local inference).
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
    """Return the stored models.providers.<name> block, or None if absent."""
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
    """Register a local (llama.cpp / LM Studio / vLLM) provider.

    Writes models.providers.<name> in openclaw.json. Idempotent: returns False
    when the existing block already matches. Written directly so no openclaw CLI
    is required and the operation is transactional with docket's other writes.
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


def get_telegram_enabled() -> bool:
    """Read channels.telegram.enabled from openclaw.json (OpenClaw-internal; raw dict)."""
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    channels = raw.get("channels")
    if not isinstance(channels, dict):
        return False
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return False
    return bool(telegram.get("enabled", False))


def channel_names() -> list[str]:
    """Return the configured channel keys from openclaw.json `channels`."""
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    channels = raw.get("channels")
    if not isinstance(channels, dict):
        return []
    return list(channels.keys())


def agent_bindings(agent_id: str, cfg: OpenClawConfig | None = None) -> list[dict[str, str]]:
    """Return [{channel, peerId}, ...] for one agent's bindings."""
    return [
        {"channel": b.match.channel, "peerId": b.match.peer.id}
        for b in (cfg or _load_oc()).bindings
        if b.agent_id == agent_id
    ]


def get_config_perms() -> str:
    """Return the octal permission string of openclaw.json (e.g. '600'), or ''."""
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
    """Return agents.defaults.sandbox.mode from openclaw.json ('unset' if absent)."""
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    defaults = agents.get("defaults") if isinstance(agents, dict) else None
    sandbox = defaults.get("sandbox") if isinstance(defaults, dict) else None
    if not isinstance(sandbox, dict):
        return "unset"
    mode = sandbox.get("mode")
    return str(mode) if mode else "unset"


def get_approval_routing() -> tuple[str, str]:
    """Return (state, mode) for approvals.exec routing; state is 'on' | 'off' | 'unset'."""
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


def secrets_values() -> list[str]:
    """Return the stored secret VALUES (for trace/Telegram redaction).

    Mirrors the ``_docket_stored_key_values`` hook redact.sh consults: the file
    backend stores ``{KEY: value}`` in secrets.json, so the values are the dict
    values; the keyring backend keeps only an index there (no values at rest),
    so it returns nothing. Empty/short values are the caller's concern.
    """
    import os as _os
    import shutil as _shutil
    import subprocess as _sp

    path = CONFIG_FILE.parent / "secrets.json"
    raw = store.read_json(path)
    if not raw:
        return []
    backend = "file"
    if _os.environ.get("DOCKET_SECRETS_BACKEND") == "keyring" and _shutil.which("secret-tool"):
        backend = "keyring"
    if backend == "keyring":
        service = _os.environ.get("DOCKET_KEYRING_SERVICE", "docket-cli")
        out: list[str] = []
        for key in raw:
            try:
                res = _sp.run(
                    ["secret-tool", "lookup", "service", service, "key", str(key)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, _sp.SubprocessError):
                continue
            if res.stdout:
                out.append(res.stdout)
        return out
    return [str(v) for v in raw.values() if v]


def security_gate_report() -> tuple[str, str, str]:
    """Return (state, policy, counts) for the daemon exec-approval policy.

    state: OK | OPEN | UNSET | NA. Shells out to `openclaw approvals get --json`.
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

    Returns available=False when the audit cannot be run or parsed.
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


def config_exists() -> bool:
    """True if openclaw.json is present."""
    return CONFIG_FILE.is_file()


def has_agent_defaults() -> bool:
    """True if openclaw.json already carries agents.defaults (tolerant of missing/malformed file)."""
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    return isinstance(agents, dict) and "defaults" in agents


def agent_count() -> int:
    """Return the number of registered agents."""
    raw: dict[str, Any] = store.read_json(CONFIG_FILE)
    agents = raw.get("agents")
    items = agents.get("list") if isinstance(agents, dict) else None
    return len(items) if isinstance(items, list) else 0


def configure_agent_defaults(default_model: str) -> None:
    """Write agents.defaults + ensure channels.telegram exists.

    Sets the default model, workspace, safeguard compaction, concurrency caps,
    and an enabled Telegram channel. These blocks are OpenClaw-internal and
    not modelled in OpenClawConfig, so they are written via the raw dict.
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


@dataclass
class VersionProbe:
    """Outcome of probing `openclaw --version`.

    available=False means the subprocess never returned cleanly (binary missing,
    launch error, or timeout) — output/returncode are meaningless in that case.
    Callers apply their own fallback text; this stays a raw, honest probe.
    """

    available: bool
    returncode: int
    output: str


def openclaw_version(timeout: float = 5) -> VersionProbe:
    """Run `openclaw --version` and return the raw outcome. Never raises."""
    import subprocess as _sp

    try:
        res = _sp.run(["openclaw", "--version"], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, OSError, _sp.TimeoutExpired):
        return VersionProbe(available=False, returncode=-1, output="")
    return VersionProbe(
        available=True, returncode=res.returncode, output=(res.stdout or "").strip()
    )


@dataclass
class AgentsAddResult:
    """Outcome of `openclaw agents add <id> --workspace <ws> --model <model> --non-interactive`.

    found=False means the openclaw binary was not on PATH — the process was
    never launched (the caller typically falls back to a direct openclaw.json
    write in that case). timed_out covers both an actual timeout and any
    OSError raised launching the process.
    """

    found: bool
    ok: bool
    returncode: int | None
    timed_out: bool


def agents_add(agent_id: str, workspace: str, model: str, timeout: float = 15) -> AgentsAddResult:
    """Register an agent via `openclaw agents add ... --non-interactive`. Never raises."""
    import shutil as _shutil
    import subprocess as _sp

    if not _shutil.which("openclaw"):
        return AgentsAddResult(found=False, ok=False, returncode=None, timed_out=False)
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
            timeout=timeout,
        )
    except (OSError, _sp.TimeoutExpired):
        return AgentsAddResult(found=True, ok=False, returncode=None, timed_out=True)
    return AgentsAddResult(
        found=True, ok=res.returncode == 0, returncode=res.returncode, timed_out=False
    )


def auth_setup_token(
    extra: list[str] | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run `openclaw models auth setup-token --provider anthropic [extra...]`.

    Interactive: stdio is NOT captured so the OAuth-like flow can prompt/print
    directly on the caller's terminal. Does not catch subprocess errors itself
    (matches the pre-ACL call sites — some let them propagate, some wrap this
    in their own try/except); returns the raw CompletedProcess.
    """
    import subprocess as _sp

    return _sp.run(
        ["openclaw", "models", "auth", "setup-token", "--provider", "anthropic", *(extra or [])],
        timeout=timeout,
    )


def auth_paste_token(
    extra: list[str] | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run `openclaw models auth paste-token --provider anthropic [extra...]`.

    Interactive: stdio is NOT captured — see `auth_setup_token` docstring.
    """
    import subprocess as _sp

    return _sp.run(
        ["openclaw", "models", "auth", "paste-token", "--provider", "anthropic", *(extra or [])],
        timeout=timeout,
    )


def onboard(timeout: float = 600) -> bool:
    """Run `openclaw onboard` interactively (no output capture). Never raises.

    Returns True on a clean (exit 0) run, False on any failure/timeout/missing
    binary — mirrors the pre-ACL caller, which ignores the return value and
    only uses this for its side effect.
    """
    import subprocess as _sp

    try:
        res = _sp.run(["openclaw", "onboard"], timeout=timeout)
    except (OSError, _sp.TimeoutExpired):
        return False
    return res.returncode == 0


def register_agent_cli(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
    """Register an agent via `openclaw agents add`.

    Shells out to the OpenClaw CLI — the daemon owns agent registration.
    Returns (ok, message); ok is False with a reason on CLI missing or failure.
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


def unregister_agent_cli(agent_id: str) -> tuple[bool, str]:
    """Delete an agent via `openclaw agents delete <id> --force`.

    The daemon owns agent lifecycle, so this lives behind the ACL.
    Returns (ok, message); ok is False with a reason on CLI missing or failure.
    """
    import shutil as _shutil
    import subprocess as _sp

    if not _shutil.which("openclaw"):
        return (False, "openclaw CLI not found")
    try:
        res = _sp.run(
            ["openclaw", "agents", "delete", agent_id, "--force"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, _sp.TimeoutExpired) as ex:
        return (False, str(ex))
    if res.returncode != 0:
        return (False, (res.stderr or res.stdout or f"exit {res.returncode}").strip())
    return (True, "")


@dataclass
class AgentRunResult:
    """Outcome of one `openclaw agent` turn.

    cost_usd is always 0.0 against daemon v2026.2.23 — that version returns only
    token counts (usage.input/output), not a USD cost field.
    """

    ok: bool
    output: str
    cost_usd: float  # 0.0 when the daemon doesn't report a USD cost
    raw: dict[str, Any]  # full parsed JSON (empty when unparseable)
    error: str = ""


# Confirmed daemon shape (v2026.2.23): text at result.payloads[0].text.
# No USD cost field — only token counts under result.meta.agentMeta.usage.
# _RUN_OUTPUT_KEYS / _RUN_COST_KEYS are tolerant fallbacks for test shims and
# possible future schema changes. First non-empty match wins.
_RUN_OUTPUT_KEYS = ("output", "text", "response", "message", "reply", "content")
_RUN_COST_KEYS = ("costUsd", "cost_usd", "cost", "totalCostUsd")


def _extract_run_output(data: dict[str, Any]) -> str:
    # Primary shape (v2026.2.23): result.payloads[0].text
    result = data.get("result")
    if isinstance(result, dict):
        payloads = result.get("payloads")
        if isinstance(payloads, list) and payloads:
            first = payloads[0]
            if isinstance(first, dict):
                text = first.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    # Tolerant fallback for test shims and possible future schema changes.
    for key in _RUN_OUTPUT_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            for sub in ("text", "content", "output"):
                inner = val.get(sub)
                if isinstance(inner, str) and inner.strip():
                    return inner
    return ""


def _extract_run_cost(data: dict[str, Any]) -> float:
    for key in _RUN_COST_KEYS:
        val = data.get(key)
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            with contextlib.suppress(ValueError):
                return float(val)
    return 0.0


def agent_run(
    agent_id: str,
    session_key: str,
    message: str,
    timeout: int = 300,
) -> AgentRunResult:
    """Run one real agent turn via the openclaw CLI (the ONLY place docket does this).

    Each call is a real, costed LLM turn; the caller is responsible for budget gating.
    Returns AgentRunResult(ok=False, ...) on CLI missing, timeout, non-zero exit, or
    unparseable output — never raises for ordinary failure modes.
    """
    import json as _json
    import shutil as _shutil
    import subprocess as _sp

    if not _shutil.which("openclaw"):
        return AgentRunResult(False, "", 0.0, {}, "openclaw CLI not found")
    cmd = [
        "openclaw",
        "agent",
        "--agent",
        agent_id,
        "--session-id",
        session_key,
        "-m",
        message,
        "--json",
        "--timeout",
        str(int(timeout)),
    ]
    try:
        res = _sp.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
    except _sp.TimeoutExpired:
        return AgentRunResult(False, "", 0.0, {}, f"timed out after {timeout}s")
    except OSError as ex:
        return AgentRunResult(False, "", 0.0, {}, str(ex))

    out = (res.stdout or "").strip()
    if res.returncode != 0:
        reason = (res.stderr or out or f"exit {res.returncode}").strip()
        return AgentRunResult(False, "", 0.0, {}, reason)
    try:
        data: dict[str, Any] = _json.loads(out) if out else {}
    except _json.JSONDecodeError:
        # Non-JSON stdout still carries the reply text — surface it rather than fail.
        return AgentRunResult(True, out, 0.0, {}, "")
    if not isinstance(data, dict):
        return AgentRunResult(True, str(data), 0.0, {}, "")
    return AgentRunResult(
        ok=True,
        output=_extract_run_output(data),
        cost_usd=_extract_run_cost(data),
        raw=data,
    )


def harden_config_perms() -> list[str]:
    """chmod 600 openclaw.json / secrets.json if group/other-accessible.

    Returns the list of paths tightened (empty if all were already owner-only).
    Only tightens, never loosens.
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
        if mode & 0o077:  # any group/other bit set
            try:
                _os.chmod(path, 0o600)
            except OSError:
                continue
            hardened.append(str(path))
    return hardened


def oc_get_path(dotpath: str, default: str = "") -> str:
    """Read an arbitrary dotted path from openclaw.json; prefer the typed methods above."""
    import json as _json

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
    """Write an arbitrary dotted path in openclaw.json; prefer the typed methods above."""
    import json as _json

    value: Any = _json.loads(json_value)
    raw = store.read_json(CONFIG_FILE)
    parts = dotpath.split(".")
    obj: Any = raw
    for part in parts[:-1]:
        obj = obj.setdefault(part, {})
    obj[parts[-1]] = value
    store.write_json(CONFIG_FILE, raw)


def set_model_both(agent_id: str, model: str) -> None:
    """Update model in openclaw.json agents.list AND .docket-meta.json.

    The two writes are NOT in a single transaction; openclaw.json is updated
    first. If the second write fails, docket doctor will detect the drift.
    """
    set_agent_model(agent_id, model)
    meta_set(agent_id, "model", model)


def exec_approvals_path() -> Path:
    """Path to the daemon's exec-approvals.json (OpenClaw-owned)."""
    return CONFIG_FILE.parent / "exec-approvals.json"


def read_exec_approvals() -> dict[str, Any]:
    """Return the parsed exec-approvals.json ({} if absent/malformed)."""
    raw = store.read_json(exec_approvals_path())
    return raw if isinstance(raw, dict) else {}


def write_exec_approvals(data: dict[str, Any]) -> bool:
    """Write exec-approvals.json, preferring the daemon path.

    Tries ``openclaw approvals set <tmp>`` first (returns True on success).
    Falls back to a direct 0600 write if the CLI is absent or fails (returns False).
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

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(serialised, encoding="utf-8")
    _os.chmod(tmp, 0o600)
    _os.replace(tmp, path)
    return False


def set_approval_routing(enabled: bool, mode: str = "session") -> None:
    """Write approvals.exec = {enabled, mode} in openclaw.json."""
    raw = store.read_json(CONFIG_FILE)
    approvals = raw.setdefault("approvals", {})
    if not isinstance(approvals, dict):
        approvals = {}
        raw["approvals"] = approvals
    approvals["exec"] = {"enabled": enabled, "mode": mode}
    store.write_json(CONFIG_FILE, raw)


def disable_approval_routing() -> None:
    """Set approvals.exec.enabled = false."""
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
    """Write agents.defaults.sandbox = {mode, scope, workspaceAccess}."""
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
    """Set agents.defaults.sandbox.mode = "off"."""
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
    """Return agent ids registered in openclaw.json; 'main' is always included."""
    if not CONFIG_FILE.exists():
        return ["main"]
    try:
        ids = [a.id for a in list_agents() if a.id]
    except Exception:
        return []
    return ids
