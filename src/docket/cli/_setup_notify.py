"""The ``setup notify`` group: channels, Telegram in one step, bindings and the flush."""

from __future__ import annotations

import datetime as _dt
import getpass as _getpass
import os
import secrets as _token_secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.core import channel as _chan
from docket.core import conversations as _conv
from docket.core import fleet as _fleet
from docket.core import inbox as _inbox
from docket.core import notify as _notify
from docket.core import pod as _pod
from docket.core import secrets as _secrets
from docket.core import telegram as _telegram
from docket.core.audit import audit_log
from docket.edges.adapters import channels as _channels
from docket.edges.adapters import system as _system

notify_app = typer.Typer(
    name="notify",
    help="Notification channels: Telegram in one step, desktop, ntfy, webhooks.",
    no_args_is_help=True,
)

_LEVELS = ("minimal", "actions", "conversation")
_TOKEN_NAME = _cfg.TELEGRAM_BOT_TOKEN_KEY


class NotifySetupError(Exception):
    """A setup step that cannot proceed; nothing was written."""


@dataclass(frozen=True)
class Written:
    """What ``enable_telegram`` wrote, store by store."""

    secret: str = ""
    actors: list[str] = field(default_factory=list)
    bindings: list[str] = field(default_factory=list)
    test: str = ""


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _spec_or_exit(name: str) -> _chan.ChannelSpec:
    spec = _chan.load_catalog().get(name)
    if spec is None:
        ui.error(f"Unknown channel '{name}'", "Run: docket setup notify list")
        raise typer.Exit(1)
    return spec


def _apply_sets(spec: _chan.ChannelSpec, sets: list[str]) -> dict[str, Any]:
    """Turn ``key=value`` pairs into a model-shaped overrides dict."""
    overrides: dict[str, Any] = {}
    config = dict(spec.config)
    for raw in sets:
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key == "actors":
            overrides["actors"] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "secret":
            overrides["secret"] = value
        else:
            config[key] = value
    if config != spec.config:
        overrides["config"] = config
    return overrides


def send_test(name: str) -> int:
    """Send one synthetic event through one channel and report; the only send besides flush."""
    spec = _spec_or_exit(name)
    deliver = _channels.sink_for(spec)
    if deliver is None:
        ui.error(f"Channel '{name}' has dialect '{spec.dialect}', which has no delivery yet")
        return 1
    event = _notify.build_test_event(spec, now=_now())
    result = deliver(spec, event, secret=_notify.resolve_secret(spec), timeout=5.0)
    if result.ok:
        ui.success(f"Test delivered to '{name}' ({spec.dialect}).")
        return 0
    ui.error(f"Test delivery to '{name}' failed: {result.error or 'unknown error'}")
    return 1


def store_secret(name: str, value: str) -> None:
    """Write one credential to the 0600 secret store (or the OS keyring when requested)."""
    secrets = _secrets.load_secrets()
    keyring = _cfg.secrets_backend_requested() == "keyring" and _system.secret_tool_available()
    if keyring:
        if not _system.secret_tool_store(_cfg.KEYRING_SERVICE, name, value):
            raise NotifySetupError(f"the OS keyring refused {name}; nothing was written")
        secrets[name] = ""
    else:
        secrets[name] = value
    _secrets.save_secrets(secrets)
    _secrets.touch_meta(name, "added")
    audit_log("keys.add", name)


def lead_ids() -> list[str]:
    """Every registered pod Lead, in fleet order."""
    leads: list[str] = []
    for aid in _fleet.all_agent_ids():
        project = _pod.pod_of(aid)
        parsed = _pod.parse_member_id(aid, project) if project else None
        if parsed is not None and parsed[0] == "lead":
            leads.append(aid)
    return leads


def _bind(agent_id: str, peer_id: str, channel: str) -> None:
    _fleet.upsert_binding(agent_id, peer_id, channel)
    _conv.record_durable(agent_id=agent_id, peer_id=peer_id, channel=channel, now=_now())


