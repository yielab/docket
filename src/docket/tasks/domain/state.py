"""The states a task can be in, and the failure kinds it records."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """A task record's ``status``. Members compare equal to their stored string."""

    pending = "pending"
    running = "running"
    in_progress = "in_progress"
    waiting_input = "waiting_input"
    waiting_approval = "waiting_approval"
    blocked = "blocked"
    failed = "failed"
    done = "done"
    cancelled = "cancelled"


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
