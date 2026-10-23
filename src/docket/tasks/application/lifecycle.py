from __future__ import annotations

import contextlib as _contextlib
import datetime as _dt
import json as _json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.agent import memory as _mem
from docket.governance import approval as _ap
from docket.governance import audit as _audit
from docket.hops.application.record import _hop_record
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.platform import git as _git
from docket.platform import process as _process
from docket.platform import store as _store
from docket.tasks.application import runs as _runs
from docket.tasks.application.queue import _task_record
from docket.tasks.domain.task import DispatchError, TaskNotFoundError, TaskResult, _normalize_task
from docket.teams import fleet as _fleet
from docket.teams import memory as _pod_memory
from docket.teams import pod as _pod
from docket.teams.settings import (
    _pod_settings,
    _resolve_timeout,
    pod_task_list_path,
    pod_turn_timeout,
    pod_verify_timeout,
)


def _apply_result(
    task: dict[str, Any], res: TaskResult, *, input_expiry_hours: int | None = None
) -> None:
    """Fold a TaskResult back onto the stored task dict (terminal state; pod-dispatch.spec.md,
    "blocked and terminal-failure re-entry"). ``blocked``/``waiting_approval``/``waiting_input``
    are never rewritten to ``pending`` here, only via ``unblock_pod``/``retry_task``/
    ``resolve_waiting_approval``/``core.answers.answer_task``. Stays pure -- HEARTBEAT.md sync
    lives in ``_finalize_task``."""
    task["status"] = res.status
    task["reason"] = res.reason
    task["hops"] = [_hop_record(h) for h in res.hops]
    task["costUsd"] = res.cost_usd
    task["claimId"] = None
    task.pop("claimPid", None)
    task.pop("consultAnswer", None)  # delivered to the hop this result came from
    if res.check_changed:
        task["checkChanged"] = list(res.check_changed)
    else:
        task.pop("checkChanged", None)
    if res.status == "blocked":
        task["blockedReason"] = res.blocked_reason or res.reason
    elif res.status == "waiting_approval":
        task["approvalToken"] = res.approval_token
        task["pendingApprovalIndex"] = res.pending_approval_index
    elif res.status == "waiting_input":
        task["question"] = res.question
        if res.question and not res.question.get("expiresAt") and input_expiry_hours:
            deadline = _clock.now() + _dt.timedelta(hours=input_expiry_hours)
            res.question["expiresAt"] = deadline.isoformat()
        if res.question and res.question.get("kind") in ("clarification", "decision"):
            task["consultations"] = int(task.get("consultations") or 0) + 1
    else:
        task["completedAt"] = _clock.iso()
        task.pop("taskGrants", None)
        if res.failure_kind:
            task["failureKind"] = res.failure_kind
        else:
            # A fresh ordinary terminal result supersedes any stale-claim
            # (or settled-refusal) marker left by an earlier attempt at
            # this same task.
            task.pop("failureKind", None)


def _finalize_task(project: str, task_id: str, res: TaskResult) -> None:
    """Persist a task's terminal outcome (status/reason/hops/cost), clear its claim, and
    re-sync HEARTBEAT.md. The only trigger that ever *removes* a ledger entry --
    ``_claim_next_task``/``_persist_hop``/``_touch_claim`` only add or keep one current."""
    expiry = _pod_settings(project).input_expiry_hours if res.status == "waiting_input" else None

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                _apply_result(t, res, input_expiry_hours=expiry)
                keys = ("input", "cached", "cacheWrite", "output")
                usage: dict[str, Any] = {**dict.fromkeys(keys, 0), "byModel": {}}
                for h in res.hops:
                    bucket = usage["byModel"].setdefault(h.model, dict.fromkeys(keys, 0))
                    for key in keys:
                        n = int((h.usage or {}).get(key, 0) or 0)
                        bucket[key] += n
                        usage[key] += n
                t["usage"] = usage
                return {"tasks": tasks}
        return None

    doc = _store.read_modify_write(pod_task_list_path(project), _fn)
    tasks_after = doc.get("tasks")
    lead_id = _pod.member_id(project, "lead")
    _mem.sync_dispatch_tasks(
        current_home().workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )
    _pod_memory.record_task_memory(project, task_id, res)


