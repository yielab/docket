"""The pod's configuration of record: apply, export, validate, plan, check, and the
recipe, role and policy libraries. Registered onto ``pod_app`` by the registry."""

from __future__ import annotations

import json as _json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.cli._target import TargetError, pod_option, resolve_pod
from docket.core import archetypes as _arch
from docket.core import config_docs as _config_docs
from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import plugins as _plugins
from docket.core import pod as _pod_core
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import policy as _policy
from docket.core import tools as _tools
from docket.core.audit import audit_log
from docket.edges import store as _store

_HOOKS = ("pre_input", "pre_tool_call", "pre_output")


def _fail(what: str, do: str = "", code: int = 1) -> NoReturn:
    ui.error(what, do)
    raise typer.Exit(code)


def _pod_name(pod: str | None) -> str:
    """The pod this command acts on; exits 1 naming what was looked for when none resolves."""
    try:
        return resolve_pod(pod, env=os.environ, cwd=Path.cwd())
    except TargetError as exc:
        _fail(str(exc))


def _scope_pod(pod: str | None) -> str:
    """The pod whose overlay applies to a library read, or ``""`` for the global set."""
    try:
        return resolve_pod(pod, env=os.environ, cwd=Path.cwd())
    except TargetError:
        return ""


def _default_dir(project: str) -> Path:
    """``<codebase>/.docket`` from the Lead's own recorded meta."""
    from docket.core import fleet as _fleet

    codebase = _fleet.meta_get(_pod_core.member_id(project, "lead"), "codebase", "")
    return Path(codebase) / ".docket"


# -- render helpers shared with init ---------------------------------------------------------


def render_apply_header(project: str, directory: Path, summary: _pod_apply.RecipeSummary) -> None:
    """Print the apply header: the recipe's description when set, then its derived summary."""
    ui.header("Apply plan", f"{project} <- {directory}")
    if summary.description:
        ui.console.print(escape(summary.description))
    ui.console.print(f"  {escape(summary.render())}")


def _render_items(items: tuple[_pod_apply.ApplyItem, ...]) -> None:
    for item in items:
        ui.console.print(f"  {escape(f'[{item.action}]')} {item.kind}: {item.name}")
        if item.note:
            ui.console.print(f"      {escape(item.name)}: {escape(item.note)}")


def render_apply_plan(plan: _pod_apply.ApplyPlan) -> None:
    """Print an apply plan one item per line, then one line per named exporter."""
    _render_items(plan.items)
    render_exporter_states(plan.exporters)


def render_exporter_states(names: tuple[str, ...]) -> None:
    """Print each exporter's state and, unless enabled, the command that enables it."""
    if not names:
        return
    from docket.core import exporter as _exporter

    catalog = _exporter.load_catalog()
    for name in names:
        spec = catalog.get(name)
        if spec is None:
            continue
        state, missing = _exporter.activation_state(spec, health=None)
        if state == "enabled":
            line = f"exporter {name}: enabled"
        elif state == "needs credential":
            line = (
                f"exporter {name}: needs credential {', '.join(missing)} "
                f"-> docket setup export enable {name}"
            )
        else:
            line = f"exporter {name}: {state} -> docket setup export enable {name}"
        ui.console.print(f"  {escape(line)}")


# -- apply ------------------------------------------------------------------------------------


def cmd_apply(
    target: str | None = typer.Argument(None, help="Recipe name, directory or one document file"),
    pod: str | None = pod_option(),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; write nothing"),
    json_out: bool = typer.Option(False, "--json", help="Print the plan as JSON"),
) -> None:
    """Install configuration onto the pod, or re-sync its instructions.

    A recipe name or a directory is planned and written whole. A single role or
    policy file installs that document. With no argument, members whose SOUL,
    AGENTS or TOOLS are stale are re-rendered from the current archetypes.

    Example: docket pod apply .docket --dry-run"""
    project = _pod_name(pod)
    if target is None:
        _sync(project, dry_run, json_out)
    elif Path(target).is_file():
        _apply_file(project, Path(target), dry_run, json_out)
    else:
        _apply_directory(project, target, dry_run, json_out)


