"""docket CLI — the Typer application.

Every command is implemented in Python (the Bash→Python migration is complete);
bin/docket is a thin launcher that execs ``python -m docket``. Command modules
live alongside this one in docket.cli; shared services are in docket.core and
docket.edges.
"""

from __future__ import annotations

import contextlib
import json as _json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket import ui
from docket.core import models_policy as _mp
from docket.core.utils import (
    CostTotals,
    DayRecord,
    aggregate_cost,
    cost_history,
    gateway_active,
    last_activity,
    model_source,
    openclaw_version,
    project_ids,
    restart_gateway,
    scan_telegram_groups,
    si_format,
)
from docket.edges import store
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

app = typer.Typer(
    name="docket",
    help="OpenClaw project agent manager",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)


def _render_restart_result(result: _sys.RestartResult) -> None:
    """Render a RestartResult exactly as system.restart_gateway() used to print it.

    edges/ no longer prints (it has no knowledge of terminals); this is the
    single place that reproduces the old wording so every call site stays
    byte-identical. Shared by the other cli/ modules that trigger a restart.
    """
    if result.status == "dry_run":
        print("[dry-run] restart_gateway called")
    elif result.status == "not_running":
        ui.warn("Gateway not running. Start it with:")
        print(f"  {result.hint}")
    elif result.status == "restarted":
        ui.info("Restarting gateway...")
        ui.success("Gateway restarted")
    elif result.status == "failed":
        ui.info("Restarting gateway...")
        ui.warn("Gateway restart failed.")
        print(f"  Check: {result.hint}")


def _do_restart_gateway() -> None:
    result = restart_gateway()
    _render_restart_result(result)
    if not result.ok:
        ui.warn("Gateway restart failed or gateway not running.")


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


def _resolve_version() -> str:
    """docket version — package metadata, falling back to the VERSION file."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("docket")
    except PackageNotFoundError:
        for cand in (
            Path(__file__).resolve().parents[3] / "VERSION",
            _cfg.OPENCLAW_DIR / "VERSION",
        ):
            if cand.is_file():
                return cand.read_text(encoding="utf-8").strip()
    return "unknown"


def _version_callback(value: bool) -> None:
    if value:
        print(f"docket {_resolve_version()}")
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version"
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug output"),
) -> None:
    if debug:
        os.environ["DEBUG"] = "1"
    if ctx.invoked_subcommand is None:
        cmd_list(json_out=False)


@app.command("install")
def cmd_install(
    gates: bool = typer.Option(False, "--gates/--no-gates", help="Enable exec-approval gates"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
    portfolio: bool = typer.Option(
        False, "--portfolio", help="Also provision the optional org Portfolio Manager"
    ),
) -> None:
    """Bootstrap OpenClaw + specialist agents."""
    from docket.cli._install import run_install

    raise typer.Exit(run_install(want_gates=gates, assume_yes=yes, want_portfolio=portfolio))


@app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List all project agents."""
    if json_out:
        _cmd_list_json()
    else:
        _cmd_list_human()


def _cmd_list_json() -> None:
    oc = _oc.load_config()
    registered = {a.id for a in _oc.list_agents(oc)}
    tg_bindings: dict[str, str | None] = {}
    for b in oc.bindings:
        if b.match.channel == "telegram":
            tg_bindings[b.agent_id] = b.match.peer.id or None

    from docket.core import pod as _pod_mod

    agents_out = []
    for aid in project_ids():
        raw = store.read_json(_cfg.meta_path(aid))
        agents_out.append(
            {
                "id": aid,
                "kind": raw.get("kind", "project"),
                "scope": raw.get("scope", "project"),
                "role": raw.get("role", ""),
                "pod": raw.get("pod", "") or (_pod_mod.pod_of(aid) or ""),
                "name": raw.get("name", aid),
                "type": raw.get("type", "repo"),
                "model": raw.get("model", _cfg.DEFAULT_MODEL),
                "modelSource": raw.get("modelSource", ""),
                "stack": raw.get("stack", ""),
                "codebase": raw.get("codebase", ""),
                "budgetUsd": raw.get("budgetUsd", ""),
                "telegram": tg_bindings.get(aid),
                "registered": aid in registered,
            }
        )
    print(_json.dumps({"agents": agents_out}, indent=2))


def _cmd_list_human() -> None:
    ids = project_ids()
    if not ids:
        ui.warn("No project agents found.")
        ui.console.print("Run: docket add")
        raise typer.Exit(0)

    oc = _oc.load_config()
    registered_ids = {a.id for a in _oc.list_agents(oc)}
    tg_bindings: dict[str, str] = {}
    for b in oc.bindings:
        if b.match.channel == "telegram":
            tg_bindings[b.agent_id] = b.match.peer.id

    total_agents = len(oc.agents.items)
    tg_binding_count = sum(1 for b in oc.bindings if b.match.channel == "telegram")
    gw_up = gateway_active()
    tg_on = _oc.get_telegram_enabled()

    gw_badge = "[green]● gateway up[/green]" if gw_up else "[red]○ gateway down[/red]"
    tg_badge = "[green]● telegram on[/green]" if tg_on else "[yellow]○ telegram off[/yellow]"

    ui.console.print()
    ui.console.print(
        f"  [bold]OpenClaw[/bold]  {gw_badge}  {tg_badge}  [dim]│[/dim]"
        f"  {total_agents} agents  {tg_binding_count} binding(s)"
        f"  [dim]│[/dim]  v{openclaw_version()}"
    )
    ui.console.print(f"  [dim]{'─' * 66}[/dim]")
    ui.console.print(
        f"[bold cyan]PROJECT AGENTS[/bold cyan] "
        f"[dim](your work - each is dedicated to one codebase/project)[/dim] "
        f"[bold]({len(ids)})[/bold]"
    )
    ui.console.print()

    home = str(Path.home())

    from docket.core import pod as _pod_mod

    for aid in ids:
        raw = store.read_json(_cfg.meta_path(aid))
        name = str(raw.get("name", aid))
        atype = str(raw.get("type", "repo"))
        role = str(raw.get("role", ""))
        pod_name = str(raw.get("pod", "")) or (_pod_mod.pod_of(aid) or "")
        descriptor = f"{role} · pod:{pod_name}" if role and pod_name else atype
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        stack = str(raw.get("stack", ""))
        codebase = str(raw.get("codebase", ""))
        src = str(raw.get("modelSource", ""))

        tg = tg_bindings.get(aid, "")
        registered = aid in registered_ids
        activity = last_activity(aid)

        ws = _cfg.workspace_dir(aid)
        has_memory = (ws / "MEMORY.md").is_file()
        has_reqs = (ws / "REQUIREMENTS.md").is_file()
        mem_days = sum(1 for _ in (ws / "memory").glob("*.md")) if (ws / "memory").is_dir() else 0

        model_short = model.split("/")[-1] if "/" in model else model
        path_short = codebase.replace(home, "~") if codebase else "[dim]none[/dim]"

        reg_badge = "[green]● registered[/green]" if registered else "[red]○ not registered[/red]"
        tg_b = (
            f"[green]● telegram[/green] [dim]({tg})[/dim]"
            if tg
            else "[yellow]○ no telegram[/yellow]"
        )
        mem_b = "[green]● memory[/green]" if has_memory else "[dim]○ no memory[/dim]"
        req_b = "[green]● reqs[/green]" if has_reqs else "[dim]○ no reqs[/dim]"

        ui.console.print()
        ui.console.print(f"  [bold cyan]{aid}[/bold cyan]  [dim]({name})[/dim]")
        ui.console.print(
            f"  {descriptor}  │  {model_short} ({src})  │"
            f"  stack: {stack or '[dim]—[/dim]'}  │  {mem_days} day-log(s)"
        )
        ui.console.print(f"  path: {path_short}  │  active: {activity}")
        ui.console.print(f"  {reg_badge}  {tg_b}  {mem_b}  {req_b}")

    unwired: list[tuple[str, str]] = []
    for aid in ids:
        if tg_bindings.get(aid):
            continue
        expected = _cfg.TELEGRAM_GROUP_NAMES.get(aid)
        if expected:
            unwired.append((aid, expected))
    # Manager is a specialist (not in the project list) — check it directly.
    if not tg_bindings.get("manager") and _cfg.TELEGRAM_GROUP_NAMES.get("manager"):
        unwired.append(("manager", _cfg.TELEGRAM_GROUP_NAMES["manager"]))

    if unwired:
        ui.console.print()
        ui.console.print(f"  [dim]{'─' * 66}[/dim]")
        ui.console.print(
            f"  [bold yellow]Telegram Setup Needed[/bold yellow]  "
            f"[dim]({len(unwired)} agent(s) without groups)[/dim]"
        )
        ui.console.print()
        for uw_id, uw_name in unwired:
            ui.console.print(
                f"    [yellow]○[/yellow] [bold]{uw_id}[/bold]  "
                f'[dim]→ create group "{uw_name}" then:[/dim] docket wire {uw_id}'
            )
        ui.console.print()
        ui.dim(
            "  Steps: 1) Create Telegram group  2) Add bot"
            "  3) Get group ID from logs  4) docket wire <id>"
        )

    ui.console.print()
    ui.console.print(
        "[bold green]ORG SPECIALISTS[/bold green] [dim](shared across all projects)[/dim]"
    )
    ui.console.print()
    ui.console.print(
        "  [dim]These work across ALL your projects. Don't wire them to individual groups.[/dim]"
    )
    ui.console.print()

    for spec in _cfg.ORG_DISPLAY_ORDER:
        spec_ws = _cfg.OPENCLAW_DIR / "workspaces" / spec
        if not spec_ws.is_dir():
            continue
        spec_meta = spec_ws / _cfg.META_FILE
        if not spec_meta.is_file():
            continue
        spec_raw = store.read_json(spec_meta)
        spec_model = str(spec_raw.get("model", _cfg.DEFAULT_MODEL))
        spec_src = str(spec_raw.get("modelSource", ""))
        spec_model_short = spec_model.split("/")[-1] if "/" in spec_model else spec_model
        why = _cfg.ROLE_WHY.get(spec, "")
        ui.console.print(
            f"  [green]✓[/green] {spec:<12} [dim]{spec_model_short:<28} ({spec_src}) — {why}[/dim]"
        )

    ui.console.print()
    ui.console.print("─" * 70)
    ui.dim("  docket info <id>     detailed view")
    ui.dim("  docket cost          token usage")
    ui.dim("  docket models        role→model policy")
    ui.dim("  docket profile <id>  pin/unpin an agent's model")
    ui.console.print()


