"""``docket pod show`` -- the pod and its effective configuration, with provenance.

Read-only. This module writes nothing and adds no new resolution logic: it composes
existing resolvers (model policy, `core.identity`'s prompt composer, role/tool
denial, the guardrail policy engine, `core.pod.PodSettings`, and
`core.dispatch.effective_pipeline_source`) into one report so an operator can see
what a real dispatch turn would actually use, instead of tracing several modules by
hand. See specs/data/cli-json-shapes.spec.md, "`docket pod show --json`".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import archetypes as _archetypes
from docket.core import dispatch as _dispatch
from docket.core import exporter as _exporter
from docket.core import fleet as _fleet
from docket.core import identity as _identity
from docket.core import mcp_tools as _mcp_tools
from docket.core import pod as _pod
from docket.core import pod_apply as _pod_apply
from docket.core import policy as _policy
from docket.core import provider as _provider
from docket.core import skills as _skills
from docket.core import tools as _tools
from docket.core.models import AgentKind, AgentMeta
from docket.edges import store as _store
from docket.edges.adapters import llm as _llm


def _roots_for(agent_id: str, meta: AgentMeta) -> tuple[Path, ...]:
    """The containment roots a standalone turn would resolve for *agent_id*: codebase >
    work_dir > the agent's own workspace (mirrors ``edges/adapters/docket_runtime.py``'s
    ``_resolve_roots``, reproduced for display; a dispatched task's worktree is per task)."""
    if meta.codebase:
        return (Path(meta.codebase),)
    if meta.work_dir:
        return (Path(meta.work_dir),)
    return (_cfg.workspace_dir(agent_id),)


_SOURCE_SCOPE: dict[str, str] = {"built-in": "built-in", "starter": "built-in", "user": "global"}


def _scope_label(source: str) -> str:
    """Map ``ArchetypeRegistry.source_of``'s ``built-in | starter | user | pod:<p>``
    onto this report's ``built-in | global | pod`` provenance model."""
    if source.startswith("pod:"):
        return "pod"
    return _SOURCE_SCOPE.get(source, "")


def _policies_for_role(role: str, project: str) -> list[dict[str, str]]:
    """Installed policies whose ``applies_to`` covers *role*, read from
    ``policy_files(project)``, each carrying its ``scope`` (``pod`` for this pod's own
    ``config/policies/`` directory, else ``global``)."""
    pod_policies_dir = _cfg.pod_config_dir(project) / "policies" if project else None
    matched: list[dict[str, str]] = []
    for path in _policy.policy_files(project):
        try:
            doc: dict[str, Any] = _policy.read_policy(path)
        except Exception:
            continue
        if _policy.validate_policy(path):
            continue
        applies = doc.get("applies_to") or []
        if "*" in applies or role in applies:
            is_pod_file = pod_policies_dir is not None and path.parent == pod_policies_dir
            scope = "pod" if is_pod_file else "global"
            matched.append(
                {
                    "id": str(doc.get("id", path.stem)),
                    "hook": str(doc.get("hook", "")),
                    "action": str(doc.get("action", "")),
                    "scope": scope,
                }
            )
    return matched


def _mcp_servers_report(
    pod_settings: _pod.PodSettings | None, project: str = ""
) -> list[dict[str, Any]]:
    """Every MCP server a turn would load: the pod's own ``mcpServers`` selection when
    set (``scope: "pod"``), else the full catalog -- global servers (``scope: "global"``)
    and the pod's own pod-scoped ones (``scope: "pod"``)."""
    catalog = sorted(_mcp_tools.load_mcp_servers(project), key=lambda s: s.name)
    selected = pod_settings.mcp_servers if pod_settings is not None else None
    if selected is None:
        own = {s.name for s in _mcp_tools.load_pod_mcp_servers(project)} if project else set()
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "scope": "pod" if s.name in own else "global",
                "isolate": s.isolate,
            }
            for s in catalog
        ]
    by_name = {s.name: s for s in catalog}
    return [
        {"name": name, "kind": by_name[name].kind, "scope": "pod", "isolate": by_name[name].isolate}
        for name in sorted(selected)
        if name in by_name
    ]


def _pod_settings_report(settings: _pod.PodSettings, project: str) -> dict[str, dict[str, Any]]:
    """Every ``PodSettings`` key's effective value and source ("set"/"default") --
    the ``settings`` object of ``docket pod show --json``."""
    report: dict[str, dict[str, Any]] = {}
    for key in _pod.PodSettings.KEYS:
        value, source = settings.value_and_source(key, project)
        report[key] = {"value": value, "source": source}
    return report


