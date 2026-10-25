from __future__ import annotations

import contextlib as _contextlib
import datetime as _dt
import json as _json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docket.governance import approval as _ap
from docket.governance import audit as _audit
from docket.kernel import clock as _clock
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.kernel.ports import process as _process
from docket.observability import trace as _trace
from docket.tasks.application import runs as _runs
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain.parts import TaskUsage
from docket.tasks.domain.task import TaskNotFoundError, TaskRecord, TaskResult
from docket.teams import fleet as _fleet
from docket.teams import memory as _pod_memory
from docket.teams import pod as _pod
from docket.teams.settings import (
    load_pod_settings,
    pod_task_list_path,
    pod_turn_timeout,
    pod_verify_timeout,
    resolve_timeout,
)


def _apply_result(
    record: TaskRecord, res: TaskResult, *, input_expiry_hours: int | None = None
) -> None:
    """Fold a TaskResult back onto the stored task (terminal state; pod-dispatch.spec.md,
    "blocked and terminal-failure re-entry"). ``blocked``/``waiting_approval``/``waiting_input``
    are never rewritten to ``pending`` here, only via ``unblock_pod``/``retry_task``/
    ``resolve_waiting_approval``/``hops.application.answers.answer_task``. Pure -- the repository
    syncs the HEARTBEAT.md ledger."""
    if res.status == _state.Status.waiting_input and (
        res.question and not res.question.get("expiresAt") and input_expiry_hours
    ):
        deadline = _clock.now() + _dt.timedelta(hours=input_expiry_hours)
        res.question["expiresAt"] = deadline.isoformat()
    # A fresh ordinary terminal result (no failure kind) supersedes any stale-claim or
    # settled-refusal marker left by an earlier attempt at this same task; a consult answer is
    # delivered to the hop this result came from (``ran``).
    _transitions.apply_to_task(
        record,
        _state.Status(res.status),
        now=_clock.iso(),
        reason=res.reason,
        failure_kind=res.failure_kind,
        blocked_reason=res.blocked_reason or res.reason,
        approval_token=res.approval_token,
        pending_index=res.pending_approval_index,
        question=res.question,
        ran=True,
    )
    record.hops = list(res.hops)
    record.cost_usd = res.cost_usd
    record.check_changed = list(res.check_changed)
    if res.status == _state.Status.waiting_input and record.question_is_consultation:
        record.consultations += 1


def _task_usage(res: TaskResult) -> TaskUsage:
    """The measured tokens of *res*'s hops: their sum and the same totals per served model."""
    keys = ("input", "cached", "cacheWrite", "output")
    total = dict.fromkeys(keys, 0)
    by_model: dict[str, dict[str, int]] = {}
    for hop in res.hops:
        bucket = by_model.setdefault(hop.model, dict.fromkeys(keys, 0))
        for key in keys:
            n = int((hop.usage or {}).get(key, 0) or 0)
            bucket[key] += n
            total[key] += n
    return TaskUsage.model_validate({**total, "byModel": by_model})


def finalize_task(project: str, task_id: str, res: TaskResult) -> None:
    """Persist a task's terminal outcome (status/reason/hops/cost), clear its claim, and
    re-sync HEARTBEAT.md. The only trigger that ever *removes* a ledger entry --
    ``claim_next_task``/``persist_hop``/``touch_claim`` only add or keep one current."""
    expiry = (
        load_pod_settings(project).input_expiry_hours if res.status == "waiting_input" else None
    )
    usage = _task_usage(res)

    def _fn(record: TaskRecord) -> None:
        _apply_result(record, res, input_expiry_hours=expiry)
        record.usage = usage

    TaskRepository.for_pod(project).update(task_id, _fn)
    _pod_memory.record_task_memory(project, task_id, res)


def sweep_stale_claims(project: str) -> None:
    """Crash recovery: fail a ``running`` task whose claim has gone stale (older than
    ``CLAIM_STALE_TIMEOUT``), tagging ``failureKind: "stale_claim"`` and leaving its
    persisted ``hops`` untouched for a later ``--resume`` (pod-dispatch.spec.md, "Per-hop
    incremental persistence and crash recovery"). Runs at the top of every ``dispatch_pod`` call."""
    now = _clock.now()
    timeout = current_home().claim_stale_timeout

    def _sweep(record: TaskRecord) -> bool:
        claimed_at = _clock.parse_iso(record.claimed_at or "")
        if record.status != _state.Status.running or claimed_at is None:
            return False
        if (now - claimed_at).total_seconds() <= timeout:
            return False
        _transitions.apply_to_task(
            record,
            _state.Status.failed,
            reason="stale claim — dispatcher likely crashed mid-task",
            failure_kind=_state.FailureKind.stale_claim,
        )
        return True

    for record in TaskRepository.for_pod(project).update_each(_sweep):
        _trace_stale_claim(project, record)


