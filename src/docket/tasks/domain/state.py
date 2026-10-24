"""The states a task can be in, and the failure kinds it records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum, nonmember
from typing import Any

from docket.kernel.errors import Conflict


class Status(StrEnum):
    """A task record's ``status``. Members compare equal to their stored string."""

    pending = "pending"
    running = "running"
    waiting_input = "waiting_input"
    waiting_approval = "waiting_approval"
    blocked = "blocked"
    failed = "failed"
    done = "done"
    cancelled = "cancelled"

    # A task no run owns any more: nothing reclaims it short of a retry.
    TERMINAL = nonmember(frozenset({"done", "failed", "cancelled"}))


class FailureKind(StrEnum):
    """The ``failureKind`` values the task state itself writes or reads back.

    Hop and gate outcomes carry further kinds as plain strings (``gate_failed``, ``rejected``,
    ``budget``, ``run_cancelled`` and the driver's own); they pass through unchanged."""

    stale_claim = "stale_claim"
    dispatch_refused = "dispatch_refused"
    approval_denied = "approval_denied"
    check_changed = "check_changed"


# A ``failed`` task ``--resume`` may reclaim: a swept crash, or a settled deterministic refusal.
# Neither is a graded hop or gate outcome.
RESUMABLE_FAILURE_KINDS: frozenset[str] = frozenset(
    {FailureKind.stale_claim, FailureKind.dispatch_refused}
)


class IllegalTransition(Conflict):
    """A task cannot move from its status to the one asked for."""


# A pipeline run (or an operator action) can end a task in any of these from whatever status the
# record holds when it lands: a stale sweep or a retry can race the run that is still finishing, and
# the record has always taken the run's outcome. They are the table's "settle" edges.
SETTLE_TARGETS: frozenset[Status] = frozenset(
    {
        Status.waiting_input,
        Status.waiting_approval,
        Status.blocked,
        Status.done,
        Status.failed,
        Status.cancelled,
    }
)

# The remaining edges: a claim starts a task, and an operator or a resolved question reopens one.
_REOPEN_EDGES: frozenset[tuple[Status, Status]] = frozenset(
    {
        (Status.pending, Status.running),
        (Status.failed, Status.running),
        (Status.blocked, Status.pending),
        (Status.failed, Status.pending),
        (Status.waiting_input, Status.pending),
        (Status.waiting_approval, Status.pending),
    }
)

ALLOWED: frozenset[tuple[Status, Status]] = _REOPEN_EDGES | frozenset(
    (frm, to) for frm in Status for to in SETTLE_TARGETS
)


@dataclass(frozen=True)
class Transition:
    """What moving a task to ``to`` does to its record: fields to set, fields to remove.

    Removals apply first, so a field both removed and set ends up set."""

    to: Status
    fields: Mapping[str, Any] = field(default_factory=dict)
    drop: tuple[str, ...] = ()


def decide(
    status: str,
    to: Status,
    *,
    now: str = "",
    reason: str | None = None,
    failure_kind: str = "",
    blocked_reason: str = "",
    pid: int = 0,
    approval_token: str | None = None,
    pending_index: int | None = None,
    question: Mapping[str, Any] | None = None,
    retry: bool = False,
    ran: bool = False,
    keep_grants: bool = False,
) -> Transition:
    """The record changes for moving a task from *status* to *to*, or ``IllegalTransition``.

    Pure: the caller supplies every fact, including the time. ``reason`` is written when given;
    ``retry`` also clears the previous outcome on the way back to ``pending``; ``ran`` marks an
    outcome the pipeline reached by running hops (their consult answer is delivered);
    ``keep_grants`` leaves a terminal task's task-wide grants in place. A ``stale_claim`` failure is
    evidence of a lost claim, not a finished task: it keeps the claim's pid and grants and stamps
    no ``completedAt``."""
    if (frm := _status_or_none(status)) is None:
        if to not in SETTLE_TARGETS:
            raise IllegalTransition(f"a task with status {status!r} cannot move to {to.value}")
    elif (frm, to) not in ALLOWED:
        raise IllegalTransition(f"a task cannot move from {frm.value} to {to.value}")

    fields: dict[str, Any] = {}
    drop: list[str] = []
    if status == Status.waiting_approval:
        drop += ["approvalToken", "pendingApprovalIndex"]
    if status == Status.waiting_input and to != Status.waiting_input:
        drop.append("question")

    if to == Status.running:
        fields.update(startedAt=now, claimedAt=now, claimPid=pid)
        drop.append("failureKind")
    elif to == Status.pending:
        drop.append("blockedReason")
        if retry:
            drop += ["failureKind", "reason", "completedAt"]
    else:
        stale = failure_kind == FailureKind.stale_claim
        if reason is not None:
            fields["reason"] = reason
        if not stale:
            drop.append("claimPid")
        if ran:
            drop.append("consultAnswer")
        if to == Status.waiting_input:
            fields["question"] = question
        elif to == Status.waiting_approval:
            fields.update(approvalToken=approval_token, pendingApprovalIndex=pending_index)
        elif to == Status.blocked:
            fields["blockedReason"] = blocked_reason
        else:
            if not stale:
                fields["completedAt"] = now
            if failure_kind:
                fields["failureKind"] = failure_kind
            else:
                drop.append("failureKind")
            if not (keep_grants or stale):
                drop.append("taskGrants")
    return Transition(to=to, fields=fields, drop=tuple(drop))


def _status_or_none(status: str) -> Status | None:
    try:
        return Status(status)
    except ValueError:
        return None