def enable_telegram(chat_ids: list[str], token: str | None, *, test: bool) -> Written:
    """Connect Telegram in one operation; a None token keeps the stored one.

    Every check runs before the first write; a message goes out only with ``test``."""
    chats = [c.strip() for c in chat_ids if c.strip()]
    if not chats:
        raise NotifySetupError("telegram needs at least one chat id; pass --chat <id>")
    if token is None and _secrets.secret_value(_TOKEN_NAME) is None:
        raise NotifySetupError(f"no {_TOKEN_NAME} is stored; pass --token or set it in the env")
    try:
        spec = _chan.enable_channel("telegram", {"actors": chats})
    except _chan.ChannelError as exc:
        raise NotifySetupError(str(exc)) from exc
    stored = ""
    if token is not None:
        store_secret(_TOKEN_NAME, token)
        stored = _TOKEN_NAME
    leads = lead_ids()
    for aid in leads:
        _bind(aid, chats[0], "telegram")
    outcome = ""
    if test:
        deliver = _channels.sink_for(spec)
        if deliver is None:
            outcome = "failed: no delivery for this dialect"
        else:
            result = deliver(
                spec,
                _notify.build_test_event(spec, now=_now()),
                secret=_notify.resolve_secret(spec),
                timeout=5.0,
            )
            outcome = "delivered" if result.ok else f"failed: {result.error or 'unknown error'}"
    return Written(secret=stored, actors=list(spec.actors), bindings=leads, test=outcome)


def _resolve_token(token: str | None) -> str | None:
    """Flag, then env, then (when nothing is stored) a hidden prompt on a TTY."""
    given = (token or os.environ.get(_TOKEN_NAME, "")).strip()
    if given:
        return given
    if _secrets.secret_value(_TOKEN_NAME) is not None:
        return None
    if not _contract._is_tty():
        ui.error(f"{_TOKEN_NAME} is not set", "Pass --token or export it")
        raise typer.Exit(1)
    entered = _getpass.getpass(f"Enter value for {_TOKEN_NAME} (hidden): ").strip()
    if not entered:
        ui.error("The bot token cannot be empty", "Pass --token")
        raise typer.Exit(1)
    return entered


@notify_app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List every channel with its dialect, state and content level.

    Example: docket setup notify list"""
    catalog = _chan.load_catalog()
    names = sorted(catalog.entries)
    if json_out:
        rows = [
            {
                "name": n,
                "dialect": catalog.entries[n].dialect,
                "enabled": catalog.entries[n].enabled,
                "capabilities": list(catalog.entries[n].capabilities),
                "content": catalog.entries[n].content,
                "scope": catalog.source_of(n),
            }
            for n in names
        ]
        _contract.emit_json(rows)
        return
    if not names:
        ui.info("No channels registered.")
        return
    ui.header("Channels")
    ui.table(
        [
            [
                n,
                catalog.entries[n].dialect,
                "enabled" if catalog.entries[n].enabled else "disabled",
                ", ".join(catalog.entries[n].capabilities) or "-",
                catalog.entries[n].content,
                catalog.source_of(n),
            ]
            for n in names
        ],
        ["NAME", "DIALECT", "STATE", "CAPABILITIES", "CONTENT", "SCOPE"],
    )


def _show_telegram_extras() -> None:
    ui.section("Bindings")
    bound = [(a, _fleet.get_binding(a, "telegram")) for a in _fleet.all_agent_ids()]
    bound = [(a, p) for a, p in bound if p]
    if not bound:
        ui.dim("  none")
    for aid, peer in bound:
        ui.console.print(f"  {aid}  chat {peer}", markup=False)
    ui.section("Conversations")
    convs = [c for c in _conv.ordered(_conv.load()) if c.channel == "telegram"]
    if not convs:
        ui.dim("  none")
    for c in convs:
        line = f"  {c.agent_id}  {c.peer_id}  {c.status.value}  {c.topic or '-'}"
        ui.console.print(line, markup=False)


@notify_app.command("show")
def cmd_show(
    name: str = typer.Argument(..., help="Channel name"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show one channel's effective document; telegram adds bindings and conversations.

    Example: docket setup notify show telegram"""
    catalog = _chan.load_catalog()
    spec = _spec_or_exit(name)
    scope = catalog.source_of(name)
    if json_out:
        _contract.emit_json({"scope": scope, **spec.model_dump(by_alias=True)})
        return
    ui.header("Channel", f"{name} ({scope})")
    rows = [
        ["dialect", spec.dialect],
        ["enabled", str(spec.enabled)],
        ["capabilities", ", ".join(spec.capabilities) or "-"],
        ["on", ", ".join(spec.on) or "-"],
        ["content", spec.content],
        ["actors", ", ".join(spec.actors) or "-"],
    ]
    rows += [[f"config.{k}", str(v) or "(empty)"] for k, v in spec.config.items()]
    if spec.secret:
        rows.append(["secret", spec.secret])
    ui.table(rows, ["FIELD", "VALUE"])
    if spec.description:
        ui.dim(f"  {spec.description}")
    if name == "telegram":
        _show_telegram_extras()


