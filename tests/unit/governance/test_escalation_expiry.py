"""Settling the escalation behind an expired approval or question and tracing it once."""

from __future__ import annotations

from tests.support.trace import trace_events

from docket.governance import escalation_expiry as _expiry
from docket.kernel.operator_contract import Escalation, new_escalation_id
from docket.platform import list_escalations, write_escalation

SUBJECT = "docket.governance.escalation_expiry"


def _pending() -> Escalation:
    return write_escalation(
        Escalation(
            id=new_escalation_id(),
            task="t-1",
            pod="demo",
            step="s",
            role="lead",
            kind="approval",
            caused_by="c1",
            prompt="rm -rf build",
            asked_at="2026-10-25T10:00:00Z",
            on_expiry="deny",
        )
    )


def _expired_events() -> list[dict[str, object]]:
    return [e for e in trace_events("demo") if e["event_type"] == "escalation_expired"]


def test_the_pending_escalation_moves_and_is_traced_once() -> None:
    escalation = _pending()

    assert _expiry.expire(escalation.id) is True
    assert _expiry.expire(escalation.id) is False

    (stored,) = list_escalations()
    assert (stored.id, stored.state) == (escalation.id, "expired")
    (event,) = _expired_events()
    assert event["payload"]["escalation"] == escalation.id  # type: ignore[index]
    assert event["payload"]["by"] == "timeout"  # type: ignore[index]


def test_an_escalation_that_is_not_stored_traces_nothing() -> None:
    _pending()

    assert _expiry.expire(new_escalation_id()) is False
    assert _expired_events() == []


def test_only_the_named_pause_moves() -> None:
    kept = _pending()
    gone = _pending()

    _expiry.expire(gone.id)

    assert [e.state for e in list_escalations() if e.id == kept.id] == ["pending"]
