"""The one expiry sweep: end every pause nobody answered by its deadline.

Each ``pending`` escalation past its ``expiresAt`` ends the way its own ``onExpiry`` says: ``deny``
denies the approval it names (the task it gated fails ``approval_denied`` through the follow-up the
denial always ran), ``block`` blocks the task waiting on its question. A question never fails a
task, so a ``deny`` that names no approval blocks, and an approval fails closed, so a ``block``
that names one denies. A pending escalation whose pause already ended (its task was cancelled) is
settled ``expired`` without side effects, and unconsumed pre-grants past their deadline are
denied. A second sweep over the same pauses adds nothing. See operator-loop.spec.md "Escalations".
"""

from __future__ import annotations

from docket.governance import approval as _approval
from docket.governance import escalation_expiry as _escalation_expiry
from docket.kernel import clock as _clock
from docket.kernel.operator_contract import Escalation
from docket.operator import pause_is_live
from docket.platform import list_escalations, settle_escalation
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task

__all__ = ["sweep_escalations"]


def _block_waiting(record: Escalation) -> bool:
    """Block the task waiting on the question *record* with ``input_expired`` and settle the record
    ``expired``; whether the task was waiting on it."""
    blocked: list[bool] = []

    def _expire(task: _task.TaskRecord) -> bool:
        if task.status != _state.Status.waiting_input or record.id not in task.escalations:
            return False
        _transitions.apply_to_task(
            task,
            _state.Status.blocked,
            reason=f"question {record.id!r} expired unanswered",
            blocked_reason="input_expired",
        )
        blocked.append(True)
        return True

    TaskRepository.for_pod(record.pod).update(record.task, _expire)
    if blocked:
        _escalation_expiry.expire(record.id)
    return bool(blocked)


def _deny(record: Escalation, token: str) -> bool:
    """End *record* by denial: its approval fails closed; a pause that names none is blocked."""
    return _approval.expire_approval(token) if token else _block_waiting(record)


def _block(record: Escalation, token: str) -> bool:
    """End *record* by blocking its task; a pause that names no question denies its approval."""
    if token or record.kind not in ("consult", "input"):
        return _approval.expire_approval(token)
    return _block_waiting(record)


def sweep_escalations(now: str | None = None) -> int:
    """End every pause past its deadline at *now* (an ISO stamp, default the clock) and prune the
    pre-grants past theirs; how many were ended."""
    moment = _clock.parse_iso(now or _clock.iso())
    if moment is None:
        return 0
    ended = 0
    tokens = _approval.approvals_of()
    for record in list_escalations(state="pending"):
        deadline = _clock.parse_iso(record.expires_at or "")
        if deadline is None or deadline > moment:
            continue
        if not pause_is_live(record):
            settle_escalation(record.id, "expired")
            continue
        token = tokens.get(record.id, "")
        if (_deny if record.on_expiry == "deny" else _block)(record, token):
            ended += 1
    epoch = moment.timestamp()
    for token in _approval.pending_past_deadline(epoch):
        if _approval.expire_approval(token):
            ended += 1
    return ended + _approval.prune_unconsumed_pregrants(epoch)
