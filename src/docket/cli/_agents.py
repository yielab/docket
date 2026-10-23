"""docket init: create a project pod, or provision agents declaratively.

``cmd_init`` is the Typer command; it builds an ``InitRequest`` and ``run_init`` returns the
process exit code.
"""

from __future__ import annotations

import json as _json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.core import blueprints as _bp
from docket.core import config_docs as _config_docs
from docket.core import fleet as _fleet
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import policy as _policy
from docket.core import provisioning as _prov
from docket.kernel.errors import InvalidInput


@dataclass(frozen=True)
class InitRequest:
    """What `docket init` was asked for, as Typer parsed it."""

    name: str | None = None
    location: str | None = None
    blueprint: str | None = None
    recipe: str | None = None
    no_apply: bool = False
    accept: str | None = None
    json_out: bool = False
    from_file: str | None = None
    full: bool = False
    with_roles: str = ""


def _stored_location(raw: str, workspace_kind: str) -> str:
    """The location as docket stores it: ``~`` expanded and absolute, relative to the cwd. A
    ``codebase`` must be an existing directory; a ``workdir`` is created when missing.
    Raises ``InvalidInput`` otherwise."""
    if not raw:
        return ""
    path = Path(os.path.abspath(Path(raw).expanduser()))
    if workspace_kind == "codebase" and not path.is_dir():
        raise InvalidInput(f"codebase '{path}' is not a directory", "Give the path of the code.")
    return str(path)


def _invalid(req: InitRequest, message: str, hint: str = "") -> int:
    """Refuse the request before anything is created: the reason on stderr, or as JSON under
    ``--json``. Exit status 2."""
    if req.json_out:
        ui.console.print_json(_json.dumps({"status": "invalid", "reason": message}))
    else:
        ui.error(escape(message), escape(hint))
    return 2


def _unnamed_teams(base: Path, chosen: Path) -> list[str]:
    """The team names under ``base/teams`` when *chosen* is ``base`` itself and ``base`` has no
    ``pod.yaml``; empty when a team was picked or the repository keeps one team."""
    teams_dir = base / "teams"
    if chosen != base or (base / "pod.yaml").is_file() or not teams_dir.is_dir():
        return []
    return sorted(p.name for p in teams_dir.iterdir() if p.is_dir())


def _resolve_repo_apply_source(
    loc_path: Path, cli_recipe: str | None, pod_name: str = ""
) -> tuple[Path | None, int]:
    """The directory `docket init` should apply after provisioning -- a present ``.docket/``
    or a resolved ``--recipe``, mutually exclusive, validated first (ADR 0012). ``(None, 1)``
    means stop (already printed); ``(None, 0)`` means nothing to apply."""
    docket_dir = _pod_apply.repo_config_dir(loc_path, pod_name)
    has_docket_dir = docket_dir.is_dir()
    teams = _unnamed_teams(loc_path / ".docket", docket_dir)
    if teams and cli_recipe is None:
        ui.error(
            f"'{loc_path / '.docket'}' holds several teams ({', '.join(teams)}); "
            "name one with --name."
        )
        return None, 2
    if cli_recipe is not None and has_docket_dir:
        ui.error(f"Both --recipe and an existing '{docket_dir}' were given; use only one.")
        return None, 1

    apply_source: Path | None = None
    if cli_recipe is not None:
        try:
            apply_source = _pod_apply.resolve_recipe(cli_recipe)
        except _pod_apply.PodApplyError as exc:
            ui.error(str(exc))
            return None, 1
    elif has_docket_dir:
        apply_source = docket_dir

    if apply_source is not None:
        config_errors = _config_docs.validate_directory(apply_source)
        if config_errors:
            for config_error in config_errors:
                ui.console.print(f"[red]{escape(str(config_error))}[/red]")
            return None, 1
    return apply_source, 0


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _refuse_shell(req: InitRequest, review: _pod_apply.PlanReview) -> int:
    if req.json_out:
        ui.console.print_json(
            _json.dumps(
                {"status": "refused", "refused": list(review.refused), "items": _items(review)}
            )
        )
        return 2
    ui.error(
        f"Not set up. The repository lets the agent run {', '.join(review.refused)}. A shell "
        "runs whatever command follows it, so docket's command checks never see what it "
        "actually does."
    )
    ui.console.print("Ask the repository to list the tools the team uses instead, like: make, npm")
    return 2


def _items(review: _pod_apply.PlanReview) -> list[dict[str, str]]:
    return [{"kind": i.kind, "name": i.name, "runs": i.runs} for i in review.runs]


