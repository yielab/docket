"""docket init / add / info / delete / maintain — agent/pod workspace CRUD.

Each ``run_*`` function returns the process exit code; the coordinator
(``cli/__init__.py``) wraps it in a Typer command and raises
``typer.Exit(code)``. ``_create_workspace``/``_provision_agent`` are the
single-agent template + registration path (pods use ``cli/_pod.py`` instead,
which this module reaches into for pod-aware add/delete).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json as _json
import os
import re as _re
import shutil as _shutil
import stat as _stat
import sys
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.cli._flags import find_unknown_flag
from docket.cli._target import TargetError, resolve_pod
from docket.core import blueprints as _bp
from docket.core import config_docs as _config_docs
from docket.core import fleet as _fleet
from docket.core import identity as _identity
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import provisioning as _prov
from docket.core import secrets as _secrets
from docket.core.audit import audit_log
from docket.core.models import AgentMeta
from docket.core.utils import last_activity, project_ids
from docket.edges import store
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters import llm as _llm

# Flags that consume the following token as their value (skipped when scanning
# for bare positionals). --with/--pod are handled by parse_pod_roles.
_ADD_VALUE_FLAGS = frozenset(
    {
        "--from",
        "--codebase",
        "--name",
        "--with",
        "--pod",
        "--model",
        "--count",
        "--blueprint",
    }
)


def _parse_add_args(
    all_args: list[str],
) -> tuple[str | None, str | None, str | None, str | None, str | None, bool]:
    """Extract (from_file, codebase, name, blueprint, recipe, no_apply) from `docket add`
    args: flags or bare positionals, trusted and skipping their interactive prompt.
    ``--recipe`` names a directory to apply after provisioning; ``--no-apply`` skips it."""
    from_file: str | None = None
    codebase: str | None = None
    name: str | None = None
    blueprint: str | None = None
    recipe: str | None = None
    no_apply = "--no-apply" in all_args
    positionals: list[str] = []

    i = 0
    while i < len(all_args):
        arg = all_args[i]
        if arg == "--no-apply":
            i += 1
            continue
        for flag, setter in (
            ("--from", "from"),
            ("--codebase", "cb"),
            ("--name", "nm"),
            ("--blueprint", "bp"),
            ("--recipe", "rc"),
        ):
            if arg == flag and i + 1 < len(all_args):
                val = all_args[i + 1]
                i += 2
                break
            if arg.startswith(flag + "="):
                val, setter = arg[len(flag) + 1 :], setter
                i += 1
                break
        else:
            # Not one of our value flags. Skip other flags (and their value if
            # they take one) so pod flags don't leak into positionals.
            if arg.startswith("-"):
                i += 2 if arg in _ADD_VALUE_FLAGS else 1
                continue
            positionals.append(arg)
            i += 1
            continue
        if setter == "from":
            from_file = val
        elif setter == "cb":
            codebase = val
        elif setter == "nm":
            name = val
        elif setter == "bp":
            blueprint = val
        elif setter == "rc":
            recipe = val

    if positionals:
        if name is None:
            name = positionals[0]
        if codebase is None and len(positionals) > 1:
            codebase = positionals[1]
    return from_file, codebase, name, blueprint, recipe, no_apply


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
    the way ``docket pod <p> apply`` does; ``--no-apply`` only prints the command that would
    do it. Called only after provisioning succeeds (ADR 0012)."""
    if no_apply:
        ui.console.print()
        ui.info(f"Skipping apply — run: docket pod {aid} apply {apply_source}")
        return 0

    try:
        plan = _pod_apply.plan_apply(aid, apply_source)
    except _pod_apply.PodApplyError as exc:
        ui.error(str(exc))
        return 1
    from docket.cli._pod import render_apply_header, render_apply_plan

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


