"""Anti-Corruption Layer: the single Python module that knows OpenClaw.

INVARIANT: No other Python module in this codebase may import or reference
openclaw.json, auth-profiles.json, session-JSONL, or any other OpenClaw-owned
file format. All knowledge of those formats lives here and nowhere else.

Phase 18 L-1 (D-14) added ``OpenClawDriver``, the one shipped implementation
of ``core.runtime_driver.RuntimeDriver`` — see that module's docstring for
the port's rationale. ``OpenClawDriver`` is what now owns the session-JSONL
cost/turn parsing that used to leak into ``core/utils.py`` and
``core/trace.py``; the free functions below (``agent_run``,
``register_agent_cli``, …) are unchanged and the driver delegates to them
directly, so nothing about their tested behavior moves.

Phase 19 P19-6 (D-19): agent registration, channel bindings, gates/isolation
flags and the org-wide default model no longer live in ``openclaw.json`` —
they moved to the docket-owned ``fleet.json`` (``core/fleet.py``'s
``FleetConfig``, read/written through ``edges/store.py``, never through the
raw-dict helpers below). This module still knows both formats: the
fleet-backed functions (``list_agents``, ``get_binding``, ``get_gates_enabled``,
…) and the still-daemon-owned raw ``openclaw.json`` helpers (auth profiles,
secrets, telegram/channel config, exec approvals, session-JSONL usage) that
are P19-7's job to delete along with the rest of this file.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import subprocess

import docket.config as _cfg
from docket.config import (
    CONFIG_FILE,
    FLEET_FILE,
    auth_profiles_path,
    meta_path,
)
from docket.core.fleet import (
    FleetAgent,
    FleetBinding,
    FleetConfig,
)
from docket.core.models import AgentMeta
from docket.core.runtime_driver import (
    DriverCapabilities,
    ProvisionResult,
    SessionSlice,
    SessionSummary,
    SessionTurn,
    TeardownResult,
    TurnResult,
    UsageDay,
    UsageReport,
    UsageTotals,
)
from docket.edges import store

# ─────────────────────────────────────────────────────────────────────────────
# auth-profiles.json models (Phase 19 P19-6: moved in from the now-deleted
# core/oc_models.py, which existed only for the ACL's own use. This is
# genuinely daemon-owned state — unlike the fleet registry, it is NOT being
# replaced by this card; it goes away entirely at P19-7 with the rest of the
# ACL, so it is kept lenient and undisturbed here rather than "improved".
# ─────────────────────────────────────────────────────────────────────────────

_LENIENT = ConfigDict(extra="allow", populate_by_name=True)


class AuthProfileUsage(BaseModel):
    model_config = _LENIENT

    disabled_until: float = Field(0.0, alias="disabledUntil")
    disabled_reason: str = Field("", alias="disabledReason")


class AuthProfile(BaseModel):
    model_config = _LENIENT

    provider: str = ""
    type: str = ""  # "token", "oauth", "api_key"


class AuthProfiles(BaseModel):
    """Shape of ~/.openclaw/agents/<agent>/agent/auth-profiles.json."""

    model_config = _LENIENT

    profiles: dict[str, AuthProfile] = Field(default_factory=dict)
    usage_stats: dict[str, AuthProfileUsage] = Field(default_factory=dict, alias="usageStats")


def load_config() -> FleetConfig:
    """Return the full fleet registry as a validated model (public entry point)."""
    return _load_fleet()


def _load_fleet() -> FleetConfig:
    raw = store.read_json(FLEET_FILE)
    return FleetConfig.model_validate(raw)


def _save_fleet(cfg: FleetConfig) -> None:
    store.write_json(FLEET_FILE, cfg)


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


def list_agents(cfg: FleetConfig | None = None) -> list[FleetAgent]:
    """Return the fleet's registered-agent list."""
    return (cfg or _load_fleet()).agents


def get_agent(agent_id: str, cfg: FleetConfig | None = None) -> FleetAgent | None:
    """Return one agent entry by id, or None if not registered."""
    for agent in (cfg or _load_fleet()).agents:
        if agent.id == agent_id:
            return agent
    return None


