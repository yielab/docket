"""Settling the escalation behind an expired approval or question and tracing it once."""

from __future__ import annotations

from tests.support.trace import trace_events

from docket.governance import escalation_expiry as _expiry
from docket.kernel.operator_contract import Escalation, new_escalation_id
from docket.platform import list_escalations, write_escalation

SUBJECT = "docket.governance.escalation_expiry"


def _pending(**legacy: str) -> Escalation:
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
            legacy=dict(legacy),
        )
    )


def _expired_events() -> list[dict[str, object]]:
    return [e for e in trace_events("demo") if e["event_type"] == "escalation_expired"]


def test_the_pending_escalation_moves_and_is_traced_once() -> None:
    escalation = _pending(token="apr-a")

    assert _expiry.expire("token", "apr-a") is True
    assert _expiry.expire("token", "apr-a") is False

    (stored,) = list_escalations()
    assert (stored.id, stored.state) == (escalation.id, "expired")
    (event,) = _expired_events()
    assert event["payload"]["escalation"] == escalation.id  # type: ignore[index]
    assert event["payload"]["by"] == "timeout"  # type: ignore[index]


def test_an_approval_with_no_escalation_traces_nothing() -> None:
    _pending(token="apr-a")

    assert _expiry.expire("token", "apr-other") is False
    assert _expired_events() == []


def test_only_the_named_pause_moves() -> None:
    kept = _pending(token="apr-keep")
    _pending(token="apr-gone")

    _expiry.expire("token", "apr-gone")

    assert [e.state for e in list_escalations() if e.id == kept.id] == ["pending"]
