from __future__ import annotations

import datetime as _dt
import json as _json
from typing import TYPE_CHECKING

from docket.governance import approval as _ap
from docket.governance import approval_pregrant as _approval_pregrant
from docket.governance import audit as _audit
from docket.kernel import clock as _clock
from docket.kernel.operator_contract import Escalation
from docket.observability import trace as _trace
from docket.platform import read_escalation
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain.task import TaskRecord
from docket.teams.settings import load_pod_settings

if TYPE_CHECKING:
    # Annotation only: the record module opens escalations, which resolve through this one.
    from docket.tasks.application.record import UnitContext

TASK_GRANT_CAP = _approval_pregrant.TASK_GRANT_CAP


def resolve_waiting_approval(
    token: str, decision: str, *, channel: str = "", actor: str = "", reason: str = ""
) -> bool:
    """React to a just-applied approval decision by moving the dispatch task it gated, if any --
    never mutates the approval record itself, only reacts to a transition
    ``governance/approval.py`` already made. See pod-dispatch.spec.md ("require_approval gate and
    waiting_approval") for the pre-hop gate's grant (-> ``pending``) and deny
    (-> ``failed``, ``failureKind: "approval_denied"``) outcomes.

    Only the status moves here. What a grant lets the next claim do (skip the gate once, pass the
    parked call once, pass it for the rest of the task) is read at that claim from the approval
    store and the task's escalations (``hops.application.resolutions``, ``hops.application.compose``).

    The task is the one the approval's context names, else the one its escalation belongs to
    (a parked in-turn call, ADR 0016 SS2, may carry only the escalation). A plain in-turn
    ``wait``-mode ask carries no task (its wait blocks the calling thread directly, so there is
    no task-level state to update here) and is unaffected: it no-ops.

    A deny carries the operator's *reason* into the task's ``reason`` as
    ``approval denied: <reason>`` so the inbox and ``task show`` say why; without one the
    text is ``approval denied``.

    Returns ``False`` as a harmless no-op for an unrelated/already-resolved token or a mismatched
    task, ``True`` when a waiting task moved."""
    try:
        rec = _ap.approval_get(token)
    except _ap.ApprovalError:
        return False
    context = rec.get("context")
    context = context if isinstance(context, dict) else {}
    check_changed = context.get("kind") == "check_changed"
    escalation_id = str(rec.get("escalation", ""))
    backed = read_escalation(escalation_id) if escalation_id else None
    task_id = str(context.get("taskId", "")) or (backed.task if backed is not None else "")
    project = str(rec.get("project", ""))
    if decision == "denied" and reason and project and project != "operator":
        # The denial reason joins the corrections ledger under the task the gate named (dispatch
        # stores it in the record's context); an approval no task carries is keyed empty.
        _corrections.record(
            project,
            "deny_reason",
            task_id=task_id,
            role=str(rec.get("role", "")) or "operator",
            text=reason,
            source=channel or "unknown",
        )
    if not project or not task_id:
        return False

    updated = False
    resolved_task_id = task_id
    now = _clock.iso()

    def _resolve(record: TaskRecord) -> bool:
        nonlocal updated, resolved_task_id
        if updated or record.id != task_id:
            return False
        if record.status != _state.Status.waiting_approval:
            return False
        if escalation_id and escalation_id not in record.escalations:
            return False
        resolved_task_id = record.id
        if decision == "granted" and check_changed:
            _transitions.apply_to_task(
                record, _state.Status.done, now=now, reason="check_changed approved"
            )
        elif decision == "granted":
            _transitions.apply_to_task(record, _state.Status.pending)
        else:
            _transitions.apply_to_task(
                record,
                _state.Status.failed,
                now=now,
                reason=f"approval denied: {reason}" if reason else "approval denied",
                failure_kind=(
                    _state.FailureKind.check_changed
                    if check_changed
                    else _state.FailureKind.approval_denied
                ),
            )
        updated = True
        return True

    TaskRepository.for_pod(project).update_each(_resolve)
    if updated:
        _trace.trace_event(
            project,
            f"agent:{project}:{resolved_task_id}",
            "lead",
            "approval_resumed" if decision == "granted" else "approval_task_denied",
            _json.dumps({"task": resolved_task_id, "escalation": escalation_id}),
        )
    return updated


