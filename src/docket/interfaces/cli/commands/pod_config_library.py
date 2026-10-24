from __future__ import annotations

import json as _json

import typer
from rich.markup import escape

from docket.governance import plugins as _plugins
from docket.governance import policy as _policy
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.pod_config import _fail, _scope_pod
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.render import ui
from docket.interfaces.cli.render.apply import render_exporter_states
from docket.kernel.home import current_home
from docket.teams import builtin_roles as _builtin_roles
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _arch
from docket.teams.apply import model as _model
from docket.teams.apply import recipes as _recipes

# -- recipes ----------------------------------------------------------------------------------


def _brings(summary: _recipes.RecipeSummary) -> str:
    """The parts a recipe brings, joined with `+` in summary order; `nothing` for an empty one."""
    parts = [
        label
        for label, present in (
            ("roles", summary.roles > 0),
            ("policies", summary.policies > 0),
            ("members", summary.members > 0),
            ("pipeline", bool(summary.pipeline)),
            ("plugins", summary.plugins > 0),
            ("skills", summary.skills > 0),
            ("mcp-servers", bool(summary.mcp_servers)),
            ("settings", summary.settings > 0),
        )
        if present
    ]
    return "+".join(parts) if parts else "nothing"


def _info_dict(
    name: str, scope: str, directory: str, summary: _recipes.RecipeSummary
) -> dict[str, object]:
    return {
        "name": name,
        "scope": scope,
        "brings": _brings(summary),
        "directory": directory,
        "description": summary.description,
        "roles": summary.roles,
        "policies": summary.policies,
        "members": summary.members,
        "pipeline": summary.pipeline,
        "plugins": summary.plugins,
        "skills": summary.skills,
        "settings": summary.settings,
        "mcp_servers": list(summary.mcp_servers),
        "exporters": list(summary.exporters),
    }


def _recipes_list(json_out: bool) -> None:
    infos = _recipes.list_recipes()
    if json_out:
        _contract.emit_json(
            [_info_dict(i.name, i.scope, str(i.directory), i.summary) for i in infos]
        )
        return
    ui.header("Recipe Library")
    ui.console.print()
    print(f"  {'NAME':<18} {'SCOPE':<9} {'BRINGS':<34} DESCRIPTION")
    print(f"  {'-' * 100}")
    for info in infos:
        print(
            f"  {info.name:<18} {info.scope:<9} {_brings(info.summary):<34} "
            f"{info.summary.description}"
        )
    ui.console.print()


def _recipes_show(name_or_dir: str, json_out: bool) -> None:
    try:
        directory = _recipes.resolve_recipe(name_or_dir)
    except _model.PodApplyError as exc:
        _fail(str(exc))
    summary = _recipes.summarize_recipe(directory)
    scope = next(
        (info.scope for info in _recipes.list_recipes() if info.directory == directory), ""
    )
    readme = directory / "README.md"
    body = readme.read_text(encoding="utf-8") if readme.is_file() else ""
    if json_out:
        payload = _info_dict(directory.name, scope, str(directory), summary)
        payload["readme"] = body
        _contract.emit_json(payload)
        return
    ui.header(directory.name)
    if summary.description:
        ui.console.print(escape(summary.description))
    if scope:
        ui.console.print(f"  scope: {scope}")
    ui.console.print(f"  directory: {directory}")
    ui.console.print(f"  {escape(summary.render())}")
    render_exporter_states(summary.exporters)
    if body:
        ui.console.print()
        ui.console.print(escape(body))


