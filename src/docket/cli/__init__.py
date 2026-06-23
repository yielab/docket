"""docket CLI — Typer application with all 33 command stubs.

Each stub exits with code 127 (DOCKET_NOT_PORTED) which the bin/docket dispatcher
recognises as "fall through to Bash". Once a command is fully ported it:
  1. Implements real logic here instead of calling _not_ported().
  2. Is added to lib/core/ported.list so the dispatcher routes to Python.
"""

from __future__ import annotations

import contextlib
import json as _json
import os
import shutil
import sys
from pathlib import Path

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
    project_ids,
    restart_gateway,
    scan_telegram_groups,
    si_format,
)
from docket.edges import store
from docket.edges.adapters import openclaw as _oc

app = typer.Typer(
    name="docket",
    help="OpenClaw project agent manager",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)

# Exit code the dispatcher checks: "not yet ported, fall to Bash"
_NOT_PORTED = 127


def _not_ported(cmd: str) -> None:
    """Signal to the dispatcher that this command is not yet on the Python path."""
    print(f"docket-py: {cmd} not yet ported — falling through to Bash", file=sys.stderr)
    raise typer.Exit(_NOT_PORTED)


def _do_restart_gateway() -> None:
    if not restart_gateway():
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


# ── default (no subcommand) → list ────────────────────────────────────────────
@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        cmd_list(json_out=False)


# ── lifecycle ──────────────────────────────────────────────────────────────────
@app.command("install")
def cmd_install() -> None:
    """Bootstrap OpenClaw + specialist agents."""
    _not_ported("install")


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

    agents_out = []
    for aid in project_ids():
        raw = store.read_json(_cfg.meta_path(aid))
        agents_out.append(
            {
                "id": aid,
                "kind": raw.get("kind", "project"),
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
    )
    ui.console.print(f"  [dim]{'─' * 66}[/dim]")
    ui.console.print(
        f"[bold cyan]PROJECT AGENTS[/bold cyan] "
        f"[dim](your work - each is dedicated to one codebase/project)[/dim] "
        f"[bold]({len(ids)})[/bold]"
    )
    ui.console.print()

    home = str(Path.home())

    for aid in ids:
        raw = store.read_json(_cfg.meta_path(aid))
        name = str(raw.get("name", aid))
        atype = str(raw.get("type", "repo"))
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
        mem_days = (
            sum(1 for _ in (ws / "memory").glob("*.md"))
            if (ws / "memory").is_dir()
            else 0
        )

        model_short = model.split("/")[-1] if "/" in model else model
        path_short = codebase.replace(home, "~") if codebase else "[dim]none[/dim]"

        reg_badge = (
            "[green]● registered[/green]"
            if registered
            else "[red]○ not registered[/red]"
        )
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
            f"  {atype}  │  {model_short} ({src})  │"
            f"  stack: {stack or '[dim]—[/dim]'}  │  {mem_days} day-log(s)"
        )
        ui.console.print(f"  path: {path_short}  │  active: {activity}")
        ui.console.print(f"  {reg_badge}  {tg_b}  {mem_b}  {req_b}")

    # Specialist agents section
    ui.console.print()
    ui.console.print(
        "[bold green]SPECIALIST AGENTS[/bold green] "
        "[dim](the team - shared across all projects)[/dim]"
    )
    ui.console.print()
    ui.console.print(
        "  [dim]These work across ALL your projects."
        " Don't wire them to individual groups.[/dim]"
    )
    ui.console.print()

    for spec in _cfg.SPECIALIST_ORDER:
        spec_ws = _cfg.OPENCLAW_DIR / "workspaces" / spec
        if not spec_ws.is_dir():
            continue
        spec_meta = spec_ws / _cfg.META_FILE
        if not spec_meta.is_file():
            continue
        spec_raw = store.read_json(spec_meta)
        spec_model = str(spec_raw.get("model", _cfg.DEFAULT_MODEL))
        spec_src = str(spec_raw.get("modelSource", ""))
        spec_model_short = (
            spec_model.split("/")[-1] if "/" in spec_model else spec_model
        )
        why = _cfg.ROLE_WHY.get(spec, "")
        ui.console.print(
            f"  [green]✓[/green] {spec:<12}"
            f" [dim]{spec_model_short:<28} ({spec_src}) — {why}[/dim]"
        )

    ui.console.print()
    ui.console.print("─" * 70)
    ui.dim("  docket info <id>     detailed view")
    ui.dim("  docket cost          token usage")
    ui.dim("  docket models        role→model policy")
    ui.dim("  docket profile <id>  pin/unpin an agent's model")
    ui.console.print()


