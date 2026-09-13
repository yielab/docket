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
import re as _re
import sys
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket import ui
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import pod as _pod_core
from docket.core.audit import audit_log
from docket.core.utils import (
    aggregate_cost,
    gateway_active,
    last_activity,
    project_ids,
)
from docket.edges import store

app = typer.Typer(
    name="docket",
    help="docket project agent manager",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)


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
        cand = Path(__file__).resolve().parents[3] / "VERSION"
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
        ui.console.print("[bold]docket[/bold] — project agent manager")
        ui.console.print("  docket init          initialize this project (Lead + Implementer)")
        ui.console.print("  docket status        show the current project's status")
        ui.console.print("  docket status --all  show global status by project")
        ui.console.print("  docket add <role>    add an agent to the current pod")
        ui.console.print("  docket doctor        check workstation-wide health")
        ui.console.print("  docket help          show the full command reference")


@app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List all project agents.

    Shows every registered agent -- pod members for each project and the shared
    org specialists (manager, knowledge, security) -- with role/pod, model and
    its source, Telegram binding, and last activity. Telegram status reflects
    docket's own channel bindings (`~/.docket/fleet.json`); the session column
    shows the agent's current project key. `--json` emits the same listing as
    one JSON document instead of the Rich table, for scripting."""
    if json_out:
        _cmd_list_json()
    else:
        _cmd_list_human()


@app.command("status")
def cmd_status(
    all_projects: bool = typer.Option(False, "--all", help="Show every project"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show current-project status, or every project with --all.

    The current-project view shows state without mixing in the global agent
    inventory or workstation health: configured path, readiness, pod roles,
    and task counts. `docket list` remains the detailed global agent
    inventory; `docket doctor` remains the global technical health check."""
    from docket.cli._status import run_status

    raise typer.Exit(run_status(all_projects=all_projects, json_out=json_out))