def _sync(project: str, dry_run: bool, json_out: bool) -> None:
    if json_out:
        _fail("--json needs something to apply", "Pass a recipe name, directory or file")
    member_ids = _pp.pod_member_ids(project)
    if not member_ids:
        _fail(f"No pod found for '{project}'", "Run docket init")
    stale = []
    for member_id in member_ids:
        status = _pp.member_sync_status(member_id)
        if status is None or not status.stale:
            continue
        stale.append(member_id)
        if dry_run:
            was = status.stored_template_version or "?"
            ui.warn(f"{member_id} is stale (v{was} -> v{_pp.POD_TEMPLATE_VERSION})")
            for name, diff in status.diffs.items():
                ui.console.print(escape(diff) if diff else f"  {name}: no content change")
        else:
            written = _pp.resync_member(member_id)
            audit_log("pod.sync", f"member={member_id} files=({','.join(written)})")
            ui.success(f"{member_id}: re-rendered {', '.join(written) or '(version stamp only)'}")
    if not stale:
        ui.success(f"Pod '{project}' is already in sync")
    elif dry_run:
        ui.dim(f"  {len(stale)} member(s) stale; rerun without --dry-run to write")
    else:
        _contract.next_step("docket pod show")


def _apply_directory(project: str, target: str, dry_run: bool, json_out: bool) -> None:
    try:
        directory = _pod_apply.resolve_recipe(target)
        plan = _pod_apply.plan_apply(project, directory)
    except _pod_apply.PodApplyError as ex:
        _fail(str(ex))
    if json_out:
        _contract.emit_json({"items": [asdict(item) for item in plan.items]})
    else:
        render_apply_header(project, directory, _pod_apply.summarize_recipe(directory))
        render_apply_plan(plan)
    if dry_run:
        return
    result = _pod_apply.apply(plan)
    if not json_out:
        changed = [item for item in result.items if item.action != "skip"]
        if changed:
            ui.success(f"Applied {len(changed)} change(s) to pod '{project}' from {directory}")
        else:
            ui.success(f"Pod '{project}' already matches {directory}")
        _contract.next_step("docket pod show")


def _plan_file(project: str, path: Path) -> tuple[_config_docs.Document, _pod_apply.ApplyItem]:
    try:
        document = _config_docs.load_document(path)
    except _config_docs.ConfigDocError as exc:
        _fail(str(exc))
    if document.kind == "role":
        roles = _store.read_json(_cfg.pod_config_dir(project) / "roles.json").get("roles", {})
        exists = document.name in roles
    elif document.kind == "policy":
        exists = (_cfg.pod_config_dir(project) / "policies" / path.name).is_file()
    else:
        _fail(
            f"A {document.kind} document is not applied on its own",
            "Put it in a directory beside its recipe and apply the directory",
        )
    action: _pod_apply.ApplyAction = "replace" if exists else "add"
    return document, _pod_apply.ApplyItem(kind=document.kind, name=document.name, action=action)  # type: ignore[arg-type]


def _install_policy(project: str, path: Path) -> None:
    policies_dir = _cfg.pod_config_dir(project) / "policies"
    policies_dir.mkdir(parents=True, exist_ok=True)
    dest = policies_dir / path.name
    dest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    dest.chmod(0o600)


def _apply_file(project: str, path: Path, dry_run: bool, json_out: bool) -> None:
    document, item = _plan_file(project, path)
    if json_out:
        _contract.emit_json({"items": [asdict(item)]})
    else:
        ui.header("Apply plan", f"{project} <- {path}")
        _render_items((item,))
    if dry_run:
        return
    try:
        if document.kind == "role":
            _arch.add_user_archetype(document.doc, project)
        else:
            error = _policy.validate_policy(path)
            if error:
                _fail(error)
            _install_policy(project, path)
    except _arch.ArchetypeError as exc:
        _fail(f"Invalid archetype: {exc}")
    audit_log("pod.apply", f"project={project} file={path} kind={document.kind}")
    if not json_out:
        ui.success(f"Applied {document.kind} '{document.name}' to pod '{project}'")
        _contract.next_step("docket pod show")


# -- export -----------------------------------------------------------------------------------


def cmd_export(
    directory: str | None = typer.Argument(None, help="Target directory; default .docket"),
    pod: str | None = pod_option(),
    force: bool = typer.Option(False, "--force", help="Write into a non-empty directory"),
) -> None:
    """Write the pod's own configuration into a directory.

    The default is the repository's .docket/, the form `pod apply` and `docket
    init` read back. A non-empty directory is refused unless --force.

    Example: docket pod export .docket --force"""
    project = _pod_name(pod)
    target = Path(directory) if directory else _default_dir(project)
    if target.exists() and any(target.iterdir()) and not force:
        _fail(f"'{target}' is not empty", "Pass --force to overwrite")
    try:
        _pod_apply.export_pod(project, target)
    except _pod_apply.PodApplyError as ex:
        _fail(str(ex))
    audit_log("pod.export", f"project={project} dir={target}")
    ui.success(f"Exported pod '{project}' to {target}")
    _contract.next_step(f"docket pod validate {target}")


