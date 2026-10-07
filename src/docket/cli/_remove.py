"""The commands being removed.
Holds list, context, logs, edit, scope, persona and help."""

from __future__ import annotations

import contextlib
import json as _json
import os
import sys
from pathlib import Path

import typer

import docket.config as _cfg
from docket import ui
from docket.cli._agents import _pick_agent
from docket.cli._setup import _resolve_version
from docket.core import fleet as _fleet
from docket.core import pod_provisioning as _pp
from docket.core.audit import audit_log
from docket.core.utils import last_activity, project_ids
from docket.edges import store


def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List all project agents.

    Shows every registered agent -- pod members for each project -- with role/pod, model and
    its source, Telegram binding, and last activity. Telegram status reflects
    docket's own channel bindings (`~/.docket/fleet.json`); the session column
    shows the agent's current project key. `--json` emits the same listing as
    one JSON document instead of the Rich table, for scripting."""
    if json_out:
        _cmd_list_json()
    else:
        _cmd_list_human()


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
                "budgetUsd": _pp.parse_budget_usd(raw.get("budgetUsd")),
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

    ui.console.print()
    ui.console.print("─" * 70)
    ui.dim("  docket info <id>     detailed view")
    ui.dim("  docket cost          token usage")
    ui.dim("  docket models        role→model policy")
    ui.dim("  docket profile <id>  pin/unpin an agent's model")
    ui.console.print()


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
    workspace; any other action exits 2. Use `docket snapshot` for a
    whole-fleet JSON export."""
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
    updates `.docket-meta.json` only -- it prints a reminder to update
    SOUL.md yourself, it does not rewrite the file."""
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
    survives `maintain rebuild`. Use this command to give an agent a
    friendly name."""
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


def cmd_logs(agent_id: str | None = typer.Argument(None)) -> None:
    """View an agent's latest memory log.

    Prints the most recent `memory/YYYY-MM-DD.md` file's first 40 lines (with
    a note if there are more). Memory logs are the durable, docket-owned
    activity record. For active tasks, read
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
    ui.console.print()


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


def cmd_help(topic: str | None = typer.Argument(None)) -> None:
    """Show help.

    With no topic, docket's full hand-written command reference (common
    commands and the current role->model policy) -- richer than
    `docket --help`'s auto-generated command list; always exits 0. With a
    topic, that command's own usage text (exit 0), or an unknown-command
    error naming it (exit 1)."""
    from docket.cli._help import run_help

    raise typer.Exit(run_help(topic))
