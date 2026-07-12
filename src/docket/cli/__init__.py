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
from docket.core import models_policy as _mp
from docket.core.utils import (
    aggregate_cost,
    gateway_active,
    last_activity,
    openclaw_version,
    project_ids,
    restart_gateway,
    scan_telegram_groups,
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
    gates: bool = typer.Option(
        True,
        "--gates/--no-gates",
        help="Exec-approval gates (on by default; use --no-gates to opt out)",
    ),
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
    from docket.cli._agents import run_add

    raise typer.Exit(run_add(list(ctx.args)))


@app.command("info")
def cmd_info(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Detailed status of one agent."""
    from docket.cli._agents import run_info

    raise typer.Exit(run_info(agent_id, json_out))


@app.command("delete")
def cmd_delete(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove a project agent or a whole pod, and optionally its workspace."""
    from docket.cli._agents import run_delete

    raise typer.Exit(run_delete(agent_id))


def _delete_pod(project: str, members: list[str]) -> int:
    """Tear down every member of a pod. One gateway restart at the end.

    Kept here (rather than in ``cli/_agents.py``, which owns the rest of the
    delete flow) because ``tests/python/test_pod_provisioning.py`` calls it
    directly as ``docket.cli._delete_pod`` — moving it would be a rename, not
    a mechanical extraction. ``_agents.run_delete`` reaches back for it with a
    deferred import, the same convention used for ``_pick_agent`` et al.
    """
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
            return 0

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
    """Maintain an agent workspace (check/clean/reset/rebuild/sessions)."""
    from docket.cli._agents import run_maintain

    raise typer.Exit(run_maintain(agent_id, mode))


@app.command(
    "context",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_context(
    ctx: typer.Context,
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
) -> None:
    """Agent context views (show/project)."""
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
    """Claude model authentication (status/login/key/setup)."""
    from docket.cli._keys import run_auth

    raise typer.Exit(run_auth(sub, list(ctx.args)))


@app.command(
    "models",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def cmd_models(ctx: typer.Context) -> None:
    """View and edit the role→model policy."""
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
    sub: str | None = typer.Argument(
        None,
        help="list | add <role> [--verify CMD] | remove <member-id> | set-verify <member-id> CMD",
    ),
) -> None:
    """Manage a project's pod: list members, add/remove a role, or set an implementer's verify command."""
    from docket.cli import _pod

    _pod.dispatch(project, sub, list(ctx.args))


@app.command("workflow")
def cmd_workflow(
    agent_id: str | None = typer.Argument(None),
    sub: str | None = typer.Argument(None),
    workflow_name: str | None = typer.Argument(None),
) -> None:
    """Manage Lobster YAML pipelines (list/create/show/delete)."""
    from docket.cli._workflow import run_workflow

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

    raise typer.Exit(run_workflow(aid, ws, sub, workflow_name))


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
    from docket.cli._cost import run_cost

    raise typer.Exit(run_cost(agent_id, json_out=json_out, history=history, days=days))


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