def run_init(all_args: list[str]) -> int:
    """Initialize a project pod, deriving ordinary defaults from the cwd (intentionally
    non-interactive with zero args: cwd is the location, its basename the pod id).
    Explicit args/options override; ``--from`` retains the declarative path."""
    project_args = all_args
    known_flags = _ADD_VALUE_FLAGS | {"--recipe", "--no-apply"}
    for arg in project_args:
        if arg.startswith("--") and arg.split("=", 1)[0] not in known_flags:
            ui.error(f"No such option: {arg.split('=', 1)[0]}")
            return 2

    _cfg.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    from_file, cli_codebase, cli_name, cli_blueprint, cli_recipe, no_apply = _parse_add_args(
        project_args
    )

    if from_file is not None:
        return _cmd_add_declarative(from_file)

    from docket.core import blueprints as _bp

    blueprint_name = cli_blueprint or _bp.DEFAULT_BLUEPRINT
    try:
        blueprint = _bp.get_blueprint(blueprint_name)
    except _bp.BlueprintError as exc:
        ui.error(str(exc))
        return 1

    # Location and identity are deterministic defaults, not a prompt sequence.
    # This makes `docket init` behave like a conventional project initializer.
    is_workdir = blueprint.workspace_kind == "workdir"
    if cli_codebase is not None:
        location = str(Path(cli_codebase).expanduser())
    else:
        location = str(_prov.default_codebase())
    loc_path = Path(location)

    suggested_name = cli_name or _prov.suggest_project_name(loc_path)
    name = cli_name or suggested_name
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
    apply_source, resolve_rc = _resolve_repo_apply_source(loc_path, cli_recipe)
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
        roles = _pod.parse_pod_roles(project_args)
    else:
        if any(a in ("--pod", "--with") or a.startswith("--with=") for a in project_args):
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
        apply_rc = _apply_repo_config(aid, apply_source, no_apply)
        if apply_rc:
            return apply_rc

    lead_id = f"{aid}-lead"
    members = _pp.pod_member_ids(aid) or created  # includes what `.docket/`/--recipe added
    ui.console.print()
    ui.success(f"Pod '{aid}' created with {len(members)} members!")
    for mid in members:
        ui.console.print(f"  - {mid}")
    ui.console.print()
    ui.console.print(f"  docket pod {aid}              # inspect the pod")
    ui.console.print(f"  docket pod {aid} add reviewer # add a role")
    ui.console.print(f"  docket wire {lead_id}   # optional Telegram binding")
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
    from docket.cli._channels import _run_test
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
    _run_test(["desktop"])


def _parse_existing_pod_add_args(all_args: list[str]) -> tuple[str | None, list[str]]:
    """Return an explicit ``--project`` and the args forwarded to ``pod add``."""
    project: str | None = None
    forwarded: list[str] = []
    i = 0
    while i < len(all_args):
        arg = all_args[i]
        if arg == "--project":
            if i + 1 >= len(all_args):
                ui.error("--project requires a pod id")
                return "", []
            project = all_args[i + 1]
            i += 2
            continue
        if arg.startswith("--project="):
            project = arg.split("=", 1)[1]
            i += 1
            continue
        forwarded.append(arg)
        i += 1
    return project, forwarded


def run_add(all_args: list[str]) -> int:
    """Add role agents to an existing pod; never provisions a new project."""
    explicit_project, forwarded = _parse_existing_pod_add_args(all_args)
    if explicit_project == "":
        return 1

    try:
        project = resolve_pod(explicit_project or None, env=os.environ, cwd=Path.cwd())
    except TargetError as exc:
        ui.error(str(exc))
        return 1

    if not forwarded or forwarded[0].startswith("-"):
        ui.error(
            "A role is required. Use: docket add <role> "
            '[--project <pod>] [--count N] [--verify "<cmd>"]'
        )
        return 1

    from docket.cli import _pod

    _pod.dispatch(project, "add", forwarded)
    return 0


def _provision_pod_from_spec(
    aid: str, blueprint_name: str, spec: dict[str, Any]
) -> list[str] | None:
    """Provision one pod from a `blueprint`-bearing `--from spec.yaml` entry. Returns
    the created member ids, or ``None`` (already warned) if the pod exists or the
    blueprint is unknown — the caller counts that as a skip, matching the single-agent
    path's idempotence contract. Goes through `cli._pod.build_pod_from_blueprint`,
    the same path `docket add` and `POST /pods` use."""
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


