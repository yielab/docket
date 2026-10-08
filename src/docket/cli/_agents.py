"""docket init: create a project pod, or provision agents declaratively.

``cmd_init`` is the Typer command; it builds an ``InitRequest`` and ``run_init`` returns the
process exit code.
``_create_workspace``/``_provision_agent`` are the single-agent template + registration path
(pods use ``cli/_pod.py`` instead).
"""

from __future__ import annotations

import contextlib
import json as _json
import re as _re
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
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import provisioning as _prov
from docket.core import secrets as _secrets
from docket.core.audit import audit_log
from docket.edges import store


@dataclass(frozen=True)
class InitRequest:
    """What `docket init` was asked for, as Typer parsed it."""

    name: str | None = None
    location: str | None = None
    blueprint: str | None = None
    recipe: str | None = None
    no_apply: bool = False
    from_file: str | None = None
    full: bool = False
    with_roles: str = ""


def _resolve_repo_apply_source(loc_path: Path, cli_recipe: str | None) -> tuple[Path | None, int]:
    """The directory `docket init` should apply after provisioning -- a present ``.docket/``
    or a resolved ``--recipe``, mutually exclusive, validated first (ADR 0012). ``(None, 1)``
    means stop (already printed); ``(None, 0)`` means nothing to apply."""
    docket_dir = loc_path / ".docket"
    has_docket_dir = docket_dir.is_dir()
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


def _apply_repo_config(aid: str, apply_source: Path, no_apply: bool) -> int:
    """Plan and apply *apply_source* onto the just-provisioned pod *aid*, printing the plan
    the way ``docket pod apply`` does; ``--no-apply`` only prints the command that would
    do it. Called only after provisioning succeeds (ADR 0012)."""
    if no_apply:
        ui.console.print()
        ui.info(f"Skipping apply — run: docket pod apply {apply_source}")
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
    _cfg.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

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
    if req.location is not None:
        location = str(Path(req.location).expanduser())
    else:
        location = str(_prov.default_codebase())
    loc_path = Path(location)

    suggested_name = req.name or _prov.suggest_project_name(loc_path)
    name = req.name or suggested_name
    if not name:
        ui.error("Name is required.")
        return 1

    slug = _prov.slugify(name)
    aid = slug

    if (_cfg.PROJECTS_DIR / aid).is_dir() or (_cfg.PROJECTS_DIR / f"{aid}-lead").is_dir():
        ui.error(f"A project or pod '{aid}' already exists.")
        return 1

    # A repository's own `.docket/` is its configuration of record (ADR 0012): discovered,
    # validated, and (unless `--no-apply`) applied after provisioning; `--recipe` starts from
    # a shipped or local recipe the same way, mutually exclusive with a present `.docket/`.
    apply_source, resolve_rc = _resolve_repo_apply_source(loc_path, req.recipe)
    if resolve_rc:
        return resolve_rc

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

    try:
        blueprint = _bp.get_blueprint(blueprint_name)
    except _bp.BlueprintError as exc:
        ui.warn(f"'{aid}': {exc} — skipping.")
        return None

    location_field = "workDir" if blueprint.workspace_kind == "workdir" else "codebase"
    location = str(spec.get(location_field, ""))
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

    for spec in agents_spec:
        aid = str(spec.get("id", "")).strip()
        if not aid:
            ui.warn("Skipping spec entry with no 'id' field.")
            continue

        # A spec entry carrying a `blueprint` field provisions a *pod*
        # (build_pod_from_blueprint) instead of the single
        # flat agent below — a genuinely different shape (a blueprint pod is
        # never fewer than a Lead + one worker), so it gets its own existence
        # check (`<aid>-lead`, not the bare `<aid>` workspace dir) rather than
        # forcing the single-agent branch to understand pods.
        blueprint_name = str(spec.get("blueprint", "")).strip()
        if blueprint_name:
            try:
                pod_created = _provision_pod_from_spec(aid, blueprint_name, spec)
            except _prov.ProjectIdError as exc:
                ui.error(f"'{aid}': {exc}")
                skipped.append(aid)
                had_invalid_id = True
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
            continue

        if (_cfg.PROJECTS_DIR / aid).is_dir():
            ui.warn(f"'{aid}' already exists — skipping.")
            skipped.append(aid)
            continue

        name = str(spec.get("name", aid))
        codebase = str(spec.get("codebase", ""))
        stack = str(spec.get("stack", ""))
        model = str(spec.get("model", ""))
        description = str(spec.get("description", ""))
        tg_group = str(spec.get("telegram", "")).strip()
        budget = str(spec.get("budgetUsd", ""))
        project_key = str(spec.get("projectKey", "default"))

        _provision_agent(
            aid,
            name,
            codebase,
            stack,
            model,
            description,
            project_key,
            budget,
            "declarative",
        )
        created.append(aid)

        if tg_group:
            _fleet.upsert_binding(aid, tg_group, "telegram", "group")
            ui.success(f"Telegram binding: {aid} ← group {tg_group}")

    ui.console.print()
    if created:
        ui.success(f"Created {len(created)} agent(s): {', '.join(created)}")
    if skipped:
        ui.warn(f"Skipped {len(skipped)} existing agent(s): {', '.join(skipped)}")
    if not created and not skipped:
        ui.warn("No agents provisioned.")
    return 1 if had_invalid_id else 0