def _config_of_record_report(settings: _pod.PodSettings | None) -> dict[str, str]:
    """``configSource``/``configDigest`` (ADR 0012) plus ``drift``: ``"yes"``/``"no"`` when the
    source directory is still present and its digest is recomputed, ``""`` when there is no
    recorded source or the directory is gone (drift is then simply unknown, not asserted)."""
    if settings is None or not settings.config_source:
        return {"configSource": "", "configDigest": "", "drift": ""}
    source_dir = Path(settings.config_source)
    drift = ""
    if source_dir.is_dir():
        current = _pod_apply.directory_digest(source_dir)
        drift = "yes" if current != settings.config_digest else "no"
    return {
        "configSource": settings.config_source,
        "configDigest": settings.config_digest,
        "drift": drift,
    }


def _provider_report(model: str) -> dict[str, Any]:
    """Where *model* resolves: catalog scope, dialect, base URL, the credential's
    name/source and the exact model row -- the provenance ``resolve_endpoint``
    itself does not report. See model-profiles.spec.md "Provider catalog" 7."""
    provider_name, _, model_id = model.partition("/")
    if not model_id:
        provider_name, model_id = "", model

    catalog = _provider.load_catalog()
    spec = catalog.get(provider_name) if provider_name else None
    endpoint = _llm.resolve_endpoint(model)

    if spec is not None:
        credential_name = spec.auth.credentials[0] if spec.auth.credentials else ""
        _value, credential_source = _provider.resolve_credential(spec)
        exact = next((row for row in spec.models if row.id == model_id), None)
        return {
            "name": spec.name,
            "scope": catalog.source_of(provider_name),
            "dialect": spec.dialect,
            "baseUrl": spec.base_url,
            "credential": {"name": credential_name, "source": credential_source},
            "model": {
                "id": model_id,
                "contextWindow": exact.context_window if exact else None,
                "maxTokens": exact.max_tokens if exact else None,
                "source": "row" if exact is not None else "none",
            },
        }

    return {
        "name": provider_name,
        "scope": "",
        "dialect": "openai-chat",
        "baseUrl": endpoint.base_url if endpoint else None,
        "credential": {
            "name": "",
            "source": "env" if endpoint is not None and endpoint.api_key else "none",
        },
        "model": {
            "id": model_id,
            "contextWindow": endpoint.context_window_tokens if endpoint else None,
            "maxTokens": endpoint.max_output_tokens if endpoint else None,
            "source": "none",
        },
    }


def _skills_report(project: str, roots: tuple[Path, ...]) -> list[dict[str, str]]:
    """Every skill a live turn's ``# Skills`` prompt section would list: ``name`` and
    ``scope`` (``codebase | pod | global``), the same three-scope, nearest-wins discovery
    ``core.identity`` composes from (ADR 0013 §3 rule 8)."""
    codebase_root = roots[0] if roots else None
    discovered = _skills.discover_skills(project, codebase_root)
    return [{"name": name, "scope": discovered[name].scope} for name in sorted(discovered)]


def _exporters_report() -> list[dict[str, Any]]:
    """Every catalog exporter's activation state and today's health counters -- global, not
    per-agent (an exporter has no per-pod scope; see observability-export.spec.md
    "Activation")."""
    catalog = _exporter.load_catalog()
    health = _exporter.read_health()
    report: list[dict[str, Any]] = []
    for name in sorted(catalog.entries):
        spec = catalog.entries[name]
        state, _missing = _exporter.activation_state(spec, health.get(name))
        _values, credential_source = _exporter.resolve_credentials(spec)
        record = health.get(name, {})
        report.append(
            {
                "name": name,
                "dialect": spec.dialect,
                "state": state,
                "scope": catalog.source_of(name),
                "credentialSource": credential_source,
                "privacy": {"label": spec.privacy_label, "classes": sorted(spec.privacy_classes)},
                "exported": record.get("exported", 0),
                "dropped": record.get("dropped", 0),
                "failed": record.get("failed", 0),
                "lastError": record.get("lastError", ""),
            }
        )
    return report


