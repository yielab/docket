"""The task commands: approve, deny, answer, retry and cancel a pod's tasks, plus runs and trace."""

from __future__ import annotations

import getpass as _getpass
import os
import sys
from typing import Any

import typer
from rich.markup import escape

from docket import ui
from docket.cli import _contract
from docket.cli._target import pod_option
from docket.core import answers as _answers
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch
from docket.core import interruptions as _interruptions
from docket.core import runs as _runs
from docket.core.task_ref import TaskRef, TaskRefError, resolve_task, short_id

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


_TYPE_COERCERS: dict[str, Any] = {
    "integer": int,
    "number": float,
    "boolean": lambda v: v.strip().lower() in ("1", "true", "yes", "y"),
}
_LIVE_RUN_STATES = ("queued", "running")


def _actor() -> str:
    try:
        return _getpass.getuser()
    except Exception:
        return "?"


def _interactive() -> bool:
    return sys.stdin.isatty()


def _resolve(pod: str | None, ref: str) -> TaskRef:
    """The task *ref* names, in *pod* or in every pod; one-line exit 1 when it names none."""
    try:
        return resolve_task(pod or os.environ.get("DOCKET_POD") or None, ref)
    except TaskRefError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc


def _task_status(ref: TaskRef) -> dict[str, Any]:
    for task in _dispatch.read_tasks(ref.project):
        if task.get("id") == ref.task_id:
            return task
    return {}


def _resume_hint(project: str) -> None:
    """After a state change: say who picks the task up, or name the command that does."""
    from docket.cli import _service

    if _service.is_running():
        ui.dim("docket is running and will pick it up")
        return
    _contract.next_step(f"docket run --pod {project}")


def _approval_actor(reason: str) -> str:
    return _actor() if reason else ""


def _pending_token(pod: str | None, ref: str) -> tuple[str, str | None]:
    """The approval token *ref* stands for and its pod: an ``apr-`` token as given, or the
    token the named task is parked on."""
    if ref.startswith("apr-"):
        return ref, None
    found = _resolve(pod, ref)
    task = _task_status(found)
    token = str(task.get("approvalToken") or "")
    if task.get("status") != "waiting_approval" or not token:
        ui.error(
            f"Task {short_id(found.task_id)} is {task.get('status', 'unknown')}, "
            "not waiting for approval",
            "Run docket inbox",
        )
        raise typer.Exit(1)
    return token, found.project


def _pregrant(pod: str | None, ref: str, command: str, tool: str) -> None:
    found = _resolve(pod, ref)
    try:
        token = _interruptions.record_pregrant(
            found.project, found.task_id, command, tool=tool, channel="cli", actor=_actor()
        )
    except _interruptions.InterruptionsError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(escape(f"Pre-granted '{command}' on task {short_id(found.task_id)} ({token})"))
    _resume_hint(found.project)


@task_app.command("approve")
def _task_approve(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    reason: str = typer.Option("", "--reason", help="Why you approve"),
    once: bool = typer.Option(False, "--once", help="Approve this call only (the default)"),
    task: bool = typer.Option(
        False, "--task", help="Also allow this exact call for the rest of the task"
    ),
    for_command: str | None = typer.Option(
        None, "--for", help="Pre-grant one exact command before the task asks"
    ),
    tool: str = typer.Option("bash", "--tool", help="Tool the --for command runs under"),
    pod: str | None = pod_option(),
) -> None:
    """Approve what a task is waiting on, or pre-grant one command before it asks.

    Resolves the task's pending approval and grants it; with --task the same call is also
    allowed for the rest of the task. --for records a single-use pre-grant for one exact
    command instead.

    Example: docket task approve 2026-10-08T10-00 --reason "reviewed the diff"
    """
    if once and task:
        ui.error("--once and --task conflict", "Pass one of them")
        raise typer.Exit(2)
    if for_command is not None:
        if task:
            ui.error("--for and --task conflict", "Pre-grants are single-use")
            raise typer.Exit(2)
        _pregrant(pod, ref, for_command, tool)
        return
    token, project = _pending_token(pod, ref)
    actor = _approval_actor(reason)
    try:
        if task:
            _ap.approval_set_option(token, "approve_task")
        _ap.approval_grant(token, channel="cli", actor=actor, reason=reason)
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        _dispatch.resolve_waiting_approval(token, "granted")
        return
    except _ap.ApprovalError as err:
        ui.error(str(err))
        raise typer.Exit(1) from err
    _, note = _dispatch.resolve_waiting_approval_detail(
        token, "granted", channel="cli", actor=actor
    )
    ui.success(f"Approved {short_id(ref) if project else ref}")
    if note:
        ui.warn(note)
    if project:
        _resume_hint(project)


