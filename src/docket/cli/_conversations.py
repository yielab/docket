"""``docket conversations`` — inspect and resume the conversation registry.

docket-owned view over ``core/conversations.py``. Since OpenClaw keeps no durable
transcript, this is where an operator sees which channel threads exist, what each is
about, and resumes one (marks it in-progress and prints a brief for the agent/dispatch
to pick up). Populated by ``docket wire`` (on binding) and ``docket conversations
set/resume``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.core import conversations as _conv


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _flag(args: list[str], name: str) -> str | None:
    """Return the value after ``--name`` (or ``--name=value``), else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def run_conversations(sub: str | None, args: list[str]) -> int:
    """Dispatch ``docket conversations <sub> ...``. Returns a process exit code."""
    sub = (sub or "list").lower()
    if sub == "list":
        return _list()
    if sub == "show":
        return _show(args)
    if sub == "resume":
        return _resume(args)
    if sub == "set":
        return _set(args)
    ui.error(f"Unknown subcommand '{sub}'. Use: list | show | resume | set.")
    return 1


def _list() -> int:
    reg = _conv.load()
    convs = _conv.ordered(reg)
    if not convs:
        ui.header("Conversations")
        ui.console.print()
        ui.info("No conversations tracked yet.")
        ui.console.print(
            "  They are registered when you wire an agent to a channel "
            "(docket wire) or with: docket conversations set <agent> <peer> --topic ..."
        )
        ui.console.print()
        return 0
    table = Table(title="Conversations")
    table.add_column("AGENT", style="bold")
    table.add_column("CHANNEL")
    table.add_column("PEER", style="dim")
    table.add_column("TOPIC")
    table.add_column("STATUS")
    table.add_column("UPDATED", style="dim")
    for c in convs:
        table.add_row(
            c.agent_id,
            c.channel,
            c.peer_id,
            c.topic or "—",
            c.status.value,
            (c.updated[:16] or "—"),
        )
    ui.console.print(table)
    return 0


def _find(reg: _conv.ConversationRegistry, ident: str) -> _conv.Conversation | None:
    """Resolve *ident* as a full conversation id or a bare agent id (first match)."""
    direct = _conv.get(reg, ident)
    if direct is not None:
        return direct
    matches = _conv.by_agent(reg, ident)
    return _conv.ordered(_conv.ConversationRegistry(conversations=matches))[0] if matches else None


def _show(args: list[str]) -> int:
    if not args:
        ui.error("Usage: docket conversations show <id|agent-id>")
        return 1
    conv = _find(_conv.load(), args[0])
    if conv is None:
        ui.error(f"No conversation matching '{args[0]}'.")
        return 1
    ui.header(f"Conversation — {conv.agent_id}")
    ui.console.print()
    for label, val in (
        ("Id", conv.id),
        ("Agent", conv.agent_id),
        ("Channel", conv.channel),
        ("Peer", f"{conv.peer_id} ({conv.peer_kind})"),
        ("Topic", conv.topic or "—"),
        ("Status", conv.status.value),
        ("Task ref", conv.task_ref or "—"),
        ("Last message", conv.last_message or "—"),
        ("Updated", conv.updated or "—"),
    ):
        ui.console.print(f"  [bold]{label + ':':<14}[/bold] {val}")
    ui.console.print()
    return 0


def _resume(args: list[str]) -> int:
    if not args:
        ui.error("Usage: docket conversations resume <id|agent-id>")
        return 1
    reg = _conv.load()
    conv = _find(reg, args[0])
    if conv is None:
        ui.error(f"No conversation matching '{args[0]}'.")
        return 1
    resumed, reg = _conv.resume(reg, conv.id, _now())
    _conv.save(reg)
    assert resumed is not None
    ui.success(f"Resuming conversation with '{resumed.agent_id}' (status → in_progress).")
    ui.console.print()
    ui.console.print(f"  [bold]Topic:[/bold]        {resumed.topic or '—'}")
    ui.console.print(f"  [bold]Task ref:[/bold]     {resumed.task_ref or '—'}")
    ui.console.print(f"  [bold]Last message:[/bold] {resumed.last_message or '—'}")
    ws = _cfg.workspace_dir(resumed.agent_id)
    if ws.is_dir():
        ui.console.print()
        ui.dim(f"  Durable context lives in {ws}/HEARTBEAT.md and memory/ — the agent")
        ui.dim("  resumes unchecked HEARTBEAT tasks on its next turn (durability contract).")
    ui.console.print()
    return 0


def _set(args: list[str]) -> int:
    """docket conversations set <agent-id> <peer-id> [--topic .. --status .. --last .. --task ..]"""
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) < 2:
        ui.error(
            "Usage: docket conversations set <agent-id> <peer-id> "
            "[--topic <t>] [--status active|in_progress|waiting|done] [--last <msg>] [--task <ref>]"
        )
        return 1
    agent_id, peer_id = positional[0], positional[1]
    status_raw = _flag(args, "--status")
    status = None
    if status_raw is not None:
        try:
            status = _conv.ConversationStatus(status_raw)
        except ValueError:
            ui.error(f"Invalid status '{status_raw}'. Use: active | in_progress | waiting | done.")
            return 1
    reg = _conv.load()
    conv, reg = _conv.record(
        reg,
        agent_id=agent_id,
        peer_id=peer_id,
        now=_now(),
        topic=_flag(args, "--topic"),
        status=status,
        last_message=_flag(args, "--last"),
        task_ref=_flag(args, "--task"),
    )
    _conv.save(reg)
    ui.success(f"Recorded conversation '{conv.id}' (status {conv.status.value}).")
    return 0