@app.command("add")
def cmd_add(agent_id: str | None = typer.Argument(None)) -> None:
    """Add a new project agent (interactive)."""
    _not_ported("add")


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
        # Interactive numbered fallback
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

    mem_count = (
        sum(1 for _ in (ws / "memory").glob("*.md"))
        if (ws / "memory").is_dir()
        else 0
    )
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
        ui.console.print(
            f"  [bold]{'Status:':<18}[/bold] [red]PAUSED[/red]{reason_str}"
        )
    ui.console.print(f"  [bold]{'Session Key:':<18}[/bold] {session_key}")
    ui.console.print(f"  [bold]{'Project Scope:':<18}[/bold] {project_key}")
    ui.console.print()

    reg_str = "[green]yes[/green]" if registered else "[red]no[/red]"
    ui.console.print(f"  [bold]{'Registered:':<18}[/bold] {reg_str}")

    if tg:
        ui.console.print(f"  [bold]{'Telegram:':<18}[/bold] [green]{tg}[/green]")
    else:
        ui.console.print(
            f"  [bold]{'Telegram:':<18}[/bold] [yellow]not wired[/yellow]"
        )

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


@app.command("delete")
def cmd_delete(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove agent and optionally its workspace."""
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


# ── maintenance ────────────────────────────────────────────────────────────────
@app.command("maintain")
def cmd_maintain(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Maintain an agent workspace (clean/reset/rebuild/check/sessions)."""
    _not_ported("maintain")


# ── context / memory ──────────────────────────────────────────────────────────
@app.command("context")
def cmd_context(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Show/search/snapshot/index/compress agent memory."""
    _not_ported("context")


# ── telegram ───────────────────────────────────────────────────────────────────
@app.command("wire")
def cmd_wire(
    agent_id: str | None = typer.Argument(None),
    channel: str = typer.Option("telegram", "--channel", help="Channel to wire (default: telegram)"),
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
                        ui.warn(
                            f"This will unbind '{prev_bound}' from group '{groups[idx][1]}'"
                        )
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
        # Non-Telegram: manual peer ID entry.
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
    channel: str = typer.Option("telegram", "--channel", help="Channel to unwire (default: telegram)"),
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


# ── configuration ──────────────────────────────────────────────────────────────
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
        ui.console.print(
            "Each project scope gets isolated workspace memory and routing."
        )
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

    # ── --budget ──────────────────────────────────────────────────────────────
    if budget is not None:
        try:
            bval = float(budget)
            if bval < 0:
                raise ValueError
        except ValueError:
            ui.error(
                f"Invalid budget '{budget}'. Must be a non-negative number (e.g. 5 or 10.50)."
            )
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

    # ── read current state ─────────────────────────────────────────────────────
    name = _oc.meta_get(aid, "name", aid)
    current = _oc.meta_get(aid, "model", _cfg.DEFAULT_MODEL)
    role = _mp.agent_role(aid)
    src = _mp.agent_model_source(aid)
    bud = _oc.meta_get(aid, "budgetUsd", "")

    # ── no model given → show status ──────────────────────────────────────────
    if model is None:
        role_models, _, _ = _mp.load_registry()
        policy_model = _mp.resolve_role_model(role, role_models)
        ui.header(f"Model: {name} ({aid})")
        ui.console.print()
        ui.console.print(f"  [bold]{'Current model:':<18}[/bold] {current}")
        ui.console.print(
            f"  [bold]{'Role:':<18}[/bold] {role}"
            f"  [dim]({_cfg.ROLE_WHY.get(role, '')})[/dim]"
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

    # ── resolve the requested model ───────────────────────────────────────────
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

    # ── no-op guard ───────────────────────────────────────────────────────────
    if new_model == current and new_src == src:
        ui.warn(f"Already using {new_model} ({new_src}). No change.")
        return

    # ── write to both stores ──────────────────────────────────────────────────
    _oc.set_model_both(aid, new_model)
    _oc.meta_set(aid, "modelSource", new_src)

    if new_src == "policy":
        ui.success(f"Model: {current} → {new_model} (follows role policy '{role}')")
    else:
        ui.success(f"Model pinned: {current} → {new_model}")
    _do_restart_gateway()


@app.command("keys")
def cmd_keys(sub: str | None = typer.Argument(None)) -> None:
    """Manage centralised API keys."""
    _not_ported("keys")


@app.command("auth")
def cmd_auth(sub: str | None = typer.Argument(None)) -> None:
    """Manage model authentication (via OpenClaw auth profiles)."""
    _not_ported("auth")


# ── models / policy ────────────────────────────────────────────────────────────
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
    else:
        ui.error(
            f"Unknown models subcommand '{sub}'.\n"
            "Usage:\n"
            "  docket models                            # show role→model policy\n"
            "  docket models set <role> <model>         # change a role's model\n"
            "  docket models preset [name]              # list or apply a provider preset\n"
            "  docket models reset                      # restore built-in defaults"
        )
        raise typer.Exit(1)


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
                reg_roles = _j.loads(
                    _cfg.MODEL_REGISTRY_FILE.read_text(encoding="utf-8")
                ).get("roles", {})
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
    ui.console.print(
        "Preset: docket models preset [anthropic|openai|google|openrouter-free|openrouter]"
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
            if (key == "economy" and cls == "cheap") or (
                key == "standard" and cls == "strong"
            ):
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
        ui.console.print(f"[bold]{fmt.format('PRESET', 'COST', 'KEY NEEDED', 'DESCRIPTION')}[/bold]")
        ui.console.print(fmt.format("------", "----", "----------", "-----------"))
        for p in _mp.KNOWN_PRESETS:
            t = _mp.PRESET_TABLE[p]
            marker = " (default)" if p == "anthropic" else ""
            ui.console.print(
                fmt.format(f"{p}{marker}", t["cost"], t["key"], t["note"])
            )
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

    # Key check — warn if the required API key isn't stored.
    key_name = t.get("key", "")
    if key_name:
        secrets_path = _cfg.OPENCLAW_DIR / "secrets.json"
        key_present = False
        if secrets_path.exists():
            try:
                import json as _j
                key_present = key_name in _j.loads(
                    secrets_path.read_text(encoding="utf-8")
                )
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


# ── team ───────────────────────────────────────────────────────────────────────
@app.command("team")
def cmd_team(sub: str | None = typer.Argument(None)) -> None:
    """Specialist team coordination (status/delegate/queue/done)."""
    _not_ported("team")


@app.command("workflow")
def cmd_workflow(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Manage Lobster YAML pipelines."""
    _not_ported("workflow")


# ── utilities ──────────────────────────────────────────────────────────────────
@app.command("logs")
def cmd_logs(agent_id: str | None = typer.Argument(None)) -> None:
    """View memory logs and gateway entries."""
    _not_ported("logs")


@app.command("edit")
def cmd_edit(agent_id: str | None = typer.Argument(None)) -> None:
    """Open workspace files in $EDITOR."""
    _not_ported("edit")


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
        budget_val = (
            float(budget_raw)
            if budget_raw and str(budget_raw) not in ("", "0")
            else None
        )
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
            budget_col = f"${bval:.2f} ({pct}%)"

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
    ui.console.print(f"[bold]{'Total:':>81} ${total_cost:.4f}[/bold]")

    if runaway:
        ui.console.print()
        for r in runaway:
            ui.warn(f"  Runaway session: {r}")

    ui.console.print()
    ui.dim("  Recorded spend from session data in ~/.openclaw/agents/*/sessions/*.jsonl")
    ui.dim("  Comparative estimates use a price snapshot — see: docket models")
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

    # Aggregate all agents per day
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

    ui.console.print(
        f"  {'DATE':<12} {'TURNS':>7} {'INPUT':>12} {'OUTPUT':>12} {'COST (USD)':>12}"
    )
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
    ui.console.print(
        f"  {'':12} {'':>7} {'':>12} {'':>12} {sum(costs):>12.4f}  total"
    )
    ui.console.print()


@app.command("doctor")
def cmd_doctor() -> None:
    """System-wide health check with auto-fix."""
    _not_ported("doctor")


@app.command("gates")
def cmd_gates(sub: str | None = typer.Argument(None)) -> None:
    """Manage tool-approval security gates."""
    _not_ported("gates")


@app.command("audit")
def cmd_audit(sub: str | None = typer.Argument(None)) -> None:
    """Show audit log."""
    _not_ported("audit")


@app.command("eval")
def cmd_eval(sub: str | None = typer.Argument(None)) -> None:
    """Run specialist-role evaluation stubs."""
    _not_ported("eval")


@app.command("snapshot")
def cmd_snapshot(agent_id: str | None = typer.Argument(None)) -> None:
    """Export agent workspace snapshot."""
    _not_ported("snapshot")


@app.command("serve")
def cmd_serve() -> None:
    """Local HTTP endpoints: /status.json /metrics /health."""
    _not_ported("serve")


@app.command("completions")
def cmd_completions(shell: str | None = typer.Argument(None)) -> None:
    """Shell completion helpers."""
    _not_ported("completions")


# ── observability ──────────────────────────────────────────────────────────────
@app.command("trace")
def cmd_trace(sub: str | None = typer.Argument(None)) -> None:
    """View agent execution traces."""
    _not_ported("trace")


@app.command("metrics")
def cmd_metrics() -> None:
    """Show session success-rate and drift metrics."""
    _not_ported("metrics")


@app.command("policies")
def cmd_policies(sub: str | None = typer.Argument(None)) -> None:
    """Manage tool-approval policies."""
    _not_ported("policies")


@app.command("approve")
def cmd_approve(approval_id: str | None = typer.Argument(None)) -> None:
    """Approve a pending tool-action."""
    _not_ported("approve")


@app.command("deny")
def cmd_deny(approval_id: str | None = typer.Argument(None)) -> None:
    """Deny a pending tool-action."""
    _not_ported("deny")


# ── help ───────────────────────────────────────────────────────────────────────
@app.command("help")
def cmd_help(topic: str | None = typer.Argument(None)) -> None:
    """Show help."""
    _not_ported("help")


# ── hidden: data-layer bridge (M2/T2.6) ───────────────────────────────────────
# Used by bin/docket (and eventually lib/helpers/json.sh) to replace the 136
# inline python3 heredocs.  All openclaw.json / .docket-meta.json knowledge
# lives in edges/adapters/openclaw.py; this command is just the CLI surface.
#
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
        # ── .docket-meta.json ──────────────────────────────────────────────────
        if verb == "meta-get":
            if len(a) < 2:
                _die("usage: meta-get <id> <field> [default]")
            print(_oc.meta_get(a[0], a[1], a[2] if len(a) > 2 else ""))

        elif verb == "meta-set":
            if len(a) < 3:
                _die("usage: meta-set <id> <field> <value>")
            _oc.meta_set(a[0], a[1], a[2])

        # ── openclaw.json — dotted-path (Bash compat escape hatch) ────────────
        elif verb == "oc-get":
            if not a:
                _die("usage: oc-get <dotpath> [default]")
            print(_oc.oc_get_path(a[0], a[1] if len(a) > 1 else ""))

        elif verb == "oc-set":
            if len(a) < 2:
                _die("usage: oc-set <dotpath> <json-value>")
            _oc.oc_set_path(a[0], a[1])

        # ── agents.list ───────────────────────────────────────────────────────
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
            _oc.add_agent(
                a[0], a[1], a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else ""
            )

        elif verb == "agent-remove":
            if not a:
                _die("usage: agent-remove <id>")
            _oc.remove_agent(a[0])

        elif verb == "model-set-both":
            if len(a) < 2:
                _die("usage: model-set-both <id> <model>")
            _oc.set_model_both(a[0], a[1])

        # ── bindings ──────────────────────────────────────────────────────────
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

        # ── security ──────────────────────────────────────────────────────────
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

        # ── defaults ──────────────────────────────────────────────────────────
        elif verb == "default-model-get":
            print(_oc.get_default_model())

        elif verb == "default-model-set":
            if not a:
                _die("usage: default-model-set <model>")
            _oc.set_default_model(a[0])

        # ── auth-profiles.json ────────────────────────────────────────────────
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
