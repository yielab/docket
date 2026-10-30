"""The ``setup secret`` group: store, list and remove a secret under any name."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from docket.governance import secrets as _secrets
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.setup_model_credentials import credential_remove
from docket.interfaces.cli.render import ui
from docket.kernel import mcp as _mcp
from docket.kernel.errors import Unavailable

secret_app = typer.Typer(
    name="secret",
    help="Secrets stored under any name, for a secret:<name> reference to resolve.",
    no_args_is_help=True,
)

_NAME = Annotated[str, typer.Argument(help="The secret's name: letters, digits, '-', '_', '.'.")]


def _checked_name(name: str) -> str:
    """*name* unchanged, or exit 1 without repeating it: a pasted value is not a name."""
    if not _mcp.SECRET_NAME_RE.fullmatch(name):
        ui.error("Not a valid secret name", "Use letters, digits, '-', '_' and '.'")
        raise typer.Exit(1)
    return name


def _read_value(name: str, from_stdin: bool) -> str:
    """The value from standard input or a hidden prompt, never from an argument."""
    if from_stdin:
        return sys.stdin.read().strip()
    if not _contract.is_tty():
        ui.error(
            "No terminal to ask for the value", f"Pipe it: docket setup secret set {name} --stdin"
        )
        raise typer.Exit(1)
    try:
        given: str = typer.prompt(
            f"Enter value for {name} (hidden)", hide_input=True, default="", show_default=False
        )
        return given.strip()
    except typer.Abort:
        ui.warn("Aborted.")
        raise typer.Exit(1) from None


@secret_app.command("set")
def cmd_set(
    name: _NAME,
    refused: Annotated[str | None, typer.Argument(hidden=True)] = None,
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Read the value from standard input.")
    ] = False,
) -> None:
    """Store a secret; the value comes from a hidden prompt or --stdin, never an argument.

    Example: printf '%s' "$TOKEN" | docket setup secret set service-token --stdin"""
    if refused is not None:
        ui.error(
            "A secret's value is never an argument",
            f"Pipe it: docket setup secret set {_checked_name(name)} --stdin",
        )
        raise typer.Exit(2)
    _checked_name(name)
    value = _read_value(name, stdin)
    if not value:
        ui.error("Value cannot be empty")
        raise typer.Exit(1)
    try:
        _secrets.store_secret(name, value)
    except Unavailable as exc:
        ui.error(exc.message, exc.hint)
        raise typer.Exit(1) from exc
    ui.success(f"Stored {name}.")


@secret_app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List stored secrets: names and dates, never values.

    Example: docket setup secret list"""
    meta = _secrets.load_secrets_meta()
    entries = []
    for name in sorted(_secrets.load_secrets()):
        entry = meta.get(name)
        entry = entry if isinstance(entry, dict) else {}
        entries.append(
            {
                "name": name,
                "added_at": str(entry.get("added_at", "")),
                "rotated_at": str(entry.get("rotated_at", "")),
            }
        )
    if json_out:
        _contract.emit_json(entries)
        return
    if not entries:
        ui.info("No secrets stored.")
        return
    ui.table(
        [[e["name"], e["added_at"], e["rotated_at"]] for e in entries], ["Name", "Added", "Rotated"]
    )


@secret_app.command("remove")
def cmd_remove(name: _NAME) -> None:
    """Delete a stored secret.

    Example: docket setup secret remove service-token"""
    if credential_remove(_checked_name(name)) != 0:
        raise typer.Exit(1)
    ui.success(f"Removed {name}.")
