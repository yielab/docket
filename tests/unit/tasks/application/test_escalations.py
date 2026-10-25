"""Opening an escalation and the pod-decided consult (`tasks/application/escalations.py`); the five
sites that open one are exercised end to end in `tests/integration/tasks/test_escalations.py`."""

from __future__ import annotations

from typing import Any

from tests.support.trace import trace_events

from docket.kernel.operator_contract import (
    Escalation,
    QuestionV11,
    is_escalation_id,
    new_escalation_id,
)
from docket.platform import list_escalations
from docket.tasks.application import escalations as _escalations
from docket.tasks.domain.task import TaskRecord

SUBJECT = "docket.tasks.application.escalations"


def _question(message: str = "Which store?") -> QuestionV11:
    return QuestionV11.model_validate(
        {
            "id": "q-1",
            "taskId": "t-1",
            "pod": "demo",
            "step": "implementer",
            "message": message,
            "requestedSchema": {"type": "object", "properties": {"note": {"type": "string"}}},
            "createdAt": "2026-10-25T10:00:00Z",
            "kind": "decision",
            "options": [
                {"id": "redis", "label": "Redis", "description": "fast"},
                {"id": "sqlite", "label": "SQLite", "description": "simple"},
            ],
            "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
        }
    )


class TestAttach:
    def test_an_id_is_listed_once(self) -> None:
        task = TaskRecord.model_validate({"id": "t-1", "description": "d"})
        escalation = Escalation.model_validate(
            {
                "id": new_escalation_id(),
                "task": "t-1",
                "pod": "demo",
                "step": "s",
                "role": "lead",
                "kind": "approval",
                "causedBy": "c1",
                "prompt": "p",
                "askedAt": "2026-10-25T10:00:00Z",
                "onExpiry": "deny",
            }
        )

        assert _escalations.attach(task, escalation) is True
        assert _escalations.attach(task, escalation) is False
        assert task.escalations == [escalation.id]


class TestDecidedConsult:
    def _decide(self, **over: Any) -> Escalation:
        return _escalations.decided_consult(
            _question(**over), role="implementer", option_id="sqlite"
        )

    def test_the_escalation_describes_the_pause_the_pod_settled(self) -> None:
        decided = self._decide()

        assert is_escalation_id(decided.id)
        assert (decided.kind, decided.task, decided.pod) == ("consult", "t-1", "demo")
        assert (decided.policy, decided.state) == ("recommendation", "decided")
        assert decided.asked_at == "2026-10-25T10:00:00Z"
        assert decided.resolution is not None
        assert (decided.resolution.option_id, decided.resolution.by) == ("sqlite", "policy")

    def test_the_decision_is_stored_decided_never_pending_and_one_event_is_written(self) -> None:
        decided = self._decide()

        assert list_escalations(state="pending") == []
        assert [e.id for e in list_escalations(state="decided")] == [decided.id]
        (event,) = [e for e in trace_events("demo") if e["event_type"] == "escalation_decided"]
        assert event["payload"]["escalation"] == decided.id

    def test_a_secret_in_the_message_is_redacted_on_the_record(self) -> None:
        decided = self._decide(message="use api_key=sk-abc123def456ghi789 for it")

        assert "sk-abc123def456ghi789" not in decided.prompt
