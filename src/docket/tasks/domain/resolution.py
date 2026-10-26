"""What settling an escalation can end in: the outcome and the four ways it is refused.

Each refusal is one kind of ``kernel.errors`` so an edge maps it once (a status, an exit code, an
``isError`` result) and never by reading a message.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.kernel.errors import Conflict, InvalidInput, NotFound, Refused
from docket.kernel.operator_contract import Escalation

__all__ = [
    "EscalationInvalid",
    "EscalationNotFound",
    "EscalationNotPending",
    "EscalationRefused",
    "Resolved",
]


class EscalationNotFound(NotFound):
    """No escalation, approval or task by that name."""


class EscalationNotPending(Conflict):
    """The pause no longer waits. *already_so* is true when it ended the way the caller asked,
    which a repeated command should read as a warning and not as a failure."""

    def __init__(self, message: str, hint: str = "", *, already_so: bool = False) -> None:
        super().__init__(message, hint)
        self.already_so = already_so


class EscalationInvalid(InvalidInput):
    """The option is not one the escalation offers, or the content breaks its schema."""


class EscalationRefused(Refused):
    """A ``pre_input`` policy blocked a string of the answer."""

    def __init__(self, policy_id: str) -> None:
        self.policy_id = policy_id
        super().__init__(f"answer blocked by policy {policy_id!r}")


@dataclass(frozen=True)
class Resolved:
    """A settled escalation and the note its approval produced (``""`` when it had none)."""

    escalation: Escalation
    note: str = ""
