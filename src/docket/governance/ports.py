"""What governance asks of the contexts above it, bound once per entry (``bootstrap.bind_adapters``).

An approval that times out denied must also settle the work it gated, and that work is a task:
``tasks`` sits above governance, so governance names only the shape of the answer. The same holds
for the escalation record an approval opens: the tool gate says an approval was created and the
context above decides what is recorded.
"""

from __future__ import annotations

from typing import Protocol

from docket.kernel.ports import Binding, PortNotBound


class ApprovalFollowUp(Protocol):
    """What becomes of the work an approval gated once the approval resolves."""

    def resolve_waiting_approval(self, token: str, decision: str) -> bool:
        """React to a just-applied *decision* (``granted`` or ``denied``); ``False`` for a no-op."""
        ...


approval_follow_up_port: Binding[ApprovalFollowUp] = Binding("approval_follow_up")
approval_follow_up: ApprovalFollowUp = approval_follow_up_port.proxy()


def bind_approval_follow_up(adapter: ApprovalFollowUp) -> None:
    approval_follow_up_port.bind(adapter)


class ApprovalEscalations(Protocol):
    """What becomes of a tool-call approval the gate just created."""

    def approval_opened(self, token: str, *, task_id: str, caused_by: str) -> None:
        """Record the pause behind approval *token*, made for call *caused_by* of task *task_id*
        (``""`` when the call serves no queued task)."""
        ...


approval_escalations_port: Binding[ApprovalEscalations] = Binding("approval_escalations")


def bind_approval_escalations(adapter: ApprovalEscalations) -> None:
    approval_escalations_port.bind(adapter)


def approval_opened(token: str, *, task_id: str, caused_by: str) -> None:
    """Tell the bound adapter an approval was created; a no-op where none is bound, because the
    embeddable runtime carries no task queue to record against."""
    try:
        adapter = approval_escalations_port.current()
    except PortNotBound:
        return
    adapter.approval_opened(token, task_id=task_id, caused_by=caused_by)
