"""What governance asks of the contexts above it, bound once per entry (``bootstrap.bind_adapters``).

An approval that times out denied must also settle the work it gated, and that work is a task:
``tasks`` sits above governance, so governance names only the shape of the answer.
"""

from __future__ import annotations

from typing import Protocol

from docket.kernel.ports import Binding


class ApprovalFollowUp(Protocol):
    """What becomes of the work an approval gated once the approval resolves."""

    def resolve_waiting_approval(self, token: str, decision: str) -> bool:
        """React to a just-applied *decision* (``granted`` or ``denied``); ``False`` for a no-op."""
        ...


approval_follow_up_port: Binding[ApprovalFollowUp] = Binding("approval_follow_up")
approval_follow_up: ApprovalFollowUp = approval_follow_up_port.proxy()


def bind_approval_follow_up(adapter: ApprovalFollowUp) -> None:
    approval_follow_up_port.bind(adapter)
