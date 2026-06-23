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
@app.command(
    "team",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_team(
    ctx: typer.Context,
    sub: str | None = typer.Argument(None),
) -> None:
    """Specialist team coordination (status/check/roles/upgrade/delegate/queue/start/done/cancel)."""
    action = sub or "status"
    extra: list[str] = list(ctx.args)

    if action == "status":
        _team_status()
    elif action == "check":
        _team_check()
    elif action == "roles":
        _team_roles()
    elif action == "upgrade":
        _team_upgrade()
    elif action == "delegate":
        _team_delegate(extra)
    elif action == "queue":
        _team_queue(extra)
    elif action in ("start", "done", "cancel"):
        state_map = {"start": "in_progress", "done": "done", "cancel": "cancelled"}
        _team_transition(state_map[action], extra)
    elif action == "init":
        ui.warn("'team init' is deprecated. Use 'docket install' instead.")
    else:
        _team_help_text()


def _team_help_text() -> None:
    ui.header("Team Management")
    ui.console.print()
    ui.console.print("Manage specialist agents with DOCKET architecture")
    ui.console.print()
    ui.console.print("[bold]Usage:[/bold]")
    ui.console.print("  docket team status              Show specialist agent health")
    ui.console.print("  docket team upgrade             Upgrade specialists to DOCKET templates")
    ui.console.print("  docket team check               Verify all specialists exist")
    ui.console.print("  docket team roles               Show agent roles and responsibilities")
    ui.console.print()
    ui.console.print("[bold]Task Delegation:[/bold]")
    ui.console.print('  docket team delegate "<task>"                 Add task (status: pending)')
    ui.console.print('  docket team delegate --priority high "<task>" High-priority task')
    ui.console.print("  docket team queue                             Show active tasks")
    ui.console.print("  docket team queue --all                       Include done + cancelled")
    ui.console.print("  docket team start <task-id>                   pending → in_progress")
    ui.console.print("  docket team done <task-id>                    pending/in_progress → done")
    ui.console.print("  docket team cancel <task-id>                  pending/in_progress → cancelled")
    ui.console.print()


_DOCKET_SOUL_RE = None


def _docket_soul_pattern() -> Any:
    import re as _re

    global _DOCKET_SOUL_RE
    if _DOCKET_SOUL_RE is None:
        _DOCKET_SOUL_RE = _re.compile(
            r"DOCKET Architecture|Context Compression|Short-Circuit|veto power"
            r"|Mandatory.*checklist|validation specialist|compressed brief|observe behavior",
            _re.IGNORECASE,
        )
    return _DOCKET_SOUL_RE


def _team_status() -> None:
    specialists = list(_cfg.SPECIALIST_ORDER)
    ui.header("Specialist Team Status")
    ui.console.print()
    upgraded = 0
    for spec in specialists:
        ws = _cfg.OPENCLAW_DIR / "workspaces" / spec
        if not ws.is_dir():
            ui.console.print(f"  [red]✗[/red] {spec:<12} Not installed")
            continue
        soul = ws / "SOUL.md"
        if not soul.is_file():
            ui.console.print(f"  [yellow]⚠[/yellow] {spec:<12} Missing SOUL.md")
            continue
        try:
            content = soul.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if _docket_soul_pattern().search(content):
            ui.console.print(f"  [green]✓[/green] {spec:<12} DOCKET-optimized")
            upgraded += 1
        else:
            ui.console.print(f"  [cyan]○[/cyan] {spec:<12} Standard (upgrade available)")
    ui.console.print()
    if upgraded >= 4:
        ui.dim("All core specialists DOCKET-optimized (knowledge & security use standard templates)")
    else:
        ui.dim("Run 'docket team upgrade' to apply DOCKET templates")
    ui.console.print()


def _team_check() -> None:
    specialists = ["programmer", "reviewer", "tester", "knowledge", "security", "manager"]
    ui.header("Specialist Agent Health Check")
    ui.console.print()
    missing: list[str] = []
    healthy = 0
    for spec in specialists:
        if _oc.agent_registered(spec):
            ui.success(f"{spec}: registered")
            healthy += 1
        else:
            ui.warn(f"{spec}: NOT registered")
            missing.append(spec)
    ui.console.print()
    if not missing:
        ui.success(f"All specialists healthy ({healthy}/6)")
    else:
        ui.error(f"Missing specialists: {' '.join(missing)}")
        ui.console.print()
        ui.console.print("Run: docket install")
        raise typer.Exit(1)


def _team_roles() -> None:
    ui.header("Specialist Agent Roles (DOCKET Architecture)")
    ui.console.print()

    def _model(role: str) -> str:
        try:
            return _mp.resolve_role_model(role)
        except Exception:
            return "?"

    ui.console.print("[bold green]Manager (Atlas)[/bold green]")
    ui.console.print("  • Orchestrates tasks and delegates to specialists")
    ui.console.print("  • Embedded classifier logic (routes tasks efficiently)")
    ui.console.print("  • Context compression before delegation")
    ui.console.print("  • Short-circuit resolution for simple queries")
    ui.console.print(f"  • Model: {_model('manager')} (role policy) | Tools: read (memory), message")
    ui.console.print()

    ui.console.print("[bold green]Programmer[/bold green]")
    ui.console.print("  • Implements code changes from compressed briefs")
    ui.console.print("  • Reads <5K tokens per task (file + brief only)")
    ui.console.print("  • Signals completion via memory files")
    ui.console.print(f"  • Model: {_model('programmer')} (role policy)")
    ui.console.print("  • Tools: read, write, edit, exec (sandbox)")
    ui.console.print()

    ui.console.print("[bold green]Reviewer (Auditor)[/bold green]")
    ui.console.print("  • Security + correctness gatekeeper")
    ui.console.print("  • 6-point mandatory checklist")
    ui.console.print("  • Veto power (bad code doesn't proceed)")
    ui.console.print(f"  • Model: {_model('reviewer')} (role policy) | Tools: read (diff only)")
    ui.console.print()

    ui.console.print("[bold green]Tester (Validator)[/bold green]")
    ui.console.print("  • Behavior-only validation (doesn't read code!)")
    ui.console.print("  • Executes reproduction steps")
    ui.console.print("  • Binary verdict: PASS or FAIL")
    ui.console.print(f"  • Model: {_model('tester')} (role policy) | Tools: exec, browser (read-only)")
    ui.console.print()

    ui.console.print("[bold green]Knowledge[/bold green]")
    ui.console.print("  • Memory distillation and indexing")
    ui.console.print("  • Pattern extraction from logs")
    ui.console.print("  • Architectural decision tracking")
    ui.console.print(f"  • Model: {_model('knowledge')} (role policy) | Tools: read, memory search")
    ui.console.print()

    ui.console.print("[bold green]Security[/bold green]")
    ui.console.print("  • Deep threat modeling (beyond code review)")
    ui.console.print("  • Penetration testing coordination")
    ui.console.print("  • Compliance audits (GDPR, HIPAA)")
    ui.console.print(f"  • Model: {_model('security')} (role policy) | Tools: read, browser")
    ui.console.print()

    ui.console.print(
        "[dim]Note: Reviewer handles routine security checks. Security specialist\n"
        "      handles deep audits, compliance, and threat modeling.[/dim]"
    )
    ui.console.print()


def _team_upgrade() -> None:
    import datetime as _dt
    import shutil as _shutil

    cli_root = Path(os.environ.get("DOCKET_CLI_ROOT", ""))
    if not cli_root.is_dir():
        cli_root = Path(__file__).parents[3]
    tmpl_dir = cli_root / "lib" / "templates"

    ui.header("Upgrading Specialists to DOCKET Architecture")
    ui.console.print()
    ui.warn("This will replace SOUL.md files with DOCKET-optimized templates")
    ui.console.print()
    ui.console.print("Changes:")
    ui.console.print("  • Manager: Add classifier logic + context compression rules")
    ui.console.print("  • Programmer: Add brief-only reading + <5K token targets")
    ui.console.print("  • Reviewer: Add 6-point security checklist + veto power")
    ui.console.print("  • Tester: Add behavior-only validation (no code reading)")
    ui.console.print("  • Knowledge: No changes (already efficient)")
    ui.console.print("  • Security: No changes (focused on deep audits)")
    ui.console.print()

    if sys.stdin.isatty():
        answer = input("Proceed with upgrade? [y/N]: ").strip().lower()
        if answer != "y":
            ui.warn("Aborted.")
            return
    else:
        ui.warn("Non-interactive mode — aborting upgrade (requires TTY confirmation).")
        return

    ui.console.print()

    upgrades = [
        ("manager", "docket-manager.md"),
        ("programmer", "docket-programmer.md"),
        ("reviewer", "docket-reviewer.md"),
        ("tester", "docket-tester.md"),
    ]
    upgraded = 0
    failed = 0

    for role, tmpl_name in upgrades:
        ui.info(f"Upgrading {role}...")
        ws = _cfg.OPENCLAW_DIR / "workspaces" / role
        if not ws.is_dir():
            ui.warn(f"{role}: workspace not found")
            failed += 1
            continue
        tmpl = tmpl_dir / tmpl_name
        if not tmpl.is_file():
            ui.warn(f"{role}: template not found ({tmpl})")
            failed += 1
            continue
        soul = ws / "SOUL.md"
        if soul.is_file():
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            _shutil.copy2(soul, soul.with_name(f"SOUL.md.backup-{stamp}"))
        _shutil.copy2(tmpl, soul)
        soul.chmod(0o600)
        ui.success(f"{role}: upgraded (backup saved)")
        upgraded += 1

    ui.info("knowledge: no upgrade needed (already optimized)")
    ui.info("security: no upgrade needed (already optimized)")
    ui.console.print()

    if failed:
        ui.warn(f"Upgraded: {upgraded}, Failed: {failed}")
        ui.console.print()
        ui.console.print("Missing agents? Run: docket install")
    else:
        ui.success(f"All specialists upgraded! ({upgraded} agents)")

    ui.console.print()
    ui.info("Restarting gateway to apply changes...")
    _do_restart_gateway()
    ui.console.print()
    ui.success("DOCKET upgrade complete!")
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
    ui.info("Mark done: docket team done <id>  |  Start: docket team start <id>  |  Cancel: docket team cancel <id>")
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
                steps = sum(1 for ln in wf.read_text(encoding="utf-8").splitlines() if ln.startswith("  - "))
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
        ui.console.print(f"  2. Run workflow:  lobster run --workspace {ws} --workflow {workflow_name}")
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
        ui.error(f"Unknown action '{action}'.  Use: list, create, show, or delete")
        raise typer.Exit(1)


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


# ── utilities ──────────────────────────────────────────────────────────────────
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

    # ── memory logs ──────────────────────────────────────────────────────────
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

    # ── gateway log (today's) ─────────────────────────────────────────────────
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
            ui.console.print(f"[bold]Gateway log:[/bold] {len(matched)} entries today for group {tg_peer}")
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