@notify_app.command("enable")
def cmd_enable(
    name: str = typer.Argument(..., help="Channel name"),
    sets: list[str] = typer.Option([], "--set", help="Override key=value (repeatable)"),
    chat: list[str] = typer.Option([], "--chat", help="Telegram chat id (repeatable)"),
    token: str | None = typer.Option(None, "--token", help="Telegram bot token"),
    test: bool = typer.Option(False, "--test", help="Send one test message afterwards"),
) -> None:
    """Turn a channel on; telegram also stores the token and binds every pod Lead.

    Nothing is sent unless --test is passed.
    Example: docket setup notify enable telegram --chat 42 --test"""
    spec = _spec_or_exit(name)
    if name != "telegram" and (chat or token):
        ui.error("--chat and --token apply to telegram only", "Use --set key=value")
        raise typer.Exit(1)
    if "content" in [s.split("=", 1)[0] for s in sets]:
        ui.error("--set content is not accepted", "Use: docket setup notify privacy")
        raise typer.Exit(1)
    if name == "telegram":
        actors = list(chat) + [
            a for s in sets if s.startswith("actors=") for a in s[7:].split(",") if a.strip()
        ]
        try:
            resolved = _resolve_token(token) if actors else None
            written = enable_telegram(actors, resolved, test=test)
        except NotifySetupError as exc:
            ui.error(str(exc))
            raise typer.Exit(1) from exc
        ui.success("Telegram connected.")
        if written.secret:
            ui.console.print(f"  secrets.json     {written.secret}", markup=False)
        ui.console.print(f"  channel catalog  actors {', '.join(written.actors)}", markup=False)
        ui.console.print(
            f"  fleet.json       {', '.join(written.bindings) or 'no pod Lead to bind'}",
            markup=False,
        )
        if written.test:
            ui.console.print(f"  test message     {written.test}", markup=False)
        if written.test.startswith("failed"):
            raise typer.Exit(1)
        _contract.next_step("docket setup notify show telegram")
        return
    try:
        enabled = _chan.enable_channel(name, _apply_sets(spec, sets))
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(f"Channel enabled: {name} ({enabled.dialect})")
    if test and send_test(name):
        raise typer.Exit(1)
    _contract.next_step(f"docket setup notify test {name}")


@notify_app.command("disable")
def cmd_disable(name: str = typer.Argument(..., help="Channel name")) -> None:
    """Turn a channel off; stored keys and bindings are kept.

    Example: docket setup notify disable ntfy"""
    try:
        _chan.disable_channel(name)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(f"Channel disabled: {name}")
    _contract.next_step("docket setup notify list")