def _trace_stale_claim(project: str, record: TaskRecord) -> None:
    """Mark *record*'s trace with the ``stale_claim`` event, so a hop that starts again after
    its claim was lost reads differently from an ordinary retry."""
    _trace.trace_event(
        project,
        f"agent:{project}:{record.id}",
        "lead",
        "stale_claim",
        _json.dumps({"task": record.id, "claimedAt": record.claimed_at}),
    )


def _claim_stale_reason(record: TaskRecord, now: _dt.datetime, lease_s: int) -> str:
    """Why *record*'s ``running`` claim is stale, or ``""``: the claiming process is gone, or the
    claim is older than *lease_s* (the pod's ``turnTimeoutS`` plus ``verifyTimeoutS``)."""
    pid = record.claim_pid
    if pid is not None and not _process.process_alive(pid):
        return f"claimant pid {pid} is gone"
    claimed_at = _clock.parse_iso(record.claimed_at or "")
    if claimed_at is None:
        return ""
    if (now - claimed_at).total_seconds() > lease_s:
        return f"claim older than the {lease_s}s lease"
    return ""


def reclaim_stale_running(project: str) -> None:
    """``--resume``: settle every stale ``running`` claim to ``failed``/``stale_claim`` so the
    claim step that follows picks it up from its last persisted hop; audited ``task.reclaimed``
    and traced as ``stale_claim``, as the timeout sweep does."""
    now = _clock.now()
    lease_s = resolve_timeout(None, pod_turn_timeout(project)) + resolve_timeout(
        None, pod_verify_timeout(project)
    )
    reasons: dict[str, str] = {}

    def _reclaim(record: TaskRecord) -> bool:
        if record.status != _state.Status.running:
            return False
        why = _claim_stale_reason(record, now, lease_s)
        if not why:
            return False
        _transitions.apply_to_task(
            record,
            _state.Status.failed,
            reason="stale claim — " + why,
            failure_kind=_state.FailureKind.stale_claim,
        )
        reasons[record.id] = why
        return True

    for record in TaskRepository.for_pod(project).update_each(_reclaim):
        _trace_stale_claim(project, record)
        _audit.audit_log("task.reclaimed", f"{project}/{record.id}: {reasons[record.id]}")


def retry_task(project: str, task_id: str) -> bool:
    """Re-queue one ``blocked`` or ``failed`` task: a locked flip to ``pending`` that keeps its
    hops and audits ``task.retry``. Returns False if not found or in any other status."""
    found = False

    def _retry(record: TaskRecord) -> bool:
        nonlocal found
        if record.status not in (_state.Status.blocked, _state.Status.failed):
            return False
        _transitions.apply_to_task(record, _state.Status.pending, retry=True)
        found = True
        return True

    TaskRepository.for_pod(project).update(task_id, _retry)
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

    def _cancel(record: TaskRecord) -> bool:
        nonlocal prior, token
        if record.status not in (_state.Status.waiting_input, _state.Status.waiting_approval):
            return False
        prior = record.status.value
        token = record.approval_token or ""
        _transitions.apply_to_task(
            record, _state.Status.cancelled, now=_clock.iso(), reason="cancelled by operator"
        )
        return True

    TaskRepository.for_pod(project).update(task_id, _cancel)
    if not prior:
        return ""
    if token:
        with _contextlib.suppress(_ap.ApprovalError):
            _ap.approval_deny(token, channel, actor=actor)
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
    repo = TaskRepository.for_pod(project)
    task = repo.get(task_id)
    if task is None:
        raise TaskNotFoundError(f"task {task_id!r} not found in pod {project!r}")
    stopped: list[str] = []
    messages: list[str] = []
    warnings: list[str] = []
    for run_id in _live_run_ids(project, task_id, task.status):
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
    current = repo.get(task_id)
    if current is not None and current.status == _state.Status.running:
        reclaim_stale_running(project)
        current = repo.get(task_id)
        reclaimed = current is None or current.status != _state.Status.running
    return TaskCancelOutcome(
        status="cancelled"
        if stopped or parked
        else (current.status.value if current is not None else "unknown"),
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
    task = TaskRepository.for_pod(project).get(task_id)
    if task is None:
        raise TaskNotFoundError(f"task {task_id!r} not found in pod {project!r}")
    record = task.worktree
    if record is None or not record.branch:
        raise DispatchError("task ran in place")
    branch = record.branch
    codebase = str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")
    base = record.base_commit
    head = _git.git_rev_parse(codebase, branch) if codebase else None
    patch = _git.git_diff_range(codebase, base, branch) if head and base else None
    if head is None or patch is None:
        raise TaskNotFoundError(f"branch {branch!r} of task {task_id!r} no longer exists")
    wt_dir = task.worktree_dir
    present = bool(wt_dir) and Path(wt_dir).is_dir()
    if present:
        _git.trust_worktree(wt_dir, record.git_dir or "", record.common_dir or "")
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

    def _unblock(record: TaskRecord) -> bool:
        if record.status != _state.Status.blocked:
            return False
        _transitions.apply_to_task(record, _state.Status.pending)
        return True

    return len(TaskRepository.for_pod(project).update_each(_unblock))
