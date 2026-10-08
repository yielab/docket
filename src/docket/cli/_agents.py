"""docket init: create a project pod, or provision agents declaratively.

``run_init`` returns the process exit code and ``cmd_init`` wraps it in the Typer command.
``_create_workspace``/``_provision_agent`` are the single-agent template + registration path
(pods use ``cli/_pod.py`` instead).
"""

from __future__ import annotations

import contextlib
import json as _json
import re as _re
import sys
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
    """Extract (from_file, codebase, name, blueprint, recipe, no_apply) from `docket init`
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
    """Provision one pod from a `blueprint`-bearing `--from spec.yaml` entry. Returns
    the created member ids, or ``None`` (already warned) if the pod exists or the
    blueprint is unknown — the caller counts that as a skip, matching the single-agent
    path's idempotence contract. Goes through `cli._pod.build_pod_from_blueprint`,
    the same path `docket init` and `POST /pods` use."""
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
    always has exactly one Lead. Resize a pod later with `docket pod add|remove`; tear
    the whole pod down with `docket pod delete`.

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
                             `docket init` always has (fields: `name`,
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
                             shipped recipe by name (`docket pod recipes`
                             shows all of them). An unresolvable
                             name errors naming the shipped recipe names and
                             exits 1 before any provisioning. Mutually
                             exclusive with a present `<location>/.docket/` --
                             giving both errors naming both sources and exits
                             1 before any provisioning.
      --no-apply             provision the pod only, skipping the apply step
                             for a present `.docket/` or a resolved `--recipe`;
                             prints the `docket pod apply <dir>` command
                             that would apply it.

    A repository's own `<location>/.docket/` -- the same directory shape
    `docket pod apply` reads (roles/*.yaml, policies/*.json,
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
