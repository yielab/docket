"""The derived operator inbox: everything across every pod that needs a human (ADR 0016 §6).

`build_inbox` reads the pods' tasks and the pending escalations; the current time and the cursor to
filter `doneSince` by are the caller's own inputs, so no clock lives in this module, matching every
other application service.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from docket.kernel import clock as _clock
from docket.kernel.brief import TaskBrief
from docket.kernel.operator_contract import (
    Escalation,
    EscalationAffordances,
    EscalationPage,
    EscalationView,
    InboxView,
    TaskView,
    a2a_state,
)
from docket.operator.ports import task_reader as _tasks
from docket.platform import list_escalations, read_escalation
from docket.teams import fleet as _fleet
from docket.teams import memory as _pod_memory
from docket.teams import pod as _pod

__all__ = [
    "MAX_DECIDED",
    "MemoryItem",
    "build_inbox",
    "escalation_page",
    "escalation_view",
    "escalation_views",
    "pause_is_live",
    "pending_memory",
    "task_view",
]

_NEEDS_YOU_STATUSES = frozenset({"blocked"})


# How many decisions the pod took alone the inbox shows, newest first.
MAX_DECIDED = 20


def _all_projects() -> list[str]:
    """Every project with at least one registered pod member. Broader than
    ``tasks.application.queue.dispatchable_pods`` (which requires a Lead at the canonical member id), so a
    paused or otherwise partially-provisioned pod is never dropped from the inbox."""
    all_ids = [a.id for a in _fleet.list_agents()]
    return sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})


def _newer(latest: str | None, candidate: str) -> str | None:
    candidate_dt = _clock.parse_iso(candidate)
    if candidate_dt is None:
        return latest
    latest_dt = _clock.parse_iso(latest) if latest else None
    if latest_dt is None or candidate_dt > latest_dt:
        return candidate
    return latest


def _task_brief(raw: Any) -> TaskBrief | None:
    if not isinstance(raw, dict):
        return None
    try:
        return TaskBrief.model_validate(raw)
    except ValidationError:
        return None


# The statuses a task can be in while a pause it opened still waits: parked on it, or running
# (a consult or an approval a turn waits on in place). Any other status ended the pause.
_WAITING_STATUSES = frozenset({"waiting_approval", "waiting_input", "running"})


def _is_live(escalation: Escalation, task_status: str | None) -> bool:
    """Whether the pause *escalation* names still waits for a person: it is stored ``pending``
    and the task it belongs to (when the pod's queue holds it) has not moved past waiting."""
    if escalation.state != "pending":
        return False
    return task_status is None or task_status in _WAITING_STATUSES


def _statuses(tasks: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    return {str(t.get("id", "")): str(t.get("status", "")) for t in tasks}


def pause_is_live(escalation: Escalation) -> bool:
    """Whether the pause *escalation* names still waits for a person: the same join the views
    make, for one record. A record that is not stored ``pending`` never does."""
    if escalation.state != "pending":
        return False
    if not escalation.task:
        return True
    status = _statuses(_tasks.read_tasks(escalation.pod)).get(escalation.task)
    return _is_live(escalation, status)


def _pending_id(task: Mapping[str, Any]) -> str | None:
    """The id of the escalation *task* waits on: the newest one it lists that is still pending."""
    for escalation_id in reversed([str(i) for i in task.get("escalations") or []]):
        record = read_escalation(escalation_id)
        if record is not None and record.state == "pending":
            return record.id
    return None


def _waits_on_a_wait(escalation: str | None) -> bool:
    """Whether the pause *escalation* names is a ``wait``: nobody is asked, so no one is needed."""
    record = read_escalation(escalation) if escalation else None
    return record is not None and record.kind == "wait"


def task_view(
    project: str, task: dict[str, Any], now: str = "", escalation: str | None = None
) -> TaskView:
    """One task record as the operator contract's ``TaskView`` -- the inbox and the HTTP task
    routes build it here. *escalation* is the pause the task waits on when the caller already
    knows it; a task that waits (``waiting_*``) otherwise looks it up on its own record."""
    status = str(task.get("status", "pending"))
    ts = str(task.get("completedAt") or task.get("startedAt") or task.get("created") or now)
    if escalation is None and status.startswith("waiting_"):
        escalation = _pending_id(task)
    return TaskView(
        id=str(task.get("id", "")),
        pod=project,
        status=status,
        a2a_state="WORKING"
        if status == "waiting_input" and _waits_on_a_wait(escalation)
        else a2a_state(
            status,
            blocked_reason=task.get("blockedReason"),
            failure_kind=task.get("failureKind"),
        ),
        reason=task.get("reason") or None,
        description=str(task.get("description", "")),
        priority=str(task.get("priority", "normal")),
        created_at=str(task.get("created", "")),
        updated_at=ts,
        escalation=escalation,
        brief=_task_brief(task.get("brief")),
    )


def _escalation_view(escalation: Escalation, live: bool) -> EscalationView:
    """*escalation* as a view. A stored ``pending`` stays so only while its pause is *live*; a
    pause that ended without settling the record (its task was cancelled) reads ``resolved``."""
    state = escalation.state
    if state == "pending" and not live:
        state = "resolved"
    pending = state == "pending"
    fields = escalation.model_dump(by_alias=True)
    fields["state"] = state
    fields["affordances"] = EscalationAffordances(
        options=[o.id for o in escalation.options] if pending else [],
        accepts_text=pending and bool((escalation.requested_schema or {}).get("properties")),
        resolve_url=f"/escalations/{escalation.id}",
    )
    return EscalationView.model_validate(fields)


def escalation_view(escalation: Escalation) -> EscalationView:
    """*escalation* as a surface reads it, its ``state`` joined with the pause it names."""
    return _escalation_view(escalation, pause_is_live(escalation))


def escalation_views(
    *, since_seq: int | None = None, pod: str | None = None, task: str | None = None
) -> list[EscalationView]:
    """The stored escalations after *since_seq* (all when omitted) that name *pod* and *task*
    when given, by ``seq``, each with its ``state`` joined with the task its pause waits on."""
    records = [
        e
        for e in list_escalations(since_seq=since_seq)
        if (pod is None or e.pod == pod) and (task is None or e.task == task)
    ]
    statuses = {
        project: _statuses(_tasks.read_tasks(project)) for project in {e.pod for e in records}
    }
    return [
        _escalation_view(e, _is_live(e, statuses[e.pod].get(e.task) if e.task else None))
        for e in records
    ]


def escalation_page(
    *, since_seq: int | None = None, pod: str | None = None, task: str | None = None
) -> EscalationPage:
    """The views of ``escalation_views`` with the cursor to pass back: the highest ``seq``
    returned, else *since_seq*, else ``0``."""
    views = escalation_views(since_seq=since_seq, pod=pod, task=task)
    return EscalationPage(escalations=views, next=max([since_seq or 0, *(v.seq for v in views)]))


def build_inbox(*, now: str, since: str | None = None) -> InboxView:
    """Every pod's tasks plus every pending escalation, sorted into ``needsYou``/``failed``/
    ``doneSince`` (terminal after *since*)/``running``, ``next`` the latest timestamp seen,
    ``escalations`` the pauses still waiting and ``decided`` the ones the pod settled alone. A
    task that waits shows once, with the id of its pending escalation; a pending escalation no
    waiting task carries (an approval a running turn waits on, one outside a pod's queue) is a
    ``needsYou`` item of its own."""
    needs_you: list[TaskView | EscalationView] = []
    failed: list[TaskView] = []
    done_since: list[TaskView] = []
    running: list[TaskView] = []
    latest: str | None = None
    since_dt = _clock.parse_iso(since) if since else None
    statuses: dict[str, dict[str, str]] = {}
    pending = list_escalations(state="pending")
    waiting_on = {(e.pod, e.task): e.id for e in pending if e.task}
    machine_waits = {(e.pod, e.task) for e in pending if e.kind == "wait"}

    for project in _all_projects():
        tasks = _tasks.read_tasks(project)
        statuses[project] = _statuses(tasks)
        for task in tasks:
            view = task_view(project, task, now, waiting_on.get((project, str(task.get("id", "")))))
            latest = _newer(latest, view.updated_at)
            if (project, view.id) in machine_waits and view.status == "waiting_input":
                continue  # waits on a time or a probe: it needs no one, its record is listed below
            if view.status.startswith("waiting_") or view.status in _NEEDS_YOU_STATUSES:
                needs_you.append(view)
            elif view.status == "failed":
                failed.append(view)
            elif view.status == "done":
                ts_dt = _clock.parse_iso(view.updated_at)
                if since_dt is None or (ts_dt is not None and ts_dt > since_dt):
                    done_since.append(view)
            elif view.status == "running":
                running.append(view)

    def _status(e: Escalation) -> str | None:
        return statuses.get(e.pod, {}).get(e.task) if e.task else None

    escalations = [_escalation_view(e, True) for e in pending if _is_live(e, _status(e))]
    carried = {(t.pod, t.id) for t in needs_you if isinstance(t, TaskView)}
    for pending_view in escalations:
        if pending_view.kind != "wait" and (pending_view.pod, pending_view.task) not in carried:
            needs_you.append(pending_view)
            latest = _newer(latest, pending_view.asked_at)
    decided = [_escalation_view(e, False) for e in reversed(list_escalations(state="decided"))][
        :MAX_DECIDED
    ]
    return InboxView(
        needs_you=needs_you,
        failed=failed,
        done_since=done_since,
        running=running,
        next=latest,
        escalations=escalations,
        decided=decided,
    )


@dataclass(frozen=True)
class MemoryItem:
    """One pod-memory entry waiting for the operator; outside the operator-v1 contract."""

    pod: str
    id: str
    kind: str
    subject: str
    note: str
    reason: str
    task: str


def pending_memory() -> list[MemoryItem]:
    """Every pending memory entry of every pod, oldest first within a pod."""
    return [
        MemoryItem(
            pod=project,
            id=entry.id,
            kind=entry.kind,
            subject=entry.subject,
            note=entry.note,
            reason=entry.reason,
            task=entry.provenance.get("task", ""),
        )
        for project in _all_projects()
        for entry in _pod_memory.list_entries(project, "pending")
    ]
