"""SUBJECT: interfaces.http.routes.a2a_task -- a task and its pending escalation as A2A objects."""

from __future__ import annotations

import json
from typing import Any

from docket.interfaces.http.routes import a2a_task
from docket.kernel.operator_contract import (
    EscalationAffordances,
    EscalationView,
    Option,
    QuestionV11,
    Recommendation,
    TaskView,
)

SUBJECT = "docket.interfaces.http.routes.a2a_task"
EXTENSION = "https://docket.dev/schemas/operator-v1.1/question.schema.json"
DECLINE = Option(id="decline", label="Decline", description="Refuse.")


def _view(kind: str = "consult", **fields: Any) -> EscalationView:
    base: dict[str, Any] = {
        "id": "esc-0123456789ab",
        "task": "task-1",
        "pod": "demo",
        "step": "implement",
        "role": "implementer",
        "kind": kind,
        "causedBy": "c1",
        "prompt": "Which store?",
        "options": [
            Option(id="redis", label="Redis", description="fast"),
            Option(id="memcached", label="Memcached", description="simple"),
            DECLINE,
        ],
        "recommendation": Recommendation(optionId="redis", rationale="deployed"),
        "requestedSchema": None,
        "askedAt": "2026-10-25T10:00:00Z",
        "expiresAt": "2026-10-26T10:00:00Z",
        "onExpiry": "block",
        "affordances": EscalationAffordances(
            options=["redis", "memcached", "decline"],
            acceptsText=False,
            resolveUrl="/escalations/esc-0123456789ab",
        ),
    }
    return EscalationView.model_validate({**base, **fields})


def _task(status: str = "waiting_input", a2a: str = "INPUT_REQUIRED", **fields: Any) -> TaskView:
    return TaskView(
        id="task-1",
        pod="demo",
        status=status,
        a2a_state=a2a,
        updated_at="2026-10-25T10:00:00Z",
        **fields,
    )


class TestRequestedSchema:
    def test_options_become_a_required_enum_without_decline(self) -> None:
        schema = a2a_task.requested_schema(_view())

        assert schema == {
            "type": "object",
            "properties": {"optionId": {"type": "string", "enum": ["redis", "memcached"]}},
            "required": ["optionId"],
        }

    def test_the_escalations_own_properties_are_kept_beside_the_option(self) -> None:
        own = {"type": "object", "properties": {"note": {"type": "string"}}, "required": []}

        schema = a2a_task.requested_schema(_view(requestedSchema=own))

        assert set(schema["properties"]) == {"note", "optionId"}
        assert schema["required"] == ["optionId"]

    def test_an_approval_asks_for_an_option_and_an_optional_reason(self) -> None:
        approval = _view(
            "approval",
            options=[
                Option(id="approve_once", label="Once", description="."),
                Option(id="deny", label="Deny", description="."),
            ],
        )

        schema = a2a_task.requested_schema(approval)

        assert schema["properties"]["optionId"]["enum"] == ["approve_once", "deny"]
        assert schema["properties"]["reason"] == {"type": "string"}
        assert schema["required"] == ["optionId"]

    def test_a_question_that_offers_only_decline_asks_for_nothing_more(self) -> None:
        schema = a2a_task.requested_schema(_view(options=[DECLINE]))

        assert schema == {"type": "object", "properties": {}, "required": []}


class TestQuestionKind:
    def test_the_five_escalation_kinds_map_onto_the_three_question_kinds(self) -> None:
        kinds = {k: a2a_task.question_kind(_view(k)) for k in ("approval", "gate", "check_changed")}
        assert set(kinds.values()) == {"approval"}
        assert a2a_task.question_kind(_view("consult")) == "decision"
        assert a2a_task.question_kind(_view("input", options=[DECLINE])) == "clarification"


class TestEscalationMessage:
    def test_it_is_an_agent_message_with_the_prompt_and_the_elicitation_data(self) -> None:
        message = a2a_task.escalation_message(_view())

        assert (message["kind"], message["role"], message["messageId"]) == (
            "message",
            "agent",
            "esc-0123456789ab",
        )
        assert (message["taskId"], message["contextId"]) == ("task-1", "demo")
        assert message["extensions"] == [EXTENSION]
        text, data = message["parts"]
        assert text == {"kind": "text", "text": "Which store?"}
        assert data["kind"] == "data"
        assert data["data"]["message"] == "Which store?"
        assert data["data"]["escalationId"] == "esc-0123456789ab"
        assert data["data"]["escalationKind"] == "consult"
        assert data["data"]["kind"] == "decision"
        assert data["data"]["onExpiry"] == "block"
        assert data["data"]["recommendation"]["optionId"] == "redis"

    def test_its_options_and_recommendation_are_the_operator_v11_models(self) -> None:
        data = a2a_task.escalation_message(_view())["parts"][1]["data"]

        for option in data["options"]:
            Option.model_validate(option)
        Recommendation.model_validate(data["recommendation"])
        QuestionV11.model_validate(
            {
                "id": "q-1",
                "taskId": "task-1",
                "pod": "demo",
                "step": "implement",
                "message": data["message"],
                "requestedSchema": data["requestedSchema"],
                "createdAt": "2026-10-25T10:00:00Z",
                "kind": data["kind"],
                "options": data["options"],
                "recommendation": data["recommendation"],
            }
        )

    def test_it_holds_nothing_that_could_settle_the_pause_by_itself(self) -> None:
        text = json.dumps(a2a_task.escalation_message(_view("approval")))

        assert "resolveUrl" not in text and "/escalations/" not in text and "apr-" not in text


class TestTaskObject:
    def test_a_submitted_task_has_no_message(self) -> None:
        task = a2a_task.task_object(_task("pending", "SUBMITTED"), None)

        assert task == {
            "kind": "task",
            "id": "task-1",
            "contextId": "demo",
            "status": {"state": "SUBMITTED", "timestamp": "2026-10-25T10:00:00Z"},
            "metadata": {"docket": {"pod": "demo", "status": "pending"}},
        }

    def test_a_parked_task_carries_its_pending_escalation(self) -> None:
        task = a2a_task.task_object(_task(), _view())

        assert task["status"]["state"] == "INPUT_REQUIRED"
        assert task["status"]["message"]["messageId"] == "esc-0123456789ab"

    def test_a_blocked_task_says_why_in_text(self) -> None:
        blocked = _task("blocked", "INPUT_REQUIRED", reason="budget")

        message = a2a_task.task_object(blocked, None)["status"]["message"]

        assert message["parts"] == [{"kind": "text", "text": "budget"}]

    def test_a_reason_left_over_from_an_earlier_pause_is_not_a_status_message(self) -> None:
        resumed = _task(
            "pending", "SUBMITTED", reason="parked a consultation (escalation=esc-0123456789ab)"
        )

        assert "message" not in a2a_task.task_object(resumed, None)["status"]

    def test_an_external_ref_travels_in_the_docket_metadata(self) -> None:
        task = a2a_task.task_object(_task("pending", "SUBMITTED"), None, external_ref="B-7")

        assert task["metadata"]["docket"]["externalRef"] == "B-7"
