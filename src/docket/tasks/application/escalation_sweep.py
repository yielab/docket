"""The one expiry sweep: end every pause nobody answered by its deadline.

Each ``pending`` escalation past its ``expiresAt`` ends the way its own ``onExpiry`` says: ``deny``
denies the approval it names (the task it gated fails ``approval_denied`` through the follow-up the
denial always ran), ``block`` blocks the task waiting on its question. A question never fails a
task, so a ``deny`` that names no approval blocks, and an approval fails closed, so a ``block``
that names one denies. A pending escalation whose pause already ended (its task was cancelled) is
settled ``expired`` without side effects, and unconsumed pre-grants past their deadline are
denied. A second sweep over the same pauses adds nothing. See operator-loop.spec.md "Escalations".
A ``wait`` is ended by ``sweep_waits`` instead (pod-dispatch.spec.md "Wait steps"): its deadline
is when the task resumes, and a probe may end it sooner.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable

from docket.governance import approval as _approval
from docket.governance import escalation_expiry as _escalation_expiry
from docket.kernel import clock as _clock
from docket.kernel.operator_contract import Escalation
from docket.operator import pause_is_live
from docket.platform import list_escalations, settle_escalation
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.tasks.domain.resolution import EscalationNotPending

__all__ = ["sweep_escalations", "sweep_waits"]

# Runs the probe command of a waiting task (the pod, the task) and says whether it exited 0.
WaitProbe = Callable[[str, _task.TaskRecord], bool]


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


def _probed(record: Escalation, moment: _dt.datetime) -> None:
    """Count one probe that did not pass and schedule the next, if the task still waits on *record*."""

    def _note(task: _task.TaskRecord) -> bool:
        wait = task.wait
        if wait is None or wait.step != record.step or wait.every_s is None:
            return False
        wait.probes += 1
        wait.next_probe_at = (moment + _dt.timedelta(seconds=wait.every_s)).isoformat()
        return True

    TaskRepository.for_pod(record.pod).update(record.task, _note)


def _tick_wait(record: Escalation, moment: _dt.datetime, probe: WaitProbe | None) -> int:
    """Advance one ``wait``: run its probe when one is due, then end it if its time has come;
    1 when it ended the wait."""
    task = TaskRepository.for_pod(record.pod).get(record.task)
    wait = task.wait if task is not None else None
    if (
        task is None
        or wait is None
        or task.status != _state.Status.waiting_input
        or wait.step != record.step
        or record.id not in task.escalations
    ):
        return 0
    next_probe = _clock.parse_iso(wait.next_probe_at or "")
    if probe is not None and wait.until and next_probe is not None and next_probe <= moment:
        if probe(record.pod, task):
            try:
                _escalations.resolve(record.id, "resume", by="probe", channel="sweep")
            except EscalationNotPending:
                return 0
            return 1
        _probed(record, moment)
    due = _clock.parse_iso(wait.due_at)
    if due is None or due > moment:
        return 0
    outcome = _escalations.WAIT_TIMEOUT if wait.until else _escalations.WAIT_RESUMED
    if not _escalations.wake_wait(record, outcome):
        return 0
    _escalation_expiry.expire(record.id)
    return 1


def sweep_waits(
    now: str | None = None, *, pod: str | None = None, probe: WaitProbe | None = None
) -> int:
    """End every ``wait`` whose time has come at *now* (default the clock), or whose *probe* passes,
    for *pod* or every pod; how many were ended. A wait whose pause already ended (its task was
    cancelled) is settled ``expired`` with no side effect. Without a *probe* only time ends a wait."""
    moment = _clock.parse_iso(now or _clock.iso())
    if moment is None:
        return 0
    ended = 0
    for record in list_escalations(state="pending"):
        if record.kind != "wait" or (pod is not None and record.pod != pod):
            continue
        if not pause_is_live(record):
            settle_escalation(record.id, "expired")
            continue
        ended += _tick_wait(record, moment, probe)
    return ended


def sweep_escalations(now: str | None = None) -> int:
    """End every pause past its deadline at *now* (an ISO stamp, default the clock) and prune the
    pre-grants past theirs; how many were ended."""
    moment = _clock.parse_iso(now or _clock.iso())
    if moment is None:
        return 0
    ended = 0
    tokens = _approval.approvals_of()
    for record in list_escalations(state="pending"):
        if record.kind == "wait":
            continue
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
    ended += sweep_waits(moment.isoformat())
    return ended + _approval.prune_unconsumed_pregrants(epoch)
