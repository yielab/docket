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
from docket.core import models_policy as _mp
from docket.core.utils import last_activity, project_ids
from docket.edges import store
from docket.edges.adapters import openclaw as _oc


def run_add(all_args: list[str]) -> int:
    """Dispatch `docket add` (interactive, or `--from <spec-file>`)."""
    from_file: str | None = None
    i = 0
    while i < len(all_args):
        arg = all_args[i]
        if arg.startswith("--from="):
            from_file = arg[len("--from=") :]
            i += 1
        elif arg == "--from" and i + 1 < len(all_args):
            from_file = all_args[i + 1]
            i += 2
        else:
            i += 1

    if from_file is not None:
        return _cmd_add_declarative(from_file)

    if not sys.stdin.isatty():
        ui.error("interactive mode requires a TTY. Use --from <spec-file> for non-interactive add.")
        return 1

    ui.console.print()
    ui.console.print("[bold]Agent type:[/bold]")
    ui.console.print("  1) repo  — tied to a codebase, has stack detection")
    ui.console.print("  2) task  — general-purpose work agent, no fixed codebase")
    ui.console.print()
    type_choice = input("Type (1=repo / 2=task) [1]: ").strip() or "1"
    agent_type = "task" if type_choice == "2" else "repo"

    name = input("Display name (e.g. 'My Shop API'): ").strip()
    if not name:
        ui.error("Name is required.")
        return 1

    def _slugify(s: str) -> str:
        s = s.lower()
        s = _re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return s

    slug = _slugify(name)
    aid_input = input(f"Agent ID [{slug}]: ").strip() or slug
    aid: str = aid_input

    if (_cfg.PROJECTS_DIR / aid).is_dir() or (_cfg.PROJECTS_DIR / f"{aid}-lead").is_dir():
        ui.error(f"A project or pod '{aid}' already exists.")
        return 1

    codebase = ""
    stack = ""
    if agent_type == "repo":
        default_cb = str(_cfg.OPENCLAW_DIR.parent / "Sites" / slug)
        codebase = input(f"Codebase path [{default_cb}]: ").strip() or default_cb
        cb_path = Path(codebase)
        if cb_path.is_dir():
            if (cb_path / "package.json").is_file():
                stack = "Node.js"
            elif (cb_path / "requirements.txt").is_file() or (cb_path / "pyproject.toml").is_file():
                stack = "Python"
            elif (cb_path / "composer.json").is_file():
                stack = "PHP"
            elif (cb_path / "go.mod").is_file():
                stack = "Go"
            elif (cb_path / "Cargo.toml").is_file():
                stack = "Rust"
        stack = input(f"Stack [{stack or 'unknown'}]: ").strip() or stack or "unknown"

    description = input("Description (one line): ").strip()
    tg_group = input("Telegram group ID (Enter to skip): ").strip()

    from docket.cli import _pod

    roles = _pod.parse_pod_roles(all_args)
    ui.console.print()
    ui.info(f"Provisioning pod '{aid}' ({', '.join(roles)})...")
    created = _pod.build_pod(aid, roles, codebase=codebase, stack=stack, description=description)
    if not created:
        ui.error("Pod provisioning failed — no members were registered.")
        return 1

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

        if (_cfg.PROJECTS_DIR / aid).is_dir():
            ui.warn(f"'{aid}' already exists — skipping.")
            skipped.append(aid)
            continue

        agent_type = str(spec.get("type", "repo"))
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
            agent_type,
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