def agent_registered(agent_id: str, cfg: FleetConfig | None = None) -> bool:
    """Return True if agent_id is registered in the fleet."""
    return get_agent(agent_id, cfg) is not None


def get_default_model(cfg: FleetConfig | None = None) -> str:
    """Return the fleet's org-wide default model id."""
    return (cfg or _load_fleet()).defaults.model


def set_default_model(model: str) -> None:
    """Write the fleet's org-wide default model id."""
    cfg = _load_fleet()
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
    compatibility (pre-P19-6 callers pass all four) but are not stored here —
    ``.docket-meta.json`` (``AgentMeta``) is their one real home; duplicating
    them in the fleet registry is exactly the second-writer shape this card
    removes. See ``core/fleet.py``'s module docstring.
    """
    cfg = _load_fleet()
    if not agent_registered(agent_id, cfg):
        cfg.agents.append(FleetAgent(id=agent_id))
        _save_fleet(cfg)


def remove_agent(agent_id: str) -> None:
    """Remove agent_id from the fleet registry."""
    cfg = _load_fleet()
    cfg.agents = [a for a in cfg.agents if a.id != agent_id]
    _save_fleet(cfg)


def get_binding(agent_id: str, channel: str = "telegram", cfg: FleetConfig | None = None) -> str:
    """Return the peer id for a channel binding, or '' if none."""
    for b in (cfg or _load_fleet()).bindings:
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
    cfg = _load_fleet()
    cfg.bindings = [
        b for b in cfg.bindings if not (b.agent_id == agent_id and b.channel == channel)
    ]
    cfg.bindings.append(
        FleetBinding(agent_id=agent_id, channel=channel, peer_kind=peer_kind, peer_id=peer_id)
    )
    _save_fleet(cfg)


def remove_binding(agent_id: str, channel: str | None = None) -> None:
    """Remove one or all channel bindings for an agent."""
    cfg = _load_fleet()
    if channel is None:
        cfg.bindings = [b for b in cfg.bindings if b.agent_id != agent_id]
    else:
        cfg.bindings = [
            b for b in cfg.bindings if not (b.agent_id == agent_id and b.channel == channel)
        ]
    _save_fleet(cfg)


def wire_group(
    agent_id: str,
    peer_id: str,
    channel: str = "telegram",
    peer_kind: str = "group",
) -> bool:
    """Wire an agent to a channel peer: allowlist entry + binding upsert.

    Returns True if the openclaw allowlist step succeeded, False if unavailable.
    The binding is always written (to fleet.json) regardless of the allowlist
    result. The allowlist step itself is genuinely daemon-owned (it tells the
    running daemon which Telegram groups may message it at all) and is
    untouched by P19-6 — it goes away with the daemon at P19-7.
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


def get_gates_enabled(cfg: FleetConfig | None = None) -> bool:
    return (cfg or _load_fleet()).security.gates_enabled


def set_gates_enabled(enabled: bool) -> None:
    cfg = _load_fleet()
    cfg.security.gates_enabled = enabled
    _save_fleet(cfg)


def get_isolation_enabled(cfg: FleetConfig | None = None) -> bool:
    return (cfg or _load_fleet()).security.isolation_enabled


def set_isolation_enabled(enabled: bool) -> None:
    cfg = _load_fleet()
    cfg.security.isolation_enabled = enabled
    _save_fleet(cfg)


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