def member_report(agent_id: str) -> dict[str, Any]:
    """Compose one member's effective configuration. Raises ``DispatchError``/
    ``PodSettingsError`` unchanged when this pod's stored settings are invalid --
    never silently substitutes a default."""
    raw = _store.read_json(_cfg.meta_path(agent_id))
    meta = AgentMeta.model_validate(raw) if raw else AgentMeta(kind=AgentKind.project)
    role = str(raw.get("role", ""))
    project = _pod.pod_of(agent_id) or ""

    model = str(raw.get("model") or "") or _cfg.DEFAULT_MODEL
    model_source = _model_source(role, project)
    readiness = _provider.model_readiness(model)
    provider_report = _provider_report(model)

    roots = _roots_for(agent_id, meta)
    composition = _identity.compose_agent_prompt(
        agent_id,
        project_roots=roots,
        context_window_tokens=readiness.context_window,
        max_output_tokens=readiness.max_output,
    )

    # Never substitute a default for a bad stored value -- raised here, before any of the resolvers below that also read
    # this pod's settings, so every value below reflects a validated PodSettings.
    pod_settings = _pod.PodSettings.load_for(project) if project else None

    role_registry_scope = _archetypes.load_registry(project)
    role_scope = _scope_label(role_registry_scope.source_of(role))

    base_registry = _tools.builtin_registry()
    role_registry = (
        _archetypes.registry_for_role(base_registry, role, project) if role else base_registry
    )
    pod_denied = set(pod_settings.denied_tools) if pod_settings is not None else set()
    denied = [
        {"name": name, "scope": "pod" if name in pod_denied else role_scope}
        for name in sorted(set(base_registry.names()) - set(role_registry.names()))
    ]
    mcp_servers = _mcp_servers_report(pod_settings, project)

    pod_settings_report = _pod_settings_report(pod_settings, project) if pod_settings else None
    pipeline = {"source": _dispatch.effective_pipeline_source(project)} if project else None
    config_of_record = _config_of_record_report(pod_settings)
    if pod_settings is not None and roots:
        pi_files, pi_source = _identity.project_instruction_files(pod_settings, roots[0])
    else:
        pi_files, pi_source = (), ""
    skills_report = _skills_report(project, roots)

    return {
        "id": agent_id,
        "workspace": str(_cfg.workspace_dir(agent_id)),
        "role": role,
        "roleScope": role_scope,
        "pod": project,
        "model": {"value": model, "source": model_source},
        "endpoint": {
            "baseUrl": readiness.base_url,
            "ready": readiness.ready,
            "contextWindowTokens": readiness.context_window,
            "maxOutputTokens": readiness.max_output,
            "issue": readiness.issue,
        },
        "provider": provider_report,
        "prompt": {
            "budgetTokens": composition.budget_tokens,
            "budgetSource": composition.budget_source,
            "sections": [
                {"name": s.name, "bytes": s.bytes, "status": s.status} for s in composition.sections
            ],
        },
        "tools": {
            "allowed": sorted(role_registry.names()),
            "denied": denied,
            "mcpServers": mcp_servers,
        },
        "policies": _policies_for_role(role, project),
        "pipeline": pipeline,
        "podSettings": pod_settings_report,
        "network": dict(
            zip(("mode", "scope"), _pod.effective_network(project or None), strict=True)
        ),
        "projectInstructions": {"files": list(pi_files), "source": pi_source},
        "skills": skills_report,
        "exporters": _exporters_report(),
        "configSource": config_of_record["configSource"],
        "configDigest": config_of_record["configDigest"],
        "drift": config_of_record["drift"],
    }


def _model_source(role: str, project: str) -> str:
    """Where a member's model comes from: the pod's own role overlay, else the role policy."""
    if project and role and _archetypes.load_registry(project).source_of(role).startswith("pod:"):
        return "pod overlay"
    return "policy"


def _caller_default() -> str:
    """The approval default an unset ``approvalMode`` takes for this caller: ``wait`` on a
    TTY, ``park`` without one."""
    return "wait" if sys.stdin.isatty() else "park"


def pod_report(project: str) -> dict[str, Any]:
    """The pod as one report; raises ``DispatchError``/``PodSettingsError`` when it is missing
    or its stored settings are invalid."""
    _dispatch.pod_pipeline(project)
    settings = _pod.PodSettings.load_for(project)
    ids = [a.id for a in _fleet.list_agents()]
    members = [
        {
            "id": mid,
            "role": role,
            "model": {
                "value": _fleet.meta_get(mid, "model", "") or _cfg.DEFAULT_MODEL,
                "source": _model_source(role, project),
            },
            "workspace": str(_cfg.workspace_dir(mid)),
            "verifyCmd": _fleet.meta_get(mid, "verifyCmd", ""),
        }
        for mid, role, _idx in _pod.members_of(ids, project)
    ]
    caller = _caller_default()
    approval = _dispatch.pod_approval_mode(project, caller_default=caller)  # type: ignore[arg-type]
    record = _config_of_record_report(settings)
    return {
        "pod": project,
        "members": members,
        "settings": _pod_settings_report(settings, project),
        "approvalMode": {
            "effective": approval,
            "source": "set" if _dispatch.pod_approval_mode_is_set(project) else "unset",
        },
        "pipeline": {"source": _dispatch.effective_pipeline_source(project)},
        "network": dict(zip(("mode", "scope"), _pod.effective_network(project), strict=True)),
        **record,
    }


def _kv(label: str, value: object) -> None:
    ui.console.print(f"  {label} {value}", markup=False, highlight=False, soft_wrap=True)