def _changed_since_review(
    req: InitRequest,
    root: Path,
    project: str,
    code: str,
    review: _pod_apply.PlanReview,
    command: str = "docket init",
) -> int:
    from docket.core import reviewed_repos as _reviewed

    if req.json_out:
        before = _reviewed.lookup(root, project)
        was = {(i.kind, i.name): i.runs for i in before.items} if before else {}
        changed = [
            {**item, "before": was.get((item["kind"], item["name"]), "")}
            for item in _items(review)
            if was.get((item["kind"], item["name"])) != item["runs"]
        ]
        ui.console.print_json(_json.dumps({"status": "code_mismatch", "items": changed}))
        return 2
    ui.error(
        f"{_stopped(command)}. The repository changed what runs on this machine since review "
        f"code {code}:"
    )
    before = _reviewed.lookup(root, project)
    was = {(i.kind, i.name): i.runs for i in before.items} if before else {}
    for item in review.runs:
        if was.get((item.kind, item.name)) != item.runs:
            ui.console.print(f"  {escape(_label(item))}")
            ui.console.print(
                f"    before: {escape(was.get((item.kind, item.name), '(not reviewed)'))}"
            )
            ui.console.print(f"    now:    {escape(item.runs)}")
    target = _pod_apply.repo_config_dir(root, project, create=True).relative_to(root).as_posix()
    ui.console.print(
        "Review the new version with: docket init --no-apply, then "
        f"docket pod update {target} --dry-run"
    )
    return 2


def _stopped(command: str) -> str:
    return "Not set up" if command == "docket init" else "Not updated"


def _label(item: _pod_apply.RunItem) -> str:
    from docket.cli._pod_config import run_item_label

    return run_item_label(item)


def _needs_review(
    req: InitRequest, review: _pod_apply.PlanReview, code: str, command: str = "docket init"
) -> int:
    from docket.cli._pod_config import render_run_items

    if req.json_out:
        ui.console.print_json(
            _json.dumps({"status": "needs_review", "reviewCode": code, "items": _items(review)})
        )
        return 2
    n = len(review.runs)
    ui.error(
        f"{_stopped(command)}. The repository brings {n} command{'s' if n != 1 else ''} that "
        f"need{'' if n != 1 else 's'} your OK, and there is no terminal to ask on. Nothing was "
        f"{'created' if command == 'docket init' else 'changed'}."
    )
    render_run_items(review.runs)
    ui.console.print("To continue, either:")
    ui.console.print(f"  run {command} once on a terminal on this machine, or")
    ui.console.print(f"  allow exactly these from the script: {command} --accept {code}")
    if command == "docket init":
        ui.console.print("  or skip the repository's configuration: docket init --no-apply")
    return 2


def review_repo_source(
    req: InitRequest,
    project: str,
    loc_path: Path,
    apply_source: Path,
    command: str = "docket init",
) -> int:
    """The operator's OK for what *apply_source* runs on this machine, asked before anything is
    created. 0 means go on; 2 means stop (already printed). Shipped recipes are exempt."""
    from docket.cli._pod_config import render_review
    from docket.core import reviewed_repos as _reviewed

    decision = _pod_apply.review_decision(loc_path, project, apply_source, req.accept)
    review = decision.review
    if decision.status == "go":
        return 0
    if decision.status == "refused":
        return _refuse_shell(req, review)
    if decision.status == "code_mismatch":
        return _changed_since_review(req, loc_path, project, req.accept or "", review, command)
    if decision.status == "needs_code":
        if not (_stdin_is_tty() and not req.json_out):
            return _needs_review(req, review, decision.code, command)
        ui.console.print()
        render_review(review)
        ui.console.print("They run with your user's permissions.")
        answer = input("Allow them? You will only be asked again if they change. [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            ui.error(
                f"{_stopped(command)}. Nothing was {'created' if command == 'docket init' else 'changed'}."
            )
            return 2
    _reviewed.remember(loc_path, project, review.runs)
    return 0