@task_app.command("deny")
def _task_deny(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    reason: str = typer.Option("", "--reason", help="Why you deny"),
    pod: str | None = pod_option(),
) -> None:
    """Deny what a task is waiting on; the task fails and nothing runs.

    Example: docket task deny 2026-10-08T10-00 --reason "touches production"
    """
    token, project = _pending_token(pod, ref)
    actor = _approval_actor(reason)
    try:
        _ap.approval_deny(token, channel="cli", actor=actor, reason=reason)
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        _dispatch.resolve_waiting_approval(token, "denied")
        return
    except _ap.ApprovalError as err:
        ui.error(str(err))
        raise typer.Exit(1) from err
    _dispatch.resolve_waiting_approval(token, "denied")
    ui.success(f"Denied {short_id(ref) if project else ref}; the action is blocked")


def _question_of(found: TaskRef) -> dict[str, Any]:
    task = _task_status(found)
    question = task.get("question")
    if task.get("status") != "waiting_input" or not isinstance(question, dict):
        ui.error(f"Task {short_id(found.task_id)} has no pending question", "Run docket inbox")
        raise typer.Exit(1)
    return question


def _option_ids(question: dict[str, Any]) -> list[str]:
    raw = question.get("options")
    return (
        [str(o.get("id", "")) for o in raw if isinstance(o, dict)] if isinstance(raw, list) else []
    )


