"""The task commands: add, list, show, diff, trace, prune, approve, deny, answer, retry, cancel."""

from __future__ import annotations

import contextlib
import getpass as _getpass
import json
import os
import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import ValidationError
from rich.markup import escape

from docket import ui
from docket.cli import _contract
from docket.cli._target import TargetError, pod_option, resolve_pod
from docket.core import answers as _answers
from docket.core import approval as _ap
from docket.core import corrections as _corrections
from docket.core import dispatch as _dispatch
from docket.core import evidence as _evidence
from docket.core import fleet as _fleet
from docket.core import interruptions as _interruptions
from docket.core import operator_contract as _oc
from docket.core import pod as _pod
from docket.core import pod_provisioning as _pp
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.task_ref import TaskRef, TaskRefError, resolve_task, short_id
from docket.edges.adapters import system as _sys

task_app = typer.Typer(
    name="task",
    help="Queue, inspect and answer a pod's tasks.",
    no_args_is_help=True,
)

MAX_DESCRIPTION = 500
TAIL_POLL_S = 0.5


class Priority(StrEnum):
    high = "high"
    normal = "normal"
    low = "low"


def _say(text: str) -> None:
    ui.console.print(text, markup=False)


def _pod_name(pod: str | None) -> str:
    try:
        return resolve_pod(pod, env=os.environ, cwd=Path.cwd())
    except TargetError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc


def _resolve(pod: str | None, ref: str) -> TaskRef:
    """Resolve *ref* in the named pod, or in every pod when none is named."""
    scope = pod or os.environ.get("DOCKET_POD", "").strip() or None
    try:
        return resolve_task(scope, ref)
    except TaskRefError as exc:
        ui.error(str(exc), "Run docket task list to see the ids")
        raise typer.Exit(1) from exc


def _task_record(found: TaskRef) -> dict[str, Any]:
    for task in _dispatch.read_tasks(found.project):
        if task.get("id") == found.task_id:
            return task
    return {}


def _worktree(project: str, task: dict[str, Any]) -> dict[str, str] | None:
    """The task's worktree record when it has a directory that was not pruned."""
    record = task.get("worktree")
    if not isinstance(record, dict) or not record.get("dir") or record.get("prunedAt"):
        return None
    path = str(record["dir"])
    base = str(record.get("baseCommit") or "")
    branch = str(record.get("branch") or "")
    codebase = str(_pod_codebase(project) or "")
    root = f"git -C {codebase} " if codebase else "git "
    return {
        "path": path,
        "branch": branch,
        "baseCommit": base,
        "diff": f"git -C {path} diff {base}",
        "merge": f"{root}merge {branch}",
    }


def _pod_codebase(project: str) -> str:
    return str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")


def _caller_default() -> Literal["wait", "park"]:
    return "wait" if sys.stdin.isatty() else "park"


def _ask_noun(kind: str, count: int) -> str:
    noun = kind.replace("_", " ")
    if count == 1:
        return noun
    return noun[:-1] + "ies" if noun.endswith("y") else noun + "s"


def _interruption_summary(task_id: str, project: str) -> str:
    """One line for `task add`: what could pause this pod's next run before it starts."""
    items = _interruptions.forecast(project, caller_default=_caller_default())
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
        _oc.TaskBrief.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        ui.error(f"Invalid brief file '{path}': {exc}", "Pass a JSON TaskBrief")
        raise typer.Exit(1) from exc
    return raw  # type: ignore[no-any-return]


@task_app.command("add")
def cmd_add(
    text: str = typer.Argument(..., metavar="TEXT", help="What the task should do"),
    priority: Priority = typer.Option(Priority.normal, "--priority", help="Queue priority"),
    brief: Path | None = typer.Option(None, "--brief", help="A TaskBrief JSON file"),
    pod: str | None = pod_option(),
) -> None:
    """Queue a task for the pod; `docket run` works the queue.

    Example: docket task add "fix the login redirect"
    """
    project = _pod_name(pod)
    loaded = _load_brief(brief)
    if not text.strip():
        ui.error("The task text is empty", 'Pass the task text, e.g. docket task add "fix it"')
        raise typer.Exit(1)
    if len(text) > MAX_DESCRIPTION:
        ui.error(f"Description too long ({len(text)} chars)", f"Limit: {MAX_DESCRIPTION}")
        raise typer.Exit(1)
    try:
        task = _dispatch.enqueue_task(project, text, priority.value, brief=loaded)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    ui.success(escape(f"Queued for pod '{project}': [{task['id']}] {text}"))
    ui.dim(f"  {_interruption_summary(str(task['id']), project)}")
    _contract.next_step("docket run")


def _cost_cell(task: dict[str, Any]) -> str:
    cost = task.get("costUsd")
    return f"${float(cost):.4f}" if cost else "-"


