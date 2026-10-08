"""The task commands: add, list, show, diff, trace, prune, approve, deny and chat."""

from __future__ import annotations

import contextlib
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


def _interruption_summary(task_id: str, project: str) -> str:
    """One line for `task add`: what could pause this pod's next run before it starts."""
    items = _interruptions.forecast(project, caller_default=_caller_default())
    askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
    if not askers:
        return _interruptions.NOTHING_WILL_ASK
    counts: dict[str, int] = {}
    for i in askers:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    parts = [f"{n} {kind.replace('_', ' ')}" for kind, n in sorted(counts.items())]
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