def _cmd_list_json() -> None:
    fleet = _fleet.load_fleet()
    registered = {a.id for a in _fleet.list_agents(fleet)}
    tg_bindings: dict[str, str | None] = {}
    for b in fleet.bindings:
        if b.channel == "telegram":
            tg_bindings[b.agent_id] = b.peer_id or None

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
        ui.console.print("Run: docket init")
        raise typer.Exit(0)

    fleet = _fleet.load_fleet()
    registered_ids = {a.id for a in _fleet.list_agents(fleet)}
    tg_bindings: dict[str, str] = {}
    for b in fleet.bindings:
        if b.channel == "telegram":
            tg_bindings[b.agent_id] = b.peer_id

    total_agents = len(fleet.agents)
    tg_binding_count = sum(1 for b in fleet.bindings if b.channel == "telegram")

    ui.console.print()
    ui.console.print(
        f"  [bold]docket[/bold]  {total_agents} agent(s)  {tg_binding_count} channel binding(s)"
        f"  [dim]│[/dim]  v{_resolve_version()}"
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
        role = str(raw.get("role", ""))
        pod_name = str(raw.get("pod", "")) or (_pod_mod.pod_of(aid) or "")
        descriptor = f"{role} · pod:{pod_name}" if role and pod_name else "repo"
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
            "  3) docket wire <id> and follow the on-screen steps"
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
        spec_ws = _cfg.WORKSPACES_DIR / spec
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
    """Add role agents to an existing project pod. Never creates a project.

    Pod inferred from the current directory, or given explicitly with
    `--project <pod>` when running outside the project's configured
    `codebase`/`workDir`. Docket chooses the most-specific registered pod
    containing the cwd and fails clearly when there is no match or the result
    is ambiguous.

    Flags (parsed from the extra CLI args, not fixed Typer options):
      --project <pod>     explicit pod, instead of directory inference
      --count N           add N indexed copies of the role
      --verify "<cmd>"    set the new Implementer's mechanical verify gate"""
    from docket.cli._agents import run_add

    raise typer.Exit(run_add(list(ctx.args)))


@app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_init(ctx: typer.Context) -> None:
    """Initialize the current project with its minimum isolated pod.

    Creates a new project pod -- an isolated team of project-scoped agents
    that owns one codebase. The default pod is lean: a Lead + an Implementer.
    The first invocation also creates docket's shared workstation foundation
    (fleet registry, org specialists, policies, default gates) -- there is no
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
                             shared working directory instead (auto-provisioned
                             under `~/.docket/workspaces/pods/<project>/` if
                             omitted) -- no stack is auto-detected. Unknown
                             name errors with "unknown blueprint 'X'; valid
                             blueprints: software, research, content, ops,
                             agentic-product" and exits 1 before any prompt.
                             Only the five built-ins exist today -- there is
                             no `docket blueprints add <file>` to register a
                             custom one. See
                             specs/functional/pod-blueprints.spec.md.
      --codebase <path>,    the codebase path (or, for a workdir-kind
      --path <path>         blueprint, the pod's shared working directory) --
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

    Every project is a repo -- a pod tied to a codebase, defaulting to the cwd
    (or the `path` argument / `--codebase`, in which case you are not
    re-prompted); the project name is suggested from that directory's name."""
    from docket.cli._agents import run_init

    raise typer.Exit(run_init(list(ctx.args)))


@app.command("info")
def cmd_info(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Detailed status of one agent.

    Shows identity, codebase/stack, model and its source, session/project
    keys, creation time, workspace path, and Telegram binding for one agent --
    pulled from `.docket-meta.json`. With no agent id given, uses fzf for
    interactive selection if available, falling back to a numbered picker."""
    from docket.cli._agents import run_info

    raise typer.Exit(run_info(agent_id, json_out))


@app.command("delete")
def cmd_delete(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove a project agent or a whole pod, and optionally its workspace.

    Given a pod id, lists every member and (in an interactive terminal)
    requires typing the exact pod id to confirm, then removes every member's
    registration, binding, conversation-registry entry, workspace/worktree,
    pod runtime directory, durable session history, and traces. The global
    audit record is preserved. Given a legacy flat agent id, separately asks
    whether to also remove its workspace.

    Cannot be undone -- back up first if unsure. Org specialists (manager,
    knowledge, security) cannot be removed this way -- the command errors
    outright rather than deleting a shared, fleet-wide agent. A deleted
    member's git worktree is removed, but its dedicated branch remains in the
    source repository so committed code is not silently destroyed; remove
    that branch separately after reviewing it."""
    from docket.cli._agents import run_delete

    raise typer.Exit(run_delete(agent_id))


def _delete_pod(project: str, members: list[str]) -> int:
    """Tear down every member of a pod. One gateway restart at the end.

    Kept here (rather than in ``cli/_agents.py``, which owns the rest of the
    delete flow) because ``tests/integration/test_pod_provisioning.py`` calls it
    directly as ``docket.cli._delete_pod`` — moving it would be a rename, not
    a mechanical extraction. ``_agents.run_delete`` reaches back for it with a
    deferred import, the same convention used for ``_pick_agent`` et al.
    """
    from docket.cli import _pod

    ui.header(f"Delete pod: {project}  ({len(members)} members)")
    ui.console.print()
    for mid in members:
        role = _fleet.meta_get(mid, "role", "?")
        ui.console.print(f"  - {mid}  ({role})")
    ui.console.print()
    ui.warn(
        "This removes every member's registration, binding, workspace, runtime, session history, "
        "and traces. The audit record is preserved."
    )
    ui.console.print()

    if sys.stdin.isatty():
        confirm = input(f"Type the pod id to confirm deletion [{project}]: ").strip()
        if confirm != project:
            ui.warn("Aborted.")
            return 0

    from docket.core import conversations as _conv

    for mid in members:
        if _fleet.get_binding(mid):
            _fleet.remove_binding(mid)
        _conv.remove_agent_durable(mid)
        ok, msg = _pod.teardown_member(mid)
        if ok:
            ui.success(f"Removed {mid}")
        else:
            ui.warn(f"{mid}: fleet deregistration reported: {msg} (workspace cleaned)")
    # Free pod runtime resources (port range + scratch dir) after all members gone.
    _pod.free_pod_resources(project)
    _pod.purge_pod_history(project, members)

    audit_log("agent.delete", f"{project} pod ({len(members)} members)")
    ui.success(f"Pod '{project}' deleted.")
    return 0


@app.command(
    "maintain",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_maintain(
    ctx: typer.Context,
    agent_id: str | None = typer.Argument(None),
    mode: str | None = typer.Argument(None),
) -> None:
    """Maintain an agent workspace (check/clean/reset/rebuild/sessions/distill).

    Subcommands:
      check (default)  health check and auto-fix -- permissions (700/600),
                        missing workspace files, fleet registration, memory
                        directory, and a per-turn context-footprint estimate
                        (warns if SOUL/AGENTS/TOOLS/HEARTBEAT/MEMORY together
                        exceed the configured token budget)
      clean             clear memory logs only (`memory/*.md`) -- distills
                        first by default (see below)
      reset             clear memory + MEMORY.md + HEARTBEAT.md -- distills
                        first by default
      rebuild           deep rebuild -- regenerate SOUL.md, AGENTS.md,
                        TOOLS.md from `.docket-meta.json`
      sessions          archive large/old session data
      distill           summarize `memory/*.md` into MEMORY.md via one
                        driver-backed turn, then archive the originals under
                        `memory/<archive-dir>/`

    `--no-distill-first` (clean/reset only) skips the automatic pre-delete
    distillation and deletes/clears memory undistilled; `--distill-first` is
    also accepted as a no-op affirmation of the default.

    Memory is never bare-deleted: before clean deletes `memory/*.md`, or reset
    clears memory + HEARTBEAT.md, docket runs one driver-backed turn that
    summarizes pending logs into MEMORY.md and archives the originals -- the
    same work `distill` does standalone. A failed distillation aborts the
    delete outright; nothing is touched. `failure_kind` (`timeout`,
    `daemon_error`, `invalid_output`) tells you whether to just retry or
    whether the model's output needs a closer look (`daemon_error` is the
    failure-kind name's literal value -- a name that predates the daemon's
    removal and now just means "the turn didn't complete cleanly," not a live
    external process). When a reset runs a real distillation, MEMORY.md is
    left freshly distilled rather than immediately cleared again in the same
    breath.

    Preserves identity (`.docket-meta.json`, fleet registration). clean/
    reset/rebuild prompt for confirmation and require a TTY -- a
    non-interactive call is cancelled, not silently applied."""
    from docket.cli._agents import run_maintain

    raise typer.Exit(run_maintain(agent_id, mode, list(ctx.args)))


@app.command(
    "context",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_context(
    ctx: typer.Context,
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Agent context views (show/project) -- read-only.

    There is no separate semantic memory index: docket's own turn loop has no
    `memory_search` tool, so an agent (and this command) reads memory files
    the same way it reads any other file -- `context` is just two dashboards.

    Subcommands:
      show (default)  the last 3 memory-log files (last 5 lines each), active
                      tasks parsed from HEARTBEAT.md, and quick stats
                      (memory-log count, session size from docket's own
                      durable per-session storage, last-active timestamp)
      project         a project-metadata-focused view -- codebase path,
                      stack, model, session key, active tasks, and MEMORY.md
                      section headers

    Both subcommands are read-only and touch only the named agent's own
    workspace. The `search`/`index`/`snapshot`/`compress` subcommands were
    removed: the per-agent index/snapshot/gzip-archive artifacts they wrote
    were read by nothing else in docket (the archive even hid old logs from
    an agent's own read/grep-based recall), and there is no separate semantic
    memory index to replace them with. Use `docket snapshot` for a
    whole-fleet JSON export. `memory`/`mem` are removed top-level commands,
    not aliases of `context`."""
    from docket.cli._context import run_context

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

    raise typer.Exit(run_context(aid, ws, sub, extra))


@app.command("wire")
def cmd_wire(
    agent_id: str | None = typer.Argument(None),
    channel: str = typer.Option(
        "telegram", "--channel", help="Channel to wire (default: telegram)"
    ),
) -> None:
    """Wire or update a channel group binding (Telegram by default).

    Inbound only: the binding authorizes a chat to send /approve, /deny,
    /status and /delegate; docket never messages the group on its own --
    there is no notification on a pending approval and no report when a task
    finishes, you poll with /status.

    With `TELEGRAM_BOT_TOKEN` configured, docket shows a one-time command such
    as `/wire A1B2C3` -- send it in the Telegram group, return to the
    terminal, and press Enter, and docket discovers and binds that group
    automatically. You can paste a numeric group ID instead; manual entry is
    also the fallback when the bot token is missing, Telegram cannot be
    reached, or no matching message is found.

    `--channel <name>` (default telegram) selects which channel to wire; the
    flag exists so additional channels can be added without a breaking
    change to this command's syntax, though Telegram is the only one shipped
    today.

    Updates docket's own fleet registry (`~/.docket/fleet.json`) bindings,
    and seeds an entry in the conversation registry (`docket conversations`).
    The binding is the entire authorization boundary once
    `docket serve --telegram` is running: anyone who can post in that chat
    can act as this agent. Guided discovery reads the matching one-time
    /wire message without advancing the Telegram poller's durable offset or
    processing unrelated messages -- if `docket serve --telegram` is already
    polling, stop it during setup so it does not receive the one-time
    command first."""
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

    name = _fleet.meta_get(aid, "name", aid)
    existing = _fleet.get_binding(aid, channel)

    ui.header(f"Wire {channel.capitalize()}: {name} ({aid})")
    ui.console.print()
    if existing:
        ui.warn(f"Currently wired to: {existing}")

    peer_id = ""
    if channel == "telegram":
        import secrets

        from docket.core import telegram as _telegram

        if _telegram.wire_discovery_configured():
            challenge = secrets.token_hex(3).upper()
            ui.console.print("Easy setup:")
            ui.console.print("  1. Add your Docket bot to the Telegram group.")
            ui.console.print(f"  2. In that group, send: [bold]/wire {challenge}[/bold]")
            ui.console.print("  3. Return here and press Enter.")
            ui.console.print()
            entered = input("Press Enter after sending it, or paste the group ID: ").strip()
            if entered:
                peer_id = entered
            else:
                result = _telegram.discover_wire_groups(challenge)
                if not result.ok:
                    ui.warn(f"Could not check Telegram: {result.error}")
                elif len(result.groups) == 1:
                    group = result.groups[0]
                    peer_id = group.chat_id
                    label = f' "{group.title}"' if group.title else ""
                    ui.success(f"Found Telegram group{label}")
                elif len(result.groups) > 1:
                    ui.console.print("Matching Telegram groups:")
                    for index, group in enumerate(result.groups, 1):
                        label = group.title or group.chat_id
                        ui.console.print(f"  {index}) {label}")
                    raw_pick = input("Choose a group number: ").strip()
                    try:
                        peer_id = result.groups[int(raw_pick) - 1].chat_id
                    except (ValueError, IndexError):
                        ui.warn("Invalid selection; switching to manual entry.")
                else:
                    ui.warn(
                        "No matching group message found. If docket serve --telegram is running,"
                        " stop it, send the shown command again, and rerun docket wire."
                    )
        else:
            ui.warn(
                "Automatic Telegram setup needs a bot token. First run:"
                " docket keys add TELEGRAM_BOT_TOKEN"
            )

    if not peer_id:
        ui.dim(f"Manual fallback: enter the peer/group ID from your {channel} setup.")
        ui.console.print()
        peer_id = input(f"{channel.capitalize()} peer/group ID (or Enter to abort): ").strip()
    if not peer_id:
        ui.warn("Aborted.")
        raise typer.Exit(0)

    _fleet.upsert_binding(aid, peer_id, channel)
    ui.success(f"Binding: {aid} ← {channel} group {peer_id}")
    if channel == "telegram":
        # docket owns its own bot (`docket serve --telegram`, once
        # `docket keys add TELEGRAM_BOT_TOKEN` is set) — this binding is the
        # ENTIRE authorization boundary for it: anyone who can post to this
        # chat can /approve, /deny, /status, or /delegate as '{aid}' the
        # moment the bot is running. There is no second allowlist step.
        ui.dim(
            "  This binding is the whole authorization story: whoever can post in this chat"
            f" can now /approve, /deny, /status, or /delegate for '{aid}' once docket's own"
            " bot is running (docket serve --telegram, with TELEGRAM_BOT_TOKEN configured)."
            " Keep the chat restricted to people who should hold that power."
        )

    # Register the thread in the docket-owned conversation registry so it is
    # tracked/resumable.
    from datetime import UTC, datetime

    from docket.core import conversations as _conv

    _conv.record_durable(
        agent_id=aid, peer_id=peer_id, channel=channel, now=datetime.now(UTC).isoformat()
    )

    ui.success(f"Done. '{aid}' is now wired to {channel} peer {peer_id}")


@app.command("unwire")
def cmd_unwire(
    agent_id: str | None = typer.Argument(None),
    channel: str = typer.Option(
        "telegram", "--channel", help="Channel to unwire (default: telegram)"
    ),
) -> None:
    """Remove a channel binding (Telegram by default).

    `--channel <name>` (default telegram) selects which channel binding to
    remove. Removes the entry from docket's own fleet registry
    (`~/.docket/fleet.json`); the agent can still function without it, but
    approvals then require CLI, HTTP, or MCP interaction."""
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

    name = _fleet.meta_get(aid, "name", aid)
    peer = _fleet.get_binding(aid, channel)

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

    _fleet.remove_binding(aid, channel)
    ui.success("Binding removed")


@app.command("scope")
def cmd_scope(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
    project_key: str | None = typer.Argument(None),
) -> None:
    """Manage session scope / project isolation key.

    Subcommands: `show` (default) prints the current scope and session key;
    `set <project-key>` changes it; `reset` restores `default`. The session
    key has the form `agent:<id>:<project>` and prevents cross-project
    contamination between parallel work on the same agent; changing it
    updates `.docket-meta.json` and `SOUL.md`."""
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
    name = _fleet.meta_get(aid, "name", aid)
    current_key = _fleet.meta_get(aid, "projectKey", "default")
    current_session = _fleet.meta_get(aid, "sessionKey", f"agent:{aid}:default")

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
        _fleet.meta_set(aid, "projectKey", project_key)
        _fleet.meta_set(aid, "sessionKey", new_session)
        audit_log("scope.set", f"{aid}={project_key}")
        ui.success(f"Session scope updated: {current_key} → {project_key}")
        ui.success(f"Session key: {new_session}")
        ui.info("Update SOUL.md to reflect the new scope if needed.")

    elif action == "reset":
        new_session = f"agent:{aid}:default"
        _fleet.meta_set(aid, "projectKey", "default")
        _fleet.meta_set(aid, "sessionKey", new_session)
        audit_log("scope.reset", aid)
        ui.success("Session scope reset to: default")
        ui.success(f"Session key: {new_session}")

    else:
        ui.error(f"Unknown action '{action}'. Use: show, set, or reset")
        raise typer.Exit(1)


@app.command("profile")
def cmd_profile(
    agent_id: str | None = typer.Argument(None),
    model: str | None = typer.Argument(None),
    budget: str | None = typer.Option(None, "--budget", help="USD cap (0 = remove)"),
    resume: bool = typer.Option(
        False, "--resume", help="Clear an auto-pause (e.g. a reached budget cap)"
    ),
) -> None:
    """Pin or unpin an agent's model; set a budget cap; resume from auto-pause.

    Every agent follows its role's policy model by default
    (`modelSource: policy`). Pinning (`modelSource: pinned`) detaches it --
    policy and preset changes will no longer touch it.

    With no model argument, shows the current model, role, source, and
    budget. A `provider/model` argument pins it; `default` re-attaches it to
    the role policy. `--budget <USD>` sets a per-agent spend cap (0 = none).
    `--resume` clears an auto-pause (e.g. a reached budget cap) -- when the
    target is a pod's Lead it also un-blocks that pod's blocked tasks so
    dispatch can claim them again, and writes a `profile.resume` audit entry.

    Tier names (economy/standard/premium) are hard-rejected as a model
    argument -- there is no shim; use a full `provider/model` id, or
    `docket models` to see/set the role policy's model classes."""
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

    if resume:
        # The only writer that CLEARS an auto-pause (`core/dispatch.py`'s
        # `_pause_lead_for_budget` is the only one that SETS it). Mirrors the
        # `--budget` branch below: if the resumed agent is a pod's Lead, also
        # unblock its budget-blocked tasks — a pause with no way to un-stick
        # the tasks that queued up behind it would be a no-op resume.
        _fleet.meta_set(aid, "paused", False)
        _fleet.meta_set(aid, "pausedReason", "")
        audit_log("profile.resume", f"agent={aid}")
        pod_project = _pod_core.pod_of(aid)
        if pod_project is not None and _pod_core.member_id(pod_project, "lead") == aid:
            unblocked = _dispatch.unblock_pod(pod_project)
            if unblocked:
                ui.info(f"  Unblocked {unblocked} budget-blocked task(s) in pod '{pod_project}'.")
        ui.success(f"Resumed '{aid}' — auto-pause cleared.")
        if budget is None and model is None:
            return

    if budget is not None:
        try:
            bval = float(budget)
            if bval < 0:
                raise ValueError
        except ValueError:
            ui.error(f"Invalid budget '{budget}'. Must be a non-negative number (e.g. 5 or 10.50).")
            raise typer.Exit(1) from None
        _fleet.meta_set(aid, "budgetUsd", budget)
        audit_log("profile.budget", f"{aid}=${budget}")
        # A pod-wide budget change is one of the two sanctioned ways a
        # budget-`blocked` task re-enters `pending` (the other is an explicit
        # `docket pod <p> queue --retry <task-id>`) — a blocked task never
        # retries on its own. Only the Lead owns the pod's cap (dispatch.pod_budget
        # reads the Lead's budgetUsd), so only changing the Lead's budget unblocks.
        pod_project = _pod_core.pod_of(aid)
        if pod_project is not None and _pod_core.member_id(pod_project, "lead") == aid:
            unblocked = _dispatch.unblock_pod(pod_project)
            if unblocked:
                ui.info(f"  Unblocked {unblocked} budget-blocked task(s) in pod '{pod_project}'.")
        if budget != "0":
            _fleet.meta_set(aid, "paused", False)
            _fleet.meta_set(aid, "pausedReason", "")
            ui.success(f"Budget cap set to ${budget} for '{aid}'.")
        else:
            ui.success(f"Budget cap removed for '{aid}'.")
        if model is None:
            return  # budget-only change, nothing more to do

    name = _fleet.meta_get(aid, "name", aid)
    current = _fleet.meta_get(aid, "model", _cfg.DEFAULT_MODEL)
    role = _mp.agent_role(aid)
    src = _mp.agent_model_source(aid)
    bud = _fleet.meta_get(aid, "budgetUsd", "")

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

    _fleet.set_model_both(aid, new_model)
    _fleet.meta_set(aid, "modelSource", new_src)
    audit_log("profile.model", f"{aid}={new_model} ({new_src})")

    if new_src == "policy":
        ui.success(f"Model: {current} → {new_model} (follows role policy '{role}')")
    else:
        ui.success(f"Model pinned: {current} → {new_model}")


@app.command("persona")
def cmd_persona(
    agent_id: str | None = typer.Argument(None),
    action: str | None = typer.Argument(None, help="set | clear | show (default: show)"),
    label: str | None = typer.Argument(None, help='display label for set, e.g. "Orion 🔭"'),
) -> None:
    """Set/clear an agent's optional display persona (docket-owned; rendered into SOUL.md).

    Identity of record is the agent's role; a persona is only a display skin
    docket controls -- never a self-authored IDENTITY.md.

    Subcommands: (show, default) current persona + role; `set "<label>"`
    assigns a display name; `clear` removes it (back to role/name).

    Stored in `.docket-meta.json` (`persona`) and rendered into `SOUL.md`;
    survives `maintain rebuild`. `docket doctor` quarantines the
    base-assistant self-authoring scaffolding a model may leave behind
    (IDENTITY.md/BOOTSTRAP.md) from managed workspaces -- use this command
    instead to give an agent a friendly name."""
    from docket.core import identity as _identity
    from docket.core.models import AgentMeta, Persona

    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Set persona for")
    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    meta = AgentMeta.model_validate(store.read_json(_cfg.meta_path(aid)))

    if action in (None, "show"):
        cur = meta.persona.label() if meta.persona else ""
        ui.header(f"Persona: {meta.display_name() or aid} ({aid})")
        ui.console.print()
        ui.console.print(
            f"  [bold]{'Role:':<12}[/bold] {meta.role or '—'}  [dim](real identity)[/dim]"
        )
        ui.console.print(f"  [bold]{'Persona:':<12}[/bold] {cur or '[dim]none[/dim]'}")
        ui.console.print()
        ui.console.print(f'  docket persona {aid} set "Orion 🔭"   # assign a display name')
        ui.console.print(f"  docket persona {aid} clear           # remove it")
        ui.console.print()
        return

    if action == "clear":
        new_persona: Persona | None = None
    elif action == "set":
        if not label or not label.strip():
            ui.error("A label is required, e.g. docket persona " + aid + ' set "Orion 🔭"')
            raise typer.Exit(1)
        new_persona = _identity.parse_persona_label(label)
    else:
        ui.error(f"Unknown action '{action}'. Use: set | clear | show.")
        raise typer.Exit(1)

    # 1. Update the docket-owned source of truth (.docket-meta.json).
    _fleet.meta_set(aid, "persona", new_persona.model_dump() if new_persona else None)

    # 2. Re-render the persona block in SOUL.md (idempotent; role text untouched).
    soul = ws / "SOUL.md"
    if soul.is_file():
        soul.write_text(
            _identity.upsert_persona_block(soul.read_text(encoding="utf-8"), new_persona),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            soul.chmod(0o600)

    if new_persona:
        audit_log("persona.set", f"{aid}={new_persona.label()}")
        ui.success(f"Persona set to '{new_persona.label()}' for '{aid}'.")
    else:
        audit_log("persona.clear", aid)
        ui.success(f"Persona cleared for '{aid}'.")


@app.command(
    "keys",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_keys(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """API key management (add/list/remove/rotate/validate/export/setup).

    Docket's model client reads keys centrally; matching provider credentials
    are also synced to the agent workspaces that need them.

    Subcommands:
      list (default)     masked table of stored keys with a format badge and
                          the date added
      add <KEY_NAME>      name must be UPPERCASE_WITH_UNDERSCORES (e.g.
                           ANTHROPIC_API_KEY); prompts for the hidden value
                           via getpass; errors (exit 1) if the name already
                           exists -- use rotate instead
      remove <KEY_NAME>    deletes a stored key, confirming interactively if
                            stdin is a TTY
      rotate <KEY_NAME>    replaces the value of an existing key (errors,
                            exit 1, if it doesn't already exist)
      validate [KEY_NAME]  checks stored key(s) against known provider
                            prefix/length rules (e.g. ANTHROPIC_API_KEY must
                            start `sk-ant-` and be >= 40 chars); no name
                            validates everything; exit 1 on any failure
      export               prints `export NAME='value'` lines (unmasked,
                            shell-quoted) for every stored key, for
                            `eval "$(docket keys export)"`
      setup                interactive wizard (requires a TTY) through
                            Anthropic / OpenAI / Google AI / OpenRouter /
                            Vercel AI Gateway keys one at a time

    Stored in `~/.docket/secrets.json` (values, 0600) and
    `secrets.meta.json` (added/rotated timestamps) -- docket-owned JSON,
    written through `edges/store.py`. Recognized provider keys:
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_AI_API_KEY, OPENROUTER_API_KEY,
    AI_GATEWAY_API_KEY, VERCEL_OIDC_TOKEN, GROQ_API_KEY, MISTRAL_API_KEY,
    XAI_API_KEY, CEREBRAS_API_KEY, HUGGINGFACE_TOKEN. The runtime reads a
    selected provider's stored credential directly -- exporting is optional.
    add/remove/rotate re-sync only matching provider credentials (plus
    allowed custom keys) to agent workspaces."""
    from docket.cli._keys import run_keys

    raise typer.Exit(run_keys(sub, list(ctx.args)))


@app.command(
    "auth",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_auth(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """Model-provider credential status (no docket-native login flow yet).

    `status` shows which provider API keys are stored; `login`/`key`/`setup`
    accept `--provider <name>` (default: anthropic) but say plainly that
    there is no docket-native auth exchange yet -- store a credential with
    `docket keys add <PROVIDER>_API_KEY` instead (see `docket auth --help`).

    `docket auth status` never writes anything -- read-only. `login`/`key`/
    `setup`/`choose` all print the same "no docket-native flow" message and
    exit 1 -- kept as named subcommands only so a pre-Phase-19 script gets an
    explicit, actionable error instead of "unknown command"."""
    from docket.cli._keys import run_auth

    raise typer.Exit(run_auth(sub, list(ctx.args)))


@app.command(
    "models",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_models(ctx: typer.Context) -> None:
    """View and edit the role->model policy -- the single place that decides
    which model each kind of agent runs on.

    Built-in defaults put high-volume/low-reasoning roles (manager, reviewer,
    tester, knowledge) on the cheap model class and reasoning-dense roles
    (programmer, security, repo) on the strong class.

    Subcommands: (bare) show the role->model policy with pricing and why;
    `set <role> <provider/model>` change one role's model, or
    `set default <provider/model>` the fallback; `preset [name]` list or
    apply a provider preset (anthropic (default), openai, google,
    openrouter-free (experimental zero-cost router), openrouter, ai-gateway
    (Vercel), local (no API key, priced at $0 (local))); `reset` restore
    built-in defaults (asks for confirmation); `provider add <name>
    <base-url> [--model ID] [--name NAME] [--ctx N] [--max-tokens N]`
    register an OpenAI-compatible endpoint so its models can be referenced
    from `set`/`preset` (`--model` sets the model id served there, `--name` a
    friendly label, `--ctx`/`--max-tokens` record context-window/output-token
    limits used by exact-model request preflight and display).

    Policy changes are live: every policy-following agent is re-resolved
    immediately; pinned agents (`docket profile <id> <model>`) are never
    touched. Overrides persist in `~/.docket/docket-models.json` (`roles:`
    map); delete it or run `reset` to restore built-ins -- `reset` prompts
    `Continue? [y/N]` and a non-interactive call that can't answer aborts
    rather than silently resetting the fleet. Applying a preset also writes
    its own economy/standard/premium anchors, re-resolves every
    policy-following agent, and warns if the preset's required key isn't
    stored yet. Unknown models are accepted if well-formed
    (`provider/model`) -- docket has no provider-side catalog to validate
    against, so a bad model id only surfaces the first time an agent
    actually calls the endpoint; pricing shows n/a (or "n/a (bring your own)"
    for an OpenRouter/AI Gateway route other than the explicit free router,
    and "$0 (local)" for a local/ollama/lmstudio provider -- never a
    fabricated dollar figure). Tier names (economy/standard/premium) are
    rejected everywhere a model/role value is expected, including here; an
    invalid model prints the current role policy table alongside the error."""
    args = ctx.args
    sub = args[0] if args else "list"
    rest = args[1:]

    migration_note = _mp.migrate_legacy_profiles()
    if migration_note:
        ui.warn(migration_note)

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
    """Wire `docket models provider add <name> <base-url> [--opts]`."""
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
        f"  {'rank anchors':<12}  "
        f"{tiers.get('premium', '')} → {tiers.get('standard', '')} → {tiers.get('economy', '')}"
    )
    ui.dim(
        "  (role-default seed table — not a runtime fallback chain; overridable in docket-models.json)"
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
    # markup=False: the literal [anthropic|...] must not be parsed as Rich
    # markup. Derived from KNOWN_PRESETS so a new preset can't silently go
    # missing from this line the way `local` once did.
    ui.console.print(
        f"Preset: docket models preset [{'|'.join(_mp.KNOWN_PRESETS)}]",
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

    role_models, _tiers, default_model = _mp.load_registry()
    updates: dict[str, str] = {}
    touched_roles: list[str] = []

    if key == "default":
        before = default_model
        updates["default"] = validated
    elif _mp.is_role(key):
        before = role_models.get(key, _cfg.DEFAULT_MODEL)
        updates[f"role.{key}"] = validated
        touched_roles.append(key)
    else:
        all_r = " ".join(_mp.ALL_ROLES)
        ui.error(f"Unknown key '{key}'. Use a role ({all_r}) or 'default'.")
        raise typer.Exit(1)

    _mp.write_registry(updates)
    audit_log("models.set", f"role={key} {before}->{validated}")
    ui.success(f"{key} → {validated}")
    price = _mp.pricing_label(validated)
    if price.startswith("n/a"):
        ui.info(f"No pricing data for {validated} — cost will show as {price}.")

    if touched_roles:
        ui.console.print()
        ui.info("Re-resolving policy-following agents...")
        n = _mp.reapply_role_policy()
        if n:
            ui.console.print(f"  {n} agent(s) updated.")


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
            "Free options: openrouter-free (experimental zero-cost router at openrouter.ai)"
            " · local (no API key, run your own OpenAI-compatible endpoint)"
        )
        return

    if preset not in _mp.PRESET_TABLE:
        valid = " ".join(_mp.KNOWN_PRESETS)
        ui.error(f"Unknown preset '{preset}'. Valid: {valid}")
        raise typer.Exit(1)

    registered: dict[str, object] = {}
    if preset in ("anthropic", "openai", "google", "local"):
        registered = _fleet.get_local_provider(preset) or {}
        if not registered:
            ui.error(
                f"Preset '{preset}' has no registered OpenAI-compatible endpoint; "
                "an API key or coding-tool subscription is not sufficient."
            )
            ui.console.print(
                f"  Register one first: docket models provider add {preset} <base-url> "
                "--model <model-id> --ctx <tokens> --max-tokens <tokens>"
            )
            raise typer.Exit(1)

    t = _mp.PRESET_TABLE[preset]
    econ, std, prem = t["economy"], t["standard"], t["premium"]
    if preset == "local":
        models = registered.get("models")
        if isinstance(models, list) and models and isinstance(models[0], dict):
            registered_id = str(models[0].get("id") or "").strip()
            if registered_id:
                econ = std = prem = f"local/{registered_id}"
    cost, note = t["cost"], t["note"]

    before_roles, _before_tiers, before_default = _mp.load_registry()

    cheap_roles = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "cheap"]
    strong_roles = [r for r in _mp.ALL_ROLES if _mp.ROLE_CLASS.get(r) == "strong"]

    updates: dict[str, str] = {
        "default": std,
        # Persist the preset's own economy/standard/premium as the rank
        # anchors too — otherwise a non-Anthropic preset still
        # left Claude ids in the "rank anchors" line `docket models` prints.
        "rank.economy": econ,
        "rank.standard": std,
        "rank.premium": prem,
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
    ui.console.print(f"  rank anchor (seed only, not a fallback) → {prem}")
    if cost == "free":
        ui.console.print("  cost → free per-token (zero cost on free-tier models)")
    else:
        ui.console.print("  cost → paid")
    if note:
        ui.console.print(f"  note → {note}")
    ui.console.print()

    _mp.write_registry(updates)

    # One entry for the whole preset application (matching agent.add's
    # whole-pod-in-one-line style), not one per role: role_after maps every
    # role to the model the preset just assigned it (econ for cheap-class,
    # std for strong-class — cheap_roles union strong_roles == ALL_ROLES).
    role_after: dict[str, str] = dict.fromkeys(cheap_roles, econ)
    role_after.update(dict.fromkeys(strong_roles, std))
    role_changes = ",".join(
        f"{r}:{before_roles.get(r, _cfg.DEFAULT_MODEL)}->{role_after[r]}" for r in _mp.ALL_ROLES
    )
    audit_log(
        "models.preset",
        f"preset={preset} default:{before_default}->{std} roles:{role_changes}",
    )
    ui.success(f"Preset '{preset}' applied.")

    ui.console.print()
    ui.info("Re-resolving policy-following agents...")
    n = _mp.reapply_role_policy()
    if n:
        ui.console.print(f"  {n} agent(s) updated.")

    key_name = t.get("key", "")
    if key_name:
        from docket.core import secrets as _secrets

        key_present = key_name in _secrets.secrets_keys()
        if not key_present:
            ui.console.print()
            ui.warn(f"API key {key_name} is not stored yet.")
            ui.console.print(f"  Add it: docket keys add {key_name}")
            if preset in ("openrouter-free", "openrouter"):
                ui.console.print("  Get one: https://openrouter.ai/keys (free account available)")
    elif preset == "local":
        ui.console.print()
        ui.success("Registered local endpoint selected; no API key needed.")

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

    before_roles, _before_tiers, before_default = _mp.load_registry()

    _mp.write_registry({}, reset=True)
    with contextlib.suppress(FileNotFoundError):
        _cfg.MODEL_REGISTRY_FILE.unlink()

    after_roles, _after_tiers, after_default = _mp.load_registry()
    role_changes = ",".join(
        f"{r}:{before_roles.get(r, _cfg.DEFAULT_MODEL)}->{after_roles.get(r, _cfg.DEFAULT_MODEL)}"
        for r in _mp.ALL_ROLES
    )
    audit_log("models.reset", f"default:{before_default}->{after_default} roles:{role_changes}")
    ui.success("Restored built-in model defaults.")

    ui.console.print()
    ui.info("Re-resolving policy-following agents...")
    n = _mp.reapply_role_policy()
    if n:
        ui.console.print(f"  {n} agent(s) updated.")


@app.command(
    "pod",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_pod(
    ctx: typer.Context,
    project: str = typer.Argument(..., help="Project (pod) id"),
    sub: str | None = typer.Argument(
        None,
        help="list | add <role> [--verify CMD] | remove <member-id> | set-verify <member-id> CMD",
    ),
) -> None:
    """Manage a project's pod: list members, add/remove a role, set an
    implementer's verify command, and run its dispatch pipeline.

    A pod is the isolated team of project-scoped agents created by
    `docket add`; every member has its own permission-locked workspace, so no
    role is ever shared between projects. See docs/AGENT-TEAMS.md.

    Subcommands:
      list (default)   show the pod's members and their roles
      add <role>       [--count N|-n N] [--verify "<cmd>"]. Role is validated
                        against the open role-archetype registry
                        (`docket roles`), not a hardcoded
                        implementer|reviewer|tester list -- a blueprint role
                        or any user-defined archetype works too; `programmer`
                        is accepted as an alias for `implementer`. The Lead
                        is unique and cannot be added this way. Duplicated
                        roles get `-2`, `-3` ids. `--count`/`-n` adds several
                        at once. `--verify "<cmd>"` sets the mechanical
                        verification gate dispatch runs after that member's
                        hop -- written into the new member's
                        `.docket-meta.json` (`verifyCmd`) and documented in
                        its TOOLS.md; passing it for a non-implementer role
                        is silently ignored with a warning, since only an
                        Implementer hop is verify-gated. A new member
                        inherits the pod's workspaceKind/workDir/blueprint
                        from its existing members.
      remove <id>      remove one member by id
      set-verify <id> "<cmd>"
                       set (or change) the verify command on an existing
                        Implementer -- the only public way to do this short
                        of the internal debug command. Rewrites the member's
                        TOOLS.md. Validated (no NUL/newline, length-capped)
                        and audit-logged (`pod.set-verify`); runs at dispatch
                        time in the Implementer's git worktree when one
                        exists, falling back to the pod's shared codebase
                        root, then the member's own workspace dir.
      delegate <task>  [--priority high|normal|low]. Queue a task on the
                        pod's task queue (in the Lead's workspace). Priority
                        defaults to normal. The description is capped at 500
                        characters. Queues only -- run it with `dispatch`.
      queue            [--retry <task-id>]. Show the queue with per-task
                        status (pending/running/done/failed/blocked) and
                        estimated cost. `--retry` moves one blocked task back
                        to pending -- the explicit, single-task way around a
                        reached budget cap (`docket profile <lead-id>
                        --budget`/`--resume` un-blocks every task in the pod
                        at once instead).
      dispatch         [--resume] [--timeout <seconds>]. Run the pod's
                        pending (and, with --resume, crash-recoverable) tasks
                        through its pipeline -- one real agent turn per hop:
                        Lead -> Implementer -> Reviewer (if present) ->
                        Tester (if present). Only the roles the pod actually
                        has take part. Each task is claimed under a filelock
                        before its first hop runs, so two dispatchers can
                        never double-run the same task, and each hop is
                        persisted as it completes so a crash loses at most
                        the in-flight hop. `--resume` also reclaims any task
                        a prior dispatcher left failed with a stale claim,
                        continuing from its last persisted hop. `--timeout`
                        overrides both the agent-turn timeout and the
                        verifyCmd timeout for this run only (otherwise each
                        falls back to the pod's own configured timeouts,
                        then a 300s default).

    Dispatch guarantees: budget-gated with real auto-pause (checked before
    each hop against the Lead's cap; over budget leaves the task blocked and
    pauses the pod's Lead until `docket profile <project>-lead --resume`); a
    timed-out or daemon-error hop retries in place (linear backoff, small
    per-role budget) before failing, a real non-zero exit or bad verdict is
    never retried; a Reviewer's REQUEST-CHANGES sends the task back to the
    Implementer for one rework cycle (default) before a second rejection
    fails it; a set verifyCmd runs in the Implementer's git worktree when one
    exists; every hop/retry/gate outcome/claim/sweep event is traced
    (`docket trace`) on a per-task session; every invocation creates a
    queryable `docket runs` record; dispatch only ever targets the project's
    own pod -- there is no cross-pod dispatch path. See
    specs/functional/pod-dispatch.spec.md."""
    from docket.cli import _pod

    _pod.dispatch(project, sub, list(ctx.args))


@app.command(
    "pipeline",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_pipeline(ctx: typer.Context) -> None:
    """Validate, plan, and run a docket-native pipeline -- the one dialect
    docket actually executes.

    A pipeline file declares a pod's hop order, gates, and rework edges
    instead of relying on the built-in default order.

    Subcommands:
      validate <file>   pure structural validation -- no project involved,
                         nothing dispatched. Checks step ids are unique, each
                         step has exactly one of role/agent, gate shapes are
                         well-formed, and rework edges point at an earlier
                         step id.
      plan <project>    [--file <path>]. Resolves the pipeline against a
                         project's actual pod roster and prints the plan --
                         the exact function `run`/`docket pod <p> dispatch`
                         use internally, not a second pretty-printer. Never
                         executes anything or spends tokens. Without --file,
                         resolves the pod's zero-migration default order
                         (lead -> implementer -> reviewer -> tester,
                         whichever roles the pod has).
      run <project>     [--file <path>] [--resume] [--timeout <seconds>]
                         [--follow]. Dispatches a project's pod through the
                         given (or default) pipeline -- delegates to the
                         exact same executor as `docket pod <project>
                         dispatch`, so it is equally budget-gated, verify/
                         Reviewer/Tester-gated, traced, and recorded in
                         `docket runs`. --resume/--timeout behave identically
                         to pod dispatch. --follow tails the run's trace
                         events live in the foreground (Ctrl-C stops
                         watching, not the dispatch itself, which keeps
                         running).

    Pipeline file schema (YAML or JSON; unknown keys rejected): `name`
    (required), `description`, `variables` (a name->{default, description,
    required} map -- declared but not yet interpolated into any hop's
    prompt/environment); `steps`: each has `id` (unique), exactly one of
    `role` (a role-archetype slug) or `agent` (a specific member id),
    optional `retries`, `timeout` (seconds), optional `gate`, or a `parallel`
    list of child steps (one nesting level). `gate.type`: `mechanical` (a
    `command`, or null to defer to the target's own verifyCmd), `verdict` (a
    `pattern` regex, `passValues`, optional `rework: {to, when, maxCycles}`
    edge back to an earlier step), or `approval` (a human sign-off message).

    A pod with no pipeline file runs the built-in default order -- declaring
    a pipeline is opt-in. `archetype` references inside a step are
    shape-validated only, never checked against the live role registry. See
    specs/functional/pipeline-format.spec.md."""
    from docket.cli._pipeline import run_pipeline

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_pipeline(sub, args[1:]))


@app.command(
    "roles",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_roles(ctx: typer.Context) -> None:
    """Manage declarative role archetypes: list/show/add/validate.

    A role archetype is the data-driven definition behind every pod role
    (lead, implementer, reviewer, tester, and the blueprint-only roles
    researcher, analyst, writer, critic, operator, monitor) -- SOUL/AGENTS
    templates, model class, gate contract, token budget -- not a hardcoded
    branch, so `docket pod <p> add <role>` accepts any name in this registry.

    Subcommands:
      list (default)   all archetypes (built-in + user-defined) with source,
                        scope, model class, gate, edit rights, and
                        description
      show <name>      the full wire-format definition (YAML, falling back
                        to JSON if PyYAML is missing) -- name, version, scope
                        (org|pod), modelClass (cheap|strong), soulTemplate,
                        agentsTemplate, gateContract
                        (none|verdict|mechanical|approval), editRights
                        (none|read-only|write, descriptive only -- not
                        enforced), toolProfile, tokenBudget
      add <file.yaml>  registers a new archetype from a standalone YAML file
                        into the user overlay (`~/.docket/docket-roles.json`)
                        -- built-ins are never edited, only shadowed by name
      validate [file]  structural field validation (closed enums, name
                        regex, non-blank templates) plus a dry-run render of
                        both templates against a representative variable set
                        -- catches a template referencing an unknown `${var}`
                        before add persists it. With no file argument,
                        validates every entry in the merged live registry
                        instead.

    Built-ins and the 6-role starter library are Python literals, never
    loaded from files; a user archetype in `~/.docket/docket-roles.json`
    overlays by name, and a malformed overlay entry is skipped rather than
    crashing a live fleet. See specs/functional/role-archetypes.spec.md."""
    from docket.cli._roles import run_roles

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_roles(sub, args=args[1:]))


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


@app.command("logs")
def cmd_logs(agent_id: str | None = typer.Argument(None)) -> None:
    """View an agent's latest memory log.

    Prints the most recent `memory/YYYY-MM-DD.md` file's first 40 lines (with
    a note if there are more). There is no gateway or daemon log to tail any
    more -- docket has no external process producing one; memory logs are
    the durable, docket-owned activity record. For active tasks, read
    HEARTBEAT.md directly (`docket edit <id>`) or use
    `docket context <id> show`. Shows the single latest file only, not a
    rolling tail across days -- use `tail -f` on the file directly for live
    monitoring. Memory logs rotate daily."""
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

    # There is no daemon gateway log to tail for a channel-bound agent's
    # group traffic; memory logs above remain the durable, docket-owned
    # activity record.
    ui.console.print()


@app.command("edit")
def cmd_edit(agent_id: str | None = typer.Argument(None)) -> None:
    """Open agent workspace files in $EDITOR.

    Opens SOUL.md (identity and session key), AGENTS.md (delegation rules),
    TOOLS.md (project commands), HEARTBEAT.md (active tasks), and
    .docket-meta.json (metadata). Respects $EDITOR, falling back to `vi` if
    unset. Be careful editing `.docket-meta.json` by hand -- use
    `docket maintain <id> check` to fix drift afterward."""
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

    # Display name comes from docket metadata (persona → name → role → id), never
    # from a self-authored IDENTITY.md — identity of record is docket-owned.
    from docket.core import memory as _mem
    from docket.core.models import AgentMeta

    meta_path = _cfg.meta_path(aid)
    name = aid
    if meta_path.exists():
        with contextlib.suppress(Exception):
            name = AgentMeta.model_validate(store.read_json(meta_path)).display_name() or aid

    _WORKSPACE_FILES = ["SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE, "WORKFLOW_AUTO.md"]
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


@app.command("cost")
def cmd_cost(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
    history: bool = typer.Option(False, "--history"),
    days: int = typer.Option(0, "--days"),
) -> None:
    """Token usage and cost breakdown, with per-agent budget caps and
    runaway-session detection.

    With no agent id, aggregates all agents; with one, shows its own
    breakdown. `--json` emits machine-readable output for either form.
    `--history` shows a per-day cost breakdown instead of the current
    totals; `--days N` (default 0 = no limit) restricts `--history` to the
    last N days.

    Token counts (input/output/cache read/cache write, turns) are real and
    measured -- reported by the model endpoint per call and accumulated by
    docket's own session storage. The dollar total is not: docket's own turn
    loop (DocketDriver) reports no billed spend at all, so `Total cost`
    always reads as "none recorded for these sessions" rather than a dollar
    figure -- a known, plainly-stated gap, not a bug, because converting a
    token count into a dollar figure is exactly the estimate-to-billing-claim
    conversion docket refuses to make inside this command. See
    `docket models` for a comparative, clearly-labelled estimate (never
    presented as billed spend), and the same estimate's use by the
    budget-auto-pause gate. docket does not print a projected "savings if
    you switched models" figure either -- that would compound one estimate
    on top of another. `--history`/`--days` currently return no rows against
    the production driver: per-day breakdowns aren't tracked by docket's own
    session store (a session's usage is one running total for its lifetime,
    not timestamped per turn) -- a documented, known limitation. The pricing
    table (`docket models`) is a manual snapshot, not a live feed, and is
    not surfaced inside this command. Useful for detecting runaway sessions
    by turn count; budget management works off the token-based estimate the
    pod-dispatch gate itself computes, not this command's dollar column."""
    from docket.cli._cost import run_cost

    raise typer.Exit(run_cost(agent_id, json_out=json_out, history=history, days=days))


@app.command("doctor")
def cmd_doctor(
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable health probe"),
    fix: bool = typer.Option(False, "--fix", help="Apply auto-fixes for detected drift"),
) -> None:
    """System-wide health check and diagnostics, with an optional auto-fix
    pass.

    `--json` emits a machine-readable health probe instead of the Rich
    report; `--fix` applies auto-fixes for detected drift (permission
    repairs, missing workspace files, session-key resync) -- this mutates
    state.

    Runs (in order): required dependencies (python3 required, fzf optional --
    no external daemon binary to check for any more); per-project agent
    workspace/registration/binding checks; model validity across every
    registered agent; a legacy `docket-models.json` `profiles:` key advisory;
    the dispatch task ledger (`TASK_LIST.json` vs. the pod Lead's
    HEARTBEAT.md dispatch ledger must agree -- a mismatch prints exactly
    which task ids are missing/stale, and `--fix` re-syncs the ledger, always
    safe since TASK_LIST.json is dispatch's own source of truth); budget-cap
    sanity and runaway-session detection; key hygiene and provider coverage;
    security-gate configuration; template/runtime-contract version (reseeds
    a missing or stale WORKFLOW_AUTO.md); a leftover pre-Phase-10 global
    programmer/reviewer/tester workspace advisory; scaffolding quarantine
    (IDENTITY.md/BOOTSTRAP.md a model may leave behind); eval-results
    freshness. There is no "external config valid JSON"/"gateway service
    running" check any more -- docket has no external daemon or gateway
    process to validate, and no second registry to detect drift against
    `.docket-meta.json`.

    `doctor` is diagnostic-only by default; `--fix` is not read-only -- it
    mutates workspace files and permissions to correct detected drift.
    Review its findings before running with `--fix` on a workspace you
    haven't backed up."""
    from docket.cli._doctor import run_doctor

    raise typer.Exit(run_doctor(json_out=json_out, do_fix=fix))


@app.command(
    "gates",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_gates(ctx: typer.Context) -> None:
    """Manage docket's approval-routing and workspace-isolation posture.

    The tool-call gate itself -- the policy engine plus the argument-aware
    high-risk command classifier, both evaluated in `core/tools.py`'s
    `dispatch_tool` chokepoint on every call docket's turn loop makes -- is
    always active and cannot be turned off. What this command manages is
    narrower: a recorded, audited approval-routing posture flag
    (enable/disable) and whether tool execution runs inside a Docker sandbox
    (isolate). Nothing on the live path (`core/tools.py`, `core/approval.py`,
    `core/telegram.py`, `core/agent_loop.py`, `serve.py`) reads the
    approval-routing flag -- an "ask" verdict always sits in docket's own
    approval store, answerable identically by the CLI, HTTP, MCP, and
    Telegram channels regardless of it.

    Subcommands:
      status (default)  reports that the tool-call gate is always active,
                          plus approval-routing on/off/unset and
                          workspace-isolation mode
      enable [--force]  records approval-routing posture as on. Does not
                          change how a gated call's "ask" verdict is
                          answered: it still sits on docket's own approval
                          store, answerable by the CLI, HTTP, MCP, and
                          Telegram channels either way. --force is accepted
                          for CLI compatibility but has nothing left to
                          force over.
      disable            records approval-routing posture as off -- same
                          caveat: a gated call still blocks on docket's own
                          approval store and every channel can still answer
                          it; this flag changes nothing about that
      isolate on|off    records whether tool execution should run inside a
                          Docker sandbox. `on` requires docker on PATH --
                          errors, exit 1, if missing. Honestly incomplete
                          today: the setting is recorded in
                          `~/.docket/fleet.json`, but docket's own turn loop
                          always runs tools unsandboxed regardless of this
                          flag -- `docket gates status` says so plainly
                          rather than claiming live enforcement that doesn't
                          exist yet.
      classes           lists the built-in high-risk action classes
                          (`HIGH_RISK_PATTERNS` in `core/security.py`) --
                          money-movement, prod-deploy, and secret-access --
                          wired onto every bash call docket's turn loop
                          dispatches: the whole command line, including
                          every segment behind a `;`/`&&`/`||`/pipe, is
                          classified before a call is allowed to run, so
                          `git push origin production` asks even though
                          `git` itself stays on the curated allowlist
                          (`git status` does not). A pod's verifyCmd
                          separately refuses a matching command outright
                          before the shell starts; a hop's real output is
                          scanned for a match on the way through the
                          pipeline (flagged, not blocked, by itself).
                          Read-only; the pattern list is not yet
                          user-configurable.

    `docket init` records approval-routing posture as on by default; pass
    --no-gates to opt out -- this changes only the recorded flag, not who
    can answer an "ask" verdict. Every state change is written to the audit
    log. Approvals are answerable headlessly via `docket approve`/`docket
    deny` or `POST /approvals/<token>` (`docket serve`), or MCP, in addition
    to Telegram -- all four channels are audit-logged regardless of this
    flag. See specs/functional/security-gates.spec.md."""
    from docket.cli._gates import run_gates

    args = list(ctx.args)
    sub = args[0] if args else None
    force = "--force" in args
    rest = [a for a in args[1:] if a != "--force"]
    want = rest[0] if rest else "on"
    raise typer.Exit(run_gates(sub, want=want, force=force))


@app.command(
    "conversations",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_conversations(ctx: typer.Context) -> None:
    """Inspect and resume the conversation registry (list/show/resume/set).

    docket's durable index of channel threads: docket's own turn loop keeps
    no durable transcript of its own, so this registry tracks which agent
    handles each thread, its topic, status, and a resume pointer.

    Subcommands: `list` (default) all tracked conversations; `show <id|
    agent-id>` full detail for one; `resume <id|agent-id>` marks it
    in_progress and prints a resume brief; `set <agent-id> <peer-id>
    [--topic] [--status] [--last] [--task]` edits an entry directly.

    Auto-seeded when you `docket wire` an agent to a channel; cleaned up on
    `docket delete`. `status` is one of active | in_progress | waiting |
    done. Durable conversation content lives in the agent's HEARTBEAT.md +
    memory/ (resumed on its next turn via the durability contract); this
    registry tracks state only."""
    from docket.cli._conversations import run_conversations

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_conversations(sub, args[1:]))


@app.command(
    "runs",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_runs(ctx: typer.Context) -> None:
    """Inspect the dispatch run registry (list/show) -- one record per dispatch invocation.

    One persisted record per pod-dispatch invocation, whatever triggered it
    (the CLI, the `docket serve` webhook, a due schedule, or the sweep loop).
    Answers "is it done, did it fail, or did it never run" for background
    dispatch, whose failures are otherwise invisible.

    Subcommands: `list [--project <project>] [--json]`; `show <run-id>
    [--json]`; `cancel <run-id>` persists one cancellation request and
    signals every in-flight hop process group -- queued work is terminal
    immediately, a running record stays "running (cancel requested)" until
    the executor observes the request and fully stops, then the task and run
    become cancelled; writes one audit entry; in-process backend work
    already executing returns to a safe checkpoint, where its late response
    is discarded before any tool or later pipeline hop can start.

    A run record's `source` is one of cli|webhook|schedule|sweep|mcp;
    `state` is one of queued|running|succeeded|failed|cancelled. A failed
    run carries the exception text in `error` -- no dispatch call site
    silently discards an exception any more. Persisted to
    `~/.docket/docket-runs.json`. `show` and both JSON read surfaces expose
    cancellation requestedAt/observedAt/stoppedAt; a missing stop timestamp
    means the executor has not fully returned yet. `POST /dispatch/<project>`
    (see `docket serve`) returns {"run": "<id>"} immediately, before any
    dispatch work is attempted; `GET /runs/<id>` and `GET /runs?project=`
    mirror this command over HTTP (Bearer-authed, same as /approvals)."""
    from docket.cli._runs import run_runs

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_runs(sub, args[1:]))


@app.command(
    "harness",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_harness(ctx: typer.Context) -> None:
    """Run one agent, one turn, to completion, for a caller-owned workspace and home.

    `run --workspace DIR (--task TEXT | --task-file PATH) --model
    PROVIDER/ID [--role implementer] [--timeout S] [--agent-id ID]` executes
    synchronously and streams newline-delimited JSON events on stdout,
    finishing with exactly one versioned result object -- see
    `docs/adr/0001-harness-mode.md` and `specs/api/harness-mode.spec.md` for
    the full wire contract. stdout carries only that NDJSON; every log goes
    to stderr.

    Refuses (exit 2, one `result` with `status: refused`) unless `DOCKET_HOME`
    is set to a caller-owned directory (never the operator's own default
    home), `DOCKET_LLM_BASE_URL` is set, `DOCKET_NO_TRACE` is unset, and
    `--workspace` is a real directory -- this command never touches the
    operator's own approvals or audit log. Approval mode is fixed to
    non-interactive refusal: a tool call that would otherwise wait for a
    human is denied immediately as `blocked` rather than hanging for up to
    two minutes. On `SIGTERM` it persists a cancellation request, kills any
    in-flight tool subprocess's process group, and exits with a `cancelled`
    result. Exit codes: 0 the run's result is `ok`; 1 it ended `failed`,
    `blocked`, or `cancelled`; 2 refused before any run started -- the one
    named exception to this CLI's flat 0/1 convention.

    `status TOKEN` reports whether a run token from a prior `run` invocation
    is `live`, `finished` (with a best-effort reconstructed result), or
    `unknown`."""
    from docket.cli._harness import run_harness

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_harness(sub, args[1:]))


@app.command(
    "mcp",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_mcp(ctx: typer.Context) -> None:
    """Expose the control plane as an MCP server (`mcp serve`), or configure external MCP tool servers (`mcp servers`).

    "Rent the protocol": external tools are configuration, not code.

    Subcommands:
      serve      expose docket's own control plane as an MCP server over
                  stdio, so an external MCP client (an IDE, another agent
                  runtime) can inspect and drive the fleet through typed
                  tool calls instead of shelling out to the CLI. Requires
                  the optional [mcp] extra (`pip install 'docket[mcp]'` or
                  `uv sync --extra mcp`) -- prints an install hint to stderr
                  and exits 1 if missing. Transport: newline-delimited
                  JSON-RPC 2.0 on stdin/stdout -- no HTTP, no bind address,
                  no bearer token; the trust boundary is whoever can spawn
                  the process. Exposes 10 tools (every call audit-logged as
                  `mcp.<tool>`): status, pods, queue, delegate, dispatch,
                  runs, approvals_list, approvals_grant, approvals_deny,
                  cost -- each mirrors the equivalent CLI/HTTP path through
                  the exact same `core/` function, no parallel logic, no
                  auto-approve. `dispatch` creates a run record and returns
                  its id immediately, then runs the pipeline in the
                  background -- poll `runs` for the outcome.
      servers    list/add/remove external MCP tool servers (stdio transport)
                  so their tools become available to an agent's turn, gated
                  by the same pre_tool_call policy and dispatch_tool
                  chokepoint as any built-in -- a remote server can never
                  shadow bash/read/write/edit/glob/grep. `add <name>
                  [--env K=V ...] [--timeout S] -- <command> [args...]`:
                  everything after `--` is passed to the server verbatim as
                  its launch command and arguments; --env/--timeout must
                  come before `--`. Tools register as `mcp__<name>__<tool>`.

    Its tools are reachable from a live turn: the client namespaces them
    `mcp__<server>__<tool>`, and the turn loop folds them into the registry
    before gating and before per-role narrowing, so a Reviewer (or any role
    that denies write) never gets a write-capable MCP tool no matter what a
    configured server advertises. `docket mcp` alone prints usage and exits
    0; an unrecognized subcommand exits 1. A tool call's own success/failure
    is expressed inside the MCP protocol (isError), never as a process exit
    code. Configured servers persist in
    `~/.docket/docket-mcp-servers.json` (docket-owned JSON); env values are
    masked when listed. Every `mcp servers add`/`remove` is audit-logged.
    See specs/functional/mcp-client.spec.md and specs/api/mcp-server.spec.md."""
    from docket.cli._mcp import run_mcp

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_mcp(sub, args[1:]))


@app.command("audit")
def cmd_audit(
    arg: str | None = typer.Argument(None, help="Last-N count, 'verify', or --json"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show the audit log, or verify its tamper-evidence chain.

    A durable, append-only, tamper-evident record of docket-initiated
    mutations (key changes, gate toggles, profile pins, scope changes,
    agent/pod add/delete, persona changes, etc.).

    With no argument, shows the last 20 entries (human-readable); `[N]`
    shows the last N; `--json` dumps the raw audit.log JSONL file verbatim;
    `verify` walks the hash chain and reports the first broken link (exit 1)
    or that it verified clean (exit 0).

    Stored at `~/.docket/audit.log` -- one JSON object per line (seq, ts
    (millisecond resolution), user, pid, action, detail, prev_hash), never
    containing secret values. Every line chains to the previous one via a
    SHA-256 prev_hash (stdlib hashlib, no new dependency); `verify` detects a
    hand-tampered line -- lines written before this chain existed are
    treated as legacy/unchained, never as tampering. Rotates to a
    single-generation `audit.log.1` backup once past AUDIT_LOG_MAX_BYTES
    (default 5 MiB, env-overridable); `verify` only checks the current file
    -- a rotation starts a fresh chain. Best-effort and never raises; there
    is no environment kill switch -- recording cannot be silently disabled.
    Always exits 0 for the listing forms (malformed lines are skipped, not
    fatal); `verify` exits 1 on a detected broken chain link."""
    from docket.cli._audit import run_audit, run_audit_verify

    if arg == "verify":
        raise typer.Exit(run_audit_verify())

    limit: int | None = None
    if arg == "--json":
        json_out = True
    elif arg and arg.isdigit():
        limit = int(arg)
    raise typer.Exit(run_audit(limit=limit, json_out=json_out))


@app.command("snapshot")
def cmd_snapshot(
    output: str | None = typer.Option(None, "--output", "-o", help="Write JSON to file"),
) -> None:
    """Export system state snapshot as JSON.

    Every project agent and specialist, its model, registration/binding
    status, last activity, and measured cost, plus the channel list. `-o`/
    `--output <path>` writes the JSON to a file instead of stdout. `gateway`
    is a legacy field kept for shape stability -- docket has no external
    gateway process, so it always reads "inactive". `costUsd`/`totalCostUsd`
    are 0.0 for the same reason `docket cost` shows no recorded spend today:
    this is a snapshot of measured-token agents, not of billed dollars.
    Useful for backups, dashboards, or feeding fleet state into another
    tool."""
    import datetime as _dt

    gw = "active" if gateway_active() else "inactive"
    fleet_state = _fleet.load_fleet()
    channels = _fleet.channel_names(fleet_state)
    registered_ids = {a.id for a in _fleet.list_agents(fleet_state)}

    def _agent_bindings(aid: str) -> list[dict[str, Any]]:
        return [
            {"channel": b.channel, "peerId": b.peer_id}
            for b in fleet_state.bindings
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
                "kind": "project",
                "model": str(raw.get("model", _cfg.DEFAULT_MODEL)),
                "registered": pid in registered_ids,
                "bindings": _agent_bindings(pid),
                "lastActivity": last_activity(pid),
                "costUsd": round(cost, 6),
            }
        )

    for spec in _cfg.SPECIALIST_ORDER:
        ws = _cfg.WORKSPACES_DIR / spec
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
    telegram: bool = typer.Option(
        False,
        "--telegram",
        help=(
            "Long-poll docket's own Telegram bot for /approve /deny /status /delegate "
            "(needs: docket keys add TELEGRAM_BOT_TOKEN)"
        ),
    ),
    token_file: str | None = typer.Option(
        None,
        "--token-file",
        help=(
            "Write the /approvals + /dispatch bearer token to this file (0600) instead of "
            "printing it to stdout"
        ),
    ),
) -> None:
    """Local HTTP endpoints: /status.json /metrics /health.

    Binds to 127.0.0.1 (loopback-only) -- not reachable off this host. With
    --dispatch, each refresh also runs every pod's queue through the
    Lead->Implementer->Reviewer->Tester pipeline. Each hop is a real agent
    turn and is budget-gated; leave it off for a read-only monitor. With
    --telegram, also polls docket's own Telegram bot so a chat bound via
    `docket wire` can /approve, /deny, /status, or /delegate -- idle until a
    bot token is stored.

    `-p`/`--port <N>` (default 7331) binds a port -- 127.0.0.1 only, never
    reachable off the host. `-i`/`--interval <seconds>` (default 30) sets
    the sweep refresh interval. `--token-file <path>` writes the bearer
    token needed for /approvals, /dispatch, and /runs to a 0600 file instead
    of printing it to stdout.

    HTTP endpoints while running: GET /status.json, /metrics, /health (no
    auth); GET /approvals, POST /approvals/<token>
    {"action": "grant"|"deny"}, GET /runs and /runs?project=<p>, GET
    /runs/<id>, POST /dispatch/<project> (all Bearer-token-authed). The
    bearer token is generated fresh per invocation (printed to stdout,
    written to --token-file if given, or overridable via
    DOCKET_SERVE_TOKEN) and compared with secrets.compare_digest. POST
    /dispatch/<project> returns {"run": "<id>"} immediately and runs the
    pipeline in the background -- poll GET /runs/<id> (or
    `docket runs show <id>`) for the outcome.

    Plain `docket serve` never dispatches and never polls Telegram; both are
    opt-in. Read-only by default, so it's safe to leave running for
    monitoring. --dispatch spends real budget; over-budget tasks are left
    blocked, not run. Per-task dispatch is traced (`docket trace`) for
    auditability."""
    from docket.serve import run_serve

    run_serve(
        port=port, interval=interval, dispatch=dispatch, telegram=telegram, token_file=token_file
    )


@app.command("completions")
def cmd_completions(shell: str | None = typer.Argument(None)) -> None:
    """Shell completion helpers.

    Prints a shell-completion script for bash or zsh. With no argument,
    prints usage/install instructions. Only bash and zsh are supported (no
    fish) -- an unknown shell name errors with exit 1.

    The top-level command-name list is generated live from the real Typer
    command registry, so it can never drift from `docket --help`.
    Second-level subcommand words (e.g. `gates status enable disable isolate
    classes`) are hand-maintained in the completion templates, since those
    subcommands are parsed manually rather than being Click subgroups --
    only the top-level command list is regression-tested against drift, so
    hand-maintained subcommand words for `pipeline`, `conversations`,
    `runs`, and `persona` can and have drifted out of sync with their real
    subcommands."""
    from docket.cli._completions import run_completions

    raise typer.Exit(run_completions(shell))


@app.command(
    "trace",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_trace(ctx: typer.Context) -> None:
    """View agent execution traces.

    Every dispatch hop emits a JSONL trace event; use this to inspect them.
    Subcommands: `<session-id>` renders one session human-readable; `tail
    <project>` follows the latest open session live; `export <project>
    [--since DATE]` is a raw JSONL passthrough; `ingest <project>` projects
    docket's own session store into the trace store.

    Traces are stored at `~/.docket/traces/<project>/<session-id>.jsonl`.
    Each dispatch hop writes events such as tool_call, cost_charged,
    approval_requested."""
    from docket.cli._trace import run_trace

    args = list(ctx.args)
    since: str | None = None
    dry_run = False
    days: int | None = None
    pos: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--since":
            since = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if args[i] == "--dry-run":
            dry_run = True
            i += 1
            continue
        if args[i] == "--days":
            raw = args[i + 1] if i + 1 < len(args) else None
            days = int(raw) if raw is not None and raw.lstrip("-").isdigit() else None
            i += 2
            continue
        pos.append(args[i])
        i += 1
    sub = pos[0] if pos else None
    target = pos[1] if len(pos) > 1 else None
    raise typer.Exit(run_trace(sub, target, since, dry_run, days))


@app.command("metrics")
def cmd_metrics(
    role: str = typer.Option("", "--role", "-r", help="Restrict to one role"),
    project: str = typer.Option("", "--project", "-p", help="Restrict to one project"),
    window: int | None = typer.Option(None, "--window", "-w", help="Window in days"),
) -> None:
    """Show session success-rate and drift metrics.

    Computes success rate, latency, cost, and guardrail trip counts from
    trace data. `-r`/`--role` filters to a specific agent role; `-p`/
    `--project` to a specific project; `-w`/`--window N` (default 50,
    METRICS_WINDOW env-overridable) sets the rolling window size in
    sessions. Output: success rate, duration (mean/p95), cost (total/mean),
    and guardrail trip counts."""
    from docket.cli._metrics import run_metrics

    raise typer.Exit(run_metrics(role=role, project=project, window=window))


@app.command(
    "policies",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_policies(ctx: typer.Context) -> None:
    """Manage tool-approval policies.

    Manages declarative guardrail policies evaluated on each agent turn.

    Subcommands: `list` installed policies; `show <name>` prints one
    policy's JSON; `init` copies the 6 baseline templates
    (block-destructive, prompt-injection, secret-pii-redact, and the three
    high-risk-action-class policies: high-risk-payment, high-risk-deploy,
    high-risk-credentials); `validate [id|file.json]` schema-checks one (or
    every) installed policy; `test <hook> <role> <text>` dry-runs the
    evaluator, emitting no traces. Valid `<hook>` values for `test` are
    pre_input, pre_tool_call, and pre_output -- a policy can fire at enqueue
    time, before a tool call, or on a hop's output."""
    from docket.cli._policies import run_policies

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_policies(sub, args=args[1:]))


@app.command("approve")
def cmd_approve(approval_id: str | None = typer.Argument(None)) -> None:
    """Approve a pending tool-action.

    Grants a pending HITL approval token from docket's own approval store
    ($APPROVALS_DIR). With no token, lists pending approvals; with a token,
    grants it. Token format: apr-*. Returns exit 1 if the token is not
    found, or if you resolve it to the opposite verdict from what it already
    has; re-resolving to the same verdict it already has is treated as an
    idempotent no-op -- a warning, but exit 0. An apr-* token is created by
    docket itself, from an in-turn `ask` verdict on a tool call
    (`dispatch_tool`, blocking that call until answered), a pod-dispatch hop
    held on a requireApprovalRoles/pipeline approval step, or a task a
    guardrail policy flagged at enqueue. There is no separate daemon prompt
    any more -- this store is the only approval mechanism, and
    `docket approve`/`docket deny` (plus the HTTP and MCP equivalents, and a
    Telegram reply in a wired chat) are the only ways to answer it, each
    audit-logged with the channel that answered. See also `docket deny`."""
    from docket.cli._approve import run_approve

    raise typer.Exit(run_approve(approval_id))


@app.command("deny")
def cmd_deny(approval_id: str | None = typer.Argument(None)) -> None:
    """Deny a pending tool-action.

    Denies a pending HITL approval token from docket's own approval store
    ($APPROVALS_DIR). With no token, lists pending approvals; with a token,
    denies it. Same token format, idempotency, and provenance rules as
    `docket approve` -- see its help for the full contract."""
    from docket.cli._deny import run_deny

    raise typer.Exit(run_deny(approval_id))


@app.command("help")
def cmd_help(topic: str | None = typer.Argument(None)) -> None:
    """Show help.

    Prints docket's full hand-written command reference (common commands and
    the current role->model policy) -- richer than `docket --help`'s
    auto-generated command list. Always exits 0."""
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
            print(_fleet.meta_get(a[0], a[1], a[2] if len(a) > 2 else ""))

        elif verb == "meta-set":
            if len(a) < 3:
                _die("usage: meta-set <id> <field> <value>")
            _fleet.meta_set(a[0], a[1], a[2])

        elif verb == "agent-registered":
            if not a:
                _die("usage: agent-registered <id>")
            if _fleet.agent_registered(a[0]):
                print("1")
            else:
                print("0")
                raise typer.Exit(1)

        elif verb == "agent-add":
            if len(a) < 2:
                _die("usage: agent-add <id> <model> [session_key] [project_key]")
            _fleet.add_agent(a[0], a[1], a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else "")

        elif verb == "agent-remove":
            if not a:
                _die("usage: agent-remove <id>")
            _fleet.remove_agent(a[0])

        elif verb == "model-set-both":
            if len(a) < 2:
                _die("usage: model-set-both <id> <model>")
            _fleet.set_model_both(a[0], a[1])

        elif verb == "binding-get":
            if not a:
                _die("usage: binding-get <id> [channel]")
            print(_fleet.get_binding(a[0], a[1] if len(a) > 1 else "telegram"))

        elif verb == "binding-upsert":
            if len(a) < 2:
                _die("usage: binding-upsert <id> <peer_id> [channel] [peer_kind]")
            _fleet.upsert_binding(
                a[0],
                a[1],
                a[2] if len(a) > 2 else "telegram",
                a[3] if len(a) > 3 else "group",
            )

        elif verb == "binding-remove":
            if not a:
                _die("usage: binding-remove <id> [channel]")
            _fleet.remove_binding(a[0], a[1] if len(a) > 1 else None)

        elif verb == "gates-get":
            print(_json.dumps(_fleet.get_gates_enabled()))

        elif verb == "gates-set":
            if not a:
                _die("usage: gates-set <true|false>")
            _fleet.set_gates_enabled(a[0].lower() in ("1", "true", "yes"))

        elif verb == "isolation-get":
            print(_json.dumps(_fleet.get_isolation_enabled()))

        elif verb == "isolation-set":
            if not a:
                _die("usage: isolation-set <true|false>")
            _fleet.set_isolation_enabled(a[0].lower() in ("1", "true", "yes"))

        elif verb == "default-model-get":
            print(_fleet.get_default_model())

        elif verb == "default-model-set":
            if not a:
                _die("usage: default-model-set <model>")
            _fleet.set_default_model(a[0])

        else:
            print(f"_json: unknown verb '{verb}'", file=sys.stderr)
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as exc:
        print(f"_json {verb}: {exc}", file=sys.stderr)
        raise typer.Exit(1) from exc
