"""The log command: the hash-chained record of what was authorized and done, and its check."""

from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperGroup

import docket.config as _cfg
from docket import ui
from docket.core import audit as _audit

_COUNT_KEY = "docket.log.count"
_DEFAULT_COUNT = 20


class _LogGroup(TyperGroup):
    """A group whose leading all-digit argument is the entry count, not a verb."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        if args and args[0].isdigit():
            ctx.meta[_COUNT_KEY] = int(args[0])
            args = args[1:]
        return super().parse_args(ctx, args)


log_app = typer.Typer(
    name="log",
    help="The hash-chained record of what was authorized and done.",
    cls=_LogGroup,
    no_args_is_help=False,
    invoke_without_command=True,
)


def show_log(limit: int | None = None, json_out: bool = False) -> int:
    """Print the last *limit* entries (default 20), or the raw JSONL with *json_out*."""
    logf = _cfg.AUDIT_LOG
    raw = _audit.read_audit_text()
    if raw is None:
        ui.info("No log yet.")
        ui.dim("  Changes (keys, gates, pods, scope) are recorded to")
        ui.dim(f"  {logf} once you make one.")
        return 0

    if json_out:
        print(raw, end="")
        return 0

    n = limit if limit is not None and limit > 0 else _DEFAULT_COUNT
    ui.header("log", f"last {n} change(s)")
    ui.console.print()
    entries = _audit.read_audit()
    if not entries:
        ui.console.print("  (empty)")
    for e in entries[-n:]:
        ts = str(e.get("ts", ""))
        user = str(e.get("user", "?"))
        action = str(e.get("action", ""))
        detail = str(e.get("detail", ""))
        ui.console.print(f"  {ts:<20}  {user:<10}  {action:<16}  {detail}")
    ui.console.print()
    ui.dim(f"Full JSONL: docket log --json  |  file: {logf}")
    return 0


def verify_log() -> int:
    """Check the hash chain: 0 when clean or absent, 1 at the first broken link."""
    result = _audit.verify_chain()
    if not result.exists:
        ui.info("No log yet. Nothing to verify.")
        return 0

    if result.break_at is not None:
        ui.error(
            f"Tamper check FAILED at line {result.break_at.line} of {result.total_lines}: "
            f"{result.break_at.reason}",
            "Compare the file against your last known-good copy",
        )
        ui.dim(f"  file: {_cfg.AUDIT_LOG}")
        return 1

    ui.success(f"{result.chained} chained line(s) verified clean.")
    if result.continued_from_seq is not None:
        ui.dim(
            f"  Chain continues from a rotated generation ending at "
            f"seq={result.continued_from_seq} -- verified against audit.log.1."
        )
    elif result.rotated_backup:
        ui.dim(
            "  A rotated backup exists (audit.log.1), but this chain does not "
            "claim continuity from it (it started fresh) -- verify only checks the "
            "current file."
        )
    return 0


@log_app.callback(invoke_without_command=True)
def log(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Print the raw JSONL file verbatim"),
) -> None:
    """Show the record of what was authorized and done: keys, gates, pods, scope, approvals.

    `docket log [N]` shows the last N entries (default 20). Each line chains to the
    previous one by SHA-256, so a hand-edited line is detectable with `docket log verify`.
    Secret values are never recorded.

    Example: docket log 50
    """
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(show_log(ctx.meta.get(_COUNT_KEY), json_out))


@log_app.command("verify")
def verify() -> None:
    """Check the chain; exit 1 and name the first broken line if it was altered.

    Example: docket log verify
    """
    raise typer.Exit(verify_log())