def _list_item(project: str, task: dict[str, Any]) -> dict[str, Any]:
    wt = _worktree(project, task)
    cost = task.get("costUsd")
    return {
        "id": str(task.get("id", "")),
        "priority": str(task.get("priority", "normal")),
        "status": str(task.get("status", "")),
        "costUsd": float(cost) if cost else None,
        "description": str(task.get("description", "")),
        "worktree": wt["path"] if wt else None,
    }


@task_app.command("list")
def cmd_list(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod: str | None = pod_option(),
) -> None:
    """The pod's task queue with status, cost and the worktree path when one exists.

    Example: docket task list --json
    """
    project = _pod_name(pod)
    items = [_list_item(project, t) for t in _dispatch.read_tasks(project)]
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


def _hop_rows(ev: _evidence.TaskEvidence) -> list[list[str]]:
    return [
        [
            hop.step_id,
            hop.role,
            "yes" if hop.ok else "no",
            hop.verdict or "-",
            str(hop.verify.exit_code) if hop.verify else "-",
            hop.commit[:8] if hop.commit else "-",
            str(hop.usage.input) if hop.usage else "-",
            str(hop.usage.output) if hop.usage else "-",
        ]
        for hop in ev.hops
    ]


def _run_lines(run_ids: tuple[str, ...]) -> list[str]:
    lines = []
    for run_id in run_ids:
        rec = _runs.get_run(run_id) or {}
        line = (
            f"{run_id}  {rec.get('state', '?')}  source={rec.get('source', '?')}  "
            f"created={str(rec.get('created', ''))[:19]}"
        )
        cancel = rec.get("cancellation")
        if isinstance(cancel, dict) and cancel.get("requestedAt"):
            stopped = cancel.get("stoppedAt") or "not yet"
            line += f"  cancel requested={cancel['requestedAt']} stopped={stopped}"
        if rec.get("error"):
            line += f"  error={rec['error']}"
        lines.append(line)
    return lines


def _render_forecast(project: str) -> None:
    items = _interruptions.forecast(project, caller_default=_caller_default())
    askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
    if not askers:
        _say(f"  {_interruptions.NOTHING_WILL_ASK}")
    for i in askers:
        _say(f"  - {i.description}")
    mode = next((i for i in items if i.kind == "mode"), None)
    if mode is not None:
        ui.dim(escape(f"  {mode.description}"))
    for label, kind in (("Always enforced:", "high_risk_class"), ("Will notify:", "channel")):
        chosen = [i for i in items if i.kind == kind]
        if chosen:
            ui.dim(f"  {label}")
            for i in chosen:
                ui.dim(escape(f"    - {i.description}"))


def _render_show(
    found: TaskRef,
    task: dict[str, Any],
    ev: _evidence.TaskEvidence,
    wt: dict[str, str] | None,
    notes: list[dict[str, Any]],
) -> None:
    ui.header("task", short_id(found.task_id))
    _say(f"  pod:      {found.project}")
    _say(f"  id:       {found.task_id}")
    _say(f"  status:   {task.get('status', '?')}")
    _say(f"  priority: {task.get('priority', 'normal')}")
    _say(f"  cost:     {_cost_cell(task)}")
    _say(f"  task:     {task.get('description', '')}")
    if ev.hops:
        ui.section("Hops")
        cols = ["HOP", "ROLE", "OK", "VERDICT", "VERIFY", "COMMIT", "TOKENS IN", "TOKENS OUT"]
        ui.table([[escape(c) for c in row] for row in _hop_rows(ev)], cols)
    if found.run_ids:
        ui.section("Runs")
        for line in _run_lines(found.run_ids):
            _say(f"  {line}")
    if wt is not None:
        ui.section("Worktree")
        _say(f"  path:   {wt['path']}")
        _say(f"  branch: {wt['branch']}")
        _say(f"  base:   {wt['baseCommit']}")
        _say(f"  diff:   {wt['diff']}")
        _say(f"  merge:  {wt['merge']}")
    if notes:
        ui.section("Corrections")
        for rec in notes:
            _say(f"  {str(rec.get('ts', ''))[:19]}  {rec.get('kind', '')}  {rec.get('text', '')}")
    ui.section("May ask you")
    _render_forecast(found.project)


def _show_json(
    found: TaskRef,
    task: dict[str, Any],
    ev: _evidence.TaskEvidence,
    wt: dict[str, str] | None,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    forecast = _interruptions.forecast(found.project, caller_default=_caller_default())
    return {
        "pod": found.project,
        "task": {**_list_item(found.project, task), "worktree": wt},
        "evidence": json.loads(ev.model_dump_json(by_alias=True)),
        "runs": [_runs.get_run(r) for r in found.run_ids],
        "corrections": notes,
        "interruptions": [
            {"kind": i.kind, "description": i.description, "detail": i.detail} for i in forecast
        ],
    }


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
        ev = _evidence.task_evidence(found.project, found.task_id)
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
) -> None:
    """Print what the task changed in its worktree, against the commit it started from.

    Example: docket task diff task-04ff
    """
    found = _resolve(pod, ref)
    wt = _worktree(found.project, _task_record(found))
    if wt is None:
        ui.error(f"Task {short_id(found.task_id)} has no worktree", "It ran in place")
        raise typer.Exit(1)
    diff = _sys.git_diff(wt["path"], wt["baseCommit"])
    if diff is None:
        ui.error(f"Could not diff {wt['path']}", f"Run {wt['diff']} yourself")
        raise typer.Exit(1)
    sys.stdout.write(diff)


