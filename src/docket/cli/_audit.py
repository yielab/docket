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
        # total_lines is only informative here: counting (chained/legacy) stops
        # at the break, so "line X of N" is the one place this field tells the
        # operator something chained+legacy can't (how much of the file lies
        # beyond the detected break). In the clean-chain summary below,
        # chained+legacy always sums to total_lines, so repeating it there
        # would be redundant — this is the field's one renderer (G-4b).
        ui.error(
            f"Tamper check FAILED at line {result.break_at.line} of {result.total_lines}: "
            f"{result.break_at.reason}"
        )
        ui.dim(f"  file: {_cfg.AUDIT_LOG}")
        return 1

    summary = f"{result.chained} chained line(s) verified clean"
    if result.legacy:
        summary += f", {result.legacy} legacy (unchained) line(s) skipped"
    ui.success(summary + ".")

    if result.continued_from_seq is not None:
        ui.dim(
            f"  Chain continues from a rotated generation ending at "
            f"seq={result.continued_from_seq} — verified against audit.log.1."
        )
    elif result.rotated_backup:
        ui.dim(
            "  A rotated backup exists (audit.log.1), but this chain does not "
            "claim continuity from it (it started fresh after a pre-chain/legacy "
            "line) — verify only checks the current file."
        )
    return 0
