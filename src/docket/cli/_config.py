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
from docket.core import policy as _policy
from docket.core import provider as _provider
from docket.core import tools as _tools
from docket.core.models import AgentKind, AgentMeta
from docket.edges import store as _store

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


def _policies_for_role(role: str) -> list[dict[str, str]]:
    """Installed policies whose ``applies_to`` covers *role* (``"*"`` or the role
    itself) — the same membership test ``core.policy.policy_eval_detail`` applies,
    read straight from ``policy_files()`` rather than re-evaluating any text."""
    matched: list[dict[str, str]] = []
    for path in _policy.policy_files():
        try:
            doc: dict[str, Any] = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(doc, dict) or _policy.validate_policy(path):
            continue
        applies = doc.get("applies_to") or []
        if "*" in applies or role in applies:
            matched.append(
                {
                    "id": str(doc.get("id", path.stem)),
                    "hook": str(doc.get("hook", "")),
                    "action": str(doc.get("action", "")),
                }
            )
    return matched


def _pod_settings_report(project: str) -> dict[str, dict[str, Any]]:
    """Every ``PodSettings`` key's effective value and source ("set"/"default") --
    same shape as ``docket pod <p> config get --json``. Propagates
    ``PodSettingsError`` (an invalid stored value refuses, never guesses a default)."""
    settings = _pod.PodSettings.load_for(project)
    report: dict[str, dict[str, Any]] = {}
    for key in _pod.PodSettings.KEYS:
        value, source = settings.value_and_source(key, project)
        report[key] = {"value": value, "source": source}
    return report


def _explain(agent_id: str) -> dict[str, Any]:
    """Compose one agent's effective configuration. Raises ``DispatchError``/
    ``PodSettingsError`` unchanged when this pod's stored settings are invalid --
    never silently substitutes a default (matches ``docket pod <p> config get``)."""
    raw = _store.read_json(_cfg.meta_path(agent_id))
    meta = AgentMeta.model_validate(raw) if raw else AgentMeta(kind=AgentKind.project)
    role = str(raw.get("role", ""))
    project = _pod.pod_of(agent_id)

    model = str(raw.get("model") or "") or _cfg.DEFAULT_MODEL
    model_source = _mp.agent_model_source(agent_id)
    readiness = _provider.model_readiness(model)

    worktree_dir = str(raw.get("worktreeDir") or "")
    roots = _roots_for(agent_id, meta, worktree_dir)
    composition = _identity.compose_agent_prompt(
        agent_id,
        project_roots=roots,
        context_window_tokens=readiness.context_window,
        max_output_tokens=readiness.max_output,
    )

    base_registry = _tools.builtin_registry()
    role_registry = _archetypes.registry_for_role(base_registry, role) if role else base_registry
    denied = sorted(set(base_registry.names()) - set(role_registry.names()))
    mcp_servers = sorted(server.name for server in _mcp_tools.load_mcp_servers())

    pod_settings = _pod_settings_report(project) if project is not None else None
    pipeline = (
        {"source": _dispatch.effective_pipeline_source(project)} if project is not None else None
    )

    return {
        "id": agent_id,
        "role": role,
        "pod": project or "",
        "model": {"value": model, "source": model_source},
        "endpoint": {
            "baseUrl": readiness.base_url,
            "ready": readiness.ready,
            "contextWindowTokens": readiness.context_window,
            "maxOutputTokens": readiness.max_output,
            "issue": readiness.issue,
        },
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
        "policies": _policies_for_role(role),
        "pipeline": pipeline,
        "podSettings": pod_settings,
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
    ui.console.print(f"  [bold]Tools allowed:[/bold] {', '.join(tools['allowed']) or '(none)'}")
    ui.console.print(f"  [bold]Tools denied:[/bold]  {', '.join(tools['denied']) or '(none)'}")
    ui.console.print(
        f"  [bold]MCP servers:[/bold]   {', '.join(tools['mcpServers']) or '(none configured)'}"
    )
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
    if report["podSettings"] is not None:
        table = Table(title="Pod dispatch settings")
        table.add_column("KEY", style="bold")
        table.add_column("VALUE")
        table.add_column("SOURCE", style="dim")
        for key, entry in report["podSettings"].items():
            table.add_row(key, str(entry["value"]), entry["source"])
        ui.console.print(table)
