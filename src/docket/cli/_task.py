"""The task commands.
Holds approve, deny, chat, runs and trace."""

from __future__ import annotations

import typer

task_app = typer.Typer(
    name="task",
    help="Queue, inspect and answer a pod's tasks.",
    no_args_is_help=True,
)


def cmd_runs(ctx: typer.Context) -> None:
    """Inspect the dispatch run registry (list/show/cancel/prune) -- one record per invocation.

    One persisted record per pod-dispatch invocation, whatever triggered it
    (the CLI, the `docket serve` webhook, a due schedule, or the sweep loop).
    Answers "is it done, did it fail, or did it never run" for background
    dispatch, whose failures are otherwise invisible.

    Subcommands: `list [--project <project>] [--json]`; `show <run-id>
    [--json]`; `cancel <run-id>` persists one cancellation request and
    signals every in-flight hop process group -- queued work is terminal
    immediately, a running record stays "running (cancel requested)" until
    the executor observes the request and fully stops, then the task and run
    become cancelled; writes one audit entry; in-process backend work
    already executing returns to a safe checkpoint, where its late response
    is discarded before any tool or later pipeline hop can start. `prune
    [--dry-run] [--days N]` deletes terminal (succeeded/failed/cancelled)
    records past the retention window (default `TRACE_RETENTION_DAYS`) --
    the same pruning `docket serve`'s periodic sweep already does; queued
    and running records are never touched.

    A run record's `source` is one of cli|webhook|schedule|sweep|mcp;
    `state` is one of queued|running|succeeded|failed|cancelled. A failed
    run carries the exception text in `error`. Persisted to
    `~/.docket/docket-runs.json`. `show` and both JSON read surfaces expose
    cancellation requestedAt/observedAt/stoppedAt; a missing stop timestamp
    means the executor has not fully returned yet. `POST /dispatch/<project>`
    (see `docket serve`) returns {"run": "<id>"} immediately, before any
    dispatch work is attempted; `GET /runs/<id>` and `GET /runs?project=`
    mirror this command over HTTP (Bearer-authed, same as /approvals)."""
    from docket.cli._runs import run_runs

    args = list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_runs(sub, args[1:]))


def cmd_trace(ctx: typer.Context) -> None:
    """View agent execution traces.

    Every dispatch hop emits a JSONL trace event; use this to inspect them.
    Subcommands: `<session-id>` renders one session human-readable; `tail
    <project>` follows the latest open session live; `export <project>
    [--since DATE]` is a raw JSONL passthrough; `ingest <project>` projects
    docket's own session store into the trace store.

    Traces are stored at `~/.docket/traces/<project>/<session-id>.jsonl`.
    Each dispatch hop writes events such as tool_call, cost_charged,
    approval_requested."""
    from docket.cli._trace import run_trace

    args = list(ctx.args)
    since: str | None = None
    dry_run = False
    days: int | None = None
    pos: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--since":
            since = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if args[i] == "--dry-run":
            dry_run = True
            i += 1
            continue
        if args[i] == "--days":
            raw = args[i + 1] if i + 1 < len(args) else None
            days = int(raw) if raw is not None and raw.lstrip("-").isdigit() else None
            i += 2
            continue
        pos.append(args[i])
        i += 1
    sub = pos[0] if pos else None
    target = pos[1] if len(pos) > 1 else None
    raise typer.Exit(run_trace(sub, target, since, dry_run, days))


def cmd_approve(
    approval_id: str | None = typer.Argument(None),
    reason: str = typer.Option("", "--reason", help="Reason for the approval"),
    option: str = typer.Option(
        "",
        "--option",
        help="approve_once (default) or approve_task: also grant this exact call "
        "for the rest of its pod task",
    ),
) -> None:
    """Approve a pending tool-action.

    Grants a pending HITL approval token from docket's own approval store
    ($APPROVALS_DIR). With no token, lists pending approvals; with a token,
    grants it. Token format: apr-*. Returns exit 1 if the token is not
    found, or if you resolve it to the opposite verdict from what it already
    has; re-resolving to the same verdict it already has is treated as an
    idempotent no-op -- a warning, but exit 0. An apr-* token is created by
    docket itself, from an in-turn `ask` verdict on a tool call
    (`dispatch_tool`, blocking that call until answered), a pod-dispatch hop
    held on a requireApprovalRoles/pipeline approval step, or a task a
    guardrail policy flagged at enqueue. This store is the only approval
    mechanism, and
    `docket approve`/`docket deny` (plus the HTTP and MCP equivalents, and a
    Telegram reply in a wired chat) are the only ways to answer it, each
    audit-logged with the channel that answered. See also `docket deny`."""
    from docket.cli._approve import run_approve

    raise typer.Exit(run_approve(approval_id, reason=reason, option=option))


def cmd_deny(
    approval_id: str | None = typer.Argument(None),
    reason: str = typer.Option("", "--reason", help="Reason for the denial"),
) -> None:
    """Deny a pending tool-action.

    Denies a pending HITL approval token from docket's own approval store
    ($APPROVALS_DIR). With no token, lists pending approvals; with a token,
    denies it. Same token format, idempotency, and provenance rules as
    `docket approve` -- see its help for the full contract."""
    from docket.cli._deny import run_deny

    raise typer.Exit(run_deny(approval_id, reason=reason))


def cmd_chat(ctx: typer.Context) -> None:
    """See and answer one task's parked question.

    `docket chat <task-id> [--pod <project>]` -- searches every pod for *task-id* (or just
    *pod* when given), then shows its brief, its pending question (if any) and its earlier
    answers. On a TTY, a pending question is followed by one prompt per schema property and
    then answered through the same `core.answers.answer_task` every other surface calls
    (`channel="cli"`, `actor=<OS user>`). Off a TTY, or with no pending question, this only
    ever displays -- use `docket pod <p> answer` to answer non-interactively."""
    from docket.cli._chat import run_chat

    raise typer.Exit(run_chat(list(ctx.args)))
