"""docket audit — view the mutating-operations audit log.

``run_audit`` returns the process exit code (always 0);
the coordinator wraps it in a Typer command.
"""

from __future__ import annotations

import contextlib

import docket.config as _cfg
from docket import ui
from docket.core import audit as _audit


def run_audit(limit: int | None = None, json_out: bool = False) -> int:
    """Show the last *limit* audit entries (default 20), or raw JSONL with json_out."""
    logf = _cfg.AUDIT_LOG

    if not logf.is_file():
        ui.info("No audit log yet.")
        ui.dim("  Mutations (keys, gates, profile, scope, add/delete) are recorded to")
        ui.dim(f"  {logf} once you make a change.")
        return 0

    if json_out:
        with contextlib.suppress(OSError):
            print(logf.read_text(encoding="utf-8"), end="")
        return 0

    n = limit if limit is not None and limit > 0 else 20

    ui.header(f"Audit log — last {n} change(s)")
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
    ui.dim(f"Full JSONL: docket audit --json  ·  file: {logf}")
    return 0
