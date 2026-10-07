"""The export setup commands.
Holds exporters."""

from __future__ import annotations

import typer


def cmd_exporters(ctx: typer.Context) -> None:
    """Observability export destinations: list, inspect, and enable by authenticating.

    Subcommands: `list [--json]` prints every catalog exporter's dialect,
    activation state, credential names and its privacy level (SHARES). `show
    <name> [--json]` prints one exporter's effective document, source, state,
    health counters and a "Leaves this host" disclosure of every content
    class. `enable <name> [--endpoint URL] [--privacy <level>|--share a,b]
    [--events ...] [--no-verify] [--yes]` prompts for a missing credential on
    a TTY (else names `docket keys add` and exits), probes the endpoint, and
    writes only the `enabled` flag plus the overrides given. `disable <name>`
    turns it back off; stored keys are kept. `test <name>` re-probes without
    changing anything. `add <file.yaml> [--no-verify] [--yes]` and `remove
    <name>` manage a full document; `export <name> [<file>]` prints or writes
    one back out. `privacy <name> [<level>|--share a,b] [--max-chars N]
    [--yes]` shows or changes what an exporter shares beyond bare structure;
    widening the shared classes prints what is newly granted and the
    destination host, then asks for confirmation on a TTY or refuses off one
    without `--yes` -- narrowing never asks. `preview <name> [--session <id>] [--level
    <level>|--share a,b] [--json]` projects a local session through the
    exporter's policy and prints what it would send -- no network call, no
    write."""
    from docket.cli._exporters import run_exporters

    args = list(ctx.args)
    action = args[0] if args else ""
    raise typer.Exit(run_exporters(action, args[1:]))