def render_pod(report: dict[str, Any]) -> None:
    ui.header("pod", report["pod"])
    ui.section("Members")
    ui.table(
        [
            [
                m["id"],
                m["role"],
                f"{m['model']['value']} ({m['model']['source']})",
                m["verifyCmd"] or "-",
            ]
            for m in report["members"]
        ],
        ["MEMBER", "ROLE", "MODEL", "VERIFY"],
    )
    ui.section("Settings")
    ui.table(
        [[key, str(e["value"]), e["source"]] for key, e in report["settings"].items()],
        ["KEY", "VALUE", "SOURCE"],
    )
    approval = report["approvalMode"]
    ui.section("Dispatch")
    note = "unset: park without a TTY, wait on one" if approval["source"] == "unset" else "set"
    _kv("Approval mode:", f"{approval['effective']} ({note})")
    _kv("Pipeline:", report["pipeline"]["source"])
    net = report["network"]
    _kv("Network:", f"{net['mode']} ({net['scope']})")
    if report["configSource"]:
        drift = report["drift"] or "unknown"
        _kv(
            "Config source:",
            f"{report['configSource']} (digest {report['configDigest'][:12]}..., drift: {drift})",
        )


def _render_endpoint(report: dict[str, Any]) -> None:
    model = report["model"]
    _kv("Role:", report["role"] or "(none)")
    _kv("Pod:", report["pod"] or "(not a pod member)")
    _kv("Workspace:", report["workspace"])
    _kv("Model:", f"{model['value']} ({model['source']})")
    endpoint = report["endpoint"]
    ready = "ready" if endpoint["ready"] else f"NOT ready - {endpoint['issue']}"
    _kv("Endpoint:", f"{endpoint['baseUrl'] or '(unresolved)'} ({ready})")
    provider = report["provider"]
    credential = provider["credential"]
    _kv(
        "Provider:",
        f"{provider['name'] or '(unresolved)'} ({provider['scope'] or 'unresolved'},"
        f" {provider['dialect']})",
    )
    _kv("Credential:", f"{credential['name'] or '(none)'} ({credential['source']})")


def _render_tools(report: dict[str, Any]) -> None:
    tools = report["tools"]
    mcp = [
        m["name"] if m.get("isolate", True) else f"{m['name']} (unjailed)"
        for m in tools["mcpServers"]
    ]
    ui.section("Tools")
    _kv("Tools allowed:", ", ".join(tools["allowed"]) or "(none)")
    _kv("Tools denied: ", ", ".join(d["name"] for d in tools["denied"]) or "(none)")
    _kv("MCP servers:  ", ", ".join(mcp) or "(none configured)")
    ui.section("Guardrail policies")
    if report["policies"]:
        ui.table(
            [[p["id"], p["hook"], p["action"]] for p in report["policies"]],
            ["ID", "HOOK", "ACTION"],
        )
    else:
        ui.dim("  No guardrail policies apply to this role.")


def _render_context(report: dict[str, Any]) -> None:
    prompt = report["prompt"]
    ui.section("Prompt composition")
    ui.table(
        [[s["name"], str(s["bytes"]), s["status"]] for s in prompt["sections"]],
        ["SECTION", "BYTES", "STATUS"],
    )
    ui.dim(f"  Static-context budget: {prompt['budgetTokens']} tokens ({prompt['budgetSource']})")
    pi = report["projectInstructions"]
    skills = ", ".join(f"{s['name']} ({s['scope']})" for s in report["skills"]) or "none"
    ui.section("Context")
    _kv("Project instr.:", f"{', '.join(pi['files'])} ({pi['source']})" if pi["source"] else "none")
    _kv("Skills:", skills)
    ui.section("Exporters")
    if report["exporters"]:
        for exp in report["exporters"]:
            _kv(
                f"{exp['name']:<14}",
                f"{exp['dialect']:<10} {exp['state']:<16} ({exp['scope']},"
                f" privacy: {exp['privacy']['label']})",
            )
    else:
        _kv("none", "enabled")


def render_member(report: dict[str, Any]) -> None:
    ui.header("member", report["id"])
    _render_endpoint(report)
    _render_tools(report)
    _render_context(report)
    if report["pipeline"] is not None:
        _kv("Pipeline:", report["pipeline"]["source"])
    net = report["network"]
    _kv("Network:", f"{net['mode']} ({net['scope']})")
    if report["configSource"]:
        drift = report["drift"] or "unknown"
        _kv(
            "Config source:",
            f"{report['configSource']} (digest {report['configDigest'][:12]}..., drift: {drift})",
        )
    if report["podSettings"] is not None:
        ui.section("Pod settings")
        ui.table(
            [[k, str(e["value"]), e["source"]] for k, e in report["podSettings"].items()],
            ["KEY", "VALUE", "SOURCE"],
        )