def _apply_repo_config(aid: str, apply_source: Path, no_apply: bool) -> int:
    """Plan and apply *apply_source* onto the just-provisioned pod *aid*, printing the plan
    the way ``docket pod update`` does; ``--no-apply`` only prints the command that would
    do it. Called only after provisioning succeeds (ADR 0012)."""
    if no_apply:
        ui.console.print()
        ui.info(f"Skipping apply — run: docket pod update {apply_source}")
        return 0

    try:
        plan = _pod_apply.plan_apply(aid, apply_source)
    except _pod_apply.PodApplyError as exc:
        ui.error(str(exc))
        return 1
    from docket.cli._pod_config import render_apply_header, render_apply_plan

    render_apply_header(aid, apply_source, _pod_apply.summarize_recipe(apply_source))
    render_apply_plan(plan)
    try:
        result = _pod_apply.apply(plan)
    except _pod_apply.PodApplyError as exc:
        ui.error(str(exc))
        return 1
    changed = [item for item in result.items if item.action != "skip"]
    if changed:
        ui.success(f"Applied {len(changed)} change(s) to pod '{aid}' from {apply_source}.")
    return 0


def run_init(req: InitRequest) -> int:
    """Provision a project pod from the request, deriving ordinary defaults from the cwd
    (non-interactive: cwd is the location, its basename the pod id). ``from_file`` takes
    the declarative path instead."""
    _cfg.mkdir_private(_cfg.PROJECTS_DIR)

    if req.from_file is not None:
        return _cmd_add_declarative(req.from_file)

    from docket.core import blueprints as _bp

    blueprint_name = req.blueprint or _bp.DEFAULT_BLUEPRINT
    try:
        blueprint = _bp.get_blueprint(blueprint_name)
    except _bp.BlueprintError as exc:
        ui.error(str(exc))
        return 1

    # Location and identity are deterministic defaults, not a prompt sequence.
    # This makes `docket init` behave like a conventional project initializer.
    is_workdir = blueprint.workspace_kind == "workdir"
    try:
        location = _stored_location(
            req.location if req.location is not None else str(_prov.default_codebase()),
            blueprint.workspace_kind,
        )
    except InvalidInput as exc:
        return _invalid(req, exc.message, exc.hint)
    loc_path = Path(location)

    name = req.name or _prov.suggest_project_name(loc_path)
    try:
        aid = _prov.validate_project_id(_prov.slugify(name))
    except _prov.ProjectIdError as exc:
        return _invalid(req, f"'{name[:40]}' is not a usable pod name: {exc}")

    if (_cfg.PROJECTS_DIR / aid).is_dir() or (_cfg.PROJECTS_DIR / f"{aid}-lead").is_dir():
        ui.error(f"A project or pod '{aid}' already exists.")
        return 1

    # A repository's own `.docket/` is its configuration of record (ADR 0012): discovered,
    # validated, and (unless `--no-apply`) applied after provisioning; `--recipe` starts from
    # a shipped or local recipe the same way, mutually exclusive with a present `.docket/`.
    apply_source, resolve_rc = _resolve_repo_apply_source(loc_path, req.recipe, aid)
    if resolve_rc:
        return resolve_rc
    if apply_source is not None and not req.no_apply:
        review_rc = review_repo_source(req, aid, loc_path, apply_source)
        if review_rc:
            return review_rc

    # No codebase to inspect for a workdir blueprint — stack is whatever the
    # operator types (or blank), never auto-detected from marker files.
    detected_stack = "" if is_workdir else _prov.detect_stack(loc_path)
    stack = detected_stack or ("" if is_workdir else "unknown")
    description = ""

    from docket.cli import _pod

    # --pod full / --with only make sense against the `software` roster —
    # any other blueprint provisions its own fixed roster as-is.
    if blueprint.name == "software":
        roles = _pod.pod_roles(req.full, req.with_roles)
    else:
        if req.full or req.with_roles:
            ui.warn(
                f"--pod/--with only apply to the 'software' blueprint — ignoring for '{blueprint.name}'."
            )
        roles = blueprint.roles

    # The shipped guardrail policies are what make the `pre_input` and `pre_tool_call`
    # screens say anything in a fresh home; idempotent, never overwrites an operator's file.
    _policy.install_policies()

    ui.console.print()
    ui.info(f"Provisioning '{blueprint.name}' pod '{aid}' ({', '.join(roles)})...")
    created = _pod.build_pod_from_blueprint(
        aid,
        blueprint.name,
        location=location,
        stack=stack,
        description=description,
        roles=roles,
        source="interactive",
    )
    if not created:
        ui.error("Pod provisioning failed — no members were registered.")
        return 1

    if apply_source is not None:
        apply_rc = _apply_repo_config(aid, apply_source, req.no_apply)
        if apply_rc:
            return apply_rc

    members = _pp.pod_member_ids(aid) or created  # includes what `.docket/`/--recipe added
    ui.console.print()
    ui.success(f"Pod '{aid}' created with {len(members)} members!")
    for mid in members:
        ui.console.print(f"  - {mid}")
    ui.console.print()
    ui.console.print("  docket pod show        # inspect the pod")
    ui.console.print("  docket pod add reviewer # add a role")
    _offer_desktop_channel()
    from docket.cli import _contract, _setup
    from docket.cli._setup_sandbox import print_sandbox_block

    ui.console.print()
    ui.console.print("This machine")
    print_sandbox_block()

    if not _setup.readiness().endpoint.ok:
        ui.warn("No model endpoint yet")
        _contract.next_step("docket setup")
    return 0


