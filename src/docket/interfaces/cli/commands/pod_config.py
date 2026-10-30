"""The pod's configuration of record: apply, export, validate, plan, check, and the
recipe, role and policy libraries. Registered onto ``pod_app`` by the registry."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.markup import escape

from docket.agent.tools import registry as _tools
from docket.governance import gate as _gate
from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.hops.application import builtin_tools as _builtin_tools
from docket.hops.application import steps as _steps
from docket.interfaces.cli.commands import agents as _agents
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.target import TargetError, pod_option
from docket.interfaces.cli.render import ui
from docket.interfaces.cli.render.apply import _render_items, render_apply_header, render_apply_plan
from docket.kernel.errors import CanonicalFormRefused, DispatchError
from docket.kernel.home import current_home
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.teams import config_docs as _config_docs
from docket.teams import fleet as _fleet
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod as _pod_core
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings
from docket.teams import records as _records
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _arch
from docket.teams.apply import check as _check
from docket.teams.apply import model as _model
from docket.teams.apply import plan as _pod_apply
from docket.teams.apply import recipes as _recipes
from docket.teams.apply import review as _review
from docket.teams.apply import write as _write

_HOOKS = ("pre_input", "pre_tool_call", "pre_output")


def _fail(what: str, do: str = "", code: int = 1) -> NoReturn:
    ui.error(what, do)
    raise typer.Exit(code)


def _scope_pod(pod: str | None) -> str:
    """The pod whose overlay applies to a library read, or ``""`` for the global set."""
    try:
        return _contract.resolve_pod_here(pod)
    except TargetError:
        return ""


def _default_dir(project: str, *, create: bool = False) -> Path:
    """The pod's configuration-of-record directory from the Lead's own recorded meta."""
    return _review.repo_config_dir(_codebase(project), project, create=create)


def _codebase(project: str) -> Path:
    return Path(_fleet.meta_get(_pod_core.member_id(project, "lead"), "codebase", ""))


# -- apply ------------------------------------------------------------------------------------


def cmd_update(
    target: str | None = typer.Argument(None, help="Recipe name, directory or one document file"),
    pod: str | None = pod_option(),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; write nothing"),
    json_out: bool = typer.Option(False, "--json", help="Print the plan as JSON"),
    accept: str | None = typer.Option(
        None, "--accept", help="Allow exactly the repository commands with this review code"
    ),
) -> None:
    """Install configuration onto the pod, or re-sync its instructions.

    A recipe name or a directory is planned and written whole. A single role or
    policy file installs that document. With no argument, members whose SOUL,
    AGENTS or TOOLS are stale are re-rendered from the current archetypes.

    Example: docket pod update .docket --dry-run"""
    project = _contract.require_pod(pod)
    if target is None:
        _sync(project, dry_run, json_out)
    elif Path(target).is_file():
        _apply_file(project, Path(target), dry_run, json_out)
    else:
        _apply_directory(project, target, dry_run, json_out, accept)


def _sync(project: str, dry_run: bool, json_out: bool) -> None:
    if json_out:
        _fail("--json needs something to apply", "Pass a recipe name, directory or file")
    member_ids = _pp.pod_member_ids(project)
    if not member_ids:
        _fail(f"No pod found for '{project}'", "Run docket init")
    stale = []
    for member_id in member_ids:
        status = _member_workspace.member_sync_status(member_id)
        if status is None or not status.stale:
            continue
        stale.append(member_id)
        if dry_run:
            was = status.stored_template_version or "?"
            ui.warn(f"{member_id} is stale (v{was} -> v{_member_workspace.POD_TEMPLATE_VERSION})")
            for name, diff in status.diffs.items():
                ui.console.print(escape(diff) if diff else f"  {name}: no content change")
        else:
            written = _member_workspace.resync_member(member_id)
            audit_log("pod.sync", f"member={member_id} files=({','.join(written)})")
            ui.success(f"{member_id}: re-rendered {', '.join(written) or '(version stamp only)'}")
    if not stale:
        ui.success(f"Pod '{project}' is already in sync")
    elif dry_run:
        ui.dim(f"  {len(stale)} member(s) stale; rerun without --dry-run to write")
    else:
        _contract.next_step("docket pod show")


def _review_directory(project: str, directory: Path, json_out: bool, accept: str | None) -> None:
    """The operator's OK for what *directory* runs on this machine; exits 2 when not given."""

    root = _codebase(project)
    request = _agents.InitRequest(accept=accept, json_out=json_out)
    if _agents.review_repo_source(request, project, root, directory, "docket pod update"):
        raise typer.Exit(2)


def _apply_directory(
    project: str, target: str, dry_run: bool, json_out: bool, accept: str | None = None
) -> None:
    try:
        directory = _recipes.resolve_recipe(target)
        plan = _pod_apply.plan_apply(project, directory)
    except _model.PodApplyRefused as ex:
        _fail(str(ex), code=2)
    except _model.PodApplyError as ex:
        _fail(str(ex))
    if not dry_run:
        _review_directory(project, directory, json_out, accept)
    if json_out:
        _contract.emit_json({"items": [asdict(item) for item in plan.items]})
    else:
        render_apply_header(project, directory, _recipes.summarize_recipe(directory))
        render_apply_plan(plan)
    if dry_run:
        return
    result = _write.apply(plan)
    if not json_out:
        changed = [item for item in result.items if item.action != "skip"]
        if changed:
            ui.success(f"Applied {len(changed)} change(s) to pod '{project}' from {directory}")
        else:
            ui.success(f"Pod '{project}' already matches {directory}")
        _contract.next_step("docket pod show")