@app.command(
    "add",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_add(ctx: typer.Context) -> None:
    """Add a new project agent (interactive or --from <spec-file>)."""
    import re as _re

    all_args: list[str] = list(ctx.args)

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
        _cmd_add_declarative(from_file)
        return

    if not sys.stdin.isatty():
        ui.error("interactive mode requires a TTY. Use --from <spec-file> for non-interactive add.")
        raise typer.Exit(1)

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
        raise typer.Exit(1)

    def _slugify(s: str) -> str:
        s = s.lower()
        s = _re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return s

    slug = _slugify(name)
    aid_input = input(f"Agent ID [{slug}]: ").strip() or slug
    aid: str = aid_input

    if (_cfg.PROJECTS_DIR / aid).is_dir() or (_cfg.PROJECTS_DIR / f"{aid}-lead").is_dir():
        ui.error(f"A project or pod '{aid}' already exists.")
        raise typer.Exit(1)

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
        raise typer.Exit(1)

    lead_id = f"{aid}-lead"
    if tg_group:
        _oc.upsert_binding(lead_id, tg_group, "telegram", "group")
        ui.success(f"Telegram binding: {lead_id} ← group {tg_group}")
        _do_restart_gateway()

    ui.console.print()
    ui.success(f"Pod '{aid}' created with {len(created)} members!")
    for mid in created:
        ui.console.print(f"  - {mid}")
    ui.console.print()
    ui.console.print(f"  docket pod {aid}              # inspect the pod")
    ui.console.print(f"  docket pod {aid} add reviewer # add a role")
    ui.console.print(f"  docket wire {lead_id}   (if no Telegram group yet)")


def _cmd_add_declarative(from_file: str) -> None:
    """Provision agents from a JSON (or YAML) spec file."""
    path = Path(from_file)
    if not path.is_file():
        ui.error(f"Spec file not found: {from_file}")
        raise typer.Exit(1)

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
            raise typer.Exit(1) from None
    else:
        try:
            spec_obj = _json.loads(content)
        except _json.JSONDecodeError as exc:
            ui.error(f"Invalid JSON in spec file: {exc}")
            raise typer.Exit(1) from None

    agents_spec: list[dict[str, Any]]
    if isinstance(spec_obj, list):
        agents_spec = spec_obj
    elif isinstance(spec_obj, dict) and "agents" in spec_obj:
        agents_spec = list(spec_obj["agents"])
    elif isinstance(spec_obj, dict):
        agents_spec = [spec_obj]
    else:
        ui.error("Spec file must be a JSON object or array of agent specs.")
        raise typer.Exit(1)

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
        _do_restart_gateway()

    ui.console.print()
    if created:
        ui.success(f"Created {len(created)} agent(s): {', '.join(created)}")
    if skipped:
        ui.warn(f"Skipped {len(skipped)} existing agent(s): {', '.join(skipped)}")
    if not created and not skipped:
        ui.warn("No agents provisioned.")


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
    meta_file.write_text(_json.dumps(meta_data, indent=2), encoding="utf-8")
    meta_file.chmod(0o600)

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


@app.command("info")
def cmd_info(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Detailed status of one agent."""
    if agent_id is None:
        if json_out:
            ui.error("An agent id is required with --json (e.g. docket info <id> --json).")
            raise typer.Exit(1)
        if not sys.stdin.isatty():
            ui.error("An agent id is required (e.g. docket info <id>).")
            raise typer.Exit(1)
        ids = project_ids()
        if not ids:
            ui.warn("No project agents found.")
            raise typer.Exit(0)
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
                raise typer.Exit(1)
        except ValueError:
            ui.error("Invalid selection.")
            raise typer.Exit(1) from None

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        raise typer.Exit(1)

    if json_out:
        _cmd_info_json(aid)
    else:
        _cmd_info_human(aid)


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


def _delete_pod(project: str, members: list[str]) -> None:
    """Tear down every member of a pod. One gateway restart at the end."""
    from docket.cli import _pod

    ui.header(f"Delete pod: {project}  ({len(members)} members)")
    ui.console.print()
    for mid in members:
        role = _oc.meta_get(mid, "role", "?")
        ui.console.print(f"  - {mid}  [{role}]")
    ui.console.print()
    ui.warn("This removes every member's registration, binding, and workspace.")
    ui.console.print()

    if sys.stdin.isatty():
        confirm = input(f"Type the pod id to confirm deletion [{project}]: ").strip()
        if confirm != project:
            ui.warn("Aborted.")
            raise typer.Exit(0)

    for mid in members:
        if _oc.get_binding(mid):
            _oc.remove_binding(mid)
        ok, msg = _pod.teardown_member(mid)
        if ok:
            ui.success(f"Removed {mid}")
        else:
            ui.warn(f"{mid}: daemon delete reported: {msg} (workspace cleaned)")

    # Free pod runtime resources (port range + scratch dir) after all members gone.
    _pod.free_pod_resources(project)

    _do_restart_gateway()
    ui.success(f"Pod '{project}' deleted.")


@app.command("delete")
def cmd_delete(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove a project agent or a whole pod, and optionally its workspace."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Delete project")

    aid: str = agent_id

    if _cfg.is_specialist(aid):
        ui.error(
            f"'{aid}' is a specialist agent — shared team infrastructure managed by"
            " 'docket install'. It cannot be deleted with 'docket delete'."
        )
        raise typer.Exit(1)

    from docket.cli import _pod

    members = _pod.pod_member_ids(aid)
    if members:
        _delete_pod(aid, members)
        return

    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        raise typer.Exit(1)

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
        raise typer.Exit(0)

    _oc.remove_agent(aid)
    ui.success("Removed from agent registry")

    if tg:
        _oc.remove_binding(aid)
        ui.success("Telegram binding removed")

    if del_ws.lower() == "y":
        shutil.rmtree(ws, ignore_errors=True)
        ui.success(f"Workspace deleted: {ws}")
    else:
        ui.warn(f"Workspace kept at: {ws}")

    _do_restart_gateway()
    ui.success(f"Done. Project '{aid}' deleted.")


@app.command(
    "maintain",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_maintain(
    ctx: typer.Context,
    agent_id: str | None = typer.Argument(None),
    mode: str | None = typer.Argument(None),
) -> None:
    """Maintain an agent workspace (check/clean/reset/rebuild/sessions)."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Maintain workspace for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        raise typer.Exit(1)

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
        raise typer.Exit(1)


def _maintain_check(agent_id: str, ws: Path) -> None:
    """check: verify permissions, missing files, session key sync, memory dir."""
    import stat as _stat

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
                import re as _re

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
    import datetime as _dt
    import shutil as _shutil

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
    import datetime as _dt
    import gzip as _gzip
    import shutil as _shutil

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


@app.command(
    "context",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_context(
    ctx: typer.Context,
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Agent context and memory management (show/search/index/snapshot/compress/project)."""

    extra: list[str] = list(ctx.args)

    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Manage context for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"'{aid}' not found.")
        raise typer.Exit(1)

    _CONTEXT_SUBS = {"show", "search", "index", "snapshot", "compress", "project"}
    action = sub or "show"

    if action not in _CONTEXT_SUBS:
        query_parts = [action, *extra]
        _context_search(aid, ws, query_parts)
        return

    if action == "show":
        _context_show(aid, ws)
    elif action == "search":
        _context_search(aid, ws, extra)
    elif action == "index":
        _context_index(aid, ws)
    elif action == "snapshot":
        _context_snapshot(aid, ws)
    elif action == "compress":
        _context_compress(aid, ws)
    elif action == "project":
        _context_project(aid, ws)


def _context_show(agent_id: str, ws: Path) -> None:
    import datetime as _dt

    try:
        raw = store.read_json(_cfg.meta_path(agent_id))
        name = str(raw.get("name", agent_id))
    except Exception:
        name = agent_id

    ui.header(f"Context: {name}")
    ui.console.print()

    ui.console.print("[bold]Recent Activity[/bold]")
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        mem_files = sorted(mem_dir.glob("*.md"), reverse=True)[:3]
        if mem_files:
            for mf in mem_files:
                ui.console.print(f"  [dim]{mf.name}[/dim]")
                try:
                    lines = mf.read_text(encoding="utf-8").splitlines()[-5:]
                    for ln in lines:
                        ui.console.print(f"    {ln}")
                except OSError:
                    pass
        else:
            ui.console.print("  [dim]No memory logs yet.[/dim]")
    else:
        ui.console.print("  [dim]No memory directory.[/dim]")

    ui.console.print()

    ui.console.print("[bold]Active Tasks[/bold]")
    hb = ws / "HEARTBEAT.md"
    if hb.is_file():
        task_lines = [
            ln for ln in hb.read_text(encoding="utf-8").splitlines() if ln.startswith("- [")
        ][:5]
        if task_lines:
            for tl in task_lines:
                ui.console.print(f"  {tl}")
        else:
            ui.console.print("  [dim]No active tasks.[/dim]")
    else:
        ui.console.print("  [dim]HEARTBEAT.md not found.[/dim]")

    ui.console.print()

    ui.console.print("[bold]Gateway Activity[/bold]")
    today = _dt.date.today().strftime("%Y-%m-%d")
    log_file = _cfg.LOG_DIR / f"openclaw-{today}.log"
    if log_file.is_file():
        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            matched = [ln for ln in all_lines if agent_id in ln][-5:]
            if matched:
                for ln in matched:
                    ui.console.print(f"  [dim]{ln}[/dim]")
            else:
                ui.console.print(f"  [dim]No entries today for '{agent_id}'.[/dim]")
        except OSError:
            ui.console.print("  [dim]Cannot read log file.[/dim]")
    else:
        ui.console.print(f"  [dim]No log for {today}.[/dim]")

    ui.console.print()

    ui.console.print("[bold]Context Statistics[/bold]")
    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    activity = last_activity(agent_id)

    sessions_dir = _cfg.OPENCLAW_DIR / "agents" / agent_id / "sessions"
    session_size = "n/a"
    if sessions_dir.is_dir():
        session_files = sorted(sessions_dir.glob("*.jsonl"))
        if session_files:
            try:
                size_bytes = session_files[-1].stat().st_size
                session_size = f"{size_bytes // 1024}KB"
            except OSError:
                pass

    ui.console.print(f"  Log files:    {mem_count}")
    ui.console.print(f"  Session size: {session_size}")
    ui.console.print(f"  Last active:  {activity}")

    ui.console.print()
    ui.console.print("[bold]Quick Actions[/bold]")
    ui.console.print(f"  docket context {agent_id} search <query>  — search memory")
    ui.console.print(f"  docket context {agent_id} index            — build search index")
    ui.console.print(f"  docket context {agent_id} snapshot         — export SNAPSHOT.md")
    ui.console.print(f"  docket context {agent_id} compress         — gzip old logs")
    ui.console.print()


def _context_search(agent_id: str, ws: Path, query_parts: list[str]) -> None:
    query = " ".join(query_parts).strip()
    if not query:
        ui.error("Usage: docket context <id> search <query>")
        raise typer.Exit(1)

    index_path = ws / ".memory-index.json"
    if not index_path.is_file():
        ui.warn("Memory not indexed yet. Run: docket context <id> index")
        raise typer.Exit(0)

    try:
        index = _json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        ui.error("Failed to read memory index.")
        raise typer.Exit(1) from None

    keywords = index.get("keywords", {})
    decisions = index.get("decisions", [])
    files = index.get("files", [])

    query_lower = query.lower()
    matches: list[str] = []

    for kw, occurrences in keywords.items():
        if query_lower in kw.lower():
            for occ in occurrences:
                matches.append(f"[keyword] {kw} in {occ}")

    for dec in decisions:
        if query_lower in dec.lower():
            matches.append(f"[decision] {dec}")

    for fname in files:
        if query_lower in fname.lower():
            matches.append(f"[file] {fname}")

    ui.header(f"Search: {query}")
    ui.console.print()
    if matches:
        for m in matches[:20]:
            ui.console.print(f"  {m}")
        if len(matches) > 20:
            ui.console.print(f"  [dim]... {len(matches) - 20} more matches[/dim]")
    else:
        ui.console.print(f"  [dim]No matches for '{query}'.[/dim]")
    ui.console.print()


def _context_index(agent_id: str, ws: Path) -> None:
    import datetime as _dt
    import re as _re

    mem_dir = ws / "memory"
    files: list[str] = []
    keywords: dict[str, list[str]] = {}
    decisions: list[str] = []

    if mem_dir.is_dir():
        for mf in sorted(mem_dir.glob("*.md")):
            files.append(mf.name)
            try:
                content = mf.read_text(encoding="utf-8")
            except OSError:
                continue
            for word in _re.findall(r"\*\*([^*]+)\*\*|`([^`]+)`", content):
                kw = (word[0] or word[1]).strip()
                if kw:
                    kw_lower = kw.lower()
                    keywords.setdefault(kw_lower, [])
                    if mf.name not in keywords[kw_lower]:
                        keywords[kw_lower].append(mf.name)

    memory_md = ws / "MEMORY.md"
    if memory_md.is_file():
        try:
            for ln in memory_md.read_text(encoding="utf-8").splitlines():
                if ln.startswith("## "):
                    decisions.append(ln[3:].strip())
        except OSError:
            pass

    index = {
        "indexed_at": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
        "keywords": keywords,
        "decisions": decisions,
    }

    index_path = ws / ".memory-index.json"
    index_path.write_text(_json.dumps(index, indent=2), encoding="utf-8")
    index_path.chmod(0o600)

    ui.success(
        f"Index built: {len(files)} file(s), {len(keywords)} keyword(s), {len(decisions)} decision(s)"
    )


def _context_snapshot(agent_id: str, ws: Path) -> None:
    import datetime as _dt

    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines: list[str] = [
        f"# SNAPSHOT.md — {name}",
        "",
        f"Generated: {now}",
        "",
        "## Metadata",
        f"- Agent ID: {agent_id}",
        f"- Type: {raw.get('type', 'repo')}",
        f"- Model: {raw.get('model', _cfg.DEFAULT_MODEL)}",
        f"- Session Key: {raw.get('sessionKey', '')}",
        f"- Codebase: {raw.get('codebase', '')}",
        "",
    ]

    lines.append("## Recent Activity")
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        for mf in sorted(mem_dir.glob("*.md"), reverse=True)[:3]:
            lines.append("")
            lines.append(f"### {mf.name}")
            try:
                for ln in mf.read_text(encoding="utf-8").splitlines()[-10:]:
                    lines.append(ln)
            except OSError:
                pass
    lines.append("")

    hb = ws / "HEARTBEAT.md"
    if hb.is_file():
        lines.append("## HEARTBEAT")
        with contextlib.suppress(OSError):
            lines.extend(hb.read_text(encoding="utf-8").splitlines())
        lines.append("")

    mem_md = ws / "MEMORY.md"
    if mem_md.is_file():
        lines.append("## MEMORY")
        with contextlib.suppress(OSError):
            lines.extend(mem_md.read_text(encoding="utf-8").splitlines())
        lines.append("")

    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    lines.append("## Stats")
    lines.append(f"- Memory log files: {mem_count}")
    lines.append(f"- Last active: {last_activity(agent_id)}")

    snap_path = ws / "SNAPSHOT.md"
    snap_path.write_text("\n".join(lines), encoding="utf-8")
    snap_path.chmod(0o600)
    ui.success(f"Snapshot written: {snap_path}")


def _context_compress(agent_id: str, ws: Path) -> None:
    import datetime as _dt
    import gzip as _gzip
    import shutil as _shutil

    mem_dir = ws / "memory"
    if not mem_dir.is_dir():
        ui.info("No memory directory.")
        return

    cutoff = _dt.datetime.now() - _dt.timedelta(days=30)
    old_files: list[Path] = []
    for f in mem_dir.glob("*.md"):
        try:
            mtime = _dt.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                old_files.append(f)
        except OSError:
            pass

    if not old_files:
        ui.info("No old logs to compress (all memory logs are < 30 days old).")
        return

    archive_dir = mem_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_dir.chmod(0o700)

    for f in old_files:
        dest = archive_dir / (f.name + ".gz")
        with f.open("rb") as f_in, _gzip.open(dest, "wb") as f_out:
            _shutil.copyfileobj(f_in, f_out)
        f.unlink()

    ui.success(f"Compressed {len(old_files)} old log(s) → memory/archive/")


def _context_project(agent_id: str, ws: Path) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))

    ui.header(f"Project Context: {name}")
    ui.console.print()
    ui.console.print(f"  [bold]{'Codebase:':<16}[/bold] {raw.get('codebase', '—')}")
    ui.console.print(f"  [bold]{'Stack:':<16}[/bold] {raw.get('stack', '—')}")
    ui.console.print(f"  [bold]{'Model:':<16}[/bold] {raw.get('model', '—')}")
    ui.console.print(f"  [bold]{'Session Key:':<16}[/bold] {raw.get('sessionKey', '—')}")
    ui.console.print()

    hb = ws / "HEARTBEAT.md"
    if hb.is_file():
        task_lines = [
            ln for ln in hb.read_text(encoding="utf-8").splitlines() if ln.startswith("- [")
        ]
        ui.console.print("[bold]Active Tasks[/bold]")
        if task_lines:
            for tl in task_lines[:5]:
                ui.console.print(f"  {tl}")
        else:
            ui.console.print("  [dim]No active tasks.[/dim]")
        ui.console.print()

    mem_md = ws / "MEMORY.md"
    if mem_md.is_file():
        headers = [
            ln[3:].strip()
            for ln in mem_md.read_text(encoding="utf-8").splitlines()
            if ln.startswith("## ")
        ]
        ui.console.print("[bold]Memory Sections[/bold]")
        for h in headers:
            ui.console.print(f"  ## {h}")
        ui.console.print()

    mem_dir = ws / "memory"
    mem_count = sum(1 for _ in mem_dir.glob("*.md")) if mem_dir.is_dir() else 0
    ui.console.print(f"  Memory logs: {mem_count}")
    ui.console.print(f"  Last active: {last_activity(agent_id)}")
    ui.console.print()


@app.command("wire")
def cmd_wire(
    agent_id: str | None = typer.Argument(None),
    channel: str = typer.Option(
        "telegram", "--channel", help="Channel to wire (default: telegram)"
    ),
) -> None:
    """Wire or update a channel group binding."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Wire channel group")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    name = _oc.meta_get(aid, "name", aid)
    existing = _oc.get_binding(aid, channel)

    ui.header(f"Wire {channel.capitalize()}: {name} ({aid})")
    ui.console.print()
    if existing:
        ui.warn(f"Currently wired to: {existing}")

    peer_id = ""

    if channel == "telegram":
        groups = scan_telegram_groups()

        if not groups:
            ui.warn("No Telegram groups found in OpenClaw logs.")
            ui.console.print()
            ui.console.print("[bold]To wire a group:[/bold]")
            ui.console.print("  1. Create a Telegram group")
            ui.console.print("  2. Add your OpenClaw bot to the group")
            ui.console.print("  3. Send a message in the group")
            ui.console.print(f"  4. Wait a few seconds, then run: docket wire {aid}")
            ui.console.print()
            ui.warn("Aborted - no groups available.")
            raise typer.Exit(0)

        unbound = [(gid, title) for gid, title, bound in groups if not bound]

        if not unbound:
            # All groups are already bound — show all and allow override.
            ui.console.print("[yellow]All groups are already bound:[/yellow]")
            ui.console.print()
            for i, (gid, title, bound) in enumerate(groups, 1):
                ui.console.print(
                    f"  [bold]{i:2}.[/bold] {gid:<22} {title:<28}"
                    f" → [cyan]{bound or '<unbound>'}[/cyan]"
                )
            ui.console.print()
            ui.console.print("You can:")
            ui.console.print(
                f"  • Create a new Telegram group, add bot, send message,"
                f" then run: docket wire {aid}"
            )
            ui.console.print("  • Unbind an existing group: docket unwire <agent-id>")
            ui.console.print("  • Override an existing binding (select number above)")
            ui.console.print()
            choice = input(f"Select group (1-{len(groups)}) or press Enter to cancel: ").strip()
            if not choice:
                ui.warn("Aborted.")
                raise typer.Exit(0)
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(groups):
                    peer_id = groups[idx][0]
                    prev_bound = groups[idx][2]
                    if prev_bound:
                        ui.warn(f"This will unbind '{prev_bound}' from group '{groups[idx][1]}'")
                        ok = input("Continue? [y/N]: ").strip()
                        if ok.lower() != "y":
                            ui.warn("Aborted.")
                            raise typer.Exit(0)
                else:
                    ui.warn("Invalid choice. Aborted.")
                    raise typer.Exit(0)
            except ValueError:
                ui.warn("Invalid choice. Aborted.")
                raise typer.Exit(0) from None

        elif len(unbound) == 1:
            gid, title = unbound[0]
            ui.console.print("[green]Found 1 unbound group:[/green]")
            ui.console.print(f"  {gid} - {title}")
            ui.console.print()
            ok = input("Wire to this group? [Y/n]: ").strip()
            if ok.lower() == "n":
                ui.warn("Aborted.")
                raise typer.Exit(0)
            peer_id = gid

        else:
            ui.console.print("[green]Available unbound groups:[/green]")
            ui.console.print()
            for i, (gid, title) in enumerate(unbound, 1):
                ui.console.print(f"  [bold]{i:2}.[/bold] {gid:<22} {title}")
            ui.console.print()
            ui.console.print("  [bold] 0.[/bold] Enter group ID manually")
            ui.console.print()
            while True:
                choice = input(
                    f"Select group (1-{len(unbound)}, 0 for manual, or Enter to cancel): "
                ).strip()
                if not choice:
                    ui.warn("Aborted.")
                    raise typer.Exit(0)
                if choice == "0":
                    peer_id = input("Telegram group ID: ").strip()
                    if not peer_id:
                        ui.warn("Aborted.")
                        raise typer.Exit(0)
                    break
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(unbound):
                        peer_id = unbound[idx][0]
                        break
                    else:
                        ui.warn(f"Invalid choice. Please enter 1-{len(unbound)} or 0.")
                except ValueError:
                    ui.warn(f"Invalid choice. Please enter 1-{len(unbound)} or 0.")

    else:
        ui.dim(
            f"No log-based discovery for {channel}."
            f" Enter the peer/group ID from your {channel} setup."
        )
        ui.console.print()
        peer_id = input(f"{channel.capitalize()} peer/group ID: ").strip()
        if not peer_id:
            ui.warn("Aborted.")
            raise typer.Exit(0)

    allowlist_ok = _oc.wire_group(aid, peer_id, channel)
    if allowlist_ok:
        ui.success(f"Group {peer_id} added to allowlist")
    else:
        ui.warn("Could not set allowlist entry — check manually")
    ui.success(f"Binding: {aid} ← {channel} group {peer_id}")
    _do_restart_gateway()
    ui.success(f"Done. '{aid}' is now wired to {channel} peer {peer_id}")


@app.command("unwire")
def cmd_unwire(
    agent_id: str | None = typer.Argument(None),
    channel: str = typer.Option(
        "telegram", "--channel", help="Channel to unwire (default: telegram)"
    ),
) -> None:
    """Remove a channel binding."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Unwire channel")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    name = _oc.meta_get(aid, "name", aid)
    peer = _oc.get_binding(aid, channel)

    if not peer:
        ui.warn(f"'{aid}' has no {channel} binding.")
        raise typer.Exit(0)

    ui.header(f"Unwire {channel.capitalize()}: {name} ({aid})")
    ui.console.print()
    ui.warn(f"This will remove the {channel} binding for peer {peer}")
    confirm = input("Confirm? [y/N]: ").strip()

    if confirm.lower() != "y":
        ui.warn("Aborted.")
        raise typer.Exit(0)

    _oc.remove_binding(aid, channel)
    ui.success("Binding removed")
    _do_restart_gateway()


@app.command("scope")
def cmd_scope(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
    project_key: str | None = typer.Argument(None),
) -> None:
    """Manage session scope / project isolation key."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Manage scope for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Project '{aid}' not found.")
        raise typer.Exit(1)

    action = sub or "show"
    name = _oc.meta_get(aid, "name", aid)
    current_key = _oc.meta_get(aid, "projectKey", "default")
    current_session = _oc.meta_get(aid, "sessionKey", f"agent:{aid}:default")

    if action == "show":
        ui.header(f"Session Scope: {name} ({aid})")
        ui.console.print()
        ui.console.print(f"  [bold]{'Current Scope:':<18}[/bold] {current_key}")
        ui.console.print(f"  [bold]{'Session Key:':<18}[/bold] {current_session}")
        ui.console.print()
        ui.console.print(
            "This session key prevents the agent from accessing other project contexts."
        )
        ui.console.print("Each project scope gets isolated workspace memory and routing.")
        ui.console.print()
        ui.console.print("Usage:")
        ui.console.print(f"  docket scope {aid} set <project-key>    # Change project scope")
        ui.console.print(f"  docket scope {aid} reset                # Reset to 'default'")
        ui.console.print()

    elif action == "set":
        if not project_key:
            ui.error(f"Project key required. Usage: docket scope {aid} set <project-key>")
            raise typer.Exit(1)
        new_session = f"agent:{aid}:{project_key}"
        _oc.meta_set(aid, "projectKey", project_key)
        _oc.meta_set(aid, "sessionKey", new_session)
        with contextlib.suppress(KeyError):
            _oc.sync_session_key(aid, new_session, project_key)
        ui.success(f"Session scope updated: {current_key} → {project_key}")
        ui.success(f"Session key: {new_session}")
        ui.info("Update SOUL.md to reflect the new scope if needed.")
        _do_restart_gateway()

    elif action == "reset":
        new_session = f"agent:{aid}:default"
        _oc.meta_set(aid, "projectKey", "default")
        _oc.meta_set(aid, "sessionKey", new_session)
        with contextlib.suppress(KeyError):
            _oc.sync_session_key(aid, new_session, "default")
        ui.success("Session scope reset to: default")
        ui.success(f"Session key: {new_session}")
        _do_restart_gateway()

    else:
        ui.error(f"Unknown action '{action}'. Use: show, set, or reset")
        raise typer.Exit(1)


@app.command("profile")
def cmd_profile(
    agent_id: str | None = typer.Argument(None),
    model: str | None = typer.Argument(None),
    budget: str | None = typer.Option(None, "--budget", help="USD cap (0 = remove)"),
) -> None:
    """Pin or unpin an agent's model; set a budget cap."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Set model for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    if budget is not None:
        try:
            bval = float(budget)
            if bval < 0:
                raise ValueError
        except ValueError:
            ui.error(f"Invalid budget '{budget}'. Must be a non-negative number (e.g. 5 or 10.50).")
            raise typer.Exit(1) from None
        _oc.meta_set(aid, "budgetUsd", budget)
        if budget != "0":
            _oc.meta_set(aid, "paused", False)
            _oc.meta_set(aid, "pausedReason", "")
            ui.success(f"Budget cap set to ${budget} for '{aid}'.")
        else:
            ui.success(f"Budget cap removed for '{aid}'.")
        if model is None:
            return  # budget-only change, nothing more to do

    name = _oc.meta_get(aid, "name", aid)
    current = _oc.meta_get(aid, "model", _cfg.DEFAULT_MODEL)
    role = _mp.agent_role(aid)
    src = _mp.agent_model_source(aid)
    bud = _oc.meta_get(aid, "budgetUsd", "")

    if model is None:
        role_models, _, _ = _mp.load_registry()
        policy_model = _mp.resolve_role_model(role, role_models)
        ui.header(f"Model: {name} ({aid})")
        ui.console.print()
        ui.console.print(f"  [bold]{'Current model:':<18}[/bold] {current}")
        ui.console.print(
            f"  [bold]{'Role:':<18}[/bold] {role}  [dim]({_cfg.ROLE_WHY.get(role, '')})[/dim]"
        )
        if src == "policy":
            ui.console.print(
                f"  [bold]{'Source:':<18}[/bold] policy — follows the role's model (docket models)"
            )
        else:
            ui.console.print(
                f"  [bold]{'Source:':<18}[/bold] pinned — unaffected by policy changes"
            )
        if bud and bud != "0":
            ui.console.print(f"  [bold]{'Budget cap:':<18}[/bold] ${float(bud):.2f}")
        else:
            ui.console.print(f"  [bold]{'Budget cap:':<18}[/bold] none")
        ui.console.print()
        ui.console.print(f"  [bold]Policy for role '{role}':[/bold] {policy_model}")
        ui.console.print()
        ui.console.print(f"  docket profile {aid} <provider/model>   # pin this agent")
        ui.console.print(f"  docket profile {aid} default            # follow role policy")
        ui.console.print(f"  docket profile {aid} --budget <USD>     # spending cap (0=none)")
        ui.console.print("  docket models                         # view/change role policy")
        ui.console.print()
        return

    if model in ("default", "policy"):
        role_models, _, _ = _mp.load_registry()
        new_model = _mp.resolve_role_model(role, role_models)
        new_src = "policy"
    else:
        try:
            new_model, warnings = _mp.validate_model(model)
        except ValueError as exc:
            ui.error(str(exc))
            raise typer.Exit(1) from None
        for w in warnings:
            ui.warn(w)
        new_src = "pinned"

    if new_model == current and new_src == src:
        ui.warn(f"Already using {new_model} ({new_src}). No change.")
        return

    _oc.set_model_both(aid, new_model)
    _oc.meta_set(aid, "modelSource", new_src)

    if new_src == "policy":
        ui.success(f"Model: {current} → {new_model} (follows role policy '{role}')")
    else:
        ui.success(f"Model pinned: {current} → {new_model}")
    _do_restart_gateway()


@app.command(
    "keys",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_keys(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """API key management (add/list/remove/rotate/validate/export/setup)."""
    extra: list[str] = list(ctx.args)
    action = sub or "list"

    if action == "list":
        _keys_list()
    elif action == "add":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys add <KEY_NAME>")
            raise typer.Exit(1)
        _keys_add(name)
    elif action == "remove":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys remove <KEY_NAME>")
            raise typer.Exit(1)
        _keys_remove(name)
    elif action == "rotate":
        name = extra[0] if extra else None
        if not name:
            ui.error("Usage: docket keys rotate <KEY_NAME>")
            raise typer.Exit(1)
        _keys_rotate(name)
    elif action == "validate":
        name = extra[0] if extra else None
        _keys_validate(name)
    elif action == "export":
        _keys_export()
    elif action == "setup":
        _keys_setup()
    else:
        ui.console.print("[bold]docket keys — API key management[/bold]")
        ui.console.print()
        ui.console.print("  docket keys list                  Show stored keys (masked)")
        ui.console.print("  docket keys add <KEY_NAME>        Store a new key")
        ui.console.print("  docket keys remove <KEY_NAME>     Remove a key")
        ui.console.print("  docket keys rotate <KEY_NAME>     Update an existing key")
        ui.console.print("  docket keys validate [KEY_NAME]   Check format validity")
        ui.console.print("  docket keys export                Print export statements")
        ui.console.print("  docket keys setup                 Interactive setup wizard")
        ui.console.print()
        raise typer.Exit(1)


def _secrets_path() -> Path:
    return _cfg.OPENCLAW_DIR / "secrets.json"


def _secrets_meta_path() -> Path:
    return _cfg.OPENCLAW_DIR / "secrets.meta.json"


def _load_secrets() -> dict[str, str]:
    try:
        data: dict[str, str] = _json.loads(_secrets_path().read_text(encoding="utf-8"))
        return data
    except Exception:
        return {}


def _save_secrets(secrets: dict[str, str]) -> None:
    path = _secrets_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_json.dumps(secrets, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _load_secrets_meta() -> dict[str, Any]:
    try:
        data: dict[str, Any] = _json.loads(_secrets_meta_path().read_text(encoding="utf-8"))
        return data
    except Exception:
        return {}


def _touch_secrets_meta(name: str, event: str) -> None:
    import datetime as _dt

    meta = _load_secrets_meta()
    now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if event == "removed":
        meta.pop(name, None)
    else:
        entry: dict[str, Any] = meta.get(name) or {}
        entry.setdefault("added_at", now)
        if event == "rotated":
            entry["rotated_at"] = now
        meta[name] = entry
    path = _secrets_meta_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


_PROVIDER_KEYS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENAI_API_KEY": "openai",
    "GOOGLE_AI_API_KEY": "google",
    "OPENROUTER_API_KEY": "openrouter",
    "GROQ_API_KEY": "groq",
    "MISTRAL_API_KEY": "mistral",
    "XAI_API_KEY": "xai",
    "CEREBRAS_API_KEY": "cerebras",
    "HUGGINGFACE_TOKEN": "huggingface",
}

_KEY_PREFIXES: dict[str, tuple[str, int]] = {
    "ANTHROPIC_API_KEY": ("sk-ant-", 40),
    "OPENAI_API_KEY": ("sk-", 40),
    "GOOGLE_AI_API_KEY": ("AIza", 0),
    "OPENROUTER_API_KEY": ("sk-or-", 0),
}


def _mask_key(value: str) -> str:
    if len(value) > 12:
        return value[:4] + "****" + value[-4:]
    return "****"


def _validate_key_format(name: str, value: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty if ok."""
    if name in _KEY_PREFIXES:
        prefix, min_len = _KEY_PREFIXES[name]
        if not value.startswith(prefix):
            return False, f"should start with '{prefix}'"
        if min_len and len(value) < min_len:
            return False, f"too short (< {min_len} chars)"
    return True, ""


def _sync_keys_to_agents() -> None:
    """Write .env files to agent workspaces with their provider keys."""
    secrets = _load_secrets()
    if not secrets:
        return

    for aid in project_ids():
        ws = _cfg.workspace_dir(aid)
        if not ws.is_dir():
            continue
        raw = store.read_json(_cfg.meta_path(aid))
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        agent_provider = model.split("/")[0] if "/" in model else ""

        env_lines: list[str] = []
        for key_name, key_provider in _PROVIDER_KEYS.items():
            if key_name not in secrets:
                continue
            if key_provider == agent_provider or key_provider not in _PROVIDER_KEYS.values():
                env_lines.append(f'{key_name}="{secrets[key_name]}"')

        for key_name, value in secrets.items():
            if key_name not in _PROVIDER_KEYS:
                env_lines.append(f'{key_name}="{value}"')

        env_file = ws / ".env"
        env_file.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        env_file.chmod(0o600)


def _keys_list() -> None:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No API keys stored yet.")
        ui.console.print("  Add a key: docket keys add <KEY_NAME>")
        ui.console.print("  Interactive setup: docket keys setup")
        return

    ui.header("Stored API Keys")
    ui.console.print()
    meta = _load_secrets_meta()
    for name, value in sorted(secrets.items()):
        masked = _mask_key(value)
        entry = meta.get(name, {})
        added = entry.get("added_at", "")[:10] if entry else ""
        date_str = f"  added {added}" if added else ""
        ok, _ = _validate_key_format(name, value)
        badge = "[green]✓[/green]" if ok else "[yellow]⚠[/yellow]"
        ui.console.print(f"  {badge} {name:<32}  {masked}{date_str}")
    ui.console.print()


def _keys_add(name: str) -> None:
    import getpass as _getpass
    import re as _re

    if not _re.match(r"^[A-Z][A-Z0-9_]*$", name):
        ui.error(
            f"Invalid key name '{name}'. Use UPPERCASE_WITH_UNDERSCORES (e.g. ANTHROPIC_API_KEY)."
        )
        raise typer.Exit(1)

    secrets = _load_secrets()
    if name in secrets:
        ui.warn(f"Key '{name}' already exists. Use 'docket keys rotate' to update it.")
        raise typer.Exit(1)

    try:
        value = _getpass.getpass(f"Enter value for {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("\nAborted.")
        raise typer.Exit(0) from None

    if not value:
        ui.error("Value cannot be empty.")
        raise typer.Exit(1)

    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format warning: {reason}")

    secrets[name] = value
    _save_secrets(secrets)
    _touch_secrets_meta(name, "added")
    _sync_keys_to_agents()
    _do_restart_gateway()
    ui.success(f"Key '{name}' stored.")


def _keys_remove(name: str) -> None:
    secrets = _load_secrets()
    if name not in secrets:
        ui.error(f"Key '{name}' not found.")
        raise typer.Exit(1)

    if sys.stdin.isatty():
        ans = input(f"Remove '{name}'? [y/N]: ").strip().lower()
        if ans != "y":
            ui.warn("Cancelled.")
            return

    del secrets[name]
    _save_secrets(secrets)
    _touch_secrets_meta(name, "removed")
    _sync_keys_to_agents()
    _do_restart_gateway()
    ui.success(f"Key '{name}' removed.")


def _keys_rotate(name: str) -> None:
    import getpass as _getpass

    secrets = _load_secrets()
    if name not in secrets:
        ui.error(f"Key '{name}' does not exist. Use 'docket keys add' to create it.")
        raise typer.Exit(1)

    try:
        value = _getpass.getpass(f"Enter new value for {name} (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.warn("\nAborted.")
        raise typer.Exit(0) from None

    if not value:
        ui.error("Value cannot be empty.")
        raise typer.Exit(1)

    ok, reason = _validate_key_format(name, value)
    if not ok:
        ui.warn(f"Key format warning: {reason}")

    secrets[name] = value
    _save_secrets(secrets)
    _touch_secrets_meta(name, "rotated")
    _sync_keys_to_agents()
    _do_restart_gateway()
    ui.success(f"Key '{name}' rotated.")


def _keys_validate(name: str | None) -> None:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No keys stored.")
        return

    targets = {name: secrets[name]} if name and name in secrets else secrets
    if name and name not in secrets:
        ui.error(f"Key '{name}' not found.")
        raise typer.Exit(1)

    any_fail = False
    for key_name, value in sorted(targets.items()):
        ok, reason = _validate_key_format(key_name, value)
        if ok:
            ui.console.print(f"  [green]✓[/green] {key_name}")
        else:
            ui.console.print(f"  [yellow]⚠[/yellow] {key_name}: {reason}")
            any_fail = True

    if any_fail:
        raise typer.Exit(1)


def _keys_export() -> None:
    secrets = _load_secrets()
    if not secrets:
        ui.info("No keys stored.")
        return

    for name, value in sorted(secrets.items()):
        # Shell-safe: escape single quotes
        safe_value = value.replace("'", "'\\''")
        print(f"export {name}='{safe_value}'")


def _keys_setup() -> None:
    import getpass as _getpass

    if not sys.stdin.isatty():
        ui.error("docket keys setup requires an interactive TTY.")
        raise typer.Exit(1)

    ui.header("API Key Setup Wizard")
    ui.console.print()
    ui.console.print("Walk through key providers. Press Enter to skip any.")
    ui.console.print()

    providers = [
        ("ANTHROPIC_API_KEY", "Anthropic (Claude)", "sk-ant-"),
        ("OPENAI_API_KEY", "OpenAI (GPT)", "sk-"),
        ("GOOGLE_AI_API_KEY", "Google AI (Gemini)", "AIza"),
        ("OPENROUTER_API_KEY", "OpenRouter", "sk-or-"),
    ]

    secrets = _load_secrets()
    changed = False

    for key_name, label, _prefix in providers:
        exists = key_name in secrets
        status = f"[already set: {_mask_key(secrets[key_name])}]" if exists else "[not set]"
        ui.console.print(f"[bold]{label}[/bold] {status}")
        action = input(f"  Configure {key_name}? [y/N]: ").strip().lower()
        if action != "y":
            ui.console.print()
            continue

        try:
            value = _getpass.getpass(f"  {key_name}: ").strip()
        except (KeyboardInterrupt, EOFError):
            ui.warn("\nAborted.")
            return

        if not value:
            ui.warn("  Skipped (empty).")
            ui.console.print()
            continue

        ok, reason = _validate_key_format(key_name, value)
        if not ok:
            ui.warn(f"  Format warning: {reason}")
            if input("  Save anyway? [y/N]: ").strip().lower() != "y":
                ui.console.print()
                continue

        secrets[key_name] = value
        event = "rotated" if exists else "added"
        _touch_secrets_meta(key_name, event)
        changed = True
        ui.success(f"  {key_name} saved.")
        ui.console.print()

    if changed:
        _save_secrets(secrets)
        _sync_keys_to_agents()
        _do_restart_gateway()
        ui.success("Keys saved and synced to agent workspaces.")
    else:
        ui.info("No changes made.")


@app.command(
    "auth",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_auth(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """Claude model authentication (status/login/key/setup)."""
    extra: list[str] = list(ctx.args)
    action = sub or "status"

    if action == "status":
        profiles = _oc.auth_profiles_summary()
        if not profiles:
            ui.warn("No auth profiles configured.")
            ui.console.print("  Run: docket auth login")
            return

        ui.console.print()
        any_ok = False
        for p in profiles:
            if p.disabled:
                badge = "[yellow]●[/yellow]"
                detail = f"(disabled: {p.disabled_reason})" if p.disabled_reason else "(disabled)"
            else:
                badge = "[green]●[/green]"
                detail = ""
                any_ok = True
            ui.console.print(f"  {badge} {p.id}  ({p.provider}, {p.type}) {detail}")

        ui.console.print()
        if any_ok:
            ui.success("At least one profile is usable.")
        else:
            ui.warn("All profiles are disabled.")

    elif action == "login":
        if not shutil.which("openclaw"):
            ui.error("'openclaw' not found in PATH. Is it installed?")
            raise typer.Exit(1)
        ui.info("Authenticating with Anthropic (setup-token)...")
        result = _oc.auth_setup_token(extra)
        if result.returncode == 0:
            ui.success("Authentication successful.")
            _do_restart_gateway()
        else:
            ui.error(f"Authentication failed (exit {result.returncode}).")
            raise typer.Exit(1)

    elif action == "key":
        if not shutil.which("openclaw"):
            ui.error("'openclaw' not found in PATH. Is it installed?")
            raise typer.Exit(1)
        ui.info("Authenticating with Anthropic (paste-token)...")
        result = _oc.auth_paste_token(extra)
        if result.returncode == 0:
            ui.success("Key stored successfully.")
            _do_restart_gateway()
        else:
            ui.error(f"Key storage failed (exit {result.returncode}).")
            raise typer.Exit(1)

    elif action in ("setup", "choose"):
        if not shutil.which("openclaw"):
            ui.error("'openclaw' not found in PATH. Is it installed?")
            raise typer.Exit(1)
        if not sys.stdin.isatty():
            ui.error("docket auth setup requires an interactive TTY.")
            raise typer.Exit(1)
        ui.console.print()
        ui.console.print("[bold]Authentication setup:[/bold]")
        ui.console.print("  1) Setup token (recommended — automatic token refresh)")
        ui.console.print("  2) Paste API key (manual — no refresh)")
        ui.console.print("  3) Cancel")
        ui.console.print()
        choice = input("Choose [1]: ").strip() or "1"
        if choice == "3":
            ui.warn("Cancelled.")
            return
        method = "paste-token" if choice == "2" else "setup-token"
        result = _oc.auth_paste_token() if method == "paste-token" else _oc.auth_setup_token()
        if result.returncode == 0:
            ui.success("Authentication configured.")
            _do_restart_gateway()
        else:
            ui.error(f"Authentication failed (exit {result.returncode}).")
            raise typer.Exit(1)

    else:
        ui.error(
            f"Unknown auth subcommand '{action}'.\n"
            "Usage:\n"
            "  docket auth              — show auth profile status\n"
            "  docket auth login        — setup-token (OAuth-like refresh)\n"
            "  docket auth key          — paste-token (manual API key)\n"
            "  docket auth setup        — interactive choice"
        )
        raise typer.Exit(1)


@app.command(
    "models",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_models(ctx: typer.Context) -> None:
    """View and edit the role→model policy."""
    args = ctx.args
    sub = args[0] if args else "list"
    rest = args[1:]

    if sub in ("list", "ls", ""):
        _cmd_models_list()
    elif sub == "set":
        if len(rest) < 2:
            ui.error("Usage: docket models set <role|default> <provider/model>")
            raise typer.Exit(1)
        _cmd_models_set(rest[0], rest[1])
    elif sub == "preset":
        _cmd_models_preset(rest[0] if rest else None)
    elif sub == "reset":
        _cmd_models_reset()
    elif sub == "provider":
        _cmd_models_provider(rest)
    else:
        ui.error(
            f"Unknown models subcommand '{sub}'.\n"
            "Usage:\n"
            "  docket models                            # show role→model policy\n"
            "  docket models set <role> <model>         # change a role's model\n"
            "  docket models preset [name]              # list or apply a provider preset\n"
            "  docket models reset                      # restore built-in defaults\n"
            "  docket models provider add <name> <url>  # register a local provider"
        )
        raise typer.Exit(1)


def _cmd_models_provider(rest: list[str]) -> None:
    """Wire `docket models provider add <name> <base-url> [--opts]` (T5.6)."""
    from docket.cli import _provider
    from docket.core import provider as _prov

    if len(rest) < 1 or rest[0] != "add":
        ui.error(
            "Usage: docket models provider add <name> <base-url> "
            "[--model ID] [--name NAME] [--ctx N] [--max-tokens N]"
        )
        raise typer.Exit(1)

    pos: list[str] = []
    opts: dict[str, str] = {}
    i = 1
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("--"):
            key = tok[2:]
            if "=" in key:
                k, v = key.split("=", 1)
                opts[k] = v
            else:
                opts[key] = rest[i + 1] if i + 1 < len(rest) else ""
                i += 1
        else:
            pos.append(tok)
        i += 1

    name = pos[0] if len(pos) > 0 else _prov.DEFAULT_PROVIDER
    base_url = pos[1] if len(pos) > 1 else _prov.DEFAULT_BASE_URL
    raise typer.Exit(
        _provider.run_provider_add(
            name=name,
            base_url=base_url,
            model_id=opts.get("model", _prov.DEFAULT_MODEL_ID),
            model_name=opts.get("name", _prov.DEFAULT_MODEL_NAME),
            ctx=int(opts.get("ctx", _prov.DEFAULT_CTX)),
            max_tokens=int(opts.get("max-tokens", _prov.DEFAULT_MAX_TOKENS)),
        )
    )


def _cmd_models_list() -> None:
    role_models, tiers, default_model = _mp.load_registry()
    reg_exists = _cfg.MODEL_REGISTRY_FILE.exists()

    ui.header("Role→model policy")
    ui.console.print()
    fmt = "  {:<12}  {:<38}  {:<14}  {:<8}  {}"
    ui.console.print(f"[bold]{fmt.format('ROLE', 'MODEL', 'PRICE', 'SOURCE', 'WHY')}[/bold]")
    ui.console.print(fmt.format("----", "-----", "-----", "------", "---"))

    for role in _mp.ALL_ROLES:
        m = role_models.get(role, _cfg.DEFAULT_MODEL)
        price = _mp.pricing_label(m)
        # source: 'user' if the registry has an explicit role override, else 'builtin'
        reg_roles: dict[str, str] = {}
        if reg_exists:
            try:
                import json as _j

                reg_roles = _j.loads(_cfg.MODEL_REGISTRY_FILE.read_text(encoding="utf-8")).get(
                    "roles", {}
                )
            except Exception:
                pass
        source = "user" if role in reg_roles and reg_roles[role] == m else "builtin"
        why = _cfg.ROLE_WHY.get(role, "")
        ui.console.print(fmt.format(role, m, price, source, why))

    ui.console.print()
    ui.console.print(f"  {'default':<12}  {default_model}")
    ui.console.print(
        f"  {'fallback':<12}  "
        f"{tiers.get('premium', '')} → {tiers.get('standard', '')} → {tiers.get('economy', '')}"
    )
    ui.console.print()
    ui.console.print(f"  Registry file: {_cfg.MODEL_REGISTRY_FILE}")
    if reg_exists:
        ui.console.print("  (user overrides active)")
    else:
        ui.console.print("  (no user overrides — using built-in defaults)")
    ui.dim(
        f"  PRICE column is an estimate from a snapshot (as of {_mp.MODEL_PRICING_AS_OF});"
        f" override in docket-models.json"
    )
    ui.console.print()
    ui.console.print("Change: docket models set <role|default> <provider/model>")
    # markup=False: the literal [anthropic|...] must not be parsed as Rich markup.
    ui.console.print(
        "Preset: docket models preset [anthropic|openai|google|openrouter-free|openrouter]",
        markup=False,
    )
    ui.console.print(
        "Pin one agent instead: docket profile <id> <provider/model>"
        "   (back: docket profile <id> default)"
    )


def _cmd_models_set(key: str, model: str) -> None:
    try:
        validated, warnings = _mp.validate_model(model)
    except ValueError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from None
    for w in warnings:
        ui.warn(w)

    updates: dict[str, str] = {}
    touched_roles: list[str] = []

    if key == "default":
        updates["default"] = validated
    elif _mp.is_role(key):
        updates[f"role.{key}"] = validated
        touched_roles.append(key)
    elif key in ("economy", "standard", "premium"):
        ui.warn("Tier names are deprecated — the role policy is the source of truth.")
        for role in _mp.ALL_ROLES:
            cls = _mp.ROLE_CLASS.get(role, "strong")
            if (key == "economy" and cls == "cheap") or (key == "standard" and cls == "strong"):
                updates[f"role.{role}"] = validated
                touched_roles.append(role)
        if key == "premium":
            ui.info(
                "premium is a fallback anchor only — no role uses it by default."
                " Pin an agent instead: docket profile <id> <provider/model>"
            )
        updates[f"tier.{key}"] = validated
        if touched_roles:
            ui.info(f"Mapped to role(s): {' '.join(touched_roles)}")
    else:
        all_r = " ".join(_mp.ALL_ROLES)
        ui.error(f"Unknown key '{key}'. Use a role ({all_r}) or 'default'.")
        raise typer.Exit(1)

    _mp.write_registry(updates)
    ui.success(f"{key} → {validated}")
    if validated not in _mp.MODEL_PRICING:
        ui.info(f"No pricing data for {validated} — cost will show as n/a.")

    if touched_roles:
        ui.console.print()
        ui.info("Re-resolving policy-following agents...")
        n = _mp.reapply_role_policy()
        if n:
            ui.console.print(f"  {n} agent(s) updated.")
        _do_restart_gateway()


def _cmd_models_preset(preset: str | None) -> None:
    if preset is None:
        ui.header("Provider presets")
        ui.console.print()
        fmt = "  {:<18}  {:<8}  {:<20}  {}"
        ui.console.print(
            f"[bold]{fmt.format('PRESET', 'COST', 'KEY NEEDED', 'DESCRIPTION')}[/bold]"
        )
        ui.console.print(fmt.format("------", "----", "----------", "-----------"))
        for p in _mp.KNOWN_PRESETS:
            t = _mp.PRESET_TABLE[p]
            marker = " (default)" if p == "anthropic" else ""
            ui.console.print(fmt.format(f"{p}{marker}", t["cost"], t["key"], t["note"]))
        ui.console.print()
        ui.console.print("Apply: docket models preset <name>")
        ui.console.print()
        ui.console.print(
            "Free options: openrouter-free (zero per-token cost, free account at openrouter.ai)"
        )
        return

    if preset not in _mp.PRESET_TABLE:
        valid = " ".join(_mp.KNOWN_PRESETS)
        ui.error(f"Unknown preset '{preset}'. Valid: {valid}")
        raise typer.Exit(1)

    t = _mp.PRESET_TABLE[preset]
    econ, std, prem = t["economy"], t["standard"], t["premium"]
    cost, note = t["cost"], t["note"]

    cheap_roles = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "cheap"]
    strong_roles = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "strong"]

    updates: dict[str, str] = {
        "tier.economy": econ,
        "tier.standard": std,
        "tier.premium": prem,
        "default": std,
    }
    for r in cheap_roles:
        updates[f"role.{r}"] = econ
    for r in strong_roles:
        updates[f"role.{r}"] = std

    ui.console.print()
    ui.info(f"Applying preset: {preset}")
    ui.console.print(f"  {' '.join(cheap_roles)}")
    ui.console.print(f"    → {econ}")
    ui.console.print(f"  {' '.join(strong_roles)}")
    ui.console.print(f"    → {std}")
    ui.console.print(f"  fallback ceiling → {prem}")
    if cost == "free":
        ui.console.print("  cost → free per-token (zero cost on free-tier models)")
    else:
        ui.console.print("  cost → paid")
    if note:
        ui.console.print(f"  note → {note}")
    ui.console.print()

    _mp.write_registry(updates)
    ui.success(f"Preset '{preset}' applied.")

    ui.console.print()
    ui.info("Re-resolving policy-following agents...")
    n = _mp.reapply_role_policy()
    if n:
        ui.console.print(f"  {n} agent(s) updated.")
    _do_restart_gateway()

    key_name = t.get("key", "")
    if key_name:
        secrets_path = _cfg.OPENCLAW_DIR / "secrets.json"
        key_present = False
        if secrets_path.exists():
            try:
                import json as _j

                key_present = key_name in _j.loads(secrets_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not key_present:
            ui.console.print()
            ui.warn(f"API key {key_name} is not stored yet.")
            ui.console.print(f"  Add it: docket keys add {key_name} <your-key>")
            if preset in ("openrouter-free", "openrouter"):
                ui.console.print("  Get one: https://openrouter.ai/keys (free account available)")

    ui.console.print()
    ui.info("Pinned agents kept their model. Pin or unpin one agent:")
    ui.console.print("  docket profile <id> <provider/model>   # pin")
    ui.console.print("  docket profile <id> default            # follow the role policy again")


def _cmd_models_reset() -> None:
    if not _cfg.MODEL_REGISTRY_FILE.exists():
        ui.info("No user overrides found (already using built-in defaults).")
        return

    ui.console.print()
    ui.warn(
        "This will remove all user model overrides and restore the built-in role policy"
        " (Anthropic defaults)."
    )
    ui.console.print()
    confirm = input("Continue? [y/N] ").strip()
    if confirm.lower() not in ("y", "yes"):
        ui.info("Aborted.")
        return

    _mp.write_registry({}, reset=True)
    with contextlib.suppress(FileNotFoundError):
        _cfg.MODEL_REGISTRY_FILE.unlink()
    ui.success("Restored built-in model defaults.")

    ui.console.print()
    ui.info("Re-resolving policy-following agents...")
    n = _mp.reapply_role_policy()
    if n:
        ui.console.print(f"  {n} agent(s) updated.")
    _do_restart_gateway()


@app.command(
    "pod",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_pod(
    ctx: typer.Context,
    project: str = typer.Argument(..., help="Project (pod) id"),
    sub: str | None = typer.Argument(None, help="list | add <role> | remove <member-id>"),
) -> None:
    """Manage a project's pod: list members, add a role (implementer/reviewer/tester), or remove one."""
    from docket.cli import _pod

    _pod.dispatch(project, sub, list(ctx.args))


@app.command(
    "team",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_team(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """Manager task queue (delegate/queue/start/done/cancel)."""
    action = sub or "queue"
    extra: list[str] = list(ctx.args)

    if action == "delegate":
        _team_delegate(extra)
    elif action == "queue":
        _team_queue(extra)
    elif action in ("start", "done", "cancel"):
        state_map = {"start": "in_progress", "done": "done", "cancel": "cancelled"}
        _team_transition(state_map[action], extra)
    else:
        _team_help_text()


def _team_help_text() -> None:
    ui.header("Manager Task Queue")
    ui.console.print()
    ui.console.print("Queue work for the org manager specialist.")
    ui.console.print("[dim]Per-project work belongs to a pod — see 'docket pod <project>'.[/dim]")
    ui.console.print()
    ui.console.print("[bold]Task Delegation:[/bold]")
    ui.console.print('  docket team delegate "<task>"                 Add task (status: pending)')
    ui.console.print('  docket team delegate --priority high "<task>" High-priority task')
    ui.console.print("  docket team queue                             Show active tasks")
    ui.console.print("  docket team queue --all                       Include done + cancelled")
    ui.console.print("  docket team start <task-id>                   pending → in_progress")
    ui.console.print("  docket team done <task-id>                    pending/in_progress → done")
    ui.console.print(
        "  docket team cancel <task-id>                  pending/in_progress → cancelled"
    )
    ui.console.print()


def _task_list_path() -> Path:
    return _cfg.OPENCLAW_DIR / "workspaces" / "manager" / "TASK_LIST.json"


def _ensure_task_list() -> None:
    mgr_ws = _cfg.OPENCLAW_DIR / "workspaces" / "manager"
    if not mgr_ws.is_dir():
        ui.error("Manager agent not initialized. Run: docket install")
        raise typer.Exit(1)
    path = _task_list_path()
    if not path.is_file():
        path.write_text(_json.dumps({"tasks": []}, indent=2), encoding="utf-8")
        path.chmod(0o600)


def _atomic_write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _team_delegate(extra: list[str]) -> None:
    import datetime as _dt

    priority = "normal"
    rest: list[str] = []
    i = 0
    while i < len(extra):
        if extra[i] in ("--priority", "-p") and i + 1 < len(extra):
            priority = extra[i + 1]
            i += 2
        else:
            rest.append(extra[i])
            i += 1

    description = rest[0] if rest else ""
    if not description:
        ui.error('Usage: docket team delegate [--priority high|normal|low] "<task description>"')
        raise typer.Exit(1)

    if priority not in ("high", "normal", "low"):
        ui.error(f"Invalid priority '{priority}'. Use: high | normal | low")
        raise typer.Exit(1)

    if len(description) > 500:
        ui.error(f"Description too long ({len(description)} chars). Limit: 500.")
        raise typer.Exit(1)

    _ensure_task_list()
    path = _task_list_path()

    import time as _time

    task_id = f"task-{int(_time.time() * 1000)}"
    created = _dt.datetime.now().astimezone().isoformat()

    data: dict[str, Any] = _json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("tasks", []).append(
        {
            "id": task_id,
            "description": description,
            "priority": priority,
            "created": created,
            "startedAt": None,
            "completedAt": None,
            "status": "pending",
            "source": "operator",
        }
    )
    _atomic_write_json(path, data)

    queue_count = sum(
        1 for t in data.get("tasks", []) if t.get("status") in ("pending", "in_progress")
    )
    ui.success(f"Task queued: [{task_id}] {description}")
    ui.console.print(f"  Priority: {priority}")
    ui.console.print(f"  Queue: {queue_count} task(s) pending")
    ui.console.print()
    ui.info("View queue: docket team queue")


def _team_queue(extra: list[str]) -> None:
    show_all = "--all" in extra or "-a" in extra
    _ensure_task_list()
    path = _task_list_path()

    ui.header("Manager Task Queue")
    ui.console.print()

    tasks: list[dict[str, Any]] = _json.loads(path.read_text(encoding="utf-8")).get("tasks", [])
    pri_order = {"high": 0, "normal": 1, "low": 2}

    active = [t for t in tasks if t.get("status") in ("pending", "in_progress")]
    done = [t for t in tasks if t.get("status") == "done"]
    cancelled = [t for t in tasks if t.get("status") == "cancelled"]

    if not active:
        ui.console.print("  No active tasks.")
    else:
        active.sort(
            key=lambda t: (
                0 if t["status"] == "in_progress" else 1,
                pri_order.get(t.get("priority", "normal"), 1),
            )
        )
        ui.console.print(f"  {'ID':<16}  {'PRI':<8}  {'CREATED':<22}  DESCRIPTION")
        ui.console.print("  " + "─" * 80)
        for t in active:
            tid = t.get("id", "?")[:14]
            pri = t.get("priority", "normal")
            cdate = (t.get("created", "?")[:19]).replace("T", " ")
            desc = t.get("description", "")
            prefix = "▶ " if t["status"] == "in_progress" else "  "
            ui.console.print(f"  {prefix.strip()}{tid:<16}  {pri:<8}  {cdate:<22}  {desc}")

    ui.console.print()
    pending_count = sum(1 for t in active if t["status"] == "pending")
    in_prog_count = sum(1 for t in active if t["status"] == "in_progress")
    summary = f"  Pending: {pending_count}   In progress: {in_prog_count}   Done: {len(done)}"
    if cancelled:
        summary += f"   Cancelled: {len(cancelled)}"
    ui.console.print(summary)

    if show_all and (done or cancelled):
        ui.console.print()
        ui.console.print(f"  {'ID':<16}  {'STATUS':<12}  {'COMPLETED':<22}  DESCRIPTION")
        ui.console.print("  " + "─" * 80)
        for t in done + cancelled:
            tid = t.get("id", "?")[:14]
            st = t.get("status", "?")
            cdate = (t.get("completedAt") or t.get("created", "?"))[:19].replace("T", " ")
            desc = t.get("description", "")
            ui.console.print(f"  {tid:<16}  {st:<12}  {cdate:<22}  {desc}")

    ui.console.print()
    ui.info(
        "Mark done: docket team done <id>  |  Start: docket team start <id>  |  Cancel: docket team cancel <id>"
    )
    if not show_all:
        ui.dim("  Show completed/cancelled: docket team queue --all")


_TRANSITION_ALLOWED: dict[str, set[str]] = {
    "in_progress": {"pending"},
    "done": {"pending", "in_progress"},
    "cancelled": {"pending", "in_progress"},
}


def _team_transition(new_state: str, extra: list[str]) -> None:
    import datetime as _dt

    task_id = extra[0] if extra else ""
    if not task_id:
        ui.error(f"Usage: docket team {new_state} <task-id>")
        raise typer.Exit(1)

    _ensure_task_list()
    path = _task_list_path()

    data: dict[str, Any] = _json.loads(path.read_text(encoding="utf-8"))
    tasks: list[dict[str, Any]] = data.get("tasks", [])
    now = _dt.datetime.now().astimezone().isoformat()

    found: dict[str, Any] | None = None
    for t in tasks:
        tid = t.get("id", "")
        if tid == task_id or tid.startswith(task_id):
            found = t
            break

    if found is None:
        ui.error(f"Task '{task_id}' not found")
        raise typer.Exit(1)

    cur = found.get("status", "pending")
    if cur not in _TRANSITION_ALLOWED.get(new_state, set()):
        ui.error(f"Cannot move '{task_id}' to {new_state} (current status: {cur})")
        raise typer.Exit(1)

    found["status"] = new_state
    if new_state == "in_progress":
        found["startedAt"] = now
    elif new_state in ("done", "cancelled"):
        found["completedAt"] = now

    _atomic_write_json(path, data)
    ui.success(f"Task → {new_state}: {found.get('description', task_id)}")


@app.command("workflow")
def cmd_workflow(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
    workflow_name: str | None = typer.Argument(None),
) -> None:
    """Manage Lobster YAML pipelines (list/create/show/delete)."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Manage workflows for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    action = sub or "list"
    wf_dir = ws / "workflows"

    try:
        raw = store.read_json(_cfg.meta_path(aid))
        agent_name = str(raw.get("name", aid))
    except Exception:
        agent_name = aid

    if action == "list":
        ui.header(f"Workflows: {agent_name}")
        ui.console.print()
        if not wf_dir.is_dir():
            ui.warn("No workflows directory")
            ui.console.print(f"  Create one: docket workflow {aid} create")
            return
        wfs = sorted(wf_dir.glob("*.lobster.y*ml"))
        if not wfs:
            ui.console.print("  No workflows defined yet")
            ui.console.print()
            ui.console.print("Create a workflow template:")
            ui.console.print(f"  docket workflow {aid} create <workflow-name>")
            return
        ui.console.print("[bold]Defined workflows:[/bold]")
        for wf in wfs:
            wf_name = wf.name
            for ext in (".lobster.yml", ".lobster.yaml"):
                wf_name = wf_name.replace(ext, "")
            try:
                steps = sum(
                    1 for ln in wf.read_text(encoding="utf-8").splitlines() if ln.startswith("  - ")
                )
            except OSError:
                steps = 0
            ui.console.print(f"  [green]●[/green] {wf_name:<24} {steps} steps")
        ui.console.print()
        ui.console.print(f"Run a workflow:  lobster run --workspace {ws} --workflow <name>")
        ui.console.print()

    elif action == "create":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} create <name>")
            raise typer.Exit(1)
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_file = wf_dir / f"{workflow_name}.lobster.yml"
        if wf_file.exists():
            ui.warn(f"Workflow '{workflow_name}' already exists")
            ui.console.print(f"  Edit: docket edit {aid}")
            return
        try:
            raw2 = store.read_json(_cfg.meta_path(aid))
        except Exception:
            raw2 = {}
        stack = str(raw2.get("stack", ""))
        codebase = str(raw2.get("codebase", ""))
        test_cmd = _test_cmd_for_stack(stack)
        template = _workflow_template(workflow_name, agent_name, codebase, test_cmd)
        wf_file.write_text(template, encoding="utf-8")
        wf_file.chmod(0o600)
        ui.success(f"Workflow created: {wf_file}")
        ui.console.print()
        ui.info("Next steps:")
        ui.console.print(f"  1. Edit workflow: $EDITOR {wf_file}")
        ui.console.print(
            f"  2. Run workflow:  lobster run --workspace {ws} --workflow {workflow_name}"
        )
        ui.console.print()

    elif action == "show":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} show <name>")
            raise typer.Exit(1)
        wf_file = wf_dir / f"{workflow_name}.lobster.yml"
        if not wf_file.is_file():
            ui.error(f"Workflow '{workflow_name}' not found")
            raise typer.Exit(1)
        ui.header(f"Workflow: {workflow_name}")
        ui.console.print()
        ui.console.print(wf_file.read_text(encoding="utf-8"))
        ui.console.print()

    elif action == "validate":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} validate <name>")
            raise typer.Exit(1)
        wf_path = _resolve_workflow_file(wf_dir, workflow_name)
        if wf_path is None:
            ui.error(f"Workflow '{workflow_name}' not found")
            raise typer.Exit(1)
        from docket.core.lobster import validate_lobster

        text = wf_path.read_text(encoding="utf-8")
        errors = validate_lobster(text)
        if errors:
            ui.error(f"Workflow '{workflow_name}' is invalid:")
            for e in errors:
                ui.console.print(f"  [red]✗[/red] {e}")
            raise typer.Exit(1)
        ui.success(f"Workflow '{workflow_name}' is valid")

    elif action in ("plan", "dry-run"):
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} plan <name>")
            raise typer.Exit(1)
        wf_path = _resolve_workflow_file(wf_dir, workflow_name)
        if wf_path is None:
            ui.error(f"Workflow '{workflow_name}' not found")
            raise typer.Exit(1)
        from docket.core.lobster import plan_lobster

        text = wf_path.read_text(encoding="utf-8")
        plan, errors = plan_lobster(text, workflow_name)
        if errors:
            ui.error(f"Workflow '{workflow_name}' is invalid:")
            for e in errors:
                ui.console.print(f"  [red]✗[/red] {e}")
            raise typer.Exit(1)
        ui.console.print(plan)

    elif action == "delete":
        if not workflow_name:
            ui.error(f"Workflow name required.  Usage: docket workflow {aid} delete <name>")
            raise typer.Exit(1)
        wf_file = wf_dir / f"{workflow_name}.lobster.yml"
        if not wf_file.is_file():
            ui.error(f"Workflow '{workflow_name}' not found")
            raise typer.Exit(1)
        if sys.stdin.isatty():
            answer = input(f"Delete workflow '{workflow_name}'? [y/N]: ").strip().lower()
            if answer != "y":
                ui.warn("Aborted.")
                return
        wf_file.unlink()
        ui.success(f"Workflow '{workflow_name}' deleted")

    else:
        ui.error(f"Unknown action '{action}'.  Use: list, create, show, validate, plan, or delete")
        raise typer.Exit(1)


def _resolve_workflow_file(wf_dir: Path, name: str) -> Path | None:
    """Return the workflow file for ``name``, trying both .yml and .yaml extensions."""
    for ext in (".lobster.yml", ".lobster.yaml"):
        p = wf_dir / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def _test_cmd_for_stack(stack: str) -> str:
    """Return a sensible default test command for a detected stack."""
    import re as _re

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


def _workflow_template(name: str, agent_name: str, codebase: str, test_cmd: str) -> str:
    return f"""\
# Lobster Workflow: {name}
# Project: {agent_name}
#
# Deterministic pipeline — zero tokens for plumbing
# Only calls LLM for creative work

name: {name}
description: "Automated workflow for {agent_name}"

steps:
  - id: check-status
    type: shell
    command: |
      cd {codebase}
      git status --short

  - id: run-tests
    type: shell
    command: |
      cd {codebase}
      {test_cmd}
    continueOnError: false

  - id: llm-analysis
    type: llm
    prompt: |
      Analyze the test results and codebase state.
      Provide a brief summary and suggest next steps.
    approval: required
    # Pauses here and sends Telegram notification

  - id: apply-changes
    type: shell
    command: |
      cd {codebase}
      # Apply any changes suggested by LLM
      echo "Changes applied"

  - id: verify
    type: shell
    command: |
      cd {codebase}
      {test_cmd}

outputs:
  - testResults
  - analysis

notifications:
  onComplete: telegram
  onError: telegram
"""


@app.command("logs")
def cmd_logs(agent_id: str | None = typer.Argument(None)) -> None:
    """View memory logs and gateway entries."""
    import datetime as _dt

    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("View logs for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    try:
        raw = store.read_json(_cfg.meta_path(aid))
        name = str(raw.get("name", aid))
    except Exception:
        name = aid

    ui.header(f"Logs: {name} ({aid})")

    mem_dir = ws / "memory"
    mem_files = sorted(mem_dir.glob("*.md")) if mem_dir.is_dir() else []
    ui.console.print()
    if mem_files:
        latest = mem_files[-1]
        ui.console.print(f"[bold]Latest memory log:[/bold] {latest.name}")
        try:
            lines = latest.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for ln in lines[:40]:
            ui.console.print(f"  {ln}")
        if len(lines) > 40:
            ui.console.print(f"  [dim]... ({len(lines) - 40} more lines)[/dim]")
    else:
        ui.console.print("  [dim]No memory logs yet.[/dim]")

    tg_peer = _oc.get_binding(aid)
    if tg_peer:
        today = _dt.date.today().strftime("%Y-%m-%d")
        log_file = _cfg.LOG_DIR / f"openclaw-{today}.log"
        if log_file.is_file():
            try:
                all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                all_lines = []
            matched = [ln for ln in all_lines if tg_peer in ln]
            ui.console.print()
            ui.console.print(
                f"[bold]Gateway log:[/bold] {len(matched)} entries today for group {tg_peer}"
            )
            for ln in matched[-10:]:
                ui.console.print(f"  {ln}")
            if len(matched) > 10:
                ui.console.print(f"  [dim]... ({len(matched) - 10} more entries)[/dim]")
    ui.console.print()


@app.command("edit")
def cmd_edit(agent_id: str | None = typer.Argument(None)) -> None:
    """Open workspace files in $EDITOR."""
    import shlex as _shlex
    import subprocess as _sub

    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Edit workspace for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    # Resolve display name from IDENTITY.md or SOUL.md (specialists have IDENTITY.md)
    name = aid
    for candidate in [ws / "IDENTITY.md", ws / "SOUL.md"]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.startswith("# "):
                    name = line[2:].strip()
                    break
            break

    _WORKSPACE_FILES = ["SOUL.md", "IDENTITY.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md"]
    files = [ws / f for f in _WORKSPACE_FILES if (ws / f).is_file()]

    ui.header(f"Edit: {name} ({aid})")
    ui.console.print()

    if not files:
        ui.warn("No workspace files found.")
        raise typer.Exit(0)

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    editor_parts = _shlex.split(editor)

    ui.console.print(f"Opening files in {editor_parts[0]}:")
    for f in files:
        ui.console.print(f"  {f.name}")
    ui.console.print()

    try:
        _sub.run(editor_parts + [str(f) for f in files])
    except FileNotFoundError:
        ui.error(f"Editor '{editor_parts[0]}' not found. Set $EDITOR or install nano.")
        raise typer.Exit(1) from None

    ui.success("Edits saved.")
    ui.console.print()
    ui.info("Restart gateway to apply changes: systemctl --user restart openclaw-gateway.service")


@app.command("cost")
def cmd_cost(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
    history: bool = typer.Option(False, "--history"),
    days: int = typer.Option(0, "--days"),
) -> None:
    """Token usage and cost breakdown."""
    if history:
        _cmd_cost_history(agent_id, days, json_out)
        return
    if json_out:
        _cmd_cost_json()
        return
    if agent_id:
        _cmd_cost_single(agent_id)
    else:
        _cmd_cost_all()


def _cmd_cost_json() -> None:
    ids = project_ids()
    agents_out = []
    total = 0.0
    for pid in ids:
        raw = store.read_json(_cfg.meta_path(pid))
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        budget_raw = raw.get("budgetUsd")
        totals: CostTotals = aggregate_cost(pid)
        cost = totals.cost_usd
        total += cost
        budget_val = float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
        agents_out.append(
            {
                "id": pid,
                "model": model,
                "input": totals.input_tokens,
                "output": totals.output_tokens,
                "costUsd": round(cost, 6),
                "pricingKnown": True,
                "turns": totals.turns,
                "budgetUsd": budget_val,
            }
        )
    print(_json.dumps({"agents": agents_out, "totalUsd": round(total, 6)}, indent=2))


def _cmd_cost_single(agent_id: str) -> None:
    ws = _cfg.workspace_dir(agent_id)
    if not ws.is_dir():
        ui.error(f"Project '{agent_id}' not found.")
        raise typer.Exit(1)
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    ui.header(f"Token Usage: {name} ({agent_id})")
    ui.console.print()
    _render_agent_cost(agent_id)
    ui.console.print()


def _cmd_cost_all() -> None:
    ids = project_ids()
    if not ids:
        ui.warn("No project agents found.")
        return

    ui.header("Token Usage — All Project Agents")
    ui.console.print()

    hdr = (
        f"{'AGENT':<16} {'MODEL':<10} {'INPUT':>10} {'OUTPUT':>10}"
        f" {'COST (USD)':>12}  {'SOURCE':<8}  {'BUDGET':<12}"
    )
    ui.console.print(f"[bold]{hdr}[/bold]")
    ui.console.print("─" * 90)

    total_cost = 0.0
    runaway: list[str] = []

    for pid in ids:
        raw = store.read_json(_cfg.meta_path(pid))
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        src = model_source(pid)
        budget_raw = raw.get("budgetUsd")
        totals = aggregate_cost(pid)

        model_short = model.split("/")[-1] if "/" in model else model
        cost_str = f"${totals.cost_usd:.4f}"

        budget_col = "—"
        if budget_raw and str(budget_raw) not in ("", "0"):
            bval = float(budget_raw)
            pct = int(totals.cost_usd / bval * 100) if bval > 0 else 0
            # Display the raw budget value (e.g. "10", "10.50") exactly as Bash
            # does — not a forced .2f — so "$10 (0%)" matches the contract.
            budget_col = f"${budget_raw} ({pct}%)"

        ui.console.print(
            f"{pid:<16} {model_short:<10} {si_format(totals.input_tokens):>10}"
            f" {si_format(totals.output_tokens):>10} {cost_str:>12}"
            f"  {src:<8}  {budget_col:<12}"
        )

        total_cost += totals.cost_usd

        runaway_turns = int(os.environ.get("RUNAWAY_TURNS_THRESHOLD", "200"))
        runaway_cost_t = float(os.environ.get("RUNAWAY_COST_THRESHOLD", "20"))
        if totals.turns > runaway_turns or totals.cost_usd >= runaway_cost_t:
            runaway.append(f"{pid} ({totals.turns} turns, ${totals.cost_usd:.4f})")

    ui.console.print()
    total_amount = f"${total_cost:.4f}"
    ui.console.print(f"[bold]{'Total:':>69} {total_amount:>12}[/bold]")

    if runaway:
        ui.console.print()
        for r in runaway:
            ui.warn(f"  Runaway session: {r}")

    ui.console.print()
    ui.dim("  Recorded spend from session data in ~/.openclaw/agents/*/sessions/*.jsonl")
    ui.dim(
        f"  Comparative estimates use a price snapshot (as of {_mp.MODEL_PRICING_AS_OF})"
        " — see: docket models"
    )
    ui.console.print()


def _render_agent_cost(agent_id: str) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    model = str(raw.get("model", _cfg.DEFAULT_MODEL))
    src = model_source(agent_id)
    budget_raw = raw.get("budgetUsd")
    totals = aggregate_cost(agent_id)

    ui.console.print(f"  [bold]{'Model:':<16}[/bold] {model}")
    ui.console.print(f"  [bold]{'Source:':<16}[/bold] {src}")
    ui.console.print(f"  [bold]{'Turns:':<16}[/bold] {totals.turns}")
    ui.console.print()
    ui.console.print(f"  [bold]{'Input:':<16}[/bold] {totals.input_tokens:,} tokens")
    ui.console.print(f"  [bold]{'Output:':<16}[/bold] {totals.output_tokens:,} tokens")
    ui.console.print(f"  [bold]{'Cache read:':<16}[/bold] {totals.cache_read:,} tokens")
    ui.console.print(f"  [bold]{'Cache write:':<16}[/bold] {totals.cache_write:,} tokens")
    ui.console.print()

    if totals.cost_usd > 0:
        ui.console.print(
            f"  [bold]{'Total cost:':<16}[/bold] [green]${totals.cost_usd:.4f}[/green]"
            " [dim](recorded)[/dim]"
        )
    else:
        ui.console.print(
            f"  [bold]{'Total cost:':<16}[/bold] "
            "[dim]none recorded by the daemon for these sessions[/dim]"
        )

    if budget_raw and str(budget_raw) not in ("", "0"):
        bval = float(budget_raw)
        pct = int(totals.cost_usd / bval * 100) if bval > 0 else 0
        color = "green"
        if pct >= 80:
            color = "yellow"
        if pct >= 100:
            color = "red"
        ui.console.print(
            f"  [bold]{'Budget:':<16}[/bold] [{color}]{pct}%[/{color}] of ${bval:.2f} cap"
        )

    runaway_turns = int(os.environ.get("RUNAWAY_TURNS_THRESHOLD", "200"))
    runaway_cost_t = float(os.environ.get("RUNAWAY_COST_THRESHOLD", "20"))
    if totals.turns > runaway_turns:
        ui.console.print()
        ui.warn(f"  High turn count: {totals.turns} turns (threshold: {runaway_turns})")
    if totals.cost_usd >= runaway_cost_t:
        ui.console.print()
        ui.warn(
            f"  High cost session: ${totals.cost_usd:.4f} exceeds ${runaway_cost_t:.0f} threshold"
        )


def _cmd_cost_history(
    agent_id: str | None,
    days: int,
    json_out: bool,
) -> None:
    if agent_id:
        ws = _cfg.workspace_dir(agent_id)
        if not ws.is_dir():
            ui.error(f"Project '{agent_id}' not found.")
            raise typer.Exit(1)
        agent_list = [agent_id]
    else:
        agent_list = project_ids()

    agg: dict[str, DayRecord] = {}
    for aid in agent_list:
        for rec in cost_history(aid):
            if rec.date in agg:
                ex = agg[rec.date]
                agg[rec.date] = DayRecord(
                    date=rec.date,
                    turns=ex.turns + rec.turns,
                    input_tokens=ex.input_tokens + rec.input_tokens,
                    output_tokens=ex.output_tokens + rec.output_tokens,
                    cost_usd=round(ex.cost_usd + rec.cost_usd, 6),
                )
            else:
                agg[rec.date] = rec

    ordered = sorted(agg.values(), key=lambda r: r.date)
    if days > 0:
        ordered = ordered[-days:]

    scope = agent_id or "all agents"

    if json_out:
        rows = [
            {
                "date": r.date,
                "turns": r.turns,
                "input": r.input_tokens,
                "output": r.output_tokens,
                "costUsd": r.cost_usd,
            }
            for r in ordered
        ]
        print(_json.dumps({"scope": scope, "history": rows}, indent=2))
        return

    ui.header(f"Cost history — {scope}")
    ui.console.print()

    if not ordered:
        ui.console.print("  (no dated session data yet)")
        ui.console.print()
        return

    ui.console.print(f"  {'DATE':<12} {'TURNS':>7} {'INPUT':>12} {'OUTPUT':>12} {'COST (USD)':>12}")
    costs = [r.cost_usd for r in ordered]
    for i, r in enumerate(ordered):
        flag = ""
        if i >= 3:
            avg = sum(costs[i - 3 : i]) / 3
            if avg > 0 and r.cost_usd > 2 * avg:
                flag = "  <- spike (>2x trailing avg)"
        ui.console.print(
            f"  {r.date:<12} {r.turns:>7} {r.input_tokens:>12}"
            f" {r.output_tokens:>12} {r.cost_usd:>12.4f}{flag}"
        )
    ui.console.print(f"  {'':12} {'':>7} {'':>12} {'':>12} {sum(costs):>12.4f}  total")
    ui.console.print()


@app.command("doctor")
def cmd_doctor(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable health probe"),
    fix: bool = typer.Option(False, "--fix", help="Apply auto-fixes for detected drift"),
) -> None:
    """System-wide health check with auto-fix."""
    from docket.cli._doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_out, do_fix=fix))


@app.command(
    "gates",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_gates(ctx: typer.Context) -> None:
    """Manage tool-approval security gates."""
    from docket.cli._gates import run_gates

    args = list(ctx.args)
    sub = args[0] if args else None
    force = "--force" in args
    rest = [a for a in args[1:] if a != "--force"]
    want = rest[0] if rest else "on"
    raise typer.Exit(run_gates(sub, want=want, force=force))


@app.command("audit")
def cmd_audit(
    arg: str | None = typer.Argument(None, help="Last-N count, or --json"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show audit log."""
    from docket.cli._audit import run_audit

    limit: int | None = None
    if arg == "--json":
        json_out = True
    elif arg and arg.isdigit():
        limit = int(arg)
    raise typer.Exit(run_audit(limit=limit, json_out=json_out))


@app.command("eval")
def cmd_eval(
    live: bool = typer.Option(False, "--live", help="Run live golden-task evals"),
    tier: str = typer.Option("standard", "--tier", help="Model tier"),
    role: str = typer.Option("", "--role", help="Restrict to one role"),
    recommend: bool = typer.Option(False, "--recommend", help="Emit tier recommendations"),
) -> None:
    """Run non-blocking specialist-role evals."""
    from docket.cli._eval import run_eval

    raise typer.Exit(run_eval(live=live, tier=tier, role=role, recommend=recommend))


@app.command("snapshot")
def cmd_snapshot(
    output: str | None = typer.Option(None, "--output", "-o", help="Write JSON to file"),
) -> None:
    """Export system state snapshot as JSON."""
    import datetime as _dt

    gw = "active" if gateway_active() else "inactive"

    try:
        raw_cfg: dict[str, Any] = store.read_json(_cfg.CONFIG_FILE)
        channels = list(raw_cfg.get("channels", {}).keys())
    except Exception:
        channels = []

    oc = _oc.load_config()
    registered_ids = {a.id for a in _oc.list_agents(oc)}

    def _agent_bindings(aid: str) -> list[dict[str, Any]]:
        return [
            {"channel": b.match.channel, "peerId": b.match.peer.id}
            for b in oc.bindings
            if b.agent_id == aid
        ]

    agents_out: list[dict[str, Any]] = []
    total_cost = 0.0

    for pid in project_ids():
        try:
            raw = store.read_json(_cfg.meta_path(pid))
        except Exception:
            raw = {}
        cost = aggregate_cost(pid).cost_usd
        total_cost += cost
        agents_out.append(
            {
                "id": pid,
                "name": str(raw.get("name", pid)),
                "type": str(raw.get("type", "repo")),
                "kind": "project",
                "model": str(raw.get("model", _cfg.DEFAULT_MODEL)),
                "registered": pid in registered_ids,
                "bindings": _agent_bindings(pid),
                "lastActivity": last_activity(pid),
                "costUsd": round(cost, 6),
            }
        )

    for spec in _cfg.SPECIALIST_ORDER:
        ws = _cfg.OPENCLAW_DIR / "workspaces" / spec
        if not ws.is_dir():
            continue
        try:
            raw = store.read_json(ws / _cfg.META_FILE)
        except Exception:
            raw = {}
        cost = aggregate_cost(spec).cost_usd
        total_cost += cost
        agents_out.append(
            {
                "id": spec,
                "name": str(raw.get("name", spec)),
                "type": "specialist",
                "kind": "specialist",
                "model": str(raw.get("model", "")),
                "registered": spec in registered_ids,
                "bindings": _agent_bindings(spec),
                "lastActivity": last_activity(spec),
                "costUsd": round(cost, 6),
            }
        )

    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "timestamp": timestamp,
        "gateway": gw,
        "channels": channels,
        "agents": agents_out,
        "totalCostUsd": round(total_cost, 6),
    }

    out = _json.dumps(result, indent=2)
    if output:
        Path(output).write_text(out + "\n", encoding="utf-8")
        ui.success(f"Snapshot written to {output}")
    else:
        print(out)


@app.command("serve")
def cmd_serve(
    port: int = typer.Option(7331, "--port", "-p", help="Port to bind (default 7331)"),
    interval: int = typer.Option(
        30, "--interval", "-i", help="Sweep refresh interval in seconds (default 30)"
    ),
    dispatch: bool = typer.Option(
        False,
        "--dispatch",
        help="Also drive each pod's queued tasks through its pipeline (real, costed agent turns)",
    ),
) -> None:
    """Local HTTP endpoints: /status.json /metrics /health.

    With --dispatch, each refresh also runs every pod's queue through the
    Lead→Implementer→Reviewer→Tester pipeline. Each hop is a real agent
    turn and is budget-gated; leave it off for a read-only monitor.
    """
    from docket.serve import run_serve

    run_serve(port=port, interval=interval, dispatch=dispatch)


@app.command("completions")
def cmd_completions(shell: str | None = typer.Argument(None)) -> None:
    """Shell completion helpers."""
    from docket.cli._completions import run_completions

    raise typer.Exit(run_completions(shell))


@app.command(
    "trace",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_trace(ctx: typer.Context) -> None:
    """View agent execution traces."""
    from docket.cli._trace import run_trace

    args = list(ctx.args)
    since: str | None = None
    pos: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--since":
            since = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        pos.append(args[i])
        i += 1
    sub = pos[0] if pos else None
    target = pos[1] if len(pos) > 1 else None
    raise typer.Exit(run_trace(sub, target, since))


@app.command("metrics")
def cmd_metrics(
    role: str = typer.Option("", "--role", "-r", help="Restrict to one role"),
    project: str = typer.Option("", "--project", "-p", help="Restrict to one project"),
    window: int | None = typer.Option(None, "--window", "-w", help="Window in days"),
) -> None:
    """Show session success-rate and drift metrics."""
    from docket.cli._metrics import run_metrics

    raise typer.Exit(run_metrics(role=role, project=project, window=window))


@app.command(
    "policies",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_policies(ctx: typer.Context) -> None:
    """Manage tool-approval policies."""
    from docket.cli._policies import run_policies

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_policies(sub, args=args[1:]))


@app.command("approve")
def cmd_approve(approval_id: str | None = typer.Argument(None)) -> None:
    """Approve a pending tool-action."""
    from docket.cli._approve import run_approve

    raise typer.Exit(run_approve(approval_id))


@app.command("deny")
def cmd_deny(approval_id: str | None = typer.Argument(None)) -> None:
    """Deny a pending tool-action."""
    from docket.cli._deny import run_deny

    raise typer.Exit(run_deny(approval_id))


@app.command("help")
def cmd_help(topic: str | None = typer.Argument(None)) -> None:
    """Show help."""
    from docket.cli._help import run_help

    raise typer.Exit(run_help())


# Invocation: python -m docket _json <verb> [arg ...]
# Exit codes: 0 = success, 1 = error, 2 = unknown verb.
@app.command(
    "_json",
    hidden=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_json(ctx: typer.Context) -> None:
    """Internal: JSON store bridge for the Bash layer."""
    argv = ctx.args
    if not argv:
        print("_json: verb required", file=sys.stderr)
        raise typer.Exit(2)

    verb = argv[0]
    a = argv[1:]

    def _die(msg: str) -> None:
        print(f"_json {verb}: {msg}", file=sys.stderr)
        raise typer.Exit(1)

    try:
        if verb == "meta-get":
            if len(a) < 2:
                _die("usage: meta-get <id> <field> [default]")
            print(_oc.meta_get(a[0], a[1], a[2] if len(a) > 2 else ""))

        elif verb == "meta-set":
            if len(a) < 3:
                _die("usage: meta-set <id> <field> <value>")
            _oc.meta_set(a[0], a[1], a[2])

        elif verb == "oc-get":
            if not a:
                _die("usage: oc-get <dotpath> [default]")
            print(_oc.oc_get_path(a[0], a[1] if len(a) > 1 else ""))

        elif verb == "oc-set":
            if len(a) < 2:
                _die("usage: oc-set <dotpath> <json-value>")
            _oc.oc_set_path(a[0], a[1])

        elif verb == "agent-registered":
            if not a:
                _die("usage: agent-registered <id>")
            if _oc.agent_registered(a[0]):
                print("1")
            else:
                print("0")
                raise typer.Exit(1)

        elif verb == "agent-add":
            if len(a) < 2:
                _die("usage: agent-add <id> <model> [session_key] [project_key]")
            _oc.add_agent(a[0], a[1], a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else "")

        elif verb == "agent-remove":
            if not a:
                _die("usage: agent-remove <id>")
            _oc.remove_agent(a[0])

        elif verb == "model-set-both":
            if len(a) < 2:
                _die("usage: model-set-both <id> <model>")
            _oc.set_model_both(a[0], a[1])

        elif verb == "binding-get":
            if not a:
                _die("usage: binding-get <id> [channel]")
            print(_oc.get_binding(a[0], a[1] if len(a) > 1 else "telegram"))

        elif verb == "binding-upsert":
            if len(a) < 2:
                _die("usage: binding-upsert <id> <peer_id> [channel] [peer_kind]")
            _oc.upsert_binding(
                a[0],
                a[1],
                a[2] if len(a) > 2 else "telegram",
                a[3] if len(a) > 3 else "group",
            )

        elif verb == "binding-remove":
            if not a:
                _die("usage: binding-remove <id> [channel]")
            _oc.remove_binding(a[0], a[1] if len(a) > 1 else None)

        elif verb == "gates-get":
            print(_json.dumps(_oc.get_gates_enabled()))

        elif verb == "gates-set":
            if not a:
                _die("usage: gates-set <true|false>")
            _oc.set_gates_enabled(a[0].lower() in ("1", "true", "yes"))

        elif verb == "isolation-get":
            print(_json.dumps(_oc.get_isolation_enabled()))

        elif verb == "isolation-set":
            if not a:
                _die("usage: isolation-set <true|false>")
            _oc.set_isolation_enabled(a[0].lower() in ("1", "true", "yes"))

        elif verb == "default-model-get":
            print(_oc.get_default_model())

        elif verb == "default-model-set":
            if not a:
                _die("usage: default-model-set <model>")
            _oc.set_default_model(a[0])

        elif verb == "auth-summary":
            agent = a[0] if a else "main"
            for p in _oc.auth_profiles_summary(agent):
                state = f"disabled:{p.disabled_reason}" if p.disabled else "ok"
                print(f"{p.id}|{p.provider}|{p.type}|{state}")

        elif verb == "auth-has-usable":
            agent = a[0] if a else "main"
            if not _oc.has_usable_profile(agent):
                raise typer.Exit(1)

        else:
            print(f"_json: unknown verb '{verb}'", file=sys.stderr)
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as exc:
        print(f"_json {verb}: {exc}", file=sys.stderr)
        raise typer.Exit(1) from exc