def _offer_desktop_channel() -> None:
    """After the created summary: say so when nothing delivers beyond the console and, on a TTY
    with a desktop session, offer to turn `desktop` on now and send one test notification so
    the operator sees it work before a parked task needs it. Off a TTY only the warning prints."""
    from docket.cli._setup_notify import send_test
    from docket.core import channel as _channel
    from docket.edges.adapters import system as _sys

    unreached = _channel.unreached_warning(_channel.load_catalog().delivering())
    if unreached is None:
        return
    ui.console.print()
    ui.warn(unreached)
    if not sys.stdin.isatty() or not _sys.desktop_notifications_available():
        return
    ans = input("Enable desktop notifications now? [Y/n]: ").strip().lower()
    if ans in ("n", "no"):
        return
    _channel.enable_channel("desktop")
    ui.success("Channel enabled: desktop -- sending one test notification, you should see it now.")
    send_test("desktop")


def _provision_pod_from_spec(
    aid: str, blueprint_name: str, spec: dict[str, Any]
) -> list[str] | None:
    """Provision one pod from a `blueprint`-bearing `--from` entry through
    `cli._pod.build_pod_from_blueprint`, the path `docket init` and `POST /pods` share.
    ``None`` (already warned) means the pod exists or the blueprint is unknown: a skip."""
    from docket.cli import _pod

    _prov.validate_project_id(aid)
    try:
        blueprint = _bp.get_blueprint(blueprint_name)
    except _bp.BlueprintError as exc:
        ui.warn(f"'{aid}': {exc} — skipping.")
        return None

    location_field = "workDir" if blueprint.workspace_kind == "workdir" else "codebase"
    location = _stored_location(str(spec.get(location_field, "")), blueprint.workspace_kind)
    stack = str(spec.get("stack", ""))
    description = str(spec.get("description", ""))
    project_key = str(spec.get("projectKey", "default"))
    budget_usd = _pp.parse_budget_usd(spec.get("budgetUsd"))

    created = _pod.build_pod_from_blueprint(
        aid,
        blueprint.name,
        location=location,
        stack=stack,
        description=description,
        project_key=project_key,
        budget_usd=budget_usd,
        source="declarative",
    )
    if not created:
        # Already warned by build_pod_from_blueprint (already-exists or a
        # genuine provisioning failure) — nothing more to render here.
        return None

    ui.success(f"Provisioned '{blueprint.name}' pod '{aid}' with {len(created)} member(s).")
    return created


