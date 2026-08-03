"""docket add / info / delete / maintain — agent (and pod) workspace CRUD.

Each ``run_*`` function returns the process exit code; the coordinator
(``cli/__init__.py``) wraps it in a Typer command and raises
``typer.Exit(code)``. ``_create_workspace``/``_provision_agent`` are the
single-agent template + registration path (pods use ``cli/_pod.py`` instead,
which this module reaches into for pod-aware add/delete).
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import gzip as _gzip
import json as _json
import re as _re
import shutil as _shutil
import stat as _stat
import sys
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import provisioning as _prov
from docket.core.audit import audit_log
from docket.core.models import AgentMeta
from docket.core.utils import last_activity, project_ids
from docket.edges import store
from docket.edges.adapters import openclaw as _oc

# Flags that consume the following token as their value (skipped when scanning
# for bare positionals). --with/--pod are handled by parse_pod_roles.
_ADD_VALUE_FLAGS = frozenset(
    {
        "--from",
        "--codebase",
        "--path",
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
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract (from_file, codebase, name, blueprint) from `docket add` args.

    ``--from <f>`` selects declarative mode. Codebase may be given as
    ``--codebase``/``--path`` (or the 2nd bare positional; for a `workdir`
    blueprint this is its working directory instead — see
    ``core/blueprints.py``); name as ``--name`` (or the 1st bare positional);
    blueprint as ``--blueprint <name>`` (ROADMAP Phase 16 W-7) — unset means
    the caller falls back to the default blueprint (`software`). Any value
    supplied here is trusted and skips its interactive prompt. Returns
    ``None`` for anything not supplied.
    """
    from_file: str | None = None
    codebase: str | None = None
    name: str | None = None
    blueprint: str | None = None
    positionals: list[str] = []

    i = 0
    while i < len(all_args):
        arg = all_args[i]
        for flag, setter in (
            ("--from", "from"),
            ("--codebase", "cb"),
            ("--path", "cb"),
            ("--name", "nm"),
            ("--blueprint", "bp"),
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

    if positionals:
        if name is None:
            name = positionals[0]
        if codebase is None and len(positionals) > 1:
            codebase = positionals[1]
    return from_file, codebase, name, blueprint


def run_add(all_args: list[str]) -> int:
    """Dispatch `docket add` (interactive, or `--from <spec-file>`).

    Interactive flow: provisions a pod from a blueprint (ROADMAP Phase 16
    W-7) — ``--blueprint <name>`` selects one; omitted defaults to
    `software`, today's Lead+Implementer pod against a codebase, unchanged.
    A `codebase`-kind blueprint prompts for the codebase path (defaults to
    the directory `docket add` ran in); a `workdir`-kind blueprint
    (research/content/ops) prompts for a working directory instead — no
    codebase is assumed, and none is auto-detected for stack. The project
    name is suggested from that path's directory name.
    """
    from_file, cli_codebase, cli_name, cli_blueprint = _parse_add_args(all_args)

    if from_file is not None:
        return _cmd_add_declarative(from_file)

    if not sys.stdin.isatty():
        ui.error("interactive mode requires a TTY. Use --from <spec-file> for non-interactive add.")
        return 1

    from docket.core import blueprints as _bp

    blueprint_name = cli_blueprint or _bp.DEFAULT_BLUEPRINT
    try:
        blueprint = _bp.get_blueprint(blueprint_name)
    except _bp.BlueprintError as exc:
        ui.error(str(exc))
        return 1

    # Location: an explicit path set up front is trusted and not re-prompted;
    # otherwise offer a sensible default. Meaning depends on workspace_kind —
    # a codebase to detect stack from, or a plain working directory.
    is_workdir = blueprint.workspace_kind == "workdir"
    prompt_label = "Working directory" if is_workdir else "Codebase path"
    if cli_codebase is not None:
        location = str(Path(cli_codebase).expanduser())
    else:
        default_loc = str(_prov.default_codebase())
        location = input(f"{prompt_label} [{default_loc}]: ").strip() or default_loc
        location = str(Path(location).expanduser())
    loc_path = Path(location)

    # Name: suggested from the location's directory name; not prompted if given.
    suggested_name = cli_name or _prov.suggest_project_name(loc_path)
    if cli_name is not None:
        name = cli_name
    else:
        name = input(f"Display name [{suggested_name}]: ").strip() or suggested_name
    if not name:
        ui.error("Name is required.")
        return 1

    slug = _prov.slugify(name)
    aid_input = input(f"Agent ID [{slug}]: ").strip() or slug
    aid: str = aid_input

    if (_cfg.PROJECTS_DIR / aid).is_dir() or (_cfg.PROJECTS_DIR / f"{aid}-lead").is_dir():
        ui.error(f"A project or pod '{aid}' already exists.")
        return 1

    # No codebase to inspect for a workdir blueprint — stack is whatever the
    # operator types (or blank), never auto-detected from marker files.
    detected_stack = "" if is_workdir else _prov.detect_stack(loc_path)
    stack = input(f"Stack [{detected_stack or 'unknown'}]: ").strip() or detected_stack or "unknown"

    description = input("Description (one line): ").strip()
    tg_group = input("Telegram group ID (Enter to skip): ").strip()

    from docket.cli import _pod

    # --pod full / --with only make sense against the `software` roster —
    # any other blueprint provisions its own fixed roster as-is.
    if blueprint.name == "software":
        roles = _pod.parse_pod_roles(all_args)
    else:
        if any(a in ("--pod", "--with") or a.startswith("--with=") for a in all_args):
            ui.warn(
                f"--pod/--with only apply to the 'software' blueprint — ignoring for '{blueprint.name}'."
            )
        roles = blueprint.roles

    ui.console.print()
    ui.info(f"Provisioning '{blueprint.name}' pod '{aid}' ({', '.join(roles)})...")
    created = _pod.build_pod_from_blueprint(
        aid, blueprint.name, location=location, stack=stack, description=description, roles=roles
    )
    if not created:
        ui.error("Pod provisioning failed — no members were registered.")
        return 1

    audit_log(
        "agent.add",
        f"{aid} blueprint={blueprint.name} pod=({','.join(roles)}) source=interactive",
    )

    lead_id = f"{aid}-lead"
    if tg_group:
        _oc.upsert_binding(lead_id, tg_group, "telegram", "group")
        ui.success(f"Telegram binding: {lead_id} ← group {tg_group}")

        from docket.cli import _do_restart_gateway

        _do_restart_gateway()

    ui.console.print()
    ui.success(f"Pod '{aid}' created with {len(created)} members!")
    for mid in created:
        ui.console.print(f"  - {mid}")
    ui.console.print()
    ui.console.print(f"  docket pod {aid}              # inspect the pod")
    ui.console.print(f"  docket pod {aid} add reviewer # add a role")
    ui.console.print(f"  docket wire {lead_id}   (if no Telegram group yet)")
    return 0


def _provision_pod_from_spec(
    aid: str, blueprint_name: str, spec: dict[str, Any]
) -> list[str] | None:
    """Provision one pod from a `blueprint`-bearing `--from spec.yaml` entry.

    Returns the created member ids, or ``None`` (already warned) if the pod
    already exists or the blueprint name is unknown — the caller counts that
    as a skip, matching the single-agent path's idempotence contract.
    """
    from docket.cli import _pod

    if _pod.pod_member_ids(aid):
        ui.warn(f"'{aid}' already exists — skipping.")
        return None

    from docket.core import blueprints as _bp

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
    budget = str(spec.get("budgetUsd", ""))

    created = _pod.build_pod_from_blueprint(
        aid,
        blueprint.name,
        location=location,
        stack=stack,
        description=description,
        project_key=project_key,
    )
    if not created:
        ui.warn(f"'{aid}': pod provisioning failed — no members were registered.")
        return None

    if budget and budget != "0":
        with contextlib.suppress(Exception):
            _oc.meta_set(f"{aid}-lead", "budgetUsd", budget)

    audit_log(
        "agent.add",
        f"{aid} blueprint={blueprint.name} pod=({','.join(blueprint.roles)}) source=declarative",
    )
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
    wired: bool = False

    for spec in agents_spec:
        aid = str(spec.get("id", "")).strip()
        if not aid:
            ui.warn("Skipping spec entry with no 'id' field.")
            continue

        # ROADMAP Phase 16 W-7: a spec entry carrying a `blueprint` field
        # provisions a *pod* (build_pod_from_blueprint) instead of the single
        # flat agent below — a genuinely different shape (a blueprint pod is
        # never fewer than a Lead + one worker), so it gets its own existence
        # check (`<aid>-lead`, not the bare `<aid>` workspace dir) rather than
        # forcing the single-agent branch to understand pods.
        blueprint_name = str(spec.get("blueprint", "")).strip()
        if blueprint_name:
            pod_created = _provision_pod_from_spec(aid, blueprint_name, spec)
            if pod_created is None:
                skipped.append(aid)
                continue
            created.extend(pod_created)
            tg_group = str(spec.get("telegram", "")).strip()
            if tg_group:
                lead_id = f"{aid}-lead"
                _oc.upsert_binding(lead_id, tg_group, "telegram", "group")
                ui.success(f"Telegram binding: {lead_id} ← group {tg_group}")
                wired = True
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
            _oc.upsert_binding(aid, tg_group, "telegram", "group")
            ui.success(f"Telegram binding: {aid} ← group {tg_group}")
            wired = True

    if wired:
        from docket.cli import _do_restart_gateway

        _do_restart_gateway()

    ui.console.print()
    if created:
        ui.success(f"Created {len(created)} agent(s): {', '.join(created)}")
    if skipped:
        ui.warn(f"Skipped {len(skipped)} existing agent(s): {', '.join(skipped)}")
    if not created and not skipped:
        ui.warn("No agents provisioned.")
    return 0


def _apply_persona_from_meta(ws: Path, soul_text: str) -> str:
    """Upsert the persona block into *soul_text* from ``ws``'s existing meta.

    A no-op for a brand-new agent (meta not written yet → no persona) and for
    agents without a persona; on ``maintain rebuild`` it re-renders the
    docket-owned persona so identity stays a pure function of metadata.
    """
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

    from docket.cli import _test_cmd_for_stack

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
    # Section names matter: the openclaw runtime re-injects the "Session Startup"
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
        "## Org Specialists\n"
        "Escalate cross-cutting work to the shared org specialists:\n"
        "| Concern           | Specialist   |\n"
        "|-------------------|--------------|\n"
        "| Memory/patterns   | knowledge    |\n"
        "| Risky actions     | security     |\n\n"
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

    # Seed the files the openclaw post-compaction audit re-reads every reset.
    _mem.seed_contract(ws, project=name, codebase=codebase, stack=stack)

    # Quarantine any OpenClaw base-assistant scaffolding so identity stays
    # docket-owned (SOUL.md), not self-authored (IDENTITY.md/BOOTSTRAP.md).
    from docket.core import identity as _identity

    _identity.quarantine_scaffolding(ws)

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
    """Create workspace, write metadata, register with openclaw."""
    if not model:
        model = _mp.resolve_role_model("repo")
        model_source_val = "policy"
    else:
        with contextlib.suppress(Exception):
            model = _mp.validate_model(model)[0]
        policy_model = _mp.resolve_role_model("repo")
        model_source_val = "policy" if model == policy_model else "pinned"

    session_key = f"agent:{agent_id}:{project_key}"

    _create_workspace(agent_id, name, codebase, stack, description, model)

    meta_data: dict[str, Any] = {
        "schemaVersion": 1,
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

    sessions_dir = _cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    ws_path = str(_cfg.PROJECTS_DIR / agent_id)
    add_result = _oc.agents_add(agent_id, ws_path, model)
    if add_result.found:
        if add_result.ok:
            ui.success(f"Registered '{agent_id}' with openclaw")
        elif add_result.timed_out:
            ui.warn("openclaw agent add timed out — register manually if needed")
        else:
            ui.warn(
                f"openclaw agent add exited {add_result.returncode} — register manually if needed"
            )

    # P19-6: fleet.json is docket's own registry, never written by the daemon
    # CLI above — register unconditionally regardless of whether `openclaw
    # agents add` was found/succeeded (previously this only ran as a fallback
    # when the CLI was unavailable, back when openclaw.json was the one
    # registry both sides shared).
    with contextlib.suppress(Exception):
        _oc.add_agent(agent_id, model, session_key, project_key)

    audit_log("agent.add", f"{agent_id} model={model} source={source}")

    if not _oc.has_usable_profile():
        ui.warn("No usable auth profile found. Run: docket auth login")


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
    registered = _oc.agent_registered(agent_id)
    tg = _oc.get_binding(agent_id)
    activity = last_activity(agent_id)

    print(
        _json.dumps(
            {
                "id": agent_id,
                "name": raw.get("name", agent_id),
                "codebase": raw.get("codebase", ""),
                "stack": raw.get("stack", ""),
                "model": raw.get("model", _cfg.DEFAULT_MODEL),
                "budgetUsd": raw.get("budgetUsd", ""),
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

    registered = _oc.agent_registered(agent_id)
    tg = _oc.get_binding(agent_id)
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

        from docket.cli import _pick_agent

        agent_id = _pick_agent("Delete project")

    aid: str = agent_id

    if _cfg.is_specialist(aid):
        ui.error(
            f"'{aid}' is a specialist agent — shared team infrastructure managed by"
            " 'docket install'. It cannot be deleted with 'docket delete'."
        )
        return 1

    from docket.cli import _delete_pod, _pod

    members = _pod.pod_member_ids(aid)
    if members:
        return _delete_pod(aid, members)

    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        return 1

    name = _oc.meta_get(aid, "name", aid)
    tg = _oc.get_binding(aid)
    registered = _oc.agent_registered(aid)

    ui.header(f"Delete: {name} ({aid})")
    ui.console.print()
    ui.console.print(f"  Workspace:    {ws}")
    ui.console.print(f"  Registered:   {'yes' if registered else 'no'}")
    ui.console.print(f"  Telegram:     {tg or 'none'}")
    ui.console.print()
    ui.warn("This will:")
    ui.console.print("  - Remove agent registration from openclaw.json")
    ui.console.print("  - Remove Telegram binding (if any)")
    ui.console.print()

    del_ws = input("Also delete workspace directory? [y/N]: ").strip()
    ui.console.print()
    confirm = input(f"Type the agent ID to confirm deletion [{aid}]: ").strip()

    if confirm != aid:
        ui.warn("Aborted.")
        return 0

    _oc.remove_agent(aid)
    audit_log("agent.delete", aid)
    ui.success("Removed from agent registry")

    if tg:
        _oc.remove_binding(aid)
        ui.success("Telegram binding removed")

    from docket.core import conversations as _conv

    _conv.save(_conv.remove_agent(_conv.load(), aid))

    if del_ws.lower() == "y":
        _shutil.rmtree(ws, ignore_errors=True)
        ui.success(f"Workspace deleted: {ws}")
    else:
        ui.warn(f"Workspace kept at: {ws}")

    from docket.cli import _do_restart_gateway

    _do_restart_gateway()
    ui.success(f"Done. Project '{aid}' deleted.")
    return 0


def run_maintain(agent_id: str | None, mode: str | None, extra: list[str] | None = None) -> int:
    """Dispatch `docket maintain`. Returns the process exit code.

    ``extra`` carries flags that follow ``mode`` (currently only
    ``--no-distill-first``, ROADMAP Phase 17 C-2) — ``cmd_maintain``'s Typer
    registration allows/ignores unknown options so they land here rather
    than erroring, the same pattern every other ``ctx.args``-based
    subcommand in this package uses.
    """
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            return 1

        from docket.cli import _pick_agent

        agent_id = _pick_agent("Maintain workspace for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        return 1

    action = mode or "check"
    args = extra or []
    # Distillation defaults ON (ROADMAP Phase 17 C-2 / D-18): `clean`/`reset`
    # must not bare-delete undistilled memory without an explicit opt-out.
    # `--distill-first` is accepted too, as a no-op affirmation of the
    # default, so the flag documented in the card's acceptance criteria is a
    # real, recognized token either way.
    distill_first = "--no-distill-first" not in args

    if action == "check":
        _maintain_check(aid, ws)
    elif action == "clean":
        return _maintain_clean(aid, ws, distill_first=distill_first)
    elif action == "reset":
        return _maintain_reset(aid, ws, distill_first=distill_first)
    elif action == "rebuild":
        _maintain_rebuild(aid, ws)
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
    for dirpath in ws.rglob("*"):
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

    meta_session = _oc.meta_get(agent_id, "sessionKey", "")
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

    # Per-turn context footprint: the artifacts OpenClaw re-feeds every turn.
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
    if est_tokens > _cfg.CONTEXT_TOKEN_BUDGET:
        ui.console.print(
            f"  [yellow]⚠[/yellow] Context footprint: ~{est_tokens:,} tok re-sent each turn"
            f" (budget {_cfg.CONTEXT_TOKEN_BUDGET:,}) — trim MEMORY.md/{_mem.HEARTBEAT_FILE}"
        )
        issues.append("oversized per-turn context")
    else:
        ui.console.print(
            f"  [green]✓[/green] Context footprint: ~{est_tokens:,} tok/turn"
            f" (budget {_cfg.CONTEXT_TOKEN_BUDGET:,})"
        )

    ui.console.print()
    if not issues:
        ui.success(f"HEALTHY — {agent_id} workspace looks good")
    else:
        ui.warn(f"ISSUES FOUND: {len(issues)} problem(s) detected")
        ui.console.print("  Run 'docket maintain <id> rebuild' to fully regenerate.")


def _run_distillation(agent_id: str, ws: Path) -> _mem.DistillResult:
    """Run `distill_memory` for *agent_id*, rendering progress/errors via ui.

    The one call site every distillation-driven `maintain` action shares
    (`distill`, and `clean`/`reset` when `--distill-first` is on). Never
    deletes or archives anything itself beyond what `distill_memory` already
    did — callers gate their own destructive step on `.ok` (ROADMAP Phase 17
    C-2's fail-closed contract: a failed driver turn must block, not warn
    and proceed).
    """
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    session_key = str(raw.get("sessionKey", ""))
    ui.info("Distilling memory before proceeding (one driver-backed turn)...")
    result = _mem.distill_memory(
        ws,
        label=name,
        agent_id=agent_id,
        session_key=session_key,
        driver=_oc.default_driver().run_turn,
    )
    if not result.ok:
        # `failure_kind` is what makes this actionable rather than just alarming:
        # C-2's fail-closed contract turns a failed distillation into a *blocked
        # delete*, so the operator's next move depends entirely on why it failed
        # -- `timeout`/`daemon_error` say retry, `invalid_output` says the model
        # returned something unusable and retrying will likely repeat it. The
        # field was populated from the driver's TurnResult since C-2 shipped but
        # nothing read it (CL-3 flagged it); this is its consumer.
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
    """clean: delete memory/*.md log files.

    `--distill-first` (default on, ROADMAP Phase 17 C-2): distill pending
    logs into MEMORY.md and archive the originals before this ever deletes
    anything. A failed distillation aborts here with no file touched — see
    `_run_distillation`/`distill_memory`'s fail-closed contract.
    """
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

    `--distill-first` (default on, ROADMAP Phase 17 C-2): distill pending
    logs into MEMORY.md and archive the originals first. A failed
    distillation aborts before any deletion (fail closed). When a real
    distillation just ran (there was something pending and it succeeded),
    the "clear MEMORY.md" step below is skipped -- MEMORY.md was *just*
    refreshed with the distilled summary, so wiping it in the same breath
    would throw away the exact thing `--distill-first` exists to preserve.
    """
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


def _maintain_rebuild(agent_id: str, ws: Path) -> None:
    """rebuild: backup existing files then regenerate workspace from metadata."""
    if not sys.stdin.isatty():
        ui.console.print("Confirmation failed. Aborted.")
        return

    ui.warn("This will backup and regenerate all workspace files from metadata.")
    confirm = input(f"Type agent ID to confirm [{agent_id}]: ").strip()
    if confirm != agent_id:
        ui.warn("Aborted.")
        return

    raw = store.read_json(_cfg.meta_path(agent_id))
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

    mem_dir = ws / "memory"
    for f in mem_dir.glob("*.md"):
        f.unlink()

    ui.success(f"Workspace rebuilt for '{agent_id}'.")


def _trim_session_file(path: Path, keep_lines: int) -> tuple[int, int]:
    """Keep the last ``keep_lines`` records of a JSONL transcript, back up the rest.

    Each line is an independent usage record, so a tail window is a safe rolling
    context: it drops the oldest turns (the bulk re-sent on every resume) while
    preserving recent conversation. Writes a one-shot ``.bak`` first.

    Returns ``(lines_before, lines_after)``; a no-op returns equal counts.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return (0, 0)
    before = len(lines)
    if before <= keep_lines:
        return (before, before)
    bak = path.with_suffix(path.suffix + ".bak")
    bak.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        bak.chmod(0o600)
    kept = lines[-keep_lines:]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return (before, len(kept))


def _maintain_sessions(agent_id: str) -> None:
    """sessions: trim oversized transcripts and archive old ones (token hygiene).

    A transcript is re-read in full on every resume, so an oversized file is paid
    for on every turn. Large+recent files are *trimmed* to a recent-tail window
    (keeps the conversation, drops the costly old middle); old files are archived.
    """
    sessions_dir = _cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"
    if not sessions_dir.is_dir():
        ui.info(f"No sessions directory found for '{agent_id}'.")
        return

    now = _dt.datetime.now()
    cutoff_days = 30
    size_threshold = _cfg.SESSION_WARN_BYTES

    files = sorted(
        sessions_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
    )
    # The newest file is likely the live session — never rewrite it in place.
    active = files[-1] if files else None

    old: list[Path] = []
    large: list[Path] = []
    for f in files:
        try:
            size = f.stat().st_size
            age_days = (now - _dt.datetime.fromtimestamp(f.stat().st_mtime)).days
        except OSError:
            continue
        if age_days > cutoff_days:
            old.append(f)
        elif size > size_threshold and f is not active:
            large.append(f)

    ui.header(f"Sessions: {agent_id}")
    ui.console.print()

    if not old and not large:
        if active is not None and active.stat().st_size > size_threshold:
            kb = active.stat().st_size // 1024
            est = active.stat().st_size // _cfg.CONTEXT_BYTES_PER_TOKEN
            ui.warn(
                f"  Active session {active.name} is large ({kb}KB, ~{est:,} tok re-read"
                " per resume) but is the live session — left untouched."
            )
            ui.console.print()
        ui.info("No trimmable or archivable session files found.")
        return

    for f in large:
        size = f.stat().st_size
        est = size // _cfg.CONTEXT_BYTES_PER_TOKEN
        ui.console.print(f"  [trim]    {f.name}  ({size // 1024}KB, ~{est:,} tok)")
    for f in old:
        size = f.stat().st_size
        age = (now - _dt.datetime.fromtimestamp(f.stat().st_mtime)).days
        ui.console.print(f"  [archive] {f.name}  ({size // 1024}KB, {age}d old)")

    ui.console.print()
    ui.console.print(
        f"  {len(large)} to trim (keep last {_cfg.SESSION_TRIM_KEEP_TURNS} turns),"
        f" {len(old)} to archive"
    )

    if not sys.stdin.isatty():
        ui.info("Non-interactive mode — reported only (no changes).")
        return

    ans = input("Apply (trim large + archive old)? [y/N]: ").strip().lower()
    if ans != "y":
        ui.warn("Cancelled.")
        return

    trimmed = 0
    for f in large:
        before, after = _trim_session_file(f, _cfg.SESSION_TRIM_KEEP_TURNS)
        if after < before:
            trimmed += 1
            ui.console.print(f"  trimmed {f.name}: {before} → {after} records (.bak kept)")

    archived = 0
    if old:
        archive_dir = sessions_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        for f in old:
            dest = archive_dir / (f.name + ".gz")
            with f.open("rb") as f_in, _gzip.open(dest, "wb") as f_out:
                _shutil.copyfileobj(f_in, f_out)
            f.unlink()
            archived += 1

    ui.success(f"Trimmed {trimmed} session(s); archived {archived} to sessions/archive/")
