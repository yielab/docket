"""The interaction contract every command follows: confirm, emit JSON, hint.

Off a TTY nothing prompts: a missing confirmation is a one-line refusal naming the flag that
supplies it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from docket.interfaces.cli.commands.target import TargetError, resolve_pod
from docket.interfaces.cli.render import ui


def is_tty() -> bool:
    return sys.stdin.isatty()


def confirm(action: str, *, yes: bool, typed: str | None = None) -> bool:
    """True when the operator confirmed ``action``; refuses (exit 1) off a TTY without consent."""
    if yes:
        return True
    if not is_tty():
        flag = f"--confirm {typed}" if typed is not None else "--yes"
        ui.error(f"{action} needs confirmation", f"Re-run with {flag}")
        raise typer.Exit(1)
    if typed is not None:
        return input(f"{action}. Type {typed} to confirm: ").strip() == typed
    return input(f"{action}. Continue? [y/N]: ").strip().lower() in ("y", "yes")


def emit_json(obj: object) -> None:
    """Plain JSON on stdout; never Rich."""
    sys.stdout.write(json.dumps(obj, indent=2) + "\n")


def resolve_pod_here(pod: str | None) -> str:
    """The pod a command acts on: ``pod``, then ``DOCKET_POD``, then the cwd. Raises
    ``TargetError`` when none or several match; each command words its own refusal."""
    return resolve_pod(pod, env=os.environ, cwd=Path.cwd())


def require_pod(pod: str | None) -> str:
    """The pod a command acts on (``resolve_pod_here``); exit 1 with the refusal when none."""
    try:
        return resolve_pod_here(pod)
    except TargetError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc


def next_step(command: str) -> None:
    """The single ``Next:`` line on stderr; silent under ``DOCKET_NO_HINTS=1``."""
    if os.environ.get("DOCKET_NO_HINTS") == "1":
        return
    ui.hint(command)
