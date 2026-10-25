"""The one expiry sweep: end every pause nobody answered by its deadline.

Each ``pending`` escalation past its ``expiresAt`` ends the way its own ``onExpiry`` says: ``deny``
denies the approval it names (the task it gated fails ``approval_denied`` through the follow-up the
denial always ran), ``block`` blocks the task waiting on its question ``input_expired``. A question
never fails a task, so a ``deny`` that names no approval blocks, and an approval fails closed, so a
``block`` that names one denies. What has no record (an approval or a question made before records
were kept) ends the same way by its own deadline, and unconsumed pre-grants past theirs are denied.
A second sweep over the same pauses adds nothing. See operator-loop.spec.md "Escalations" item 13.
"""

from __future__ import annotations

import datetime as _dt
import json as _json

from docket.governance import approval as _approval
from docket.governance import escalation_expiry as _escalation_expiry
from docket.kernel import clock as _clock
from docket.kernel.operator_contract import Escalation
from docket.observability import trace as _trace
from docket.platform import list_escalations
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

__all__ = ["sweep_escalations"]


def _all_projects() -> list[str]:
    """Every project with at least one registered pod member."""
    return sorted({p for agent in _fleet.list_agents() if (p := _pod.pod_of(agent.id))})


def _block_waiting(
    project: str, task_id: str, question_id: str, now: _dt.datetime | None
) -> list[tuple[str, str]]:
    """Block the ``waiting_input`` tasks of *project* whose question has expired at *now*: only
    *task_id*'s, and only its question *question_id*, when those are given. Returns the
    ``(task, question)`` pairs blocked."""
    blocked: list[tuple[str, str]] = []

    def _expire(t: _task.TaskRecord) -> bool:
        question = t.question
        if t.status != _state.Status.waiting_input or question is None:
            return False
        if (task_id and t.id != task_id) or (question_id and question.id != question_id):
            return False
        if now is not None:
            exp_dt = _clock.parse_iso(question.expires_at or "")
            if exp_dt is None or exp_dt > now:
                return False
        _transitions.apply_to_task(
            t,
            _state.Status.blocked,
            reason=f"question {question.id!r} expired unanswered",
            blocked_reason="input_expired",
        )
        blocked.append((t.id, question.id))
        return True

    TaskRepository.for_pod(project).update_each(_expire)
    for blocked_task, blocked_question in blocked:
        _escalation_expiry.expire("questionId", blocked_question)
        _trace.trace_event(
            project,
            f"agent:{project}:{blocked_task}",
            "lead",
            "input_expired",
            _json.dumps({"task": blocked_task, "questionId": blocked_question}),
        )
    return blocked


def _deny(record: Escalation) -> bool:
    """End *record* by denial: its approval fails closed; a pause that names none is blocked."""
    token = str(record.legacy.get("token", ""))
    if token:
        return _approval.expire_approval(token)
    return _block(record)


def _block(record: Escalation) -> bool:
    """End *record* by blocking its task; a pause that names no question denies its approval."""
    question_id = str(record.legacy.get("questionId", ""))
    if question_id and not record.legacy.get("token"):
        return bool(_block_waiting(record.pod, record.task, question_id, None))
    return _approval.expire_approval(str(record.legacy.get("token", "")))


def sweep_escalations(now: str | None = None) -> int:
    """End every pause past its deadline at *now* (an ISO stamp, default the clock) and prune the
    pre-grants past theirs; how many were ended."""
    moment = _clock.parse_iso(now or _clock.iso())
    if moment is None:
        return 0
    ended = 0
    for record in list_escalations(state="pending"):
        deadline = _clock.parse_iso(record.expires_at or "")
        if deadline is None or deadline > moment:
            continue
        if (_deny if record.on_expiry == "deny" else _block)(record):
            ended += 1
    epoch = moment.timestamp()
    for token in _approval.pending_past_deadline(epoch):
        if _approval.expire_approval(token):
            ended += 1
    for project in _all_projects():
        ended += len(_block_waiting(project, "", "", moment))
    return ended + _approval.prune_unconsumed_pregrants(epoch)
