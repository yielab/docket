"""The task commands: add, list, show, diff, trace, prune, approve, deny, answer, retry, cancel."""

from __future__ import annotations

import json
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from rich.markup import escape

from docket.governance import approval as _ap
from docket.hops.application import answers as _answers
from docket.hops.application import interruptions as _interruptions
from docket.hops.application import report as _report
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.commands.task_approval import (
    _actor,
    _answer_content,
    _approval_actor,
    _option_ids,
    _resume_hint,
)
from docket.interfaces.cli.commands.task_render import (
    _event_line,
    _follow,
    _list_item,
    _render_show,
    _say,
    _show_json,
    _trace_file,
    _worktree,
)
from docket.interfaces.cli.render import ui
from docket.kernel import brief as _brief
from docket.kernel.errors import DispatchError
from docket.observability import trace as _trace
from docket.tasks.application import actions as _actions
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import evidence as _evidence
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application import worktree_prune as _worktree_prune
from docket.tasks.domain.refs import TaskRef, TaskRefError, short_id

task_app = typer.Typer(
    name="task",
    help="Queue, inspect and answer a pod's tasks.",
    no_args_is_help=True,
)

MAX_DESCRIPTION = 500


class Priority(StrEnum):
    high = "high"
    normal = "normal"
    low = "low"


def _resolve(pod: str | None, ref: str) -> TaskRef:
    """Resolve *ref* in the named pod, or in every pod when none is named."""
    scope = pod or os.environ.get("DOCKET_POD", "").strip() or None
    try:
        return _queue.resolve_task(scope, ref)
    except TaskRefError as exc:
        ui.error(str(exc), "Run docket task list to see the ids")
        raise typer.Exit(1) from exc


def _task_record(found: TaskRef) -> dict[str, Any]:
    for task in _queue.read_tasks(found.project):
        if task.get("id") == found.task_id:
            return task
    return {}


def _ask_noun(kind: str, count: int) -> str:
    noun = kind.replace("_", " ")
    if count == 1:
        return noun
    return noun[:-1] + "ies" if noun.endswith("y") else noun + "s"


def _interruption_summary(task_id: str, project: str) -> str:
    """One line for `task add`: what could pause this pod's next run before it starts."""
    items = _interruptions.forecast(project, caller_default=_report.caller_default())
    askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
    if not askers:
        return _interruptions.NOTHING_WILL_ASK
    counts: dict[str, int] = {}
    for i in askers:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    parts = [f"{n} {_ask_noun(kind, n)}" for kind, n in sorted(counts.items())]
    return f"May ask you: {', '.join(parts)} -- see: docket task show {short_id(task_id)}"