def _sweep_stale_claims(project: str) -> None:
    """Crash recovery: fail a ``running`` task whose claim has gone stale (older than
    ``CLAIM_STALE_TIMEOUT``), tagging ``failureKind: "stale_claim"`` and leaving its
    persisted ``hops`` untouched for a later ``--resume`` (pod-dispatch.spec.md, "Per-hop
    incremental persistence and crash recovery"). Runs at the top of every ``dispatch_pod`` call."""
    now = _clock.now()
    swept: list[dict[str, Any]] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        changed = False
        for t in tasks:
            if t.get("status") != "running":
                continue
            claimed_at = _clock.parse_iso(str(t.get("claimedAt") or ""))
            if claimed_at is None:
                continue
            if (now - claimed_at).total_seconds() <= current_home().claim_stale_timeout:
                continue
            t["status"] = "failed"
            t["reason"] = "stale claim — dispatcher likely crashed mid-task"
            t["failureKind"] = "stale_claim"
            t["claimId"] = None
            swept.append(dict(t))
            changed = True
        return {"tasks": tasks} if changed else None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    for t in swept:
        task_id = str(t.get("id", "task"))
        _trace.trace_event(
            project,
            f"agent:{project}:{task_id}",
            "lead",
            "stale_claim",
            _json.dumps({"task": task_id, "claimedAt": t.get("claimedAt")}),
        )


def _claim_stale_reason(task: dict[str, Any], now: _dt.datetime, lease_s: int) -> str:
    """Why *task*'s ``running`` claim is stale, or ``""``: the claiming process is gone, or the
    claim is older than *lease_s* (the pod's ``turnTimeoutS`` plus ``verifyTimeoutS``)."""
    pid = task.get("claimPid")
    if isinstance(pid, int) and not _process.process_alive(pid):
        return f"claimant pid {pid} is gone"
    claimed_at = _clock.parse_iso(str(task.get("claimedAt") or ""))
    if claimed_at is None:
        return ""
    if (now - claimed_at).total_seconds() > lease_s:
        return f"claim older than the {lease_s}s lease"
    return ""


def reclaim_stale_running(project: str) -> None:
    """``--resume``: settle every stale ``running`` claim to ``failed``/``stale_claim`` so the
    claim step that follows picks it up from its last persisted hop; audited ``task.reclaimed``."""
    now = _clock.now()
    lease_s = _resolve_timeout(None, pod_turn_timeout(project)) + _resolve_timeout(
        None, pod_verify_timeout(project)
    )
    reclaimed: list[tuple[str, str]] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        changed = False
        for t in tasks:
            if t.get("status") != "running":
                continue
            why = _claim_stale_reason(t, now, lease_s)
            if not why:
                continue
            t["status"] = "failed"
            t["reason"] = "stale claim — " + why
            t["failureKind"] = "stale_claim"
            t["claimId"] = None
            reclaimed.append((str(t.get("id", "task")), why))
            changed = True
        return {"tasks": tasks} if changed else None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    for task_id, why in reclaimed:
        _audit.audit_log("task.reclaimed", f"{project}/{task_id}: {why}")


def retry_task(project: str, task_id: str) -> bool:
    """Re-queue one ``blocked`` or ``failed`` task: a locked flip to ``pending`` that keeps its
    hops and audits ``task.retry``. Returns False if not found or in any other status."""
    found = False

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal found
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                _normalize_task(t)
                if t.get("status") not in ("blocked", "failed"):
                    return None
                t["status"] = "pending"
                for key in ("blockedReason", "failureKind", "reason", "completedAt"):
                    t.pop(key, None)
                found = True
                return {"tasks": tasks}
        return None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    if found:
        _audit.audit_log("task.retry", f"{project}/{task_id}")
    return found


def cancel_parked_task(
    project: str, task_id: str, *, channel: str, actor: str = "", reason: str = ""
) -> str:
    """Cancel a task parked in ``waiting_input`` or ``waiting_approval``: it ends ``cancelled``,
    its question or approval is cleared (a pending approval record is denied) and no hop runs.
    Audited ``task.cancel``. Returns the prior status, or ``""`` when the task is not parked."""
    prior = ""
    token = ""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal prior, token
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") != task_id:
                continue
            _normalize_task(t)
            if t.get("status") not in ("waiting_input", "waiting_approval"):
                return None
            prior = str(t["status"])
            token = str(t.get("approvalToken") or "")
            for key in ("question", "approvalToken", "pendingApprovalIndex", "taskGrants"):
                t.pop(key, None)
            t["status"] = "cancelled"
            t["reason"] = "cancelled by operator"
            t["completedAt"] = _clock.iso()
            t["claimId"] = None
            return {"tasks": tasks}
        return None

    doc = _store.read_modify_write(pod_task_list_path(project), _fn)
    if not prior:
        return ""
    if token:
        with _contextlib.suppress(_ap.ApprovalError):
            _ap.approval_deny(token, channel, actor=actor)
    tasks_after = doc.get("tasks")
    _mem.sync_dispatch_tasks(
        current_home().workspace_dir(_pod.member_id(project, "lead")),
        tasks_after if isinstance(tasks_after, list) else [],
    )
    _audit.audit_log("task.cancel", _cancel_detail(project, task_id, prior, channel, reason))
    return prior


def _cancel_detail(project: str, task_id: str, was: str, channel: str, reason: str) -> str:
    detail = f"{project}/{task_id}: was={was} channel={channel}"
    return f"{detail} reason={reason}" if reason else detail


