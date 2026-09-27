"""``docket config explain <agent>`` — the effective configuration, with provenance.

Read-only. This module writes nothing and adds no new resolution logic: it composes
existing resolvers (model policy, `core.identity`'s prompt composer, role/tool
denial, the guardrail policy engine, `core.pod.PodSettings`, and
`core.dispatch.effective_pipeline_source`) into one report so an operator can see
what a real dispatch turn would actually use, instead of tracing several modules by
hand. See specs/data/cli-json-shapes.spec.md, "`docket config explain <agent>
--json`".
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.core import archetypes as _archetypes
from docket.core import dispatch as _dispatch
from docket.core import identity as _identity
from docket.core import mcp_tools as _mcp_tools
from docket.core import models_policy as _mp
from docket.core import pod as _pod
from docket.core import pod_apply as _pod_apply
from docket.core import policy as _policy
from docket.core import provider as _provider
from docket.core import tools as _tools
from docket.core.models import AgentKind, AgentMeta
from docket.edges import store as _store
from docket.edges.adapters import llm as _llm

_USAGE = "Usage: docket config explain <agent-id> [--json]"


def dispatch(sub: str | None, extra: list[str]) -> None:
    """``docket config <action> ...`` — today's only action is ``explain``."""
    if sub != "explain":
        ui.error(f"Unknown config action {sub!r}. {_USAGE}")
        raise typer.Exit(1)

    json_out = "--json" in extra
    rest = [a for a in extra if a != "--json"]
    if len(rest) != 1:
        ui.error(_USAGE)
        raise typer.Exit(1)
    agent_id = rest[0]

    if not _cfg.workspace_dir(agent_id).is_dir():
        ui.error(f"Agent '{agent_id}' not found.")
        raise typer.Exit(1)

    try:
        report = _explain(agent_id)
    except (_dispatch.DispatchError, _pod.PodSettingsError) as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    if json_out:
        print(_json.dumps(report, indent=2))
    else:
        _render_human(agent_id, report)


def _roots_for(agent_id: str, meta: AgentMeta, worktree_dir: str) -> tuple[Path, ...]:
    """The containment roots a real turn would resolve for *agent_id*: worktree >
    codebase > work_dir > the agent's own workspace (mirrors
    ``edges/adapters/docket_runtime.py``'s ``_resolve_roots``, reproduced for display)."""
    if worktree_dir:
        return (Path(worktree_dir),)
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


def _mcp_servers_report(pod_settings: _pod.PodSettings | None) -> list[dict[str, str]]:
    """Every MCP server a turn would load: the pod's own ``mcpServers`` selection when
    set (``scope: "pod"``), else the full shared catalog (``scope: "global"``)."""
    catalog = sorted(_mcp_tools.load_mcp_servers(), key=lambda s: s.name)
    selected = pod_settings.mcp_servers if pod_settings is not None else None
    if selected is None:
        return [{"name": s.name, "kind": s.kind, "scope": "global"} for s in catalog]
    by_name = {s.name: s for s in catalog}
    return [
        {"name": name, "kind": by_name[name].kind, "scope": "pod"}
        for name in sorted(selected)
        if name in by_name
    ]


def _pod_settings_report(settings: _pod.PodSettings, project: str) -> dict[str, dict[str, Any]]:
    """Every ``PodSettings`` key's effective value and source ("set"/"default") --
    same shape as ``docket pod <p> config get --json``."""
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


def _explain(agent_id: str) -> dict[str, Any]:
    """Compose one agent's effective configuration. Raises ``DispatchError``/
    ``PodSettingsError`` unchanged when this pod's stored settings are invalid --
    never silently substitutes a default (matches ``docket pod <p> config get``)."""
    raw = _store.read_json(_cfg.meta_path(agent_id))
    meta = AgentMeta.model_validate(raw) if raw else AgentMeta(kind=AgentKind.project)
    role = str(raw.get("role", ""))
    project = _pod.pod_of(agent_id) or ""

    model = str(raw.get("model") or "") or _cfg.DEFAULT_MODEL
    model_source = _mp.agent_model_source(agent_id)
    readiness = _provider.model_readiness(model)
    provider_report = _provider_report(model)

    worktree_dir = str(raw.get("worktreeDir") or "")
    roots = _roots_for(agent_id, meta, worktree_dir)
    composition = _identity.compose_agent_prompt(
        agent_id,
        project_roots=roots,
        context_window_tokens=readiness.context_window,
        max_output_tokens=readiness.max_output,
    )

    # Never substitute a default for a bad stored value (matches `docket pod <p>
    # config get`) -- raised here, before any of the resolvers below that also read
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
    mcp_servers = _mcp_servers_report(pod_settings)

    pod_settings_report = _pod_settings_report(pod_settings, project) if pod_settings else None
    pipeline = {"source": _dispatch.effective_pipeline_source(project)} if project else None
    config_of_record = _config_of_record_report(pod_settings)

    return {
        "id": agent_id,
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
        "configSource": config_of_record["configSource"],
        "configDigest": config_of_record["configDigest"],
        "drift": config_of_record["drift"],
    }