def agent_bindings(agent_id: str, cfg: FleetConfig | None = None) -> list[dict[str, str]]:
    """Return [{channel, peerId}, ...] for one agent's bindings."""
    return [
        {"channel": b.channel, "peerId": b.peer_id}
        for b in (cfg or _load_fleet()).bindings
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
    """Return the fleet's sandbox isolation mode ('unset' if never configured)."""
    return _load_fleet().security.isolation_mode


def get_approval_routing() -> tuple[str, str]:
    """Return (state, mode) for exec-approval routing; state is 'on' | 'off' | 'unset'."""
    sec = _load_fleet().security
    return (sec.approval_routing_state, sec.approval_routing_mode)


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
    """Return the number of agents registered in the fleet."""
    return len(_load_fleet().agents)


def configure_agent_defaults(default_model: str) -> None:
    """Write agents.defaults + ensure channels.telegram exists; seed the fleet default model.

    The openclaw.json block (workspace, safeguard compaction, concurrency caps,
    an enabled Telegram channel) is daemon-internal bootstrap state, unrelated
    to the fleet registry and untouched by P19-6 — it is written via the raw
    dict exactly as before. The default *model*, however, is a fleet concept
    since P19-6 (``get_default_model``/``set_default_model`` read/write
    fleet.json), so this also seeds it there — the one call site
    (``docket install``) that used to set both in one round-trip still does.
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
    set_default_model(default_model)


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
    extra: list[str] | None = None,
    provider: str = "anthropic",
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run `openclaw models auth setup-token --provider <provider> [extra...]`.

    ``provider`` defaults to "anthropic" for backward compatibility with
    every pre-existing call site (Phase 18 L-2 added the parameter so
    `docket auth --provider <x>` can thread a real choice through instead of
    the value being hardcoded).

    Interactive: stdio is NOT captured so the OAuth-like flow can prompt/print
    directly on the caller's terminal. Does not catch subprocess errors itself
    (matches the pre-ACL call sites — some let them propagate, some wrap this
    in their own try/except); returns the raw CompletedProcess.
    """
    import subprocess as _sp

    return _sp.run(
        ["openclaw", "models", "auth", "setup-token", "--provider", provider, *(extra or [])],
        timeout=timeout,
    )


def auth_paste_token(
    extra: list[str] | None = None,
    provider: str = "anthropic",
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run `openclaw models auth paste-token --provider <provider> [extra...]`.

    ``provider`` defaults to "anthropic" — see `auth_setup_token` docstring.

    Interactive: stdio is NOT captured — see `auth_setup_token` docstring.
    """
    import subprocess as _sp

    return _sp.run(
        ["openclaw", "models", "auth", "paste-token", "--provider", provider, *(extra or [])],
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


# R-2: typed classification of an ``ok=False`` turn, so callers (the retry loop
# in core/dispatch.py) can decide retryability from a field instead of
# string-matching ``error``. Only ``timeout``/``daemon_error`` are retryable — a
# transient hiccup talking to the daemon/CLI. ``nonzero_exit`` and
# ``invalid_output`` are real answers (the turn ran and said something, or the
# CLI is fundamentally misbehaving) and are never retried. Always ``None`` when
# ``ok`` is True. See ``core.runtime_driver.FailureKind``/``TurnResult`` (the
# RuntimeDriver port) for the canonical definitions.
#
# W-5 (Phase 16, finishing Phase 18 CL-1's blocked sweep): the ``AgentRunResult``
# alias that used to live here is gone. It existed only because
# ``core/dispatch.py``'s ``Runner`` type alias and roughly 76 test call sites
# across test_r2/r4/r5/r6/r7/cd2/dispatch/g1/l1 still spelled the pre-Phase-18-L-1
# name; CL-1 could not rename that file (a different in-flight card owned it at
# the time). W-5 owns ``core/dispatch.py`` this wave and swept every remaining
# call site to ``TurnResult`` directly, so the alias had zero references left
# anywhere in the tree and was deleted rather than kept as a compatibility shim.


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
    env: dict[str, str] | None = None,
    *,
    on_spawn: Callable[[int], None] | None = None,
) -> TurnResult:
    """Run one real agent turn via the openclaw CLI (the ONLY place docket does this).

    Each call is a real, costed LLM turn; the caller is responsible for budget gating.
    Returns TurnResult(ok=False, ...) on CLI missing, timeout, non-zero exit, or
    unparseable output — never raises for ordinary failure modes. ``failure_kind``
    classifies which of those it was (see ``FailureKind``), for retry decisions.

    ``env``, when given, is layered on top of the current process environment for
    this subprocess only (e.g. a pod's allocated port range / scratch dir) — the
    parent docket process's own environment is never mutated. ``None``/empty
    preserves today's behaviour of inheriting the parent env unchanged.

    ROADMAP Phase 16 W-2 (cancellation): the subprocess is started in its own
    session (``start_new_session=True``), so its pid doubles as its process
    group id. ``on_spawn`` — if given — fires with that pid immediately after
    the subprocess starts (before this call blocks on its output); docket's
    run registry (``core/runs.py``) uses this to record which OS process
    group a dispatch run is currently waiting on, so ``docket runs cancel``
    can kill it later from a separate process. A timeout here kills the
    *whole group* (``edges.adapters.system.kill_process_group``), not just
    the immediate ``openclaw`` process — it may itself have shelled out
    further (e.g. to ``git``/``npm``), and an orphaned process group is
    exactly the failure mode this guards against.
    """
    import json as _json
    import os as _os
    import shutil as _shutil
    import subprocess as _sp

    from docket.edges.adapters import system as _sys

    if not _shutil.which("openclaw"):
        return TurnResult(False, "", 0.0, {}, "openclaw CLI not found", failure_kind="daemon_error")
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
    run_env = {**_os.environ, **env} if env else None
    try:
        proc = _sp.Popen(
            cmd,
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            text=True,
            env=run_env,
            start_new_session=True,
        )
    except OSError as ex:
        return TurnResult(False, "", 0.0, {}, str(ex), failure_kind="daemon_error")

    if on_spawn is not None:
        on_spawn(proc.pid)

    try:
        out_raw, err_raw = proc.communicate(timeout=timeout + 15)
    except _sp.TimeoutExpired:
        _sys.kill_process_group(proc.pid)
        with contextlib.suppress(Exception):
            proc.communicate(timeout=5)
        return TurnResult(False, "", 0.0, {}, f"timed out after {timeout}s", failure_kind="timeout")
    except OSError as ex:
        return TurnResult(False, "", 0.0, {}, str(ex), failure_kind="daemon_error")

    out = (out_raw or "").strip()
    if proc.returncode != 0:
        reason = (err_raw or out or f"exit {proc.returncode}").strip()
        return TurnResult(False, "", 0.0, {}, reason, failure_kind="nonzero_exit")
    try:
        data: dict[str, Any] = _json.loads(out) if out else {}
    except _json.JSONDecodeError:
        # Non-JSON stdout still carries the reply text — surface it rather than fail.
        return TurnResult(True, out, 0.0, {}, "")
    if not isinstance(data, dict):
        return TurnResult(True, str(data), 0.0, {}, "")
    return TurnResult(
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
    """Update an agent's model.

    Pre-P19-6 this wrote both openclaw.json's agents.list AND
    .docket-meta.json, which was the exact second-writer shape that made
    drift possible. `.docket-meta.json` (`AgentMeta`) is model's one home now
    — the fleet registry never tracked it (see `core/fleet.py`) — so this is
    a single write. Kept as a named function (rather than inlining
    `meta_set` at every call site) since "update an agent's model" is a
    meaningful operation on its own, and it is what `docket profile`/
    `docket models set` call.
    """
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
    """Write the fleet's exec-approval routing state."""
    cfg = _load_fleet()
    cfg.security.approval_routing_state = "on" if enabled else "off"
    cfg.security.approval_routing_mode = mode
    _save_fleet(cfg)


def disable_approval_routing() -> None:
    """Turn exec-approval routing off."""
    cfg = _load_fleet()
    cfg.security.approval_routing_state = "off"
    _save_fleet(cfg)


def set_sandbox_isolation(
    mode: str = "non-main",
    scope: str = "agent",
    workspace_access: str = "rw",
) -> None:
    """Write the fleet's sandbox isolation mode.

    ``scope``/``workspace_access`` are accepted for call-site compatibility
    with the pre-P19-6 openclaw.json shape, but are not persisted: docket has
    never had a caller that passes anything but the defaults
    (``core/security.py``'s ``apply_workspace_isolation`` always calls this
    with mode="non-main" only), and the CLI's own status text
    (``cli/_gates.py``'s ``_isolate``) is already a static string, not a
    render of these fields.
    """
    cfg = _load_fleet()
    cfg.security.isolation_mode = mode
    cfg.security.isolation_enabled = mode not in ("off", "unset")
    _save_fleet(cfg)


def disable_sandbox_isolation() -> None:
    """Set the fleet's sandbox isolation mode to 'off'."""
    cfg = _load_fleet()
    cfg.security.isolation_mode = "off"
    cfg.security.isolation_enabled = False
    _save_fleet(cfg)


def all_agent_ids() -> list[str]:
    """Return agent ids registered in the fleet; 'main' is always included."""
    if not FLEET_FILE.exists():
        return ["main"]
    try:
        ids = [a.id for a in list_agents() if a.id]
    except Exception:
        return []
    return ids


# ─────────────────────────────────────────────────────────────────────────────
# RuntimeDriver port (Phase 18 L-1 / D-14): OpenClawDriver
#
# Everything below this line owns the session-JSONL parsing that used to leak
# into core/utils.py (aggregate_cost/cost_history) and core/trace.py
# (trace_ingest). See core/runtime_driver.py's module docstring for the port's
# rationale and core/dispatch.py for the one real integration point
# (``default_driver().run_turn`` is the pipeline's Runner).
# ─────────────────────────────────────────────────────────────────────────────


def _sessions_dir(agent_id: str) -> Path:
    """Daemon session-log directory for *agent_id* (OpenClaw's own layout)."""
    return _cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"


def _iso_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_session_jsonl(path: Path) -> dict[str, Any]:
    """Aggregate one session JSONL file's ``message.usage`` records.

    Moved verbatim from core/utils.py's ``_parse_session_file`` (Phase 18 L-1) —
    this is the actual daemon session-record format knowledge the card exists
    to pull out of ``core/``.
    """
    import json as _json

    t: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "cost": 0.0,
        "turns": 0,
    }
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data: dict[str, Any] = _json.loads(line)
            except Exception:
                continue
            msg = data.get("message", {})
            usage: dict[str, Any] = msg.get("usage", {}) if isinstance(msg, dict) else {}
            if usage:
                t["input"] = int(t["input"]) + int(usage.get("input", 0))
                t["output"] = int(t["output"]) + int(usage.get("output", 0))
                t["cacheRead"] = int(t["cacheRead"]) + int(usage.get("cacheRead", 0))
                t["cacheWrite"] = int(t["cacheWrite"]) + int(usage.get("cacheWrite", 0))
                cost_field = usage.get("cost", {})
                t["cost"] = float(t["cost"]) + (
                    float(cost_field.get("total", 0)) if isinstance(cost_field, dict) else 0.0
                )
                t["turns"] = int(t["turns"]) + 1
    except Exception:
        pass
    return t


def _write_cost_index(index_path: Path, index: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        store.write_json(index_path, index)


def _usage_totals(agent_id: str) -> UsageTotals:
    """Token/cost totals for *agent_id*, incrementally cached by (mtime, size).

    Moved verbatim from core/utils.py's ``aggregate_cost`` (Phase 18 L-1). Set
    ``DOCKET_NO_COST_INDEX=1`` to force a full recompute.
    """
    import json as _json
    import os as _os

    sessions_dir = _sessions_dir(agent_id)
    index_path = _cfg.OPENCLAW_DIR / "agents" / agent_id / ".cost-index.json"
    use_index = _os.environ.get("DOCKET_NO_COST_INDEX") != "1"

    index: dict[str, Any] = {}
    if use_index and index_path.exists():
        try:
            index = _json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}

    totals = UsageTotals()
    seen: set[str] = set()
    changed = False

    if sessions_dir.is_dir():
        for path in sorted(sessions_dir.glob("*.jsonl")):
            name = path.name
            seen.add(name)
            try:
                st = path.stat()
                sig: list[int] = [int(st.st_mtime), st.st_size]
            except OSError:
                continue

            ent = index.get(name)
            if use_index and ent and ent.get("sig") == sig:
                t: dict[str, Any] = ent["totals"]
            else:
                t = _parse_session_jsonl(path)
                index[name] = {"sig": sig, "totals": t}
                changed = True

            totals.input_tokens += int(t.get("input", 0))
            totals.output_tokens += int(t.get("output", 0))
            totals.cache_read += int(t.get("cacheRead", 0))
            totals.cache_write += int(t.get("cacheWrite", 0))
            totals.cost_usd += float(t.get("cost", 0.0))
            totals.turns += int(t.get("turns", 0))

    if use_index:
        for name in list(index.keys()):
            if name not in seen:
                del index[name]
                changed = True
        if changed:
            _write_cost_index(index_path, index)

    return totals


def _write_hist_index(
    hist_path: Path,
    sigs: dict[str, list[int]],
    hist: dict[str, dict[str, Any]],
) -> None:
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        store.write_json(hist_path, {"sigs": sigs, "history": hist})


def _usage_by_day(agent_id: str) -> list[UsageDay]:
    """Per-day token/cost breakdown for *agent_id*, cached by the file-set signature.

    Moved verbatim from core/utils.py's ``cost_history`` (Phase 18 L-1).
    """
    import json as _json
    import os as _os

    sessions_dir = _sessions_dir(agent_id)
    hist_path = _cfg.OPENCLAW_DIR / "agents" / agent_id / ".cost-history.json"
    use_index = _os.environ.get("DOCKET_NO_COST_INDEX") != "1"

    sigs: dict[str, list[int]] = {}
    files: list[Path] = []
    if sessions_dir.is_dir():
        files = sorted(sessions_dir.glob("*.jsonl"))
        for f in files:
            try:
                st = f.stat()
                sigs[f.name] = [int(st.st_mtime), st.st_size]
            except OSError:
                pass

    cached: dict[str, Any] = {}
    if use_index and hist_path.exists():
        try:
            cached = _json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            cached = {}

    hist: dict[str, dict[str, Any]]
    if use_index and cached.get("sigs") == sigs:
        hist = cached.get("history", {})
    else:
        hist = {}
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    d: dict[str, Any] = _json.loads(line)
                except Exception:
                    continue
                msg = d.get("message", {})
                usage: dict[str, Any] = msg.get("usage", {}) if isinstance(msg, dict) else {}
                if not usage:
                    continue
                ts = d.get("timestamp", "")
                day = ts[:10] if isinstance(ts, str) and len(ts) >= 10 else "unknown"
                b = hist.setdefault(day, {"turns": 0, "input": 0, "output": 0, "cost": 0.0})
                b["turns"] = int(b["turns"]) + 1
                b["input"] = int(b["input"]) + int(usage.get("input", 0))
                b["output"] = int(b["output"]) + int(usage.get("output", 0))
                cost_field = usage.get("cost", {})
                b["cost"] = float(b["cost"]) + (
                    float(cost_field.get("total", 0)) if isinstance(cost_field, dict) else 0.0
                )
        if use_index:
            _write_hist_index(hist_path, sigs, hist)

    return [
        UsageDay(
            date=day,
            turns=int(b["turns"]),
            input_tokens=int(b["input"]),
            output_tokens=int(b["output"]),
            cost_usd=round(float(b["cost"]), 6),
        )
        for day, b in sorted(hist.items())
    ]


def _read_new_turns(agent_id: str, session_id: str, offset: int) -> SessionSlice:
    """Decode one session file's records past *offset* (a line-count cursor).

    Moved verbatim (semantics-preserving) from core/trace.py's ``trace_ingest``
    inner loop (Phase 18 L-1) — the daemon session-record ``type``/``timestamp``
    vocabulary is decoded here and nowhere else.
    """
    import json as _json

    src = _sessions_dir(agent_id) / f"{session_id}.jsonl"
    try:
        all_lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return SessionSlice(session_id, False, "", [], None, offset)

    new_lines = all_lines[offset:]
    if not new_lines:
        return SessionSlice(session_id, False, "", [], None, offset)

    session_start_ts = ""
    with contextlib.suppress(Exception):
        session_start_ts = str(_json.loads(all_lines[0]).get("timestamp", ""))

    turns: list[SessionTurn] = []
    last_ts: str | None = None
    for line in new_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec: dict[str, Any] = _json.loads(stripped)
        except _json.JSONDecodeError:
            continue

        etype = str(rec.get("type", ""))
        ts = str(rec.get("timestamp", _iso_now()))
        last_ts = ts

        if etype == "tool_use":
            turns.append(
                SessionTurn(ts=ts, kind="tool_call", daemon_type=etype, record_id=rec.get("id"))
            )
        elif etype == "tool_result":
            turns.append(
                SessionTurn(ts=ts, kind="tool_result", daemon_type=etype, record_id=rec.get("id"))
            )
        # "message" and any other daemon record type: last_ts is updated above,
        # but nothing is projected — matches trace_ingest's pre-L-1 behaviour.

    return SessionSlice(
        session_id=session_id,
        had_new_content=True,
        session_start_ts=session_start_ts,
        turns=turns,
        last_ts=last_ts,
        next_offset=offset + len(new_lines),
    )


class OpenClawDriver:
    """The one shipped ``RuntimeDriver`` (Phase 18 L-1 / D-14).

    Every method either delegates to an existing, already-tested ACL free
    function (``run_turn``/``provision``/``teardown``) or owns session-JSONL
    parsing that used to live outside the ACL (``list_sessions``/
    ``read_new_turns``/``usage``). Stateless — safe to share via
    ``default_driver()`` or construct fresh; nothing here retains per-instance
    state.
    """

    def run_turn(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int = 300,
        env: dict[str, str] | None = None,
        *,
        on_spawn: Callable[[int], None] | None = None,
    ) -> TurnResult:
        return agent_run(agent_id, session_key, message, timeout, env, on_spawn=on_spawn)

    def provision(self, agent_id: str, workspace: str, model: str) -> ProvisionResult:
        ok, message = register_agent_cli(agent_id, workspace, model)
        return ProvisionResult(ok=ok, message=message)

    def teardown(self, agent_id: str) -> TeardownResult:
        ok, message = unregister_agent_cli(agent_id)
        return TeardownResult(ok=ok, message=message)

    def list_sessions(self, agent_id: str) -> list[SessionSummary]:
        sessions_dir = _sessions_dir(agent_id)
        if not sessions_dir.is_dir():
            return []
        return [
            SessionSummary(session_id=path.name[: -len(".jsonl")])
            for path in sorted(sessions_dir.glob("*.jsonl"))
        ]

    def read_new_turns(self, agent_id: str, session_id: str, offset: int) -> SessionSlice:
        return _read_new_turns(agent_id, session_id, offset)

    def usage(self, agent_id: str) -> UsageReport:
        return UsageReport(totals=_usage_totals(agent_id), by_day=_usage_by_day(agent_id))

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            driver_name="openclaw",
            # Confirmed against daemon v2026.2.23: `openclaw agent --json` never
            # populates a USD cost field, so run_turn's cost_usd is always 0.0
            # (see agent_run's docstring) even though usage()'s session-JSONL
            # read can surface a real recorded cost when a session file does
            # carry usage.cost.total.
            reports_cost_usd=False,
            supports_provisioning=True,
            supports_sessions=True,
        )


_DRIVER: OpenClawDriver | None = None


def default_driver() -> OpenClawDriver:
    """Return the process-wide ``OpenClawDriver`` singleton.

    Stateless, so a fresh instance would behave identically — this just gives
    callers (``core/dispatch.py``'s ``run = runner or default_driver().run_turn``)
    a single named object rather than constructing one per call.
    """
    global _DRIVER
    if _DRIVER is None:
        _DRIVER = OpenClawDriver()
    return _DRIVER