def _create_workspace(
    agent_id: str,
    name: str,
    codebase: str,
    stack: str,
    description: str,
    model: str,
) -> None:
    """Create a single project agent's workspace directory and template files."""
    ws = _cfg.PROJECTS_DIR / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)

    session_key = f"agent:{agent_id}:default"

    test_cmd = _test_cmd_for_stack(stack)

    soul = (
        f"# SOUL.md — {name}\n\n"
        "## Identity\n"
        f"You are the autonomous agent for **{name}**. "
        "You know this project deeply. You do not discuss or act on other projects.\n\n"
        f"**Session Key:** `{session_key}`\n\n"
        "This session key isolates you from other project contexts. "
        "You may only access resources and memory within this coordinate space.\n\n"
        "## Description\n"
        f"{description}\n\n"
        "## Codebase\n"
        f"{codebase}\n\n"
        "## Stack\n"
        f"{stack}\n\n"
        "## Test Command\n"
        f"`{test_cmd}`\n\n"
        "## Traits\n"
        "- Read files before making any changes. Never assume structure.\n"
        "- Completion signal: output `<promise>DONE</promise>` when a task is complete.\n"
        f"- Proactive: check {_mem.HEARTBEAT_FILE} every session.\n"
        f"- Scope: never act outside {codebase}.\n"
        "- Context isolation: respect the session key boundary — no cross-project access.\n\n"
        "## Safety\n"
        "- Never push to main/master without HITL approval.\n"
        "- Never delete files without explicit instruction.\n"
    )
    # Section names matter: the turn loop re-injects the "Session Startup"
    # and "Red Lines" H2 blocks after every compaction (readPostCompactionContext).
    # Keep these headings verbatim or the injection silently stops firing.
    agents = (
        f"# AGENTS.md — {name}\n\n"
        "## Session Startup\n"
        "_Lean — re-sent every turn._\n"
        f"1. Read {_mem.REQUIRED_STARTUP_FILE} — startup protocol + your codebase\n"
        "   path (the runtime requires this after every context reset).\n"
        f"2. Read {_mem.HEARTBEAT_FILE} — active tasks/decisions (small; always). Unchecked\n"
        "   items mean you were interrupted mid-task: resume them, don't greet idle.\n"
        "3. Read history ONLY when the task needs it: open MEMORY.md, then the\n"
        "   specific memory/YYYY-MM-DD.md you need. Do not slurp the whole\n"
        "   memory/ dir or re-read MEMORY.md when the task doesn't need it —\n"
        "   every byte you read is re-sent on every later turn.\n"
        "4. Log outcomes to today's memory/YYYY-MM-DD.md (one file per day).\n\n"
        "## Red Lines\n"
        f"- Only act on {name}. Redirect other project questions to the correct group.\n"
        "- Never push to main/master or delete files without HITL approval.\n"
        f"- Before starting multi-step work, write it to {_mem.HEARTBEAT_FILE} — an unwritten\n"
        "  task does not survive a context reset.\n\n"
        "## Project Path\n"
        f"{codebase}\n\n"
        "## First Run\n"
        "If MEMORY.md is missing, read the codebase and write it:\n"
        "1. Check package.json / requirements.txt / composer.json\n"
        "2. Read key entry points\n"
        "3. Check git log --oneline -20\n"
        "4. Write MEMORY.md: architecture, current state, key files, known issues\n"
    )
    tools = (
        f"# TOOLS.md — {name}\n\n"
        "## Project Path\n"
        f"{codebase}\n\n"
        "## Stack\n"
        f"{stack}\n\n"
        "## Commands\n"
        "```bash\n"
        f"{test_cmd}       # run tests\n"
        "git log --oneline -10  # recent history\n"
        "git diff HEAD          # review before commit\n"
        "```\n\n"
        "## Environment Notes\n"
        "_Add: DB name, ports, env vars, dev server command, seed scripts._\n"
    )

    heartbeat = _mem.heartbeat_seed(name)

    for fname, text in [
        ("SOUL.md", soul),
        ("AGENTS.md", agents),
        ("TOOLS.md", tools),
        (_mem.HEARTBEAT_FILE, heartbeat),
    ]:
        fpath = ws / fname
        fpath.write_text(text, encoding="utf-8")
        fpath.chmod(0o600)

    # Seed the files the turn loop's system-prompt composition re-reads every turn.
    _mem.seed_contract(ws, project=name, codebase=codebase, stack=stack)

    ws.chmod(0o700)
    (ws / "memory").chmod(0o700)