def _render_human(agent_id: str, report: dict[str, Any]) -> None:
    ui.header(f"Effective configuration — {agent_id}")
    ui.console.print()
    ui.console.print(f"  [bold]{'Role:':<16}[/bold] {report['role'] or '(none)'}")
    ui.console.print(f"  [bold]{'Pod:':<16}[/bold] {report['pod'] or '(not a pod member)'}")
    model = report["model"]
    ui.console.print(
        f"  [bold]{'Model:':<16}[/bold] {model['value']}  [dim]({model['source']})[/dim]"
    )
    endpoint = report["endpoint"]
    ready = "ready" if endpoint["ready"] else f"NOT ready — {endpoint['issue']}"
    ui.console.print(
        f"  [bold]{'Endpoint:':<16}[/bold] {endpoint['baseUrl'] or '(unresolved)'}  [dim]({ready})[/dim]"
    )
    provider = report["provider"]
    credential = provider["credential"]
    provider_name = provider["name"] or "(unresolved)"
    scope = provider["scope"] or "unresolved"
    ui.console.print(
        f"  [bold]{'Provider:':<16}[/bold] {provider_name}  [dim]({scope}, {provider['dialect']})[/dim]"
    )
    ui.console.print(
        f"  [bold]{'Credential:':<16}[/bold] {credential['name'] or '(none)'}"
        f"  [dim]({credential['source']})[/dim]"
    )
    ui.console.print()

    table = Table(title="Prompt composition")
    table.add_column("SECTION", style="bold")
    table.add_column("BYTES", justify="right")
    table.add_column("STATUS", style="dim")
    for section in report["prompt"]["sections"]:
        table.add_row(section["name"], str(section["bytes"]), section["status"])
    ui.console.print(table)
    ui.dim(
        f"  Static-context budget: {report['prompt']['budgetTokens']} tokens "
        f"({report['prompt']['budgetSource']})"
    )
    ui.console.print()

    tools = report["tools"]
    denied_names = [d["name"] for d in tools["denied"]]
    mcp_names = [m["name"] for m in tools["mcpServers"]]
    ui.console.print(f"  [bold]Tools allowed:[/bold] {', '.join(tools['allowed']) or '(none)'}")
    ui.console.print(f"  [bold]Tools denied:[/bold]  {', '.join(denied_names) or '(none)'}")
    ui.console.print(f"  [bold]MCP servers:[/bold]   {', '.join(mcp_names) or '(none configured)'}")
    ui.console.print()

    if report["policies"]:
        table = Table(title="Guardrail policies")
        table.add_column("ID", style="bold")
        table.add_column("HOOK")
        table.add_column("ACTION")
        for p in report["policies"]:
            table.add_row(p["id"], p["hook"], p["action"])
        ui.console.print(table)
    else:
        ui.dim("  No guardrail policies apply to this role.")
    ui.console.print()

    if report["pipeline"] is not None:
        ui.console.print(f"  [bold]{'Pipeline:':<16}[/bold] {report['pipeline']['source']}")
    if report["configSource"]:
        drift = report["drift"] or "unknown"
        ui.console.print(
            f"  [bold]{'Config source:':<16}[/bold] {report['configSource']}"
            f"  [dim](digest {report['configDigest'][:12]}..., drift: {drift})[/dim]"
        )
    if report["podSettings"] is not None:
        table = Table(title="Pod dispatch settings")
        table.add_column("KEY", style="bold")
        table.add_column("VALUE")
        table.add_column("SOURCE", style="dim")
        for key, entry in report["podSettings"].items():
            table.add_row(key, str(entry["value"]), entry["source"])
        ui.console.print(table)
