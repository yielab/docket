"""The task commands: add, list, show, diff, trace, prune, pregrant, answer, retry, cancel."""

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

from docket.hops.application import interruptions as _interruptions
from docket.hops.application import report as _report
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.commands.task_approval import (
    _actor,
    _answer_content,
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
from docket.kernel.errors import DispatchError, DocketError
from docket.kernel.operator_contract import EscalationView, is_escalation_id
from docket.observability import trace as _trace
from docket.operator import escalation_view, escalation_views
from docket.platform import prune_settled_escalations, read_escalation
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import evidence as _evidence
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application import worktree_prune as _worktree_prune
from docket.tasks.application.escalations import resolve
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.refs import TaskRef, TaskRefError, short_id
from docket.tasks.domain.resolution import EscalationNotPending, EscalationRefused
from docket.tasks.domain.task import TaskRecord

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


def _task_record(found: TaskRef) -> TaskRecord:
    record = TaskRepository.for_pod(found.project).get(found.task_id)
    if record is None:
        ui.error(f"Task {short_id(found.task_id)} is no longer queued", "Run docket task list")
        raise typer.Exit(1)
    return record


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


def _parse_vars(values: list[str]) -> dict[str, str]:
    """``NAME=VALUE`` strings as a mapping, the last of a repeated name winning; a malformed one
    exits 2 naming it."""
    out: dict[str, str] = {}
    for raw in values:
        name, sep, value = raw.partition("=")
        if not sep or not name.strip():
            ui.error(f"--var {raw!r} is not NAME=VALUE", "Pass --var NAME=VALUE")
            raise typer.Exit(2)
        out[name.strip()] = value
    return out


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
    autonomy: str | None = typer.Option(
        None,
        "--autonomy",
        metavar="L3|L4|L5",
        help="Level its pauses are decided at; only narrows the pod profile's ceiling",
    ),
    var: list[str] = typer.Option(
        [],
        "--var",
        metavar="NAME=VALUE",
        help="Pipeline variable for this task; repeat for several",
    ),
    pod: str | None = pod_option(),
) -> None:
    """Queue a task for the pod; `docket run` works the queue.

    Example: docket task add "fix the login redirect"
    """
    project = _contract.require_pod(pod)
    loaded = _load_brief(brief)
    variables = _parse_vars(var)
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
            autonomy=autonomy,
            variables=variables or None,
        )
    except DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if not created:
        ui.success(escape(f"already queued for pod '{project}': [{task.id}]"))
        return
    ui.success(escape(f"Queued for pod '{project}': [{task.id}] {text}"))
    ui.dim(f"  {_interruption_summary(task.id, project)}")
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
    items = [_list_item(project, t) for t in TaskRepository.for_pod(project).list()]
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


def _task_of_escalation(ref: str) -> str:
    """*ref* itself, or for an ``esc-`` id the id of the task that escalation pauses."""
    if not is_escalation_id(ref):
        return ref
    record = read_escalation(ref)
    if record is None or not record.task:
        ui.error(f"No queued task waits on {ref}", "Run docket inbox")
        raise typer.Exit(1)
    return record.task


