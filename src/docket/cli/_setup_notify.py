"""The notification setup commands.
Holds channels, wire, unwire, notify and conversations."""

from __future__ import annotations

import sys

import typer

import docket.config as _cfg
from docket import ui
from docket.cli._agents import _pick_agent
from docket.core import fleet as _fleet


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
        # chat can /approve, /deny, /status, /delegate or /answer as '{aid}' the
        # moment the bot is running. There is no second allowlist step.
        ui.dim(
            "  This binding is the whole authorization story: whoever can post in this chat"
            f" can now /approve, /deny, /status, /delegate or /answer for '{aid}' once docket's own"
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


def cmd_conversations(ctx: typer.Context) -> None:
    """Inspect and resume the conversation registry (list/show/resume/set/prune).

    docket's durable index of channel threads: docket's own turn loop keeps
    no durable transcript of its own, so this registry tracks which agent
    handles each thread, its topic, status, and a resume pointer.

    Subcommands: `list` (default) all tracked conversations; `show <id|
    agent-id>` full detail for one; `resume <id|agent-id>` marks it
    in_progress and prints a resume brief; `set <agent-id> <peer-id>
    [--topic] [--status] [--last] [--task]` edits an entry directly;
    `prune [--dry-run] [--days N]` deletes `done` conversations past the
    retention window (default `TRACE_RETENTION_DAYS`) -- the same pruning
    `docket serve`'s periodic sweep already does.

    Auto-seeded when you `docket wire` an agent to a channel; cleaned up on
    `docket delete`. `status` is one of active | in_progress | waiting |
    done. Durable conversation content lives in the agent's HEARTBEAT.md +
    memory/ (resumed on its next turn via the durability contract); this
    registry tracks state only."""
    from docket.cli._conversations import run_conversations

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_conversations(sub, args[1:]))


def cmd_channels(ctx: typer.Context) -> None:
    """Notification/conversation/decision destinations: list, inspect, and enable.

    Subcommands: `list [--json]` prints every catalog channel's dialect,
    enabled state, capabilities and content level. `show <name> [--json]`
    prints one channel's effective document and scope. `enable <name> [--set
    k=v ...]` writes only the `enabled` flag plus the overrides given (`--set
    actors=a,b` sets the actors list, `--set secret=NAME` sets the credential
    name, anything else lands in `config`); it refuses without writing when a
    required field the built-in names is still empty (`ntfy` needs a
    non-empty `topic`, `telegram` needs a non-empty `actors`). `disable
    <name>` turns it back off. `add <file.yaml>` and `remove <name>` manage a
    full document; `export <name> [<file>]` prints or writes one back out.
    `content <name> [<level>] [--yes]` shows or changes how much a delivery
    carries (`minimal < actions < conversation`); widening prints the change
    and asks for confirmation on a TTY or refuses off one without `--yes` --
    narrowing never asks. `test <name>` sends one synthetic
    `dev.docket.channel.test` event through that one channel and reports
    success or failure -- useful to verify a webhook URL or a command binary
    before relying on it. Every other subcommand here only edits the catalog;
    `test` and `docket notify` are the only things in this command group that
    ever send anything."""
    from docket.cli._channels import run_channels

    args = list(ctx.args)
    action = args[0] if args else ""
    raise typer.Exit(run_channels(action, args[1:]))


def cmd_notify(ctx: typer.Context) -> None:
    """Flush operator events to every enabled channel.

    `docket serve`'s sweep and `docket pod <p> dispatch` already flush after every real
    state change; this command forces one in between, or previews it. `docket notify
    flush [--dry-run]` -- with no `--dry-run`, diffs the inbox against the last flush,
    delivers each new event (`dev.docket.task.*`/`approval.*`) to every enabled channel
    whose `on` matches, and prints the counts; `--dry-run` prints what would be sent
    without delivering or advancing the dedupe snapshot."""
    from docket.cli._notify import run_notify

    args = list(ctx.args)
    if args and not args[0].startswith("--"):
        action, rest = args[0], args[1:]
    else:
        action, rest = "", args
    raise typer.Exit(run_notify(action, rest))