def _provision_agent(
    agent_id: str,
    name: str,
    codebase: str,
    stack: str,
    model: str,
    description: str,
    project_key: str,
    budget: str,
    source: str,
) -> None:
    """Create workspace, write metadata, register in the fleet registry."""
    if not model:
        model = _mp.resolve_role_model(_mp.REPO_AGENT_ROLE)
    else:
        with contextlib.suppress(Exception):
            model = _mp.validate_model(model)[0]

    session_key = f"agent:{agent_id}:{project_key}"

    _create_workspace(agent_id, name, codebase, stack, description, model)

    meta_data: dict[str, Any] = {
        "kind": "project",
        "name": name,
        "codebase": codebase,
        "stack": stack,
        "model": model,
        "description": description,
        "sessionKey": session_key,
        "projectKey": project_key,
        "templateVersion": str(_cfg.TEMPLATE_VERSION),
    }
    if budget and budget not in ("", "0"):
        meta_data["budgetUsd"] = budget

    meta_file = _cfg.PROJECTS_DIR / agent_id / ".docket-meta.json"
    store.write_json(meta_file, meta_data)

    # Registration is fleet.json only -- there is no daemon to register with
    # (and no daemon session directory to pre-create; core/session.py creates
    # a session's storage lazily).
    with contextlib.suppress(Exception):
        _fleet.add_agent(agent_id)

    audit_log("agent.add", f"{agent_id} model={model} source={source}")

    if not _secrets.secrets_keys():
        ui.warn(
            "No model-provider credential stored. Run: docket setup provider add <provider> --credential"
        )


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
        help="Provision only; print the docket pod apply command for .docket/ or the recipe.",
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
    if from_file is not None and (no_apply or any(o is not None for o in others)):
        raise typer.BadParameter("--from takes no other argument or option", param_hint="--from")
    req = InitRequest(
        name=name or project,
        location=codebase or location,
        blueprint=blueprint,
        recipe=recipe,
        no_apply=no_apply,
        from_file=from_file,
        full=pod == "full",
        with_roles=with_roles or "",
    )
    raise typer.Exit(run_init(req))


def _test_cmd_for_stack(stack: str) -> str:
    """Return a sensible default test command for a detected stack."""
    if _re.search(r"pytest|Python|FastAPI|Django|Flask", stack, _re.I):
        return "pytest -v"
    if _re.search(r"Node|npm|Next|React|Express|Fastify", stack, _re.I):
        return "npm test"
    if _re.search(r"PHP|Drupal|Laravel", stack, _re.I):
        return "./vendor/bin/phpunit"
    if _re.search(r"\bGo\b", stack):
        return "go test ./..."
    if _re.search(r"Rust", stack, _re.I):
        return "cargo test"
    return "# add test command"