def check_task_grant(token: str) -> tuple[bool, str]:
    """Before a parked approval *token* is granted for the rest of its task: ``(new, note)``.
    *new* is whether that adds a task-wide grant (``False`` for a call already covered, or one
    that is no task's); *note* is non-empty, and the grant is made once only, when the task
    already holds ``TASK_GRANT_CAP`` of them (audited ``approval.task_grant_refused``)."""
    key = _task_grant_key(token)
    if key is None:
        return False, ""
    task_id, (tool, digest, role) = key
    held = _approval_pregrant.task_grants(task_id)
    if any((g.tool, g.args_digest, g.role) == (tool, digest, role) for g in held):
        return False, ""
    if len(held) < TASK_GRANT_CAP:
        return True, ""
    _audit.audit_log(
        "approval.task_grant_refused",
        f"token={token} tool={tool} cap={TASK_GRANT_CAP}",
    )
    return False, (
        f"This task already has {TASK_GRANT_CAP} task-wide grants; this call was approved once only."
    )


def audit_task_grant(token: str, *, channel: str, actor: str) -> None:
    """Audit that parked approval *token* now covers its call for the rest of the task."""
    channel = channel if channel in _ap.APPROVAL_CHANNELS else "unknown"
    tool = str((_ap.approval_get(token).get("context") or {}).get("tool", ""))
    _audit.audit_log(
        "approval.task_grant",
        f"token={token} tool={tool} channel={channel} actor={actor or '?'}",
    )


def is_parked(token: str) -> bool:
    """Whether approval *token* is a call the tool gate parked mid-turn (its grant is read by the
    hop that re-runs), not a gate at a pipeline position."""
    try:
        context = _ap.approval_get(token).get("context")
    except _ap.ApprovalError:
        return False
    return isinstance(context, dict) and bool(context.get("parked"))


def _task_grant_key(token: str) -> tuple[str, tuple[str, str, str]] | None:
    """The task and ``(tool, argsDigest, role)`` a parked approval *token* could grant for the rest
    of its task, else ``None`` (not parked, or naming no task)."""
    try:
        rec = _ap.approval_get(token)
    except _ap.ApprovalError:
        return None
    context = rec.get("context")
    context = context if isinstance(context, dict) else {}
    task_id = str(context.get("taskId", ""))
    tool = str(context.get("tool", ""))
    digest = str(context.get("argsDigest", ""))
    role = str(rec.get("role", ""))
    if not (context.get("parked") and task_id and tool and digest and role):
        return None
    return task_id, (tool, digest, role)


def pregrants_for(task_id: str) -> list[dict[str, str]]:
    """The ``{token, tool, argsDigest}`` of every call a person approved for *task_id* that is
    still unspent: the hop passes each at most once, whatever else it asks."""
    return [
        {"token": c.token, "tool": c.tool, "argsDigest": c.args_digest}
        for c in _approval_pregrant.pending_pregrants(task_id)
    ]


def approved_ready(record: TaskRecord) -> bool:
    """A pending task a person already approved: a call approved ahead is unspent, or the pre-hop
    gate it stopped at was granted and no claim has applied that yet."""
    if record.status != _state.Status.pending:
        return False
    if _approval_pregrant.pending_pregrants(record.id):
        return True
    return any(
        e.resolution is not None and e.resolution.applied_at is None
        for e in _resolved_positions(record)
    )


def _resolved_positions(record: TaskRecord) -> list[Escalation]:
    """The task's approvals at a pipeline position (a gate or the enqueue screen) that a person
    resolved."""
    found: list[Escalation] = []
    for escalation_id in record.escalations:
        escalation = read_escalation(escalation_id)
        if (
            escalation is not None
            and escalation.kind in ("approval", "gate")
            and escalation.state == "resolved"
        ):
            found.append(escalation)
    return found


def mint_task_grant_pregrants(ctx: UnitContext, role: str) -> list[dict[str, str]]:
    """One fresh single-use pre-grant per task-wide grant made for *role*, bound to this project
    and role: a grant never reaches a hop of another role."""
    grants = [g for g in _approval_pregrant.task_grants(ctx.task_id) if g.role == role]
    if not grants:
        return []
    deadline = _clock.now() + _dt.timedelta(
        hours=load_pod_settings(ctx.project).approval_expiry_hours
    )
    minted: list[dict[str, str]] = []
    for grant in grants:
        try:
            pre = _approval_pregrant.create_pregrant(
                ctx.project,
                role,
                grant.tool,
                grant.args_digest,
                task_id=ctx.task_id,
                expires_at=deadline.isoformat(),
                channel=grant.channel if grant.channel in _ap.APPROVAL_CHANNELS else "cli",
                actor=grant.actor or "approve_task",
                source=_approval_pregrant.MINTED,
            )
        except _ap.ApprovalError:
            continue
        minted.append({"token": pre, "tool": grant.tool, "argsDigest": grant.args_digest})
    return minted