def cmd_recipes(
    name: str | None = typer.Argument(None, help="Recipe name or directory to show"),
    json_out: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    """List the recipe library, or show one recipe.

    Recipes resolve nearest scope first: your own ~/.docket/recipes/ before the
    shipped library. Nothing is installed; `pod update` installs.

    Example: docket pod recipes tdd"""
    if name is None:
        _recipes_list(json_out)
    else:
        _recipes_show(name, json_out)


# -- roles ------------------------------------------------------------------------------------


def _role_row(
    registry: _arch.ArchetypeRegistry, name: str, arch: _role_schema.RoleArchetype
) -> dict[str, str]:
    return {
        "name": name,
        "source": registry.source_of(name),
        "scope": arch.scope,
        "modelClass": arch.model_class,
        "gate": arch.gate_contract.kind,
        "description": arch.description,
    }


def _roles_list(project: str, json_out: bool) -> None:
    registry = _arch.load_registry(project)
    rows = [_role_row(registry, name, arch) for name, arch in registry.items()]
    if json_out:
        _contract.emit_json(rows)
        return
    ui.header("Role Archetypes")
    ui.console.print()
    print(f"  {'NAME':<14} {'SOURCE':<10} {'SCOPE':<5} {'CLASS':<7} {'GATE':<11} DESCRIPTION")
    print(f"  {'-' * 100}")
    for row in rows:
        print(
            f"  {row['name']:<14} {row['source']:<10} {row['scope']:<5} {row['modelClass']:<7} "
            f"{row['gate']:<11} {row['description'][:40]}"
        )
    ui.console.print()
    ui.dim(f"  Built-in: {', '.join(_builtin_roles.BUILTIN_ROLE_ORDER)}")
    ui.dim(f"  Starter library: {', '.join(_builtin_roles.STARTER_ROLE_ORDER)}")
    ui.console.print()


def _roles_show(project: str, name: str, json_out: bool) -> None:
    registry = _arch.load_registry(project)
    found = registry.get(name)
    if found is None:
        _fail(f"Archetype not found: {name}", "List them with docket pod roles")
    wire = found.to_wire()
    if json_out:
        _contract.emit_json({**wire, "source": registry.source_of(name)})
        return
    try:
        import yaml as _yaml  # type: ignore[import-untyped]

        text = _yaml.safe_dump(wire, sort_keys=False, allow_unicode=True)
    except ImportError:
        text = _json.dumps(wire, indent=2)
    ui.header(name)
    ui.dim(f"  source: {registry.source_of(name)}")
    ui.console.print()
    print(text)


def cmd_roles(
    name: str | None = typer.Argument(None, help="Role archetype to show"),
    pod: str | None = pod_option(),
    json_out: bool = typer.Option(False, "--json", help="Print JSON"),
) -> None:
    """List the role archetypes, or show one in full.

    The registry is built-ins, the starter library, your overlay and, inside a
    pod, the pod's own overlay (nearest wins). Install one with `pod update`.

    Example: docket pod roles reviewer"""
    project = _scope_pod(pod)
    if name is None:
        _roles_list(project, json_out)
    else:
        _roles_show(project, name, json_out)


# -- policies ---------------------------------------------------------------------------------


def _policy_rows(project: str) -> list[dict[str, str]]:
    rows = []
    for path in _policy.policy_files(project):
        try:
            p = _policy.read_policy(path)
        except Exception as exc:
            rows.append(
                {"id": f"[parse error: {exc}]", "hook": "", "action": "", "description": ""}
            )
            continue
        rows.append(
            {
                "id": str(p.get("id", "?")),
                "hook": str(p.get("hook", "?")),
                "action": str(p.get("action", "?")),
                "description": str(p.get("description", "")),
            }
        )
    return rows


def _plugin_rows(project: str) -> list[dict[str, str]]:
    try:
        registry = _plugins.discover(project)
    except _plugins.PluginError as exc:
        _fail(str(exc))
    return [
        {"name": n, "scope": p.scope, "file": str(p.file), "sha256": p.sha256}
        for n, p in sorted(registry.items())
    ]


def _render_plugins(rows: list[dict[str, str]]) -> None:
    ui.section("Predicate plugins")
    if not rows:
        ui.dim("  No plugins applied.")
        return
    print(f"  {'NAME':<24} {'SCOPE':<12} {'FILE':<44} SHA256")
    print(f"  {'-' * 100}")
    for r in rows:
        print(f"  {r['name']:<24} {r['scope']:<12} {r['file']:<44} {r['sha256']}")


def _policies_list(project: str, json_out: bool, with_plugins: bool) -> None:
    rows = _policy_rows(project)
    plugin_rows = _plugin_rows(project) if with_plugins else []
    if json_out:
        _contract.emit_json({"policies": rows, "plugins": plugin_rows} if with_plugins else rows)
        return
    ui.header("Guardrail Policies")
    ui.console.print()
    if not rows:
        ui.warn("No policies installed")
        ui.info("Run: docket setup")
    else:
        print(f"  {'ID':<30} {'HOOK':<16} {'ACTION':<16} DESCRIPTION")
        print(f"  {'-' * 80}")
        for r in rows:
            print(
                f"  {r['id'][:28]:<30} {r['hook'][:14]:<16} {r['action'][:14]:<16} {r['description'][:45]}"
            )
        ui.dim(f"  Policy files in {current_home().policies_dir}")
    ui.console.print()
    if with_plugins:
        _render_plugins(plugin_rows)


def _policies_show(project: str, policy_id: str, json_out: bool) -> None:
    for path in _policy.policy_files(project):
        try:
            parsed = _policy.read_policy(path)
        except Exception:
            continue
        if parsed.get("id", "") == policy_id:
            print(_json.dumps(parsed, indent=4))
            return
    _fail(f"Policy not found: {policy_id}", "List them with docket pod policies")


def cmd_policies(
    policy_id: str | None = typer.Argument(None, help="Policy id to show"),
    pod: str | None = pod_option(),
    json_out: bool = typer.Option(False, "--json", help="Print JSON"),
    with_plugins: bool = typer.Option(False, "--plugins", help="Also list predicate plugins"),
) -> None:
    """List the guardrail policies in force, or show one.

    The global set plus, inside a pod, the pod's own files; a pod only ever adds.
    --plugins adds the predicate plugins a rule's `when:` can reach. Judge a call
    with `pod check`.

    Example: docket pod policies block-destructive"""
    project = _scope_pod(pod)
    if policy_id is None:
        _policies_list(project, json_out, with_plugins)
    elif with_plugins:
        _fail("--plugins lists with no policy id", "Drop the id or the flag", 2)
    else:
        _policies_show(project, policy_id, json_out)