def _create_workspace(
    agent_id: str,
    agent_type: str,
    name: str,
    codebase: str,
    stack: str,
    description: str,
    model: str,
) -> None:
    """Create workspace directory and template files."""
    ws = _cfg.PROJECTS_DIR / agent_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)

    session_key = f"agent:{agent_id}:default"

    from docket.cli import _test_cmd_for_stack

    test_cmd = _test_cmd_for_stack(stack)

    if agent_type == "repo":
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
            "- Proactive: check HEARTBEAT.md every session.\n"
            f"- Scope: never act outside {codebase}.\n"
            "- Context isolation: respect the session key boundary — no cross-project access.\n\n"
            "## Safety\n"
            "- Never push to main/master without HITL approval.\n"
            "- Never delete files without explicit instruction.\n"
        )
        agents = (
            f"# AGENTS.md — {name}\n\n"
            "## Every Session (keep this lean — it is re-sent every turn)\n"
            "1. Read HEARTBEAT.md — current tasks/decisions (small; always).\n"
            "2. Read history ONLY when the task needs it: open MEMORY.md, then the\n"
            "   specific memory/YYYY-MM-DD.md you need. Do not slurp the whole\n"
            "   memory/ dir or re-read MEMORY.md when the task doesn't need it —\n"
            "   every byte you read is re-sent on every later turn.\n"
            "3. Log outcomes to today's memory/YYYY-MM-DD.md (one file per day).\n\n"
            "## Project Path\n"
            f"{codebase}\n\n"
            "## Org Specialists\n"
            "Escalate cross-cutting work to the shared org specialists:\n"
            "| Concern           | Specialist   |\n"
            "|-------------------|--------------|\n"
            "| Memory/patterns   | knowledge    |\n"
            "| Risky actions     | security     |\n\n"
            "## Scope Rule\n"
            f"Only act on {name}. Redirect other project questions to the correct group.\n\n"
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
    else:
        soul = (
            f"# SOUL.md — {name}\n\n"
            "## Identity\n"
            f"You are the autonomous agent for **{name}**. "
            "You handle tasks, research, and file operations for this context only.\n\n"
            f"**Session Key:** `{session_key}`\n\n"
            "This session key isolates you from other project contexts. "
            "You may only access resources and memory within this coordinate space.\n\n"
            "## Description\n"
            f"{description}\n\n"
            "## Work Directory\n"
            f"~/Sites/{agent_id}/\n\n"
            "## Traits\n"
            "- Break requests into numbered steps and execute them.\n"
            "- Log all completed tasks to memory/YYYY-MM-DD.md.\n"
            "- Proactive: check HEARTBEAT.md every session.\n"
            "- Scope: stay within this context. Do not reference other projects.\n"
            "- Context isolation: respect the session key boundary — no cross-project access.\n\n"
            "## Safety\n"
            "- Never post publicly or send external messages without HITL approval.\n"
            "- Ask before overwriting existing files.\n"
        )
        agents = (
            f"# AGENTS.md — {name}\n\n"
            "## Every Session (keep this lean — it is re-sent every turn)\n"
            "1. Read HEARTBEAT.md — current tasks/decisions (small; always).\n"
            "2. Read memory/YYYY-MM-DD.md only when the task needs prior context;\n"
            "   don't slurp the whole memory/ dir — what you read is re-sent on\n"
            "   every later turn.\n\n"
            "## Work Directory\n"
            f"~/Sites/{agent_id}/\n\n"
            "## Task Protocol\n"
            "1. Break request into numbered steps\n"
            "2. Execute each step\n"
            "3. Log results to memory/YYYY-MM-DD.md\n"
            "4. Report blockers immediately\n\n"
            "## Scope Rule\n"
            f"Only handle {name} tasks.\n"
        )
        tools = (
            f"# TOOLS.md — {name}\n\n"
            "## Work Directory\n"
            f"~/Sites/{agent_id}/\n\n"
            "## Notes\n"
            "_Add: API keys needed, URLs to monitor, file locations, tools to use._\n"
        )

    heartbeat = (
        f"# HEARTBEAT.md — {name}\n\n"
        "Check every session. Delete items when done.\n\n"
        "## Active Tasks\n"
        "_none yet_\n\n"
        "## Pending Decisions\n"
        "_none_\n\n"
        "## Notes\n"
        "_none_\n"
    )

    for fname, text in [
        ("SOUL.md", soul),
        ("AGENTS.md", agents),
        ("TOOLS.md", tools),
        ("HEARTBEAT.md", heartbeat),
    ]:
        fpath = ws / fname
        fpath.write_text(text, encoding="utf-8")
        fpath.chmod(0o600)

    ws.chmod(0o700)
    (ws / "memory").chmod(0o700)


def _provision_agent(
    agent_id: str,
    agent_type: str,
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
    role = "repo" if agent_type == "repo" else "task"
    if not model:
        model = _mp.resolve_role_model(role)
        model_source_val = "policy"
    else:
        with contextlib.suppress(Exception):
            model = _mp.validate_model(model)[0]
        policy_model = _mp.resolve_role_model(role)
        model_source_val = "policy" if model == policy_model else "pinned"

    session_key = f"agent:{agent_id}:{project_key}"

    _create_workspace(agent_id, agent_type, name, codebase, stack, description, model)

    meta_data: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "type": agent_type,
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
    else:
        with contextlib.suppress(Exception):
            _oc.add_agent(agent_id, model, session_key, project_key)

    with contextlib.suppress(Exception):
        _oc.sync_session_key(agent_id, session_key, project_key)

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
                "type": raw.get("type", "repo"),
                "codebase": raw.get("codebase", ""),
                "stack": raw.get("stack", ""),
                "model": raw.get("model", _cfg.DEFAULT_MODEL),
                "budgetUsd": raw.get("budgetUsd", ""),
                "paused": raw.get("paused", "") == "true",
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
    atype = str(raw.get("type", "repo"))
    codebase = str(raw.get("codebase", "—"))
    stack = str(raw.get("stack", "—"))
    model = str(raw.get("model", _cfg.DEFAULT_MODEL))
    budget = raw.get("budgetUsd")
    paused = raw.get("paused", "") == "true"
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
    ui.console.print(f"  [bold]{'Type:':<18}[/bold] {atype}")
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

    if tg and atype == "repo" and codebase not in ("", "—"):
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
    ui.success("Removed from agent registry")

    if tg:
        _oc.remove_binding(aid)
        ui.success("Telegram binding removed")

    if del_ws.lower() == "y":
        _shutil.rmtree(ws, ignore_errors=True)
        ui.success(f"Workspace deleted: {ws}")
    else:
        ui.warn(f"Workspace kept at: {ws}")

    from docket.cli import _do_restart_gateway

    _do_restart_gateway()
    ui.success(f"Done. Project '{aid}' deleted.")
    return 0


def run_maintain(agent_id: str | None, mode: str | None) -> int:
    """Dispatch `docket maintain`. Returns the process exit code."""
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

    if action == "check":
        _maintain_check(aid, ws)
    elif action == "clean":
        _maintain_clean(aid, ws)
    elif action == "reset":
        _maintain_reset(aid, ws)
    elif action == "rebuild":
        _maintain_rebuild(aid, ws)
    elif action == "sessions":
        _maintain_sessions(aid)
    else:
        ui.error(
            f"Unknown maintain subcommand '{action}'. Use: check, clean, reset, rebuild, sessions"
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

    required = ["SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md", ".docket-meta.json"]
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
                    str(raw.get("type", "repo")),
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
    per_turn_files = ["SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md", "MEMORY.md"]
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
            f" (budget {_cfg.CONTEXT_TOKEN_BUDGET:,}) — trim MEMORY.md/HEARTBEAT.md"
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


def _maintain_clean(agent_id: str, ws: Path) -> None:
    """clean: delete memory/*.md log files."""
    if not sys.stdin.isatty():
        ui.console.print("Cancelled (non-interactive).")
        return

    mem_dir = ws / "memory"
    if not mem_dir.is_dir():
        ui.warn("No memory directory found.")
        return

    logs = sorted(mem_dir.glob("*.md"))
    if not logs:
        ui.info("No memory logs to clean.")
        return

    ui.warn(f"This will delete {len(logs)} memory log file(s).")
    ans = input("Continue? [y/N]: ").strip().lower()
    if ans != "y":
        ui.warn("Cancelled.")
        return

    for f in logs:
        f.unlink()
    ui.success(f"Deleted {len(logs)} memory log file(s).")


def _maintain_reset(agent_id: str, ws: Path) -> None:
    """reset: delete memory logs + clear MEMORY.md + reset HEARTBEAT.md."""
    if not sys.stdin.isatty():
        ui.console.print("Cancelled (non-interactive).")
        return

    ui.warn("This will:")
    ui.console.print("  - Delete all memory/*.md log files")
    ui.console.print("  - Clear MEMORY.md")
    ui.console.print("  - Reset HEARTBEAT.md to empty template")
    ans = input("Continue? [y/N]: ").strip().lower()
    if ans != "y":
        ui.warn("Cancelled.")
        return

    mem_dir = ws / "memory"
    removed = 0
    if mem_dir.is_dir():
        for f in mem_dir.glob("*.md"):
            f.unlink()
            removed += 1

    memory_md = ws / "MEMORY.md"
    if memory_md.is_file():
        memory_md.write_text(
            "# MEMORY.md\n\n_Cleared by docket maintain reset._\n", encoding="utf-8"
        )
        memory_md.chmod(0o600)

    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    heartbeat_text = (
        f"# HEARTBEAT.md — {name}\n\n"
        "Check every session. Delete items when done.\n\n"
        "## Active Tasks\n_none_\n\n"
        "## Pending Decisions\n_none_\n\n"
        "## Notes\n_none_\n"
    )
    hb = ws / "HEARTBEAT.md"
    hb.write_text(heartbeat_text, encoding="utf-8")
    hb.chmod(0o600)

    ui.success(
        f"Reset complete: {removed} memory log(s) deleted, MEMORY.md cleared, HEARTBEAT.md reset."
    )


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

    for fname in ["SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md", "MEMORY.md"]:
        src = ws / fname
        if src.is_file():
            _shutil.copy2(src, backup_dir / fname)

    ui.success(f"Backup saved to: {backup_dir}")

    _create_workspace(
        agent_id,
        str(raw.get("type", "repo")),
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