# -- validate ---------------------------------------------------------------------------------


def cmd_validate(
    path: str | None = typer.Argument(None, help="A document or a directory of them"),
) -> None:
    """Validate any configuration document, or every document in a directory.

    The default is .docket/ in the current directory when it exists, else the
    directory itself. Roles, policies, pipelines, pod manifests and MCP server
    documents are each checked by the validator that owns their kind. Exit 1 when
    any is invalid.

    Example: docket pod validate .docket"""
    target = Path(path) if path else _validate_default()
    if not target.exists():
        _fail(f"Not found: {target}")
    results = _config_docs.validate_path(target)
    for result in results:
        if result.error is not None:
            ui.fail(str(result.error))
            continue
        assert result.document is not None
        doc = result.document
        if doc.deprecated:
            ui.warn(f"{result.path} has no 'kind:'; add 'kind: {doc.kind}'")
        ui.success(f"{result.path} ({doc.kind} {doc.name})")
    if not target.is_file():
        summary = _pod_apply.summarize_recipe(target)
        ui.dim(f"  {summary.render()}")
        if summary.description:
            ui.dim(f"  {summary.description}")
    if any(r.error is not None for r in results):
        raise typer.Exit(1)


def _validate_default() -> Path:
    candidate = Path.cwd() / ".docket"
    return candidate if candidate.is_dir() else Path.cwd()


# -- plan -------------------------------------------------------------------------------------


def cmd_plan(
    pod: str | None = pod_option(),
    pipeline: str | None = typer.Option(None, "--pipeline", help="Plan this pipeline file"),
) -> None:
    """Show the steps the pod's pipeline would run, from the real executor.

    Without --pipeline the pod's bound pipeline is planned, else its default
    order. Nothing is started and no tokens are spent.

    Example: docket pod plan --pipeline review.yaml"""
    project = _pod_name(pod)
    spec = _plan_spec(pipeline) if pipeline else None
    try:
        _dispatch.pod_pipeline(project)
        roster = _dispatch.pod_full_roster(project)
        effective = spec if spec is not None else _dispatch.effective_pipeline(project, None)
        source = (
            f"file '{pipeline}'"
            if spec is not None
            else _dispatch.effective_pipeline_source(project)
        )
    except _dispatch.DispatchError as ex:
        _fail(str(ex))
    plan = _orch.resolve_plan(effective, roster, registry=_arch.load_registry())
    ui.header("Pipeline plan", project)
    ui.console.print(f"Source: {source}")
    ui.console.print()
    ui.console.print(_orch.render_plan(plan), markup=False)
    ui.console.print()


def _plan_spec(pipeline: str) -> _pipeline.PipelineSpec:
    path = Path(pipeline)
    if not path.is_file():
        _fail(f"Pipeline file not found: {pipeline}")
    (result,) = _config_docs.validate_path(path, kind="pipeline")
    if result.error is not None:
        _fail(f"Pipeline file is invalid: {result.error}")
    spec = _pipeline.load_pipeline(path.read_text(encoding="utf-8")).spec
    if spec is None:
        _fail(f"Pipeline file is invalid: {pipeline}")
    return spec


# -- check ------------------------------------------------------------------------------------


def _unreachable_handler(_args: dict[str, Any], _ctx: _tools.ToolContext) -> NoReturn:
    """The dry-run Tool exists only to carry ``kind="exec"`` through the evaluator."""
    raise AssertionError("pod check must never execute a tool")