def _cmd_add_declarative(from_file: str) -> int:
    """Provision agents from a JSON (or YAML) spec file."""
    path = Path(from_file)
    if not path.is_file():
        ui.error(f"Spec file not found: {from_file}")
        return 1

    content = path.read_text(encoding="utf-8")
    spec_obj: Any

    if from_file.endswith((".yaml", ".yml")):
        try:
            import yaml as _yaml  # type: ignore[import-untyped]

            spec_obj = _yaml.safe_load(content)
        except ImportError:
            ui.error(
                "PyYAML is not installed. Install it with: pip install pyyaml\n"
                "Or convert your spec to JSON."
            )
            return 1
    else:
        try:
            spec_obj = _json.loads(content)
        except _json.JSONDecodeError as exc:
            ui.error(f"Invalid JSON in spec file: {exc}")
            return 1

    agents_spec: list[dict[str, Any]]
    if isinstance(spec_obj, list):
        agents_spec = spec_obj
    elif isinstance(spec_obj, dict) and "agents" in spec_obj:
        agents_spec = list(spec_obj["agents"])
    elif isinstance(spec_obj, dict):
        agents_spec = [spec_obj]
    else:
        ui.error("Spec file must be a JSON object or array of agent specs.")
        return 1

    created: list[str] = []
    skipped: list[str] = []
    had_invalid_id = False
    had_refused = False

    for spec in agents_spec:
        aid = str(spec.get("id", "")).strip()
        if not aid:
            ui.warn("Skipping spec entry with no 'id' field.")
            continue

        blueprint_name = str(spec.get("blueprint", "")).strip()
        if not blueprint_name:
            ui.error(
                escape(
                    f"'{aid}': an entry needs a 'blueprint' ({', '.join(_bp.load_registry().names())})"
                )
            )
            skipped.append(aid)
            had_refused = True
            continue
        try:
            pod_created = _provision_pod_from_spec(aid, blueprint_name, spec)
        except _prov.ProjectIdError as exc:
            ui.error(escape(f"'{aid}': {exc}"))
            skipped.append(aid)
            had_invalid_id = True
            continue
        except InvalidInput as exc:
            ui.error(escape(f"'{aid}': {exc.message}"))
            skipped.append(aid)
            had_refused = True
            continue
        if pod_created is None:
            skipped.append(aid)
            continue
        created.extend(pod_created)
        tg_group = str(spec.get("telegram", "")).strip()
        if tg_group:
            lead_id = f"{aid}-lead"
            _fleet.upsert_binding(lead_id, tg_group, "telegram", "group")
            ui.success(f"Telegram binding: {lead_id} ← group {tg_group}")

    ui.console.print()
    if created:
        ui.success(f"Created {len(created)} agent(s): {', '.join(created)}")
    if skipped:
        ui.warn(f"Skipped {len(skipped)} existing agent(s): {', '.join(skipped)}")
    if not created and not skipped:
        ui.warn("No agents provisioned.")
    if had_refused:
        return 2
    return 1 if had_invalid_id else 0


def cmd_init(
    project: str | None = typer.Argument(
        None, help="The pod's name; defaults to the current directory's name."
    ),
    location: str | None = typer.Argument(
        None,
        help="The codebase (or a workdir blueprint's working directory); defaults to the cwd.",
    ),
    blueprint: str | None = typer.Option(
        None,
        "--blueprint",
        help="software (the default), research, content, ops or agentic-product.",
    ),
    pod: str | None = typer.Option(
        None,
        "--pod",
        help="'full': Lead, Implementer, Reviewer and Tester (software blueprint only).",
    ),
    with_roles: str | None = typer.Option(
        None,
        "--with",
        help="Roles to add to the lean pod, comma-separated: reviewer, tester, implementer.",
    ),
    codebase: str | None = typer.Option(
        None, "--codebase", help="The location, as an option instead of the argument."
    ),
    name: str | None = typer.Option(
        None, "--name", help="The pod's name, as an option instead of the argument."
    ),
    from_file: str | None = typer.Option(
        None,
        "--from",
        help="Provision pods and agents from one JSON or YAML file; excludes every other option.",
    ),
    recipe: str | None = typer.Option(
        None,
        "--recipe",
        help="Apply a shipped recipe (docket pod recipes) or a recipe directory afterwards.",
    ),
    no_apply: bool = typer.Option(
        False,
        "--no-apply",
        help="Provision only; print the docket pod update command for .docket/ or the recipe.",
    ),
    accept: str | None = typer.Option(
        None,
        "--accept",
        help="Allow exactly the commands a repository brings, by the review code a refused init printed.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Print a refused review as JSON (status, reviewCode, items)."
    ),
) -> None:
    """Create the team for this repository: a pod of agents that owns this codebase.

    With no arguments the pod is named after the current directory and holds
    a Lead and an Implementer (ids `<pod>-lead`, `<pod>-implementer`).
    A `.docket/` directory next to the code, what `docket pod export` writes,
    is validated first and applied after provisioning, so the repository's
    own team definition is what you get; `--recipe` starts from a shipped
    team instead. Blueprints, `--from` entries and the apply step:
    specs/functional/pod-blueprints.spec.md.

    Example: docket init --recipe secure-build"""
    if pod not in (None, "full"):
        raise typer.BadParameter("only 'full' is accepted", param_hint="--pod")
    others = (project, location, blueprint, pod, with_roles, codebase, name, recipe)
    if from_file is not None and (
        no_apply or accept or json_out or any(o is not None for o in others)
    ):
        raise typer.BadParameter("--from takes no other argument or option", param_hint="--from")
    req = InitRequest(
        name=name or project,
        location=codebase or location,
        blueprint=blueprint,
        recipe=recipe,
        no_apply=no_apply,
        accept=accept,
        json_out=json_out,
        from_file=from_file,
        full=pod == "full",
        with_roles=with_roles or "",
    )
    raise typer.Exit(run_init(req))
