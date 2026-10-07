"""The log commands.
Holds audit."""

from __future__ import annotations

import typer


def cmd_audit(
    arg: str | None = typer.Argument(None, help="Last-N count, or 'verify'"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show the audit log, or verify its tamper-evidence chain.

    A durable, append-only, tamper-evident record of docket-initiated
    mutations (key changes, gate toggles, profile pins, scope changes,
    agent/pod add/delete, persona changes, etc.).

    With no argument, shows the last 20 entries (human-readable); `[N]`
    shows the last N; `--json` dumps the raw audit.log JSONL file verbatim;
    `verify` walks the hash chain and reports the first broken link (exit 1)
    or that it verified clean (exit 0).

    Stored at `~/.docket/audit.log` -- one JSON object per line (seq, ts
    (millisecond resolution), user, pid, action, detail, prev_hash), never
    containing secret values. Every line chains to the previous one via a
    SHA-256 prev_hash (stdlib hashlib, no new dependency); `verify` detects a
    hand-tampered line, and a line without `seq`/`prev_hash` is a break.
    Rotates to a single-generation `audit.log.1` backup once past
    AUDIT_LOG_MAX_BYTES (default 5 MiB, env-overridable); the first entry
    after a rotation claims continuity, and `verify` checks that claim
    against the backup. Best-effort and never raises; there
    is no environment kill switch -- recording cannot be silently disabled.
    Always exits 0 for the listing forms (malformed lines are skipped, not
    fatal); `verify` exits 1 on a detected broken chain link."""
    from docket.cli._audit import run_audit, run_audit_verify

    if arg == "verify":
        raise typer.Exit(run_audit_verify())

    limit: int | None = None
    if arg and arg.isdigit():
        limit = int(arg)
    raise typer.Exit(run_audit(limit=limit, json_out=json_out))