_LIVE_RUN_STATES = ("queued", "running")


@dataclass(frozen=True)
class TaskCancelOutcome:
    """What ``cancel_task`` found and did: the task's status after, the runs it asked to stop,
    the parked state it cancelled from, whether a stale claim was settled, and the lines to show."""

    status: str
    cancelled_runs: tuple[str, ...] = ()
    parked_from: str = ""
    reclaimed: bool = False
    messages: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def cancelled(self) -> bool:
        """True when something was in flight and is now stopping, cancelled or settled."""
        return bool(self.cancelled_runs or self.parked_from or self.reclaimed)


def _live_run_ids(project: str, task_id: str, status: object) -> list[str]:
    """Ids of the pod's queued or running runs that carry the task: one that lists it, or an
    in-flight one (it names its tasks only when it finishes) while the task is running."""
    ids: list[str] = []
    for record in _runs.list_runs(project):
        if record.get("state") not in _LIVE_RUN_STATES:
            continue
        carried = [str(t) for t in record.get("taskIds") or []]
        if task_id in carried or (not carried and status == "running"):
            ids.append(str(record["id"]))
    return ids


def cancel_task(
    project: str, task_id: str, *, channel: str, actor: str = "", reason: str = ""
) -> TaskCancelOutcome:
    """Stop whatever holds *task_id*: its live runs, its parked state, or a stale ``running``
    claim. One ``task.cancel`` audit entry per call that cancelled; raises ``TaskNotFoundError``."""
    task = _task_record(project, task_id)
    if task is None:
        raise TaskNotFoundError(f"task {task_id!r} not found in pod {project!r}")
    stopped: list[str] = []
    messages: list[str] = []
    warnings: list[str] = []
    for run_id in _live_run_ids(project, task_id, task.get("status")):
        result = _runs.cancel_run(run_id, source=channel)
        if result.ok:
            stopped.append(run_id)
            messages.append(result.message)
        else:
            warnings.append(result.message)
    parked = cancel_parked_task(project, task_id, channel=channel, actor=actor, reason=reason)
    if stopped and not parked:
        _audit.audit_log(
            "task.cancel", _cancel_detail(project, task_id, "running", channel, reason)
        )
    reclaimed = False
    current = _task_record(project, task_id) or {}
    if current.get("status") == "running":
        reclaim_stale_running(project)
        current = _task_record(project, task_id) or {}
        reclaimed = current.get("status") != "running"
    return TaskCancelOutcome(
        status="cancelled" if stopped or parked else str(current.get("status", "unknown")),
        cancelled_runs=tuple(stopped),
        parked_from=parked,
        reclaimed=reclaimed,
        messages=tuple(messages),
        warnings=tuple(warnings),
    )


def task_diff(project: str, task_id: str) -> dict[str, Any]:
    """What the task's branch changed against the commit it started from, read from the codebase
    repository (the branch outlives its worktree). Raises ``TaskNotFoundError`` for an unknown
    task or a deleted branch and ``DispatchError`` for a task that ran in place."""
    task = _task_record(project, task_id)
    if task is None:
        raise TaskNotFoundError(f"task {task_id!r} not found in pod {project!r}")
    record = task.get("worktree")
    branch = str(record.get("branch") or "") if isinstance(record, dict) else ""
    if not isinstance(record, dict) or not branch:
        raise DispatchError("task ran in place")
    codebase = str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")
    base = str(record.get("baseCommit") or "")
    head = _git.git_rev_parse(codebase, branch) if codebase else None
    patch = _git.git_diff_range(codebase, base, branch) if head and base else None
    if head is None or patch is None:
        raise TaskNotFoundError(f"branch {branch!r} of task {task_id!r} no longer exists")
    wt_dir = str(record.get("dir") or "")
    present = bool(wt_dir) and not record.get("prunedAt") and Path(wt_dir).is_dir()
    if present:
        _git.trust_worktree(
            wt_dir, str(record.get("gitDir") or ""), str(record.get("commonDir") or "")
        )
    return {
        "task": task_id,
        "branch": branch,
        "baseCommit": base,
        "head": head,
        "patch": patch,
        "untracked": _git.git_untracked(wt_dir) if present else [],
        "worktreePresent": present,
    }


def unblock_pod(project: str) -> int:
    """Un-block every ``blocked`` task in *project*'s queue. Wired to ``docket pod set
    budgetUsd`` and ``docket run --resume`` -- the sanctioned re-entry paths besides ``retry_task``.
    Returns the number of tasks unblocked."""
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        return 0
    count = 0

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal count
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        changed = False
        for t in tasks:
            _normalize_task(t)
            if t.get("status") == "blocked":
                t["status"] = "pending"
                t.pop("blockedReason", None)
                count += 1
                changed = True
        return {"tasks": tasks} if changed else None

    _store.read_modify_write(path, _fn)
    return count