def _load_brief(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        _brief.TaskBrief.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        ui.error(f"Invalid brief file '{path}': {exc}", "Pass a JSON TaskBrief")
        raise typer.Exit(1) from exc
    return raw  # type: ignore[no-any-return]


@task_app.command("add")
def cmd_add(
    text: str = typer.Argument(..., metavar="TEXT", help="What the task should do"),
    priority: Priority = typer.Option(Priority.normal, "--priority", help="Queue priority"),
    brief: Path | None = typer.Option(None, "--brief", help="A TaskBrief JSON file"),
    external_ref: str | None = typer.Option(
        None, "--external-ref", help="A label from your plan of record, stored verbatim"
    ),
    idempotency_key: str | None = typer.Option(
        None, "--idempotency-key", help="Queue once: a second add with this key adds nothing"
    ),
    base_ref: str | None = typer.Option(
        None, "--base-ref", help="Branch or commit the task worktree starts from"
    ),
    pipeline: str | None = typer.Option(
        None, "--pipeline", help="Pod-local pipeline or recipe name for this task"
    ),
    gate: str | None = typer.Option(
        None, "--gate", help="Command run as an extra gate after the implementer"
    ),
    max_tokens: int | None = typer.Option(
        None, "--max-tokens", help="Token budget across the task's hops"
    ),
    pod: str | None = pod_option(),
) -> None:
    """Queue a task for the pod; `docket run` works the queue.

    Example: docket task add "fix the login redirect"
    """
    project = _contract.require_pod(pod)
    loaded = _load_brief(brief)
    if not text.strip():
        ui.error("The task text is empty", 'Pass the task text, e.g. docket task add "fix it"')
        raise typer.Exit(1)
    if len(text) > MAX_DESCRIPTION:
        ui.error(f"Description too long ({len(text)} chars)", f"Limit: {MAX_DESCRIPTION}")
        raise typer.Exit(1)
    try:
        task, created = _queue.enqueue_task_once(
            project,
            text,
            priority.value,
            brief=loaded,
            channel="cli",
            external_ref=external_ref,
            idempotency_key=idempotency_key,
            base_ref=base_ref,
            pipeline=pipeline,
            gate={"command": gate} if gate is not None else None,
            max_tokens=max_tokens,
        )
    except DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if not created:
        ui.success(escape(f"already queued for pod '{project}': [{task['id']}]"))
        return
    ui.success(escape(f"Queued for pod '{project}': [{task['id']}] {text}"))
    ui.dim(f"  {_interruption_summary(str(task['id']), project)}")
    _contract.next_step("docket run")


@task_app.command("list")
def cmd_list(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod: str | None = pod_option(),
) -> None:
    """The pod's task queue with status, cost and the worktree path when one exists.

    Example: docket task list --json
    """
    project = _contract.require_pod(pod)
    items = [_list_item(project, t) for t in _queue.read_tasks(project)]
    if json_out:
        _contract.emit_json({"pod": project, "tasks": items})
        return
    if not items:
        ui.warn(f"No tasks queued for pod '{project}'.")
        return
    rows = [
        [
            short_id(i["id"]),
            i["priority"],
            i["status"],
            f"${i['costUsd']:.4f}" if i["costUsd"] else "-",
            escape(i["worktree"] or "-"),
            escape(i["description"]),
        ]
        for i in items
    ]
    ui.table(rows, ["ID", "PRI", "STATUS", "COST", "WORKTREE", "DESCRIPTION"])


@task_app.command("show")
def cmd_show(
    ref: str = typer.Argument(..., help="Task id, short id, unique prefix or run id"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod: str | None = pod_option(),
) -> None:
    """One task's whole story: hops, evidence, runs, corrections and its worktree.

    Example: docket task show task-04ff
    """
    found = _resolve(pod, ref)
    task = _task_record(found)
    try:
        ev = _evidence.task_evidence(found.project, found.task_id, "1.1.0")
    except _evidence.EvidenceNotFound as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    wt = _worktree(found.project, task)
    notes = [r for r in _corrections.read(found.project) if r.get("taskId") == found.task_id]
    if json_out:
        _contract.emit_json(_show_json(found, task, ev, wt, notes))
    else:
        _render_show(found, task, ev, wt, notes)
    if ref.startswith("run-") and (_runs.get_run(ref) or {}).get("state") == "failed":
        raise typer.Exit(1)


@task_app.command("diff")
def cmd_diff(
    ref: str = typer.Argument(..., help="Task id, short id, unique prefix or run id"),
    pod: str | None = pod_option(),
    json_out: bool = typer.Option(False, "--json", help="Print the whole diff object as JSON"),
) -> None:
    """Print what the task's branch changed, against the commit it started from.

    Works after the worktree is removed; --json prints the branch, commits, patch and any
    untracked files.

    Example: docket task diff task-04ff
    """
    found = _resolve(pod, ref)
    try:
        doc = _lifecycle.task_diff(found.project, found.task_id)
    except DispatchError as exc:
        ui.error(str(exc), f"Task {short_id(found.task_id)} has no worktree branch to diff")
        raise typer.Exit(1) from exc
    if json_out:
        _contract.emit_json(doc)
    else:
        sys.stdout.write(str(doc["patch"]))


@task_app.command("trace")
def cmd_trace(
    ref: str = typer.Argument(..., help="Task id, short id, unique prefix or run id"),
    tail: bool = typer.Option(False, "--tail", help="Follow until the session ends"),
    export: bool = typer.Option(False, "--export", help="Print the raw JSONL"),
    json_out: bool = typer.Option(False, "--json", help="Emit the events as JSON"),
    pod: str | None = pod_option(),
) -> None:
    """The task's trace: every tool call, model call, cost and approval, in order.

    Example: docket task trace task-04ff --tail
    """
    found = _resolve(pod, ref)
    path = _trace_file(found)
    if not path.is_file():
        ui.error(f"No trace for task {short_id(found.task_id)}", "Run it first: docket run")
        raise typer.Exit(1)
    if export:
        sys.stdout.write(path.read_text(encoding="utf-8"))
    elif json_out:
        _contract.emit_json({"pod": found.project, "events": _trace.read_trace(path)})
    elif tail:
        ui.header("trace", short_id(found.task_id))
        _follow(path)
    else:
        ui.header("trace", short_id(found.task_id))
        for r in _trace.read_trace(path):
            _say(_event_line(r))


def _prune_worktrees(project: str, force: bool, dry_run: bool) -> None:
    entries = _worktree_prune.prune_task_worktrees(project, force=force, dry_run=dry_run)
    if not entries:
        ui.info("No finished task worktrees to prune.")
    for e in entries:
        line = f"{e.task_id}: {e.action}" + (f" ({e.reason})" if e.reason else "")
        (ui.warn if e.action == "kept" else ui.info)(escape(line))


def _prune_records(project: str, days: int | None, dry_run: bool) -> None:
    retention_s = days * 86400 if days is not None else None
    report = _trace.expire_old_traces(retention_s=retention_s, dry_run=dry_run, project=project)
    verb = "Would delete" if dry_run else "Deleted"
    ui.info(f"{verb} {report.expired_count} trace file(s) past {report.retention_s // 86400} days.")
    removed = _runs.prune_terminal(retention_s=retention_s, dry_run=dry_run, project=project)
    ui.info(f"{'Would remove' if dry_run else 'Removed'} {removed} terminal run record(s).")


@task_app.command("prune")
def cmd_prune(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report and change nothing"),
    force: bool = typer.Option(False, "--force", help="Remove dirty worktrees too"),
    yes: bool = typer.Option(False, "--yes", help="Confirm --force without asking"),
    traces: bool = typer.Option(False, "--traces", help="Also expire old traces and run records"),
    days: int | None = typer.Option(None, "--days", min=0, help="Retention window for --traces"),
    pod: str | None = pod_option(),
) -> None:
    """Remove finished tasks' worktrees; with --traces, also expire old traces and run records.

    A dirty worktree or unmerged branch is kept unless --force.

    Example: docket task prune --dry-run
    """
    if days is not None and not traces:
        ui.error("--days needs --traces", "Add --traces")
        raise typer.Exit(2)
    project = _contract.require_pod(pod)
    if force and not dry_run and not _contract.confirm("Remove dirty worktrees too", yes=yes):
        raise typer.Exit(1)
    _prune_worktrees(project, force, dry_run)
    if traces:
        _prune_records(project, days, dry_run)
    _contract.next_step("docket task list")


def _pending_token(pod: str | None, ref: str) -> tuple[str, str | None, str]:
    """The approval token *ref* stands for, its pod and the label to confirm with: an
    ``apr-`` token as given (its pod read from the record), or the token the named task is
    parked on."""
    if ref.startswith("apr-"):
        try:
            project = str(_ap.approval_get(ref).get("project") or "")
        except _ap.ApprovalError:
            project = ""
        return ref, project or None, ref
    found = _resolve(pod, ref)
    task = _task_record(found)
    token = str(task.get("approvalToken") or "")
    if task.get("status") != "waiting_approval" or not token:
        ui.error(
            f"Task {short_id(found.task_id)} is {task.get('status', 'unknown')}, "
            "not waiting for approval",
            "Run docket inbox",
        )
        raise typer.Exit(1)
    return token, found.project, short_id(found.task_id)


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

    Example: docket task approve task-04ff --reason "reviewed the diff"
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
    token, project, label = _pending_token(pod, ref)
    actor = _approval_actor(reason)
    try:
        if task:
            _ap.approval_set_option(token, "approve_task")
        _ap.approval_grant(token, channel="cli", actor=actor, reason=reason)
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        _actions.resolve_waiting_approval(token, "granted")
        return
    except _ap.ApprovalError as err:
        ui.error(str(err))
        raise typer.Exit(1) from err
    _, note = _actions.resolve_waiting_approval_detail(token, "granted", channel="cli", actor=actor)
    ui.success(f"Approved {label}")
    if note:
        ui.warn(note)
    context = _ap.approval_get(token).get("context")
    if project and not (isinstance(context, dict) and context.get("kind") == "check_changed"):
        _resume_hint(project)


@task_app.command("deny")
def _task_deny(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    reason: str = typer.Option("", "--reason", help="Why you deny"),
    pod: str | None = pod_option(),
) -> None:
    """Deny what a task is waiting on; the task fails and nothing runs.

    Example: docket task deny task-04ff --reason "touches production"
    """
    token, _project, label = _pending_token(pod, ref)
    actor = _approval_actor(reason)
    try:
        _ap.approval_deny(token, channel="cli", actor=actor, reason=reason)
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        _actions.resolve_waiting_approval(token, "denied")
        return
    except _ap.ApprovalError as err:
        ui.error(str(err))
        raise typer.Exit(1) from err
    _actions.resolve_waiting_approval(token, "denied", channel="cli", actor=actor, reason=reason)
    ui.success(f"Denied {label}; the action is blocked")


def _question_of(found: TaskRef) -> dict[str, Any]:
    task = _task_record(found)
    question = task.get("question")
    if task.get("status") != "waiting_input" or not isinstance(question, dict):
        ui.error(f"Task {short_id(found.task_id)} has no pending question", "Run docket inbox")
        raise typer.Exit(1)
    return question


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

    Example: docket task answer task-04ff --option opt2
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

    Example: docket task retry task-04ff
    """
    found = _resolve(pod, ref)
    if not _lifecycle.retry_task(found.project, found.task_id):
        status = _task_record(found).get("status", "unknown")
        ui.error(
            f"Task {short_id(found.task_id)} is {status}", "Only failed or blocked tasks retry"
        )
        raise typer.Exit(1)
    ui.success(f"Requeued task {short_id(found.task_id)}")
    _resume_hint(found.project)


@task_app.command("cancel")
def _task_cancel(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    pod: str | None = pod_option(),
) -> None:
    """Stop the run a task is in, cancel a parked task, and settle a claim left behind by a dead
    dispatch.

    A live run is asked to stop and its processes are signalled. A task waiting for an answer or
    an approval is cancelled and leaves the inbox. A task still marked running whose dispatcher
    is gone is settled as failed, ready for `docket task retry`.

    Example: docket task cancel task-04ff
    """
    found = _resolve(pod, ref)
    try:
        outcome = _lifecycle.cancel_task(found.project, found.task_id, channel="cli")
    except DispatchError as exc:
        ui.error(str(exc), "Run docket task list to see the ids")
        raise typer.Exit(1) from exc
    for line in outcome.messages:
        ui.success(line)
    for line in outcome.warnings:
        ui.warn(line)
    if outcome.parked_from:
        ui.success(f"Cancelled task {short_id(found.task_id)}; it was {outcome.parked_from}")
    if outcome.reclaimed:
        ui.success(f"Settled the stale claim on task {short_id(found.task_id)}")
    if not outcome.cancelled:
        ui.error(
            f"Task {short_id(found.task_id)} is {outcome.status}", "Nothing is in flight to cancel"
        )
        raise typer.Exit(1)
    if outcome.reclaimed:
        _contract.next_step(f"docket task retry {short_id(found.task_id)}")