def _event_line(r: dict[str, Any]) -> str:
    ts = str(r.get("ts", "?"))[:19]
    etype = str(r.get("event_type", "?"))
    role = str(r.get("agent_role", "") or "")
    payload = r.get("payload", {})
    parts: list[str] = []
    if etype == "llm_call" and isinstance(payload, dict):
        parts.append(str(payload.get("model") or ""))
        in_tok, out_tok = payload.get("inputTokens"), payload.get("outputTokens")
        if in_tok is not None or out_tok is not None:
            parts.append(f"in={in_tok or 0}/out={out_tok or 0}")
        if payload.get("ok") is False:
            parts.append(f"failed: {payload.get('failureKind') or 'unknown'}")
    elif isinstance(payload, dict):
        for k in ("tool", "hop", "status", "action", "text", "task_id", "pct"):
            if payload.get(k) is not None:
                parts.append(f"{k}={payload[k]}")
    extras = []
    if r.get("cost_usd") is not None:
        with contextlib.suppress(TypeError, ValueError):
            extras.append(f"${float(r['cost_usd']):.4f}")
    if r.get("duration_ms") is not None:
        extras.append(f"{r['duration_ms']}ms")
    who = f"  ({role})" if role and role != "unknown" else ""
    summary = "  " + "  ".join(p for p in parts if p) if any(parts) else ""
    tail = f"  [{'  '.join(extras)}]" if extras else ""
    return f"  {ts}  {etype:<25}{who}{summary}{tail}"


def _trace_file(found: TaskRef) -> Path:
    return _trace.project_trace_dir(found.project) / f"agent:{found.project}:{found.task_id}.jsonl"


def _follow(path: Path) -> None:
    """Print events as they are written; return once the session has ended."""
    seen = 0
    with contextlib.suppress(KeyboardInterrupt):
        while True:
            records = _trace.read_trace(path)
            for r in records[seen:]:
                _say(_event_line(r))
            seen = len(records)
            if any(r.get("event_type") == "session_end" for r in records):
                return
            time.sleep(TAIL_POLL_S)


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
    entries = _pp.prune_task_worktrees(project, force=force, dry_run=dry_run)
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
    removed = _runs.prune_terminal(retention_s=retention_s, dry_run=dry_run)
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
    project = _pod_name(pod)
    if force and not dry_run and not _contract.confirm("Remove dirty worktrees too", yes=yes):
        raise typer.Exit(1)
    _prune_worktrees(project, force, dry_run)
    if traces:
        _prune_records(project, days, dry_run)
    _contract.next_step("docket task list")


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


def _resume_hint(project: str) -> None:
    """After a state change: say who picks the task up, or name the command that does."""
    from docket.cli import _service

    if _service.is_running():
        ui.dim("docket is running and will pick it up")
        return
    _contract.next_step(f"docket run --pod {project}")


def _approval_actor(reason: str) -> str:
    return _actor() if reason else ""


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
        _dispatch.resolve_waiting_approval(token, "granted")
        return
    except _ap.ApprovalError as err:
        ui.error(str(err))
        raise typer.Exit(1) from err
    _, note = _dispatch.resolve_waiting_approval_detail(
        token, "granted", channel="cli", actor=actor
    )
    ui.success(f"Approved {label}")
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

    Example: docket task deny task-04ff --reason "touches production"
    """
    token, _project, label = _pending_token(pod, ref)
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
    _dispatch.resolve_waiting_approval(token, "denied", channel="cli", actor=actor, reason=reason)
    ui.success(f"Denied {label}; the action is blocked")


def _question_of(found: TaskRef) -> dict[str, Any]:
    task = _task_record(found)
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
    if not _dispatch.retry_task(found.project, found.task_id):
        status = _task_record(found).get("status", "unknown")
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

    Example: docket task cancel task-04ff
    """
    found = _resolve(pod, ref)
    cancelled = _cancel_live_runs(found, _task_record(found).get("status"))
    reclaimed = False
    if _task_record(found).get("status") == "running":
        _dispatch.reclaim_stale_running(found.project)
        reclaimed = _task_record(found).get("status") != "running"
        if reclaimed:
            ui.success(f"Settled the stale claim on task {short_id(found.task_id)}")
    if not cancelled and not reclaimed:
        status = _task_record(found).get("status", "unknown")
        ui.error(f"Task {short_id(found.task_id)} is {status}", "Nothing is in flight to cancel")
        raise typer.Exit(1)
    if reclaimed:
        _contract.next_step(f"docket task retry {short_id(found.task_id)}")