def _parse_fields(fields: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in fields:
        key, sep, value = item.partition("=")
        if not sep or not key:
            ui.error(f"--field {item!r} is not name=value", "Pass --field name=value")
            raise typer.Exit(2)
        out[key] = value
    return out


def _render_options(question: dict[str, Any]) -> None:
    raw = question.get("options")
    options = [o for o in raw if isinstance(o, dict)] if isinstance(raw, list) else []
    recommendation = question.get("recommendation")
    recommended = recommendation.get("optionId") if isinstance(recommendation, dict) else None
    for option in options:
        mark = " (recommended)" if option.get("id") == recommended else ""
        ui.console.print(escape(f"  {option.get('id', '')} - {option.get('label', '')}{mark}"))
        if option.get("description"):
            ui.dim(escape(f"    {option['description']}"))


def _prompt_content(question: dict[str, Any]) -> dict[str, Any]:
    """One prompt for the option (blank takes the recommended one), then one per schema
    property; a blank optional property is dropped, a blank required one is left to the
    answer's own validation."""
    content: dict[str, Any] = {}
    recommendation = question.get("recommendation")
    recommended = recommendation.get("optionId") if isinstance(recommendation, dict) else ""
    if _option_ids(question):
        default = f" [{recommended}]" if recommended else ""
        content["optionId"] = input(f"  Option{default}: ").strip() or (recommended or "")
    schema = question.get("requestedSchema", {})
    required: list[str] = schema.get("required", [])
    for name, prop in schema.get("properties", {}).items():
        label = f"{name}{' (required)' if name in required else ''}"
        raw_value = input(f"  {label}: ").strip()
        if not raw_value and name not in required:
            continue
        coerce = _TYPE_COERCERS.get(prop.get("type"))
        try:
            content[name] = coerce(raw_value) if coerce is not None else raw_value
        except ValueError:
            content[name] = raw_value
    return content


def _answer_content(
    question: dict[str, Any], text: list[str] | None, option: str | None, fields: list[str]
) -> dict[str, Any]:
    """The content an answer carries, built from flags; prompts on a TTY when none was given."""
    content = _parse_fields(fields)
    words = " ".join(text or []).strip()
    if words:
        properties = question.get("requestedSchema", {}).get("properties", {})
        if len(properties) != 1:
            ui.error("A bare text answer needs a one-property question", "Pass --field name=value")
            raise typer.Exit(1)
        content.setdefault(next(iter(properties)), words)
    if option:
        content["optionId"] = option
    if content:
        return content
    ids = _option_ids(question)
    if not _interactive():
        if ids:
            ui.error("This question has options", f"Pass --option <id>: {', '.join(ids)}")
        else:
            ui.error("Nothing to answer with", "Pass text, --field name=value or --option <id>")
        raise typer.Exit(1)
    ui.console.print(escape(f"  Question: {question.get('message', '')}"))
    _render_options(question)
    return _prompt_content(question)


@task_app.command("answer")
def _task_answer(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    text: list[str] = typer.Argument(None, help="Answer for a one-property question"),
    option: str | None = typer.Option(None, "--option", help="Pick one of the question's options"),
    field: list[str] = typer.Option([], "--field", help="Answer one property, name=value"),
    decline: bool = typer.Option(False, "--decline", help="Decline instead of answering"),
    pod: str | None = pod_option(),
) -> None:
    """Answer the question a task is parked on and let it continue.

    On a terminal with no text or option it shows the question and prompts. Off a terminal
    pass text, --field name=value or --option <id>; a question with options needs --option.

    Example: docket task answer 2026-10-08T10-00 --option opt2
    """
    found = _resolve(pod, ref)
    question = _question_of(found)
    action = "decline" if decline else "accept"
    content = None if decline else _answer_content(question, text, option, field)
    ids = _option_ids(question)
    if content is not None and ids and not content.get("optionId"):
        ui.error("This question has options", f"Pass --option <id>: {', '.join(ids)}")
        raise typer.Exit(1)
    try:
        _answers.answer_task(
            found.project, found.task_id, action, content, channel="cli", actor=_actor()
        )
    except _answers.AnswerRejected as exc:
        ui.error(f"Answer blocked by policy '{exc.policy_id}'")
        raise typer.Exit(1) from exc
    except _answers.AnswerError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    verb = "Declined" if decline else "Answered"
    ui.success(f"{verb} task {short_id(found.task_id)}")
    _resume_hint(found.project)


@task_app.command("retry")
def _task_retry(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    pod: str | None = pod_option(),
) -> None:
    """Put a failed or blocked task back on the queue, keeping the hops it finished.

    Example: docket task retry 2026-10-08T10-00
    """
    found = _resolve(pod, ref)
    if not _dispatch.retry_task(found.project, found.task_id):
        status = _task_status(found).get("status", "unknown")
        ui.error(
            f"Task {short_id(found.task_id)} is {status}", "Only failed or blocked tasks retry"
        )
        raise typer.Exit(1)
    ui.success(f"Requeued task {short_id(found.task_id)}")
    _resume_hint(found.project)


def _live_runs(found: TaskRef, status: object) -> list[str]:
    """Ids of the pod's queued or running runs that carry the task: one that lists it, or an
    in-flight one (it names its tasks only when it finishes) while the task is running."""
    ids: list[str] = []
    for record in _runs.list_runs(found.project):
        if record.get("state") not in _LIVE_RUN_STATES:
            continue
        carried = [str(t) for t in record.get("taskIds") or []]
        if found.task_id in carried or (not carried and status == "running"):
            ids.append(str(record["id"]))
    return ids


def _cancel_live_runs(found: TaskRef, status: object) -> int:
    """Request cancellation of every live run of the task; return how many took."""
    cancelled = 0
    for run_id in _live_runs(found, status):
        outcome = _runs.cancel_run(run_id)
        if outcome.ok:
            ui.success(outcome.message)
            cancelled += 1
        else:
            ui.warn(outcome.message)
    return cancelled


@task_app.command("cancel")
def _task_cancel(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    pod: str | None = pod_option(),
) -> None:
    """Stop the run a task is in and settle a claim left behind by a dead dispatch.

    A live run is asked to stop and its processes are signalled. A task still marked running
    whose dispatcher is gone is settled as failed, ready for `docket task retry`.

    Example: docket task cancel 2026-10-08T10-00
    """
    found = _resolve(pod, ref)
    cancelled = _cancel_live_runs(found, _task_status(found).get("status"))
    reclaimed = False
    if _task_status(found).get("status") == "running":
        _dispatch.reclaim_stale_running(found.project)
        reclaimed = _task_status(found).get("status") != "running"
        if reclaimed:
            ui.success(f"Settled the stale claim on task {short_id(found.task_id)}")
    if not cancelled and not reclaimed:
        status = _task_status(found).get("status", "unknown")
        ui.error(f"Task {short_id(found.task_id)} is {status}", "Nothing is in flight to cancel")
        raise typer.Exit(1)
    if reclaimed:
        _contract.next_step(f"docket task retry {short_id(found.task_id)}")
