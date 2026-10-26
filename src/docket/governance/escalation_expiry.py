"""Settle the escalation behind an approval or a question that just expired.

Both expiry sweeps (``approval_sweep_expired`` and ``sweep_expired_questions``) end the pause
their record named; the escalation moves to ``expired`` and ``escalation_expired`` is written
only when this call moved it, so a second sweep over the same pause adds nothing.
"""

from __future__ import annotations

from docket.kernel import escalation_events as _events
from docket.platform import read_escalation, settle_escalation

__all__ = ["expire"]


def expire(escalation_id: str) -> bool:
    """Move the pending escalation *escalation_id* to ``expired`` and trace it; whether this call
    moved it. An approval made where no escalation is kept (the embeddable runtime) has none."""
    pending = read_escalation(escalation_id)
    if pending is None or not settle_escalation(escalation_id, "expired"):
        return False
    _events.emit(_events.EXPIRED, pending.model_copy(update={"state": "expired"}))
    return True
