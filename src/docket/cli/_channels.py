"""docket channels -- list, inspect and turn on a notification/conversation/decision
destination.

`core/channel.py` owns the `kind: channel` document, the merged catalog and validation; this
module renders those results and applies `--set key=value` overrides -- the same split
`cli/_exporters.py` keeps from `core/exporter.py`. Delivery (an actual send) is out of scope
for this module; see `core/channel.py`'s module docstring.
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Any

from docket import ui
from docket.core import channel as _chan
from docket.core.audit import audit_log

# `--set key=value` keys that go onto a top-level list field instead of `config`.
_LIST_KEYS = {"actors": "actors"}


def run_channels(action: str, args: list[str]) -> int:
    """Dispatch one `docket channels <action> ...` call. Returns a process exit code."""
    handlers = {
        "list": _run_list,
        "show": _run_show,
        "enable": _run_enable,
        "disable": _run_disable,
        "add": _run_add,
        "remove": _run_remove,
        "export": _run_export,
        "content": _run_content,
    }
    handler = handlers.get(action)
    if handler is None:
        ui.error(
            f"Unknown channels action '{action}'.\n"
            "Usage:\n"
            "  docket channels list [--json]\n"
            "  docket channels show <name> [--json]\n"
            "  docket channels enable <name> [--set k=v ...]\n"
            "  docket channels disable <name>\n"
            "  docket channels add <file.yaml>\n"
            "  docket channels remove <name>\n"
            "  docket channels export <name> [<file>]\n"
            "  docket channels content <name> [<level>] [--yes]"
        )
        return 1
    return handler(args)


def _parse_sets(args: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split *args* into positionals and repeated `--set key=value` overrides -- distinct
    from `_parse_opts` (a fixed `--flag value` shape) because the same option repeats with a
    different key each time."""
    pos: list[str] = []
    sets: dict[str, str] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--set":
            raw = args[i + 1] if i + 1 < len(args) else ""
            i += 2
        elif tok.startswith("--set="):
            raw = tok[len("--set=") :]
            i += 1
        else:
            pos.append(tok)
            i += 1
            continue
        if "=" in raw:
            key, value = raw.split("=", 1)
            sets[key] = value
    return pos, sets


def _apply_sets(spec: _chan.ChannelSpec, sets: dict[str, str]) -> dict[str, Any]:
    """Turn `--set key=value` pairs into a model-shaped overrides dict: `actors` becomes a
    comma-split list on the top-level field, every other key lands in `config`."""
    overrides: dict[str, Any] = {}
    config = dict(spec.config)
    for key, value in sets.items():
        if key in _LIST_KEYS:
            overrides[_LIST_KEYS[key]] = [v.strip() for v in value.split(",") if v.strip()]
        elif key == "secret":
            overrides["secret"] = value
        else:
            config[key] = value
    if config != spec.config:
        overrides["config"] = config
    return overrides


def _run_list(args: list[str]) -> int:
    json_out = "--json" in args
    catalog = _chan.load_catalog()

    if json_out:
        rows = []
        for name in sorted(catalog.entries):
            spec = catalog.entries[name]
            rows.append(
                {
                    "name": name,
                    "dialect": spec.dialect,
                    "enabled": spec.enabled,
                    "capabilities": list(spec.capabilities),
                    "content": spec.content,
                    "scope": catalog.source_of(name),
                }
            )
        ui.console.print(_json.dumps(rows, indent=2))
        return 0

    if not catalog.entries:
        ui.console.print("No channels registered.")
        return 0

    ui.header("Channels")
    ui.console.print()
    fmt = "  {:<10}  {:<9}  {:<9}  {:<24}  {:<13}  {}"
    ui.console.print(
        f"[bold]{fmt.format('NAME', 'DIALECT', 'STATE', 'CAPABILITIES', 'CONTENT', 'SCOPE')}[/bold]"
    )
    for name in sorted(catalog.entries):
        spec = catalog.entries[name]
        state = "enabled" if spec.enabled else "disabled"
        ui.console.print(
            fmt.format(
                name,
                spec.dialect,
                state,
                ", ".join(spec.capabilities) or "-",
                spec.content,
                catalog.source_of(name),
            )
        )
    return 0


def _run_show(args: list[str]) -> int:
    pos, sets = _parse_sets(args)
    json_out = "--json" in pos
    pos = [p for p in pos if p != "--json"]
    if not pos:
        ui.error("Usage: docket channels show <name> [--json]")
        return 1
    del sets  # show takes no --set overrides

    name = pos[0]
    catalog = _chan.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown channel '{name}'.")
        return 1
    scope = catalog.source_of(name)

    if json_out:
        payload = {"scope": scope, **spec.model_dump(by_alias=True)}
        ui.console.print(_json.dumps(payload, indent=2))
        return 0

    ui.header(f"Channel: {name} ({scope})")
    ui.console.print()
    ui.console.print(f"  dialect        {spec.dialect}")
    ui.console.print(f"  enabled        {spec.enabled}")
    ui.console.print(f"  capabilities   {', '.join(spec.capabilities) or '-'}")
    ui.console.print(f"  on             {', '.join(spec.on) or '-'}")
    ui.console.print(f"  content        {spec.content}")
    ui.console.print(f"  actors         {', '.join(spec.actors) or '-'}")
    if spec.config:
        for key, value in spec.config.items():
            ui.console.print(f"  config.{key:<7} {value or '(empty)'}")
    if spec.secret:
        ui.console.print(f"  secret         {spec.secret}")
    if spec.description:
        ui.console.print()
        ui.console.print(f"  {spec.description}")
    return 0


