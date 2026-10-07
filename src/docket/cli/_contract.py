"""The interaction contract every command follows: confirm, emit JSON, require a value, hint.

Off a TTY nothing prompts: a missing confirmation or value is a one-line refusal naming the
flag that supplies it.
"""

from __future__ import annotations

import json
import os
import sys

import typer

from docket import ui


def _is_tty() -> bool:
    return sys.stdin.isatty()


def confirm(action: str, *, yes: bool, typed: str | None = None) -> bool:
    """True when the operator confirmed ``action``; refuses (exit 1) off a TTY without consent."""
    if yes:
        return True
    if not _is_tty():
        flag = f"--confirm {typed}" if typed is not None else "--yes"
        ui.error(f"{action} needs confirmation", f"Re-run with {flag}")
        raise typer.Exit(1)
    if typed is not None:
        return input(f"{action}. Type {typed} to confirm: ").strip() == typed
    return input(f"{action}. Continue? [y/N]: ").strip().lower() in ("y", "yes")


def emit_json(obj: object) -> None:
    """Plain JSON on stdout; never Rich."""
    sys.stdout.write(json.dumps(obj, indent=2) + "\n")


def require_value(name: str, value: str | None, flag: str) -> str:
    """Return ``value``; with none, exit 1 naming ``flag``. Never opens a picker."""
    if value:
        return value
    ui.error(f"{name} is required", f"Pass {flag}")
    raise typer.Exit(1)


def next_step(command: str) -> None:
    """The single ``Next:`` line on stderr; silent under ``DOCKET_NO_HINTS=1``."""
    if os.environ.get("DOCKET_NO_HINTS") == "1":
        return
    ui.hint(command)
