"""Settle the escalation behind an approval or a question that just expired.

Both expiry sweeps (``approval_sweep_expired`` and ``sweep_expired_questions``) end the pause
their record named; the escalation moves to ``expired`` and ``escalation_expired`` is written
only when this call moved it, so a second sweep over the same pause adds nothing.
"""

from __future__ import annotations

from docket.kernel import escalation_events as _events
from docket.platform import list_escalations, settle_escalation

__all__ = ["expire"]


def expire(key: str, value: str) -> bool:
    """Move the pending escalation whose ``legacy[key]`` is *value* to ``expired`` and trace it;
    whether one moved. An approval or a question made before escalations were kept has none."""
    pending = next(
        (e for e in list_escalations(state="pending") if e.legacy.get(key) == value), None
    )
    if pending is None or not settle_escalation(key, value, "expired"):
        return False
    _events.emit(_events.EXPIRED, pending.model_copy(update={"state": "expired"}))
    return True
