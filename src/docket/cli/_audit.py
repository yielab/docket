"""docket audit — view the mutating-operations audit log, and verify its chain.

``run_audit`` / ``run_audit_verify`` return the process exit code; the
coordinator wraps each in a Typer command.
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


def run_audit_verify() -> int:
    """Verify the audit log's tamper-evidence hash chain.

    Returns 0 when the current file is clean (or absent — nothing to
    verify), 1 when the first broken link is found (reported with its line
    number). Legacy (pre-chain) lines are reported as unchained, never as
    tampering.
    """
    result = _audit.verify_chain()

    if not result.exists:
        ui.info("No audit log yet. Nothing to verify.")
        return 0

    if result.break_at is not None:
        ui.error(f"Tamper check FAILED at line {result.break_at.line}: {result.break_at.reason}")
        ui.dim(f"  file: {_cfg.AUDIT_LOG}")
        return 1

    summary = f"{result.chained} chained line(s) verified clean"
    if result.legacy:
        summary += f", {result.legacy} legacy (unchained) line(s) skipped"
    ui.success(summary + ".")

    if result.rotated_backup:
        ui.dim(
            "  A rotated backup exists (audit.log.1) — verify only checks the "
            "current file; each rotation starts a fresh chain."
        )
    return 0