@task_app.command("show")
def cmd_show(
    ref: str = typer.Argument(
        ..., help="Task id, short id, unique prefix, run id or escalation id"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod: str | None = pod_option(),
) -> None:
    """One task's whole story: hops, evidence, runs, corrections and its worktree.

    Example: docket task show task-04ff
    """
    found = _resolve(pod, _task_of_escalation(ref))
    record = _task_record(found)
    try:
        ev = _evidence.task_evidence(found.project, found.task_id, "1.1.0")
    except _evidence.EvidenceNotFound as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    wt = _worktree(found.project, record)
    notes = [r for r in _corrections.read(found.project) if r.get("taskId") == found.task_id]
    if json_out:
        _contract.emit_json(_show_json(found, record, ev, wt, notes))
    else:
        _render_show(found, record, ev, wt, notes)
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
    settled = prune_settled_escalations(retention_s=retention_s, dry_run=dry_run)
    ui.info(f"{'Would remove' if dry_run else 'Removed'} {settled} settled escalation record(s).")


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


@task_app.command("pregrant")
def _task_pregrant(
    ref: str = typer.Argument(..., help="Task id, short id or run id"),
    command: str = typer.Argument(..., help="The exact command to approve before the task asks"),
    tool: str = typer.Option("bash", "--tool", help="Tool the command runs under"),
    pod: str | None = pod_option(),
) -> None:
    """Approve one exact command for a task before it asks; the approval is single-use.

    Example: docket task pregrant task-04ff "git push origin main"
    """
    found = _resolve(pod, ref)
    try:
        _interruptions.record_pregrant(
            found.project, found.task_id, command, tool=tool, channel="cli", actor=_actor()
        )
    except _interruptions.InterruptionsError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(escape(f"Pre-granted '{command}' on task {short_id(found.task_id)}"))
    _resume_hint(found.project)


_APPROVAL_OPTIONS = ("approve_once", "approve_task", "deny")
_APPROVAL_KINDS = ("approval", "gate", "check_changed")


def _escalation_of(pod: str | None, ref: str) -> tuple[EscalationView, str]:
    """The pause *ref* names, as a view, with the label to confirm it by: an ``esc-`` id as
    given, else the task's newest pending escalation (the command ends when it has none)."""
    if is_escalation_id(ref):
        record = read_escalation(ref)
        if record is None:
            ui.error(f"No escalation {ref}", "Run docket inbox")
            raise typer.Exit(1)
        return escalation_view(record), record.id
    found = _resolve(pod, ref)
    pending = [
        v for v in escalation_views(pod=found.project, task=found.task_id) if v.state == "pending"
    ]
    if not pending:
        ui.error(
            f"Task {short_id(found.task_id)} waits on no question or approval", "Run docket inbox"
        )
        raise typer.Exit(1)
    return pending[-1], short_id(found.task_id)


def _settle(
    view: EscalationView, label: str, option: str | None, content: dict[str, Any] | None
) -> bool:
    """Resolve *view* with *option* and *content* as the operator and say how it went (a repeat of
    the decision already taken is a warning); whether the pause was settled by this call."""
    try:
        resolved = resolve(view.id, option, content, by=_actor(), channel="cli")
    except EscalationNotPending as err:
        if err.already_so:
            ui.warn(err.message)
            return False
        ui.error(err.message)
        raise typer.Exit(1) from err
    except EscalationRefused as exc:
        ui.error(f"Answer blocked by policy '{exc.policy_id}'")
        raise typer.Exit(1) from exc
    except DocketError as err:
        ui.error(err.message)
        raise typer.Exit(1) from err
    if option == "deny":
        ui.success(f"Denied {label}; the action is blocked")
    elif view.kind in _APPROVAL_KINDS:
        ui.success(f"Approved {label}")
    elif option == "decline":
        ui.success(f"Declined task {label}")
    else:
        ui.success(f"Answered task {label}")
    if resolved.note:
        ui.warn(resolved.note)
    return True


def _answer_an_approval(
    view: EscalationView, label: str, option: str | None, others: bool, reason: str
) -> None:
    """`task answer --option <id>` on an approval: only its three options, and no text."""
    if others or option not in _APPROVAL_OPTIONS:
        ui.error(
            f"{label} waits on an approval", f"Pass only --option {'|'.join(_APPROVAL_OPTIONS)}"
        )
        raise typer.Exit(1)
    settled = _settle(view, label, option, {"reason": reason} if reason else None)
    if settled and option != "deny" and view.kind != "check_changed":
        _resume_hint(view.pod)


@task_app.command("answer")
def _task_answer(
    ref: str = typer.Argument(..., help="Task id, short id, run id or escalation id"),
    text: list[str] = typer.Argument(None, help="Answer for a one-property question"),
    option: str | None = typer.Option(None, "--option", help="Pick one of the options"),
    field: list[str] = typer.Option([], "--field", help="Answer one property, name=value"),
    decline: bool = typer.Option(False, "--decline", help="Decline instead of answering"),
    reason: str = typer.Option("", "--reason", help="Why, for an approval"),
    pod: str | None = pod_option(),
) -> None:
    """Answer what a task is waiting on and let it continue.

    A question takes text, --field or --option; on a terminal with none of them it shows the
    question and prompts. Off a terminal pass text, --field name=value or --option <id>; a
    question with options needs --option. An approval takes --option approve_once, approve_task
    or deny, and --reason. The reference may be the escalation id that `docket inbox` prints.

    Example: docket task answer esc-1a2b3c4d5e6f --option approve_once
    """
    others = bool(text or field or decline)
    view, label = _escalation_of(pod, ref)
    if view.kind in _APPROVAL_KINDS:
        _answer_an_approval(view, label, option, others, reason)
        return
    question = view.as_question()
    if decline:
        if _settle(view, label, "decline", None):
            _resume_hint(view.pod)
        return
    content = _answer_content(question, text, option, field)
    ids = _option_ids(question)
    if ids and not content.get("optionId"):
        ui.error("This question has options", f"Pass --option <id>: {', '.join(ids)}")
        raise typer.Exit(1)
    chosen = content.pop("optionId", None)
    if _settle(view, label, chosen, content or None):
        _resume_hint(view.pod)


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
        status = _task_record(found).status
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