def _check_verdict(
    hook: str, role: str, text: str, tool: str, call_args: dict[str, str], project: str
) -> tuple[str, str, str, str]:
    """``(action, reason, policy_id, policy_action)`` the live gate would reach."""
    registry = _tools.builtin_registry()
    builtin = {n: t for n in registry.names() if (t := registry.get(n)) is not None}
    if hook != "pre_tool_call":
        return _policy.policy_test(hook, role, text, project=project), "", "", ""
    if tool not in builtin:
        _fail(f"Unknown tool '{tool}'", f"Valid: {' '.join(sorted(builtin))}", 2)
    if builtin[tool].kind == "exec":
        verdict = _tools.evaluate_tool_call(
            _tools.Tool(
                name=tool,
                description="",
                parameters={"required": ["command"]},
                handler=_unreachable_handler,
                kind="exec",
            ),
            {"command": text, **call_args},
            _tools.ToolContext(role=role, project=project),
        )
        return verdict.decision, verdict.reason, verdict.policy_id, verdict.policy_action
    call = _policy.ToolCallFacts(tool=tool, args=call_args, branch_of=lambda: "")
    hit = _policy.policy_eval_detail(role, hook, text, project=project, call=call)
    action = {"block": "deny", "require_approval": "ask"}.get(hit.action, "allow")
    reason = f"command classifier skipped: '{tool}' is kind={builtin[tool].kind}"
    return action, reason, hit.policy_id, hit.action


def _call_args(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            _fail(f"--arg must be key=value, got {pair!r}", "", 2)
        out[key] = value
    return out


def cmd_check(
    text: str = typer.Argument(..., help="The command, input or output text to judge"),
    role: str = typer.Option(..., "--role", help="Role the call would run as"),
    hook: str = typer.Option("pre_tool_call", "--hook", help=" | ".join(_HOOKS)),
    tool: str = typer.Option("bash", "--tool", help="Built-in tool simulated at pre_tool_call"),
    arg: list[str] | None = typer.Option(None, "--arg", help="key=value for a rule's when:"),
    pod: str | None = pod_option(),
) -> None:
    """Would the pod's rules allow this? A dry run; no traces are written.

    An exec tool is judged by the command classifier plus the policy hook, as the
    live gate does; any other tool by the policy hook alone.

    Example: docket pod check "git push origin production" --role implementer"""
    if hook not in _HOOKS:
        _fail(f"Unknown hook '{hook}'", f"Valid: {' '.join(_HOOKS)}", 2)
    project = _scope_pod(pod)
    action, reason, policy_id, policy_action = _check_verdict(
        hook, role, text, tool, _call_args(arg), project
    )
    ui.console.print()
    for label, value in (("Hook", hook), ("Role", role), ("Text", text[:80])):
        ui.console.print(f"  {label + ':':<8}{escape(value)}")
    ui.console.print(f"  {'Result:':<8}{action}")
    if reason:
        ui.console.print(f"  {'Reason:':<8}{escape(reason)}")
    if policy_id:
        ui.console.print(f"  {'Policy:':<8}{escape(repr(policy_id))} -> {policy_action}")
    ui.console.print()


# -- recipes ----------------------------------------------------------------------------------


def _brings(summary: _pod_apply.RecipeSummary) -> str:
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
    name: str, scope: str, directory: str, summary: _pod_apply.RecipeSummary
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
        "unjailed_mcp_servers": list(summary.unjailed_mcp_servers),
    }


def _recipes_list(json_out: bool) -> None:
    infos = _pod_apply.list_recipes()
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
        directory = _pod_apply.resolve_recipe(name_or_dir)
    except _pod_apply.PodApplyError as exc:
        _fail(str(exc))
    summary = _pod_apply.summarize_recipe(directory)
    scope = next(
        (info.scope for info in _pod_apply.list_recipes() if info.directory == directory), ""
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
    shipped library. Nothing is installed; `pod apply` installs.

    Example: docket pod recipes tdd"""
    if name is None:
        _recipes_list(json_out)
    else:
        _recipes_show(name, json_out)


# -- roles ------------------------------------------------------------------------------------


def _role_row(
    registry: _arch.ArchetypeRegistry, name: str, arch: _arch.RoleArchetype
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
    ui.dim(f"  Built-in: {', '.join(_arch.BUILTIN_ROLE_ORDER)}")
    ui.dim(f"  Starter library: {', '.join(_arch.STARTER_ROLE_ORDER)}")
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
    pod, the pod's own overlay (nearest wins). Install one with `pod apply`.

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
        ui.dim(f"  Policy files in {_cfg.POLICIES_DIR}")
    ui.console.print()
    if with_plugins:
        _render_plugins(plugin_rows)


def _render_plugins(rows: list[dict[str, str]]) -> None:
    ui.section("Predicate plugins")
    if not rows:
        ui.dim("  No plugins applied.")
        return
    print(f"  {'NAME':<24} {'SCOPE':<12} {'FILE':<44} SHA256")
    print(f"  {'-' * 100}")
    for r in rows:
        print(f"  {r['name']:<24} {r['scope']:<12} {r['file']:<44} {r['sha256']}")


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
