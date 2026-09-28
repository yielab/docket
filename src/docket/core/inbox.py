"""The derived operator inbox: everything across every pod that needs a human (ADR 0016 §6).

`build_inbox` is pure over state its caller already read (pod tasks, pending approvals); the
current time and the cursor to filter `doneSince` by are the caller's own inputs, so no clock or
store lives in this module, matching every other `core/` service.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core.operator_contract import ApprovalView, InboxView, TaskView, a2a_state

__all__ = ["build_inbox"]

_NEEDS_YOU_STATUSES = frozenset({"blocked"})


def _all_projects() -> list[str]:
    """Every project with at least one registered pod member. Broader than
    ``core.dispatch.dispatchable_pods`` (which requires a Lead at the canonical member id), so a
    paused or otherwise partially-provisioned pod is never dropped from the inbox."""
    all_ids = [a.id for a in _fleet.list_agents()]
    return sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})


def _parse_iso(ts: str) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        dt = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return dt


def _newer(latest: str | None, candidate: str) -> str | None:
    candidate_dt = _parse_iso(candidate)
    if candidate_dt is None:
        return latest
    latest_dt = _parse_iso(latest) if latest else None
    if latest_dt is None or candidate_dt > latest_dt:
        return candidate
    return latest


def _task_view(project: str, task: dict[str, Any], now: str) -> TaskView:
    status = str(task.get("status", "pending"))
    ts = str(task.get("completedAt") or task.get("startedAt") or task.get("created") or now)
    return TaskView(
        id=str(task.get("id", "")),
        pod=project,
        status=status,
        a2a_state=a2a_state(
            status,
            blocked_reason=task.get("blockedReason"),
            failure_kind=task.get("failureKind"),
        ),
        reason=task.get("reason") or None,
        description=str(task.get("description", "")),
        priority=str(task.get("priority", "normal")),
        created_at=str(task.get("created", "")),
        updated_at=ts,
        approval_token=task.get("approvalToken"),
    )


def _approval_view(record: dict[str, Any]) -> ApprovalView:
    context = record.get("context")
    context = context if isinstance(context, dict) else {}
    return ApprovalView(
        token=str(record.get("token", "")),
        pod=str(record.get("project", "")),
        task_id=context.get("taskId"),
        role=str(record.get("role", "")),
        tool=context.get("tool"),
        action=record.get("action"),
        policy=record.get("policy"),
        state=str(record.get("state", "pending")),
        created_at=str(record.get("created", "")),
        expires_at=record.get("expiresAt"),
    )


def build_inbox(*, now: str, since: str | None = None) -> InboxView:
    """Every pod's tasks plus every pending approval, sorted into ``needsYou``/``failed``/
    ``doneSince`` (terminal after *since*, or every terminal task when omitted)/``running``.
    ``next`` is the maximum timestamp seen across every item."""
    needs_you: list[TaskView | ApprovalView] = []
    failed: list[TaskView] = []
    done_since: list[TaskView] = []
    running: list[TaskView] = []
    latest: str | None = None
    since_dt = _parse_iso(since) if since else None

    for project in _all_projects():
        for task in _dispatch.read_tasks(project):
            view = _task_view(project, task, now)
            latest = _newer(latest, view.updated_at)
            if view.status.startswith("waiting_") or view.status in _NEEDS_YOU_STATUSES:
                needs_you.append(view)
            elif view.status == "failed":
                failed.append(view)
            elif view.status == "done":
                ts_dt = _parse_iso(view.updated_at)
                if since_dt is None or (ts_dt is not None and ts_dt > since_dt):
                    done_since.append(view)
            elif view.status == "running":
                running.append(view)

    for record in _approval.list_pending():
        context = record.get("context")
        context = context if isinstance(context, dict) else {}
        if context.get("taskId"):
            continue  # already surfaced through its task's `approvalToken`
        approval_view = _approval_view(record)
        needs_you.append(approval_view)
        latest = _newer(latest, approval_view.created_at)

    return InboxView(
        needs_you=needs_you, failed=failed, done_since=done_since, running=running, next=latest
    )