@notify_app.command("add")
def cmd_add(file: Path = typer.Argument(..., help="A kind: channel YAML document")) -> None:
    """Add a channel from a document.

    Example: docket setup notify add ./my-channel.yaml"""
    try:
        spec = _chan.load_channel_document(file)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    _chan.save_channel(spec)
    audit_log("channel.added", f"name={spec.name} dialect={spec.dialect}")
    ui.success(f"Channel added: {spec.name} ({spec.dialect})")
    _contract.next_step(f"docket setup notify enable {spec.name}")


@notify_app.command("remove")
def cmd_remove(
    name: str = typer.Argument(..., help="Channel name"),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation"),
) -> None:
    """Remove a channel document.

    Example: docket setup notify remove my-webhook --yes"""
    if _chan.load_catalog().source_of(name) == "built-in":
        ui.error(f"'{name}' is a built-in channel with no global override", "Nothing to remove")
        raise typer.Exit(1)
    if not _contract.confirm(f"Remove channel '{name}'", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    try:
        _chan.delete_channel(name)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    audit_log("channel.removed", f"name={name}")
    ui.success(f"Removed channel '{name}'.")
    _contract.next_step("docket setup notify list")


@notify_app.command("export")
def cmd_export(
    name: str = typer.Argument(..., help="Channel name"),
    file: Path | None = typer.Argument(None, help="Write here instead of stdout"),
) -> None:
    """Print or write one channel document.

    Example: docket setup notify export telegram ./telegram.yaml"""
    try:
        text = _chan.export_channel(name)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    if file is None:
        typer.echo(text, nl=False)
        return
    file.write_text(text, encoding="utf-8")
    ui.success(f"Exported '{name}' to {file}")


@notify_app.command("privacy")
def cmd_privacy(
    name: str = typer.Argument(..., help="Channel name"),
    level: str | None = typer.Argument(None, help="minimal, actions or conversation"),
    yes: bool = typer.Option(False, "--yes", help="Confirm a widening change"),
) -> None:
    """Show or change how much a delivery carries; widening asks, narrowing never does.

    Example: docket setup notify privacy telegram actions --yes"""
    spec = _spec_or_exit(name)
    if level is None:
        ui.header("Channel", name)
        ui.console.print(f"  content: {spec.content}", markup=False)
        return
    if level not in _LEVELS:
        ui.error(f"'{level}' is not a content level", f"Use one of: {', '.join(_LEVELS)}")
        raise typer.Exit(1)
    if _chan.is_widening(spec.content, level):
        ui.warn(f"'{name}' will widen content from '{spec.content}' to '{level}'.")
        if not _contract.confirm(f"Widen '{name}'", yes=yes):
            raise typer.Exit(1)
    try:
        updated = _chan.set_content(name, level)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(f"Channel content updated: {name} ({updated.content})")
    _contract.next_step(f"docket setup notify show {name}")


@notify_app.command("test")
def cmd_test(name: str = typer.Argument(..., help="Channel name")) -> None:
    """Send one synthetic test event through one channel.

    Example: docket setup notify test desktop"""
    raise typer.Exit(send_test(name))


def _discover_peer(label: str) -> str:
    """Guided group discovery (bot token required), then a manual entry fallback."""
    peer = ""
    if _telegram.wire_discovery_configured():
        challenge = _token_secrets.token_hex(3).upper()
        ui.console.print(f"  1. Add your docket bot to the group, then send: /wire {challenge}")
        entered = input("Press Enter after sending it, or paste the group ID: ").strip()
        if entered:
            return entered
        found = _telegram.discover_wire_groups(challenge)
        if not found.ok:
            ui.warn(f"Could not check Telegram: {found.error}")
        elif len(found.groups) == 1:
            peer = found.groups[0].chat_id
            ui.success(f"Found Telegram group {found.groups[0].title}".rstrip())
        elif found.groups:
            for i, group in enumerate(found.groups, 1):
                ui.console.print(f"  {i}) {group.title or group.chat_id}", markup=False)
            try:
                peer = found.groups[int(input("Choose a group number: ").strip()) - 1].chat_id
            except (ValueError, IndexError):
                ui.warn("Invalid selection; switching to manual entry.")
        else:
            ui.warn("No matching group message found; stop docket start if it is polling")
    return peer or input(f"{label} peer/group ID (or Enter to abort): ").strip()


@notify_app.command("bind")
def cmd_bind(
    member: str = typer.Argument(..., help="Pod member id, e.g. demo-lead"),
    channel: str = typer.Option("telegram", "--channel", help="Channel to bind"),
    chat: str | None = typer.Option(None, "--chat", help="Chat or group id"),
) -> None:
    """Bind one pod member to a chat (the per-pod exception to enable).

    The binding is the whole authorization boundary: anyone who can post in that chat can
    approve, deny and delegate as this member once docket is serving Telegram.
    Example: docket setup notify bind demo-lead --chat -100123"""
    if not _cfg.workspace_dir(member).is_dir():
        ui.error(f"Agent '{member}' not found", "Run: docket status --all")
        raise typer.Exit(1)
    peer = (chat or "").strip()
    if not peer:
        if not _contract._is_tty():
            ui.error("A chat id is required", "Pass --chat <id>")
            raise typer.Exit(1)
        existing = _fleet.get_binding(member, channel)
        if existing:
            ui.warn(f"Currently bound to: {existing}")
        peer = _discover_peer(channel.capitalize())
    if not peer:
        ui.warn("Aborted.")
        raise typer.Exit(0)
    _bind(member, peer, channel)
    ui.success(f"Binding: {member} <- {channel} chat {peer}")
    ui.dim("  This binding is the whole authorization story for that chat.")
    _contract.next_step("docket setup notify show telegram")


@notify_app.command("unbind")
def cmd_unbind(
    member: str = typer.Argument(..., help="Pod member id"),
    channel: str = typer.Option("telegram", "--channel", help="Channel to unbind"),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation"),
) -> None:
    """Remove a member's chat binding.

    Example: docket setup notify unbind demo-lead --yes"""
    if not _cfg.workspace_dir(member).is_dir():
        ui.error(f"Agent '{member}' not found", "Run: docket status --all")
        raise typer.Exit(1)
    peer = _fleet.get_binding(member, channel)
    if not peer:
        ui.warn(f"'{member}' has no {channel} binding.")
        return
    if not _contract.confirm(f"Remove the {channel} binding for chat {peer}", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(0)
    _fleet.remove_binding(member, channel)
    ui.success("Binding removed")
    _contract.next_step("docket setup notify show telegram")


@notify_app.command("flush")
def cmd_flush(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview, deliver nothing"),
) -> None:
    """Deliver new operator events to every enabled channel now.

    Example: docket setup notify flush --dry-run"""
    now = _now()
    if dry_run:
        events, _snapshot = _notify.diff_events(
            _notify.read_state(), _inbox.build_inbox(now=now), now
        )
        ui.header("Notify (dry run)")
        if not events:
            ui.dim("  Nothing to send.")
        for event in events:
            ui.console.print(
                f"  {event.kind}  pod={event.pod}  subject={event.subject}", markup=False
            )
        if events:
            ui.dim("  Nothing delivered; the dedupe snapshot was not touched.")
        return
    specs = list(_chan.load_catalog().entries.values())
    report = _notify.flush(specs, _channels.sink_for, now=now)
    if report.events == 0:
        ui.dim("Nothing to send.")
        return
    ui.success(
        f"Flushed: {report.events} event(s), {report.delivered} delivered, "
        f"{report.failed} failed, {report.skipped} skipped"
    )
    if report.failed:
        raise typer.Exit(1)
    _contract.next_step("docket inbox")
