"""A `turn` escalation: how a conversation task's pause is opened and how it ends.

Real pod, real task, real records. The turn-running hop that opens one in dispatch is not part of
this slice, so the task is put into `waiting_input` directly and its escalation is opened through
`open_for_turn`, the opener that hop will call.
"""

from __future__ import annotations

import pytest
from tests.support import escalations as _support_escalations
from tests.support.escalations import PROJECT, turn_escalation
from tests.support.tasks import stored_task, update_task

from docket.platform import read_escalation
from docket.tasks.application import escalation_sweep as _sweep
from docket.tasks.application import escalations as _esc
from docket.tasks.domain.resolution import EscalationInvalid, EscalationNotPending

SUBJECT = "docket.tasks.application.escalations"

demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("demo_pod")

_LATER = "2999-01-01T00:00:00+00:00"


def test_a_turn_offers_reply_and_close_and_carries_the_answer() -> None:
    escalation = turn_escalation(answer="Use a dict.")

    assert (escalation.kind, escalation.state, escalation.prompt) == (
        "turn",
        "pending",
        "Use a dict.",
    )
    assert [o.id for o in escalation.options] == ["reply", "close"]
    assert (escalation.policy, escalation.on_expiry) == ("deny", "deny")
    assert escalation.expires_at is not None
    assert escalation.requested_schema == {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    assert stored_task(PROJECT, escalation.task).escalations == [escalation.id]


def test_a_reply_reopens_the_task_pending() -> None:
    escalation = turn_escalation()

    resolved = _esc.resolve(
        escalation.id, "reply", {"text": "and the eviction?"}, by="a", channel="http"
    )

    task = stored_task(PROJECT, escalation.task)
    assert task.status == "pending"
    assert resolved.escalation.state == "resolved"
    assert resolved.escalation.resolution is not None
    assert resolved.escalation.resolution.content == {"text": "and the eviction?"}
    assert resolved.escalation.resolution.applied_at is None


@pytest.mark.parametrize("content", [None, {}, {"text": 3}])
def test_a_reply_without_a_text_is_refused_and_the_turn_keeps_waiting(content: object) -> None:
    escalation = turn_escalation()

    with pytest.raises(EscalationInvalid):
        _esc.resolve(escalation.id, "reply", content, by="a", channel="http")  # type: ignore[arg-type]

    assert stored_task(PROJECT, escalation.task).status == "waiting_input"
    stored = read_escalation(escalation.id)
    assert stored is not None and stored.state == "pending"


def test_close_ends_the_conversation_done() -> None:
    escalation = turn_escalation()

    resolved = _esc.resolve(escalation.id, "close", None, by="a", channel="http")

    assert stored_task(PROJECT, escalation.task).status == "done"
    assert resolved.escalation.state == "resolved"
    assert resolved.escalation.resolution is not None
    assert resolved.escalation.resolution.applied_at is not None


def test_decline_is_not_an_option_of_a_turn() -> None:
    escalation = turn_escalation()

    with pytest.raises(EscalationInvalid):
        _esc.resolve(escalation.id, "decline", None, by="a", channel="http")


def test_an_expired_turn_ends_the_task_done_not_blocked() -> None:
    escalation = turn_escalation()

    assert _sweep.sweep_escalations(_LATER) == 1

    task = stored_task(PROJECT, escalation.task)
    assert (task.status, task.blocked_reason) == ("done", None)
    stored = read_escalation(escalation.id)
    assert stored is not None and stored.state == "expired"
    assert _sweep.sweep_escalations(_LATER) == 0


def test_a_cancelled_task_stays_cancelled_when_its_turn_expires_or_is_resolved() -> None:
    escalation = turn_escalation()
    update_task(PROJECT, escalation.task, status="cancelled")

    _sweep.sweep_escalations(_LATER)
    with pytest.raises(EscalationNotPending):
        _esc.resolve(escalation.id, "close", None, by="a", channel="http")

    assert stored_task(PROJECT, escalation.task).status == "cancelled"


def test_a_second_resolve_is_not_pending_and_carries_its_code() -> None:
    escalation = turn_escalation()
    _esc.resolve(escalation.id, "reply", {"text": "more"}, by="a", channel="http")

    with pytest.raises(EscalationNotPending) as refused:
        _esc.resolve(escalation.id, "close", None, by="a", channel="http")

    assert refused.value.code == "escalation_not_pending"
    assert stored_task(PROJECT, escalation.task).status == "pending"