def _apply_persona_from_meta(ws: Path, soul_text: str) -> str:
    """Upsert the persona block into *soul_text* from ``ws``'s existing meta. A no-op
    for a brand-new or persona-less agent; on ``maintain rebuild`` it re-renders the
    docket-owned persona so identity stays a pure function of metadata."""
    from docket.core import identity as _identity
    from docket.core.models import AgentMeta

    meta_file = ws / _cfg.META_FILE
    if not meta_file.exists():
        return soul_text
    try:
        meta = AgentMeta.model_validate(store.read_json(meta_file))
    except Exception:
        return soul_text
    return _identity.upsert_persona_block(soul_text, meta.persona)


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

    # Re-apply the docket-owned persona from metadata (if any) so a `maintain
    # rebuild` regenerates identity from meta rather than dropping the persona.
    soul = _apply_persona_from_meta(ws, soul)

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
        model_source_val = "policy"
    else:
        with contextlib.suppress(Exception):
            model = _mp.validate_model(model)[0]
        policy_model = _mp.resolve_role_model(_mp.REPO_AGENT_ROLE)
        model_source_val = "policy" if model == policy_model else "pinned"

    session_key = f"agent:{agent_id}:{project_key}"

    _create_workspace(agent_id, name, codebase, stack, description, model)

    meta_data: dict[str, Any] = {
        "kind": "project",
        "name": name,
        "codebase": codebase,
        "stack": stack,
        "model": model,
        "modelSource": model_source_val,
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


def run_info(agent_id: str | None, json_out: bool) -> int:
    """Dispatch `docket info`. Returns the process exit code."""
    if agent_id is None:
        if json_out:
            ui.error("An agent id is required with --json (e.g. docket info <id> --json).")
            return 1
        if not sys.stdin.isatty():
            ui.error("An agent id is required (e.g. docket info <id>).")
            return 1
        ids = project_ids()
        if not ids:
            ui.warn("No project agents found.")
            return 0
        ui.console.print("Available agents:")
        for i, pick in enumerate(ids, 1):
            ui.console.print(f"  {i}) {pick}")
        raw_choice = input("Enter number: ").strip()
        try:
            idx = int(raw_choice) - 1
            if 0 <= idx < len(ids):
                agent_id = ids[idx]
            else:
                ui.error("Invalid selection.")
                return 1
        except ValueError:
            ui.error("Invalid selection.")
            return 1

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        return 1

    if json_out:
        _cmd_info_json(aid)
    else:
        _cmd_info_human(aid)
    return 0


def _cmd_info_json(agent_id: str) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    registered = _fleet.agent_registered(agent_id)
    tg = _fleet.get_binding(agent_id)
    activity = last_activity(agent_id)

    print(
        _json.dumps(
            {
                "id": agent_id,
                "name": raw.get("name", agent_id),
                "codebase": raw.get("codebase", ""),
                "stack": raw.get("stack", ""),
                "model": raw.get("model", _cfg.DEFAULT_MODEL),
                "budgetUsd": _pp.parse_budget_usd(raw.get("budgetUsd")),
                "paused": AgentMeta.coerce_paused(raw.get("paused", False)),
                "sessionKey": raw.get("sessionKey", f"agent:{agent_id}:default"),
                "projectKey": raw.get("projectKey", "default"),
                "registered": registered,
                "telegram": tg or None,
                "lastActive": activity,
            },
            indent=2,
        )
    )


def _cmd_info_human(agent_id: str) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    ws = _cfg.workspace_dir(agent_id)

    name = str(raw.get("name", agent_id))
    codebase = str(raw.get("codebase", "—"))
    stack = str(raw.get("stack", "—"))
    model = str(raw.get("model", _cfg.DEFAULT_MODEL))
    budget = raw.get("budgetUsd")
    paused = AgentMeta.coerce_paused(raw.get("paused", False))
    paused_reason = str(raw.get("pausedReason", ""))
    session_key = str(raw.get("sessionKey", f"agent:{agent_id}:default"))
    project_key = str(raw.get("projectKey", "default"))

    registered = _fleet.agent_registered(agent_id)
    tg = _fleet.get_binding(agent_id)
    activity = last_activity(agent_id)

    mem_count = sum(1 for _ in (ws / "memory").glob("*.md")) if (ws / "memory").is_dir() else 0
    has_memory = "yes" if (ws / "MEMORY.md").is_file() else "no"
    has_reqs = "yes" if (ws / "REQUIREMENTS.md").is_file() else "no"

    ui.header(f"Project: {name} ({agent_id})")
    ui.console.print()
    ui.console.print(f"  [bold]{'Workspace:':<18}[/bold] {ws}")
    ui.console.print(f"  [bold]{'Codebase:':<18}[/bold] {codebase}")
    ui.console.print(f"  [bold]{'Stack:':<18}[/bold] {stack}")
    ui.console.print(f"  [bold]{'Model:':<18}[/bold] {model}")
    if budget and str(budget) not in ("", "0"):
        ui.console.print(f"  [bold]{'Budget cap:':<18}[/bold] ${float(budget):.2f}")
    if paused:
        reason_str = f" ({paused_reason})" if paused_reason else ""
        ui.console.print(f"  [bold]{'Status:':<18}[/bold] [red]PAUSED[/red]{reason_str}")
    ui.console.print(f"  [bold]{'Session Key:':<18}[/bold] {session_key}")
    ui.console.print(f"  [bold]{'Project Scope:':<18}[/bold] {project_key}")
    ui.console.print()

    reg_str = "[green]yes[/green]" if registered else "[red]no[/red]"
    ui.console.print(f"  [bold]{'Registered:':<18}[/bold] {reg_str}")

    if tg:
        ui.console.print(f"  [bold]{'Telegram:':<18}[/bold] [green]{tg}[/green]")
    else:
        ui.console.print(f"  [bold]{'Telegram:':<18}[/bold] [yellow]not wired[/yellow]")

    ui.console.print(f"  [bold]{'Last active:':<18}[/bold] {activity}")
    ui.console.print(f"  [bold]{'Memory days:':<18}[/bold] {mem_count}")
    ui.console.print(f"  [bold]{'MEMORY.md:':<18}[/bold] {has_memory}")
    ui.console.print(f"  [bold]{'REQUIREMENTS:':<18}[/bold] {has_reqs}")

    ui.console.print()
    ui.header("Workspace files")
    for f in sorted(ws.iterdir()):
        if not f.is_file():
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").count("\n")
        except OSError:
            lines = 0
        ui.console.print(f"  {f.name:<30} {lines} lines")

    if tg and codebase not in ("", "—"):
        ui.console.print()
        ui.header("First-run prompt (send in Telegram group if MEMORY.md is missing)")
        ui.console.print()
        ui.console.print(
            f"  Read the codebase at {codebase} and update your\n"
            "  SOUL.md and MEMORY.md with: tech stack, entry points,\n"
            "  architecture, current state, recent git activity."
        )
        ui.console.print()


def run_delete(agent_id: str | None) -> int:
    """Dispatch `docket delete`. Returns the process exit code."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            return 1

        agent_id = _pick_agent("Delete project")

    aid: str = agent_id

    from docket.cli import _pod

    members = _pod.pod_member_ids(aid)
    if members:
        return _pod._delete_pod(aid, members)

    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        return 1

    name = _fleet.meta_get(aid, "name", aid)
    tg = _fleet.get_binding(aid)
    registered = _fleet.agent_registered(aid)

    ui.header(f"Delete: {name} ({aid})")
    ui.console.print()
    ui.console.print(f"  Workspace:    {ws}")
    ui.console.print(f"  Registered:   {'yes' if registered else 'no'}")
    ui.console.print(f"  Telegram:     {tg or 'none'}")
    ui.console.print()
    ui.warn("This will:")
    ui.console.print("  - Remove agent registration from the fleet registry")
    ui.console.print("  - Remove Telegram binding (if any)")
    ui.console.print()

    del_ws = input("Also delete workspace directory? [y/N]: ").strip()
    ui.console.print()
    confirm = input(f"Type the agent ID to confirm deletion [{aid}]: ").strip()

    if confirm != aid:
        ui.warn("Aborted.")
        return 0

    _fleet.remove_agent(aid)
    audit_log("agent.delete", aid)
    ui.success("Removed from agent registry")

    if tg:
        _fleet.remove_binding(aid)
        ui.success("Telegram binding removed")

    from docket.core import conversations as _conv

    _conv.remove_agent_durable(aid)

    if del_ws.lower() == "y":
        _shutil.rmtree(ws, ignore_errors=True)
        ui.success(f"Workspace deleted: {ws}")
    else:
        ui.warn(f"Workspace kept at: {ws}")

    ui.success(f"Done. Project '{aid}' deleted.")
    return 0


def run_maintain(agent_id: str | None, mode: str | None, extra: list[str] | None = None) -> int:
    """Dispatch `docket maintain`; returns the exit code. ``extra`` carries flags
    following ``mode`` (``--no-distill-first``) — Typer allows/ignores unknown options so
    they land here, the pattern every ``ctx.args`` subcommand uses."""
    bad = find_unknown_flag(extra or [], frozenset({"--no-distill-first"}))
    if bad is not None:
        ui.error(f"docket maintain: unrecognized flag '{bad}'")
        return 2
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            return 1

        agent_id = _pick_agent("Maintain workspace for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        return 1

    action = mode or "check"
    args = extra or []
    # Distillation defaults ON: `clean`/`reset` must not bare-delete
    # undistilled memory without an explicit opt-out.
    distill_first = "--no-distill-first" not in args

    if action == "check":
        _maintain_check(aid, ws)
    elif action == "clean":
        return _maintain_clean(aid, ws, distill_first=distill_first)
    elif action == "reset":
        return _maintain_reset(aid, ws, distill_first=distill_first)
    elif action == "rebuild":
        return _maintain_rebuild(aid, ws)
    elif action == "sessions":
        _maintain_sessions(aid)
    elif action == "distill":
        return _maintain_distill(aid, ws)
    else:
        ui.error(
            f"Unknown maintain subcommand '{action}'. "
            "Use: check, clean, reset, rebuild, sessions, distill"
        )
        return 1
    return 0


def _maintain_check(agent_id: str, ws: Path) -> None:
    """check: verify permissions, missing files, session key sync, memory dir."""
    ui.header(f"Health Check: {agent_id}")
    ui.console.print()

    issues: list[str] = []

    perm_ok = True
    managed_paths = [ws]
    for top_level in ws.iterdir():
        # A pod Implementer's Git worktrees are repository content. Recursing through it
        # turns executables into 0600 files and directories into 0700, corrupting the
        # checkout while claiming to heal Docket's workspace. Only Docket-owned
        # prompt/meta/memory paths belong here.
        if top_level.name == "tasks" or top_level.is_symlink():
            continue
        managed_paths.append(top_level)
        if top_level.is_dir():
            managed_paths.extend(path for path in top_level.rglob("*") if not path.is_symlink())
    for dirpath in managed_paths:
        try:
            mode = dirpath.stat().st_mode
            if dirpath.is_dir():
                if _stat.S_IMODE(mode) != 0o700:
                    dirpath.chmod(0o700)
            elif dirpath.is_file() and _stat.S_IMODE(mode) != 0o600:
                dirpath.chmod(0o600)
        except OSError:
            perm_ok = False
    if perm_ok:
        ui.console.print("  [green]✓[/green] Permissions: ok (dirs 700, files 600)")
    else:
        ui.console.print("  [yellow]⚠[/yellow] Permissions: some could not be set")

    required = ["SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE, ".docket-meta.json"]
    missing_files = [f for f in required if not (ws / f).is_file()]
    if missing_files:
        issues.extend(missing_files)
        for mf in missing_files:
            ui.console.print(f"  [red]✗[/red] Missing file: {mf}")
        if sys.stdin.isatty():
            ans = input("  Regenerate missing workspace files? [y/N]: ").strip().lower()
            if ans == "y":
                raw = store.read_json(_cfg.meta_path(agent_id))
                _create_workspace(
                    agent_id,
                    str(raw.get("name", agent_id)),
                    str(raw.get("codebase", "")),
                    str(raw.get("stack", "")),
                    str(raw.get("description", "")),
                    str(raw.get("model", _cfg.DEFAULT_MODEL)),
                )
                ui.success("Workspace files regenerated.")
                missing_files = []
    else:
        ui.console.print("  [green]✓[/green] Required files: all present")

    meta_session = _fleet.meta_get(agent_id, "sessionKey", "")
    soul_path = ws / "SOUL.md"
    soul_session = ""
    if soul_path.is_file():
        for ln in soul_path.read_text(encoding="utf-8").splitlines():
            if "Session Key:" in ln or "session_key" in ln.lower():
                m = _re.search(r"`([^`]+)`", ln)
                if m:
                    soul_session = m.group(1)
                    break

    if meta_session and soul_session and meta_session != soul_session:
        ui.console.print(
            f"  [yellow]⚠[/yellow] Session key mismatch:\n"
            f"     meta:   {meta_session}\n"
            f"     SOUL.md: {soul_session}"
        )
        issues.append("session key mismatch")
    else:
        ui.console.print("  [green]✓[/green] Session key: in sync")

    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        mem_count = sum(1 for _ in mem_dir.glob("*.md"))
        ui.console.print(f"  [green]✓[/green] Memory directory: {mem_count} log(s)")
    else:
        ui.console.print("  [yellow]⚠[/yellow] Memory directory: missing")
        mem_dir.mkdir(exist_ok=True)
        mem_dir.chmod(0o700)
        ui.console.print("       → created memory/")

    # Per-turn context footprint: the artifacts the turn loop re-feeds every turn.
    # docket can't trim the live prompt, but oversized SOUL/AGENTS/MEMORY here
    # means every turn pays for it — flag it so the user can prune/rebuild.
    per_turn_files = ["SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE, "MEMORY.md"]
    ctx_bytes = 0
    for fname in per_turn_files:
        fp = ws / fname
        if fp.is_file():
            with contextlib.suppress(OSError):
                ctx_bytes += fp.stat().st_size
    est_tokens = ctx_bytes // _cfg.CONTEXT_BYTES_PER_TOKEN
    # The budget this agent's turn actually resolves to: an explicit override,
    # else a documented share of its registered model window (see
    # core/identity.py's resolve_static_context_budget), else today's plain
    # constant when the model has no registered window at all.
    model = str(store.read_json(_cfg.meta_path(agent_id)).get("model", _cfg.DEFAULT_MODEL))
    endpoint = _llm.resolve_endpoint(model)
    budget_tokens, budget_source = _identity.resolve_static_context_budget(
        endpoint.context_window_tokens if endpoint else None,
        endpoint.max_output_tokens if endpoint else None,
    )
    budget_note = f"budget {budget_tokens:,} via {budget_source}"
    if est_tokens > budget_tokens:
        ui.console.print(
            f"  [yellow]⚠[/yellow] Context footprint: ~{est_tokens:,} tok re-sent each turn"
            f" ({budget_note}) — trim MEMORY.md/{_mem.HEARTBEAT_FILE}"
        )
        issues.append("oversized per-turn context")
    else:
        ui.console.print(
            f"  [green]✓[/green] Context footprint: ~{est_tokens:,} tok/turn ({budget_note})"
        )

    ui.console.print()
    if not issues:
        ui.success(f"HEALTHY — {agent_id} workspace looks good")
    else:
        ui.warn(f"ISSUES FOUND: {len(issues)} problem(s) detected")
        ui.console.print("  Run 'docket maintain <id> rebuild' to fully regenerate.")


def _run_distillation(agent_id: str, ws: Path) -> _mem.DistillResult:
    """Run `distill_memory` for *agent_id*, rendering progress/errors via ui. The one
    call site every distillation-driven `maintain` action shares. Callers gate their
    own destructive step on ``.ok`` (fail-closed) — see
    specs/functional/agent-lifecycle.spec.md. Runs through docket's own gated turn
    loop via ``edges.adapters.docket_runtime.default_driver()``, like any agent's turn."""
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    session_key = str(raw.get("sessionKey", ""))
    ui.info("Distilling memory before proceeding (one driver-backed turn)...")
    result = _mem.distill_memory(
        ws,
        label=name,
        agent_id=agent_id,
        session_key=session_key,
        driver=_dr.default_driver().run_turn,
    )
    if not result.ok:
        # `failure_kind` is what makes this actionable rather than just alarming:
        # the fail-closed contract turns a failed distillation into a *blocked
        # delete*, so the operator's next move depends entirely on why it failed
        # -- `timeout`/`daemon_error` say retry, `invalid_output` says the model
        # returned something unusable and retrying will likely repeat it.
        # Parentheses, not brackets: `ui.error` renders through Rich, which
        # parses `[timeout]` as a style tag and silently swallows it -- the
        # message came out as "Distillation failed : ..." until this was caught
        # by the test below.
        kind = f" ({result.failure_kind})" if result.failure_kind else ""
        ui.error(
            f"Distillation failed{kind}: {result.error or 'unknown error'} -- nothing deleted."
        )
    elif result.skipped:
        ui.info("No memory logs to distill.")
    else:
        ui.success(
            f"Distilled {result.logs_distilled} log(s) into MEMORY.md; "
            f"original(s) archived under memory/{_mem.DISTILLED_ARCHIVE_DIRNAME}/."
        )
    return result


def _maintain_distill(agent_id: str, ws: Path) -> int:
    """distill: summarize memory/*.md into MEMORY.md via one driver turn; archive originals."""
    result = _run_distillation(agent_id, ws)
    return 0 if result.ok else 1


def _maintain_clean(agent_id: str, ws: Path, *, distill_first: bool = True) -> int:
    """clean: delete memory/*.md log files. By default it distills
    pending logs into MEMORY.md and archives the originals before any deletion; a
    failed distillation aborts here untouched — see `_run_distillation`'s contract."""
    if not sys.stdin.isatty():
        ui.console.print("Cancelled (non-interactive).")
        return 0

    mem_dir = ws / "memory"
    if not mem_dir.is_dir():
        ui.warn("No memory directory found.")
        return 0

    logs = _mem.pending_daily_logs(ws)
    if not logs:
        ui.info("No memory logs to clean.")
        return 0

    ui.warn(f"This will delete {len(logs)} memory log file(s).")
    ans = input("Continue? [y/N]: ").strip().lower()
    if ans != "y":
        ui.warn("Cancelled.")
        return 0

    if distill_first:
        result = _run_distillation(agent_id, ws)
        if not result.ok:
            return 1
    else:
        ui.warn("Skipping distillation (--no-distill-first) -- logs will be deleted undistilled.")

    # Re-glob: a successful distillation already archived pending logs out of
    # memory/*.md, so this only ever finds something left to unlink when
    # distillation was skipped entirely (disabled, or found nothing pending).
    remaining = sorted(mem_dir.glob("*.md"))
    for f in remaining:
        f.unlink()
    if remaining:
        ui.success(f"Deleted {len(remaining)} memory log file(s).")
    else:
        ui.success("No memory log files left to delete (already archived).")
    return 0


def _maintain_reset(agent_id: str, ws: Path, *, distill_first: bool = True) -> int:
    """reset: delete memory logs + clear MEMORY.md + reset HEARTBEAT.md.
    `--distill-first` (default on) distills pending logs into MEMORY.md first; a
    failed distillation aborts before any deletion (fail closed). When a real
    distillation just ran, the "clear MEMORY.md" step below is skipped — it was
    *just* refreshed, so wiping it would throw away what `--distill-first` preserves."""
    if not sys.stdin.isatty():
        ui.console.print("Cancelled (non-interactive).")
        return 0

    ui.warn("This will:")
    ui.console.print("  - Delete all memory/*.md log files")
    ui.console.print("  - Clear MEMORY.md")
    ui.console.print(f"  - Reset {_mem.HEARTBEAT_FILE} to empty template")
    ans = input("Continue? [y/N]: ").strip().lower()
    if ans != "y":
        ui.warn("Cancelled.")
        return 0

    logs_distilled = 0
    memory_preserved = False
    if distill_first:
        result = _run_distillation(agent_id, ws)
        if not result.ok:
            return 1
        logs_distilled = result.logs_distilled
        memory_preserved = not result.skipped
    else:
        ui.warn("Skipping distillation (--no-distill-first) -- memory will be cleared undistilled.")

    mem_dir = ws / "memory"
    removed = 0
    if mem_dir.is_dir():
        for f in mem_dir.glob("*.md"):
            f.unlink()
            removed += 1

    memory_md = ws / "MEMORY.md"
    if memory_preserved:
        ui.info("MEMORY.md left as-is (just refreshed by distillation).")
    elif memory_md.is_file():
        memory_md.write_text(
            "# MEMORY.md\n\n_Cleared by docket maintain reset._\n", encoding="utf-8"
        )
        memory_md.chmod(0o600)

    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    hb = ws / _mem.HEARTBEAT_FILE
    hb.write_text(_mem.heartbeat_seed(name), encoding="utf-8")
    hb.chmod(0o600)

    distilled_note = f", {logs_distilled} distilled+archived first" if logs_distilled else ""
    ui.success(
        f"Reset complete: {removed} memory log(s) deleted{distilled_note}, MEMORY.md "
        f"{'preserved (freshly distilled)' if memory_preserved else 'cleared'}, "
        f"{_mem.HEARTBEAT_FILE} reset."
    )
    return 0


def _maintain_rebuild(agent_id: str, ws: Path) -> int:
    """rebuild: backup+regenerate a legacy flat agent's templates. Refuses a pod
    member outright (its files are owned by pod provisioning) and never touches
    memory/ -- rebuild has no reason to remove logs."""
    raw = store.read_json(_cfg.meta_path(agent_id))
    pod_id = str(raw.get("pod", ""))
    role = str(raw.get("role", ""))
    if pod_id or role:
        ui.error(
            f"'{agent_id}' is a pod member (pod '{pod_id or '?'}', role '{role or '?'}'). "
            "rebuild supports only legacy flat agents -- a pod member's files are owned "
            "by pod provisioning, not this command."
        )
        return 1

    if not sys.stdin.isatty():
        ui.console.print("Confirmation failed. Aborted.")
        return 0

    ui.warn("This will backup and regenerate all workspace files from metadata.")
    confirm = input(f"Type agent ID to confirm [{agent_id}]: ").strip()
    if confirm != agent_id:
        ui.warn("Aborted.")
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = ws / f".backup-{stamp}"
    backup_dir.mkdir(exist_ok=True)

    for fname in ["SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE, "MEMORY.md"]:
        src = ws / fname
        if src.is_file():
            _shutil.copy2(src, backup_dir / fname)

    ui.success(f"Backup saved to: {backup_dir}")

    _create_workspace(
        agent_id,
        str(raw.get("name", agent_id)),
        str(raw.get("codebase", "")),
        str(raw.get("stack", "")),
        str(raw.get("description", "")),
        str(raw.get("model", _cfg.DEFAULT_MODEL)),
    )

    ui.success(f"Workspace rebuilt for '{agent_id}'.")
    return 0


def _maintain_sessions(agent_id: str) -> None:
    """sessions: report on this agent's durable session storage. Reports sizes only
    — no manual trim, since a truncation outside ``compact_session``'s fail-closed
    summarisation is exactly the durability loss that module prevents."""
    from urllib.parse import unquote as _url_unquote

    from docket.core import session as _session

    ui.header(f"Sessions: {agent_id}")
    ui.console.print()
    ui.dim(
        "  Sessions compact on the turn path once history exceeds the role budget; sizes are on disk."
    )
    ui.console.print()

    if not _cfg.SESSIONS_DIR.is_dir():
        ui.info("No session storage found yet.")
        return

    prefix = f"agent:{agent_id}:"
    found = False
    for entry in sorted(_cfg.SESSIONS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        key = _url_unquote(entry.name)
        if not key.startswith(prefix):
            continue
        found = True
        record = _session.load_session(key)
        session_file = entry / "session.json"
        size_kb = session_file.stat().st_size // 1024 if session_file.is_file() else 0
        ui.console.print(
            f"  {key}: {len(record.messages)} message(s), {size_kb}KB, "
            f"last active {record.updated or 'never'}"
        )
    if not found:
        ui.info(f"No session storage found for '{agent_id}'.")


def _pick_agent(prompt: str) -> str:
    """Interactive numbered picker for agent IDs (TTY only)."""
    ids = project_ids()
    if not ids:
        ui.warn("No project agents found.")
        raise typer.Exit(0)
    ui.console.print(f"{prompt}:")
    for i, pick in enumerate(ids, 1):
        ui.console.print(f"  {i}) {pick}")
    raw = input("Enter number: ").strip()
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(ids):
            return ids[idx]
    except ValueError:
        pass
    ui.error("Invalid selection.")
    raise typer.Exit(1)


def cmd_init(ctx: typer.Context) -> None:
    """Initialize the current project with its minimum isolated pod.

    Creates a new project pod -- an isolated team of project-scoped agents
    that owns one codebase. The default pod is lean: a Lead + an Implementer.
    The first invocation also creates docket's shared workstation foundation
    (fleet registry, policies, default gates) -- there is no
    separate setup step. See docs/AGENT-TEAMS.md.

    With no arguments, docket derives the project id, path, and stack from the
    current directory (non-interactive, deterministic). Member ids are
    predictable: `<project>-lead`, `<project>-implementer`, `<project>-reviewer`,
    `<project>-tester` (duplicated roles get `-2`, `-3` suffixes). A pod
    always has exactly one Lead. Resize a pod later with `docket pod`; tear
    the whole pod down with `docket delete`.

    Flags (parsed from the extra CLI args, not fixed Typer options):
      --pod full            provision Lead, Implementer, Reviewer, and Tester.
                             Only applies to the default `software` blueprint;
                             ignored (with a warning) for any other blueprint,
                             which provisions its own fixed roster.
      --with <roles>        start from the lean pod and add named roles
                             (comma-separated: reviewer, tester, implementer).
                             Same `software`-only restriction as `--pod full`.
      --blueprint <name>    (default `software`) provision a named pod
                             blueprint instead of the plain lean/full pod --
                             `software` (codebase, lead+implementer), `research`
                             (workdir, lead/researcher/analyst/writer/critic,
                             $20 default budget, Critic gates the final step
                             with one rework cycle), `content` (workdir,
                             lead/writer/critic, $15), `ops` (workdir,
                             lead/operator/monitor, $30, Operator gated on its
                             own verifyCmd, Monitor is a human-approval gate),
                             `agentic-product` (codebase, full software
                             roster). A codebase blueprint treats the location
                             argument as an existing, never-auto-created
                             codebase path and auto-detects its stack; a
                             workdir blueprint treats it as the pod's one
                             shared working directory instead -- no stack is
                             auto-detected. `docket init` always passes the
                             cwd (or an explicit `--codebase`/`path`) as the
                             location, so it never hits the auto-provisioned
                             `~/.docket/workspaces/pods/<project>/` default;
                             that path is only reached via `--from` entries
                             that omit `workDir` or `POST /pods` calls that
                             omit `path`. Unknown
                             name errors with "unknown blueprint 'X'; valid
                             blueprints: software, research, content, ops,
                             agentic-product" and exits 1 before any prompt.
                             Only the five built-ins exist today -- there is
                             no `docket blueprints add <file>` to register a
                             custom one. See
                             specs/functional/pod-blueprints.spec.md.
      --codebase <path>     the codebase path (or, for a workdir-kind
                             blueprint, the pod's shared working directory) --
                             same value as the `path` positional; supplying it
                             up front skips its interactive prompt.
      --name <name>         display name -- same value as the 1st positional;
                             skips its prompt.
      --from <spec-file>    non-interactive, declarative provisioning -- one
                             or many agents/pods from a single JSON or YAML
                             file (`.yaml`/`.yml` needs PyYAML), the same
                             mechanism a CI job or fleet-bootstrap script would
                             use. The file is a bare list, `{"agents": [...]}`,
                             or one entry object. Each entry needs an `id`; an
                             entry with a `blueprint` field provisions a pod
                             (fields: `codebase`/`workDir`, `stack`,
                             `description`, `projectKey`, `budgetUsd`,
                             `telegram`); an entry with no `blueprint`
                             provisions a single flat agent the same shape
                             `docket add` always has (fields: `name`,
                             `codebase`, `stack`, `model`, `description`,
                             `telegram`, `budgetUsd`, `projectKey`). Mutually
                             exclusive with every other flag/prompt. An entry
                             whose id already exists, or names an unknown
                             blueprint, is skipped with a warning rather than
                             failing the rest of the file -- the command
                             always exits 0, so check the printed summary
                             rather than only the exit code in a script.
      --recipe <name|dir>   apply a shipped or local recipe directory after
                             provisioning -- a directory path as given, else a
                             shipped recipe by name (`docket recipes list`
                             shows all of them). An unresolvable
                             name errors naming the shipped recipe names and
                             exits 1 before any provisioning. Mutually
                             exclusive with a present `<location>/.docket/` --
                             giving both errors naming both sources and exits
                             1 before any provisioning.
      --no-apply             provision the pod only, skipping the apply step
                             for a present `.docket/` or a resolved `--recipe`;
                             prints the `docket pod <p> apply <dir>` command
                             that would apply it.

    A repository's own `<location>/.docket/` -- the same directory shape
    `docket pod <p> apply` reads (roles/*.yaml, policies/*.json,
    pipeline.yaml, pod.yaml) -- is discovered automatically: every document
    under it is validated before anything is provisioned, and applied after
    (unless `--no-apply`) through that same command's plan/apply path. A
    validation error exits 1 naming the file and field, with nothing
    provisioned. See specs/functional/pod-blueprints.spec.md, "Pod manifests:
    apply".

    Every project is a repo -- a pod tied to a codebase, defaulting to the cwd
    (or the `path` argument / `--codebase`, in which case you are not
    re-prompted); the project name is suggested from that directory's name."""
    from docket.cli._agents import run_init

    raise typer.Exit(run_init(list(ctx.args)))


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