def _plan_file(project: str, path: Path) -> tuple[_config_docs.Document, _model.ApplyItem]:
    try:
        document = _config_docs.load_document(path)
    except _config_docs.ConfigDocError as exc:
        _fail(str(exc), code=2 if isinstance(exc, CanonicalFormRefused) else 1)
    if document.kind == "role":
        if problems := _check.role_file_send_problems(path, project):
            _fail("; ".join(problems))
        exists = _arch.load_registry(project).source_of(document.name) == f"pod:{project}"
    elif document.kind == "policy":
        exists = (current_home().pod_config_dir(project) / "policies" / path.name).is_file()
    else:
        _fail(
            f"A {document.kind} document is not applied on its own",
            "Put it in a directory beside its recipe and apply the directory",
        )
    action: _model.ApplyAction = "replace" if exists else "add"
    return document, _model.ApplyItem(kind=document.kind, name=document.name, action=action)  # type: ignore[arg-type]


def _install_policy(project: str, path: Path) -> None:
    policies_dir = current_home().pod_config_dir(project) / "policies"
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
    except _role_schema.ArchetypeError as exc:
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

    The default is the repository's .docket/ (.docket/teams/<pod>/ when the
    repository keeps several teams), the form `pod update` and `docket
    init` read back. A non-empty directory is refused unless --force.

    Example: docket pod export .docket --force"""
    project = _contract.require_pod(pod)
    target = Path(directory) if directory else _default_dir(project, create=True)
    if target.exists() and any(target.iterdir()) and not force:
        _fail(f"'{target}' is not empty", "Pass --force to overwrite")
    try:
        _write.export_pod(project, target)
    except _model.PodApplyError as ex:
        _fail(str(ex))
    audit_log("pod.export", f"project={project} dir={target}")
    ui.success(f"Exported pod '{project}' to {target}")
    if _records.records_files(target):
        ui.dim(
            "  The records documents were exported; rows stay in the pod's records.sqlite, never exported"
        )
    _contract.next_step(f"docket pod validate {target}")


# -- validate ---------------------------------------------------------------------------------


def cmd_validate(
    path: str | None = typer.Argument(None, help="A document or a directory of them"),
) -> None:
    """Validate any configuration document, or every document in a directory.

    The default is .docket/ in the current directory when it exists, else the
    directory itself. Roles, policies, pipelines, prompts, pod manifests and MCP
    server documents are each checked by the validator that owns their kind. Exit
    1 when any is invalid.

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
        ui.success(f"{result.path} ({doc.kind} {doc.name})")
    problems = _file_problems(target) if target.is_file() else _reference_problems(target)
    for problem in problems:
        ui.fail(problem)
    if not target.is_file():
        summary = _recipes.summarize_recipe(target)
        ui.dim(f"  {summary.render()}")
        if summary.description:
            ui.dim(f"  {summary.description}")
    if problems or any(r.error is not None for r in results):
        raise typer.Exit(1)


def _file_problems(path: Path) -> list[str]:
    """What a single role file gets wrong against the catalog it would join (read/act rule)."""
    if path.parent.name != "roles":
        return []
    return _check.role_file_send_problems(path, _scope_pod(None))


def _reference_problems(directory: Path) -> list[str]:
    """What the directory's references and prompt inputs get wrong, resolved against the pod
    inferred from the current directory (else the built-ins)."""
    manifest = next(
        (p for p in (directory / "pod.yaml", directory / "pod.yml") if p.is_file()), None
    )
    members: object = []
    if manifest is not None:
        try:
            members = _config_docs.load_document(manifest, kind="pod").doc.get("members", [])
        except _config_docs.ConfigDocError:
            members = []  # the kind validator above already reported the manifest
    return _check.directory_problems(directory, _scope_pod(None), members)


def _validate_default() -> Path:
    candidate = Path.cwd() / ".docket"
    pod = _scope_pod(None)
    if pod:
        candidate = _review.repo_config_dir(Path.cwd(), pod)
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
    project = _contract.require_pod(pod)
    spec = _plan_spec(pipeline) if pipeline else None
    try:
        _pod_core.pod_pipeline(project)
        roster = _pod_core.pod_full_roster(project)
        effective = spec if spec is not None else _steps.effective_pipeline(project, None)
        source = (
            f"file '{pipeline}'" if spec is not None else _steps.effective_pipeline_source(project)
        )
    except DispatchError as ex:
        _fail(str(ex))
    plan = _orch.resolve_plan(effective, roster, registry=_arch.load_registry(project))
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


def _pod_allow_commands(project: str) -> tuple[str, ...]:
    """The pod's ``allowCommands`` as the live gate sees it: empty when the setting is unreadable."""
    try:
        return _pod_settings.PodSettings.load_for(project).allow_commands
    except _pod_settings.PodSettingsError:
        return ()


def _check_verdict(
    hook: str, role: str, text: str, tool: str, call_args: dict[str, str], project: str
) -> tuple[str, str, str, str]:
    """``(action, reason, policy_id, policy_action)`` the live gate would reach."""
    registry = _builtin_tools.builtin_registry()
    builtin = {n: t for n in registry.names() if (t := registry.get(n)) is not None}
    if hook != "pre_tool_call":
        return _policy.policy_test(hook, role, text, project=project), "", "", ""
    if tool not in builtin:
        _fail(f"Unknown tool '{tool}'", f"Valid: {' '.join(sorted(builtin))}", 2)
    if builtin[tool].kind == "exec":
        verdict = _gate.evaluate_tool_call(
            _tools.Tool(
                name=tool,
                description="",
                parameters={"required": ["command"]},
                handler=_unreachable_handler,
                kind="exec",
            ),
            {"command": text, **call_args},
            _tools.ToolContext(
                role=role, project=project, allow_commands=_pod_allow_commands(project)
            ),
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
