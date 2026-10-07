"""The exec commands.
Holds harness."""

from __future__ import annotations

import typer


def cmd_harness(ctx: typer.Context) -> None:
    """Run one agent, one turn, to completion, for a caller-owned workspace and home.

    `run --workspace DIR (--task TEXT | --task-file PATH) --model
    PROVIDER/ID [--role implementer] [--timeout S] [--agent-id ID]` executes
    synchronously and streams newline-delimited JSON events on stdout,
    finishing with exactly one versioned result object -- see
    `docs/adr/0001-harness-mode.md` and `specs/api/harness-mode.spec.md` for
    the full wire contract. stdout carries only that NDJSON; every log goes
    to stderr.

    Refuses (exit 2, one `result` with `status: refused`) unless `DOCKET_HOME`
    is set to a caller-owned directory (never the operator's own default
    home), `DOCKET_LLM_BASE_URL` is set, `DOCKET_NO_TRACE` is unset, and
    `--workspace` is a real directory -- this command never touches the
    operator's own approvals or audit log. Approval mode is fixed to
    non-interactive refusal: a tool call that would otherwise wait for a
    human is denied immediately as `blocked` rather than hanging for up to
    two minutes. On `SIGTERM` it persists a cancellation request, kills any
    in-flight tool subprocess's process group, and exits with a `cancelled`
    result. Exit codes: 0 the run's result is `ok`; 1 it ended `failed`,
    `blocked`, or `cancelled`; 2 refused before any run started -- the one
    named exception to this CLI's flat 0/1 convention.

    `status TOKEN` reports whether a run token from a prior `run` invocation
    is `live`, `finished` (with a best-effort reconstructed result), or
    `unknown`."""
    from docket.cli._harness import run_harness

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_harness(sub, args[1:]))