def _run_enable(args: list[str]) -> int:
    pos, sets = _parse_sets(args)
    if not pos:
        ui.error("Usage: docket channels enable <name> [--set k=v ...]")
        return 1
    name = pos[0]

    if "content" in sets:
        ui.error("Use `docket channels content <name> <level>` to change content, not --set.")
        return 1

    catalog = _chan.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown channel '{name}'.")
        return 1

    overrides = _apply_sets(spec, sets)
    try:
        enabled_spec = _chan.enable_channel(name, overrides)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        return 1
    ui.success(f"Channel enabled: {name}  ({enabled_spec.dialect})")
    ui.console.print(
        f"  scope: global  capabilities: {', '.join(enabled_spec.capabilities) or '-'}"
        f"  content: {enabled_spec.content}"
    )
    return 0


def _run_disable(args: list[str]) -> int:
    pos, _sets = _parse_sets(args)
    if not pos:
        ui.error("Usage: docket channels disable <name>")
        return 1
    name = pos[0]
    try:
        _chan.disable_channel(name)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        return 1
    ui.success(f"Channel disabled: {name}")
    return 0


def _run_add(args: list[str]) -> int:
    pos, _sets = _parse_sets(args)
    if not pos:
        ui.error("Usage: docket channels add <file.yaml>")
        return 1
    try:
        spec = _chan.load_channel_document(pos[0])
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        return 1

    _chan.save_channel(spec)
    audit_log("channel.added", f"name={spec.name} dialect={spec.dialect}")
    ui.success(f"Channel added: {spec.name}  ({spec.dialect})")
    return 0


def _run_remove(args: list[str]) -> int:
    pos, _sets = _parse_sets(args)
    if not pos:
        ui.error("Usage: docket channels remove <name>")
        return 1
    name = pos[0]
    try:
        _chan.delete_channel(name)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        return 1
    audit_log("channel.removed", f"name={name}")
    ui.success(f"Removed channel '{name}'.")
    return 0


def _run_export(args: list[str]) -> int:
    pos, _sets = _parse_sets(args)
    if not pos:
        ui.error("Usage: docket channels export <name> [<file>]")
        return 1
    try:
        text = _chan.export_channel(pos[0])
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        return 1
    if len(pos) > 1:
        Path(pos[1]).write_text(text, encoding="utf-8")
        ui.success(f"Exported '{pos[0]}' to {pos[1]}")
    else:
        ui.console.print(text, end="")
    return 0


def _confirm_widening(name: str, old_level: str, new_level: str, yes: bool) -> bool:
    """A widening content change is a confirmed command, never a silent write. ``--yes``
    proceeds immediately; otherwise a TTY is asked `y/N` (anything but `y` refuses) and a
    non-TTY refuses naming ``--yes`` without asking."""
    if yes:
        return True
    ui.warn(f"'{name}' will widen content from '{old_level}' to '{new_level}'.")
    if not sys.stdin.isatty():
        ui.error(f"Refusing to widen '{name}' off a TTY without --yes.")
        return False
    answer = input("Continue? [y/N] ").strip().lower()
    return answer == "y"


def _run_content(args: list[str]) -> int:
    yes = "--yes" in args
    args = [a for a in args if a != "--yes"]
    pos, _sets = _parse_sets(args)
    if not pos:
        ui.error("Usage: docket channels content <name> [<level>] [--yes]")
        return 1
    name = pos[0]
    level = pos[1] if len(pos) > 1 else None

    catalog = _chan.load_catalog()
    spec = catalog.get(name)
    if spec is None:
        ui.error(f"Unknown channel '{name}'.")
        return 1

    if level is None:
        ui.header(f"Channel: {name}")
        ui.console.print(f"  content: {spec.content}")
        return 0

    if level not in ("minimal", "actions", "conversation"):
        ui.error(f"'{level}' is not a known content level (valid: minimal, actions, conversation)")
        return 1

    if _chan.is_widening(spec.content, level) and not _confirm_widening(
        name, spec.content, level, yes
    ):
        return 1

    try:
        updated = _chan.set_content(name, level)
    except _chan.ChannelError as exc:
        ui.error(str(exc))
        return 1

    ui.success(f"Channel content updated: {name}")
    ui.console.print(f"  content: {updated.content}")
    return 0
