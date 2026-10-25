"""Helpers shared by the split halves of one test file."""

from __future__ import annotations

from typing import Any

from docket.kernel.operator_contract import EscalationView, make_event


class _ChannelSpecLike:
    def __init__(self, config: dict[str, str]) -> None:
        self.config = config
        self.dialect = ""
        self.secret: str | None = None


def _event_approval() -> Any:
    return make_event(
        "approval.requested",
        "alpha",
        "approval:tok-1",
        {"pod": "alpha", "token": "tok-1"},
        time="2026-09-28T00:00:00Z",
        version="pending:tok-1",
    )


def _event_minimal_with_canary() -> Any:
    """A minimal-content event whose underlying action is the literal CANARY_7f3 string."""
    approval = EscalationView.model_validate(
        {
            "id": "esc-0123456789ab",
            "task": "",
            "pod": "alpha",
            "step": "",
            "role": "implementer",
            "kind": "approval",
            "causedBy": "c1",
            "prompt": "git push origin CANARY_7f3",
            "askedAt": "2026-09-28T00:00:00Z",
            "onExpiry": "deny",
            "affordances": {"resolveUrl": "/escalations/esc-0123456789ab"},
        }
    )
    # Build the event at minimal content level
    from docket.operator.notify import render_data

    data = render_data(approval, "minimal")
    return make_event(
        "approval.requested",
        "alpha",
        "escalation:esc-0123456789ab",
        data,
        time="2026-09-28T00:00:00Z",
        version="pending",
    )
