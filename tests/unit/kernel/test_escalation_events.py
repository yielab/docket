"""The `escalation_*` trace events (`kernel/escalation_events.py`): one payload for every pause,
built from the escalation record and written through the tracer port."""

from __future__ import annotations

import json
from typing import Any

from tests.support.trace import trace_events

from docket.kernel import escalation_events as _events
from docket.kernel.operator_contract import (
    Escalation,
    Option,
    Recommendation,
    Resolution,
    new_escalation_id,
)
from docket.kernel.ports import tracer_port

SUBJECT = "docket.kernel.escalation_events"


def _escalation(**over: Any) -> Escalation:
    base: dict[str, Any] = {
        "id": new_escalation_id(),
        "task": "t-1",
        "pod": "demo",
        "step": "implementer",
        "role": "implementer",
        "kind": "consult",
        "causedBy": "implementer",
        "prompt": "Which store?",
        "options": [
            Option(id="redis", label="Redis", description="fast"),
            Option(id="sqlite", label="SQLite", description="simple"),
        ],
        "recommendation": Recommendation(optionId="sqlite", rationale="simple"),
        "askedAt": "2026-10-25T10:00:00Z",
        "expiresAt": "2026-10-25T11:00:00Z",
        "onExpiry": "block",
    }
    base.update(over)
    return Escalation.model_validate(base)


class TestPayload:
    def test_every_event_carries_the_identifying_fields(self) -> None:
        e = _escalation()
        for event_type in _events.EVENT_TYPES:
            payload = _events.payload(event_type, e)
            assert payload["escalation"] == e.id
            assert (payload["kind"], payload["task"], payload["step"]) == (
                "consult",
                "t-1",
                "implementer",
            )
            assert (payload["policy"], payload["askedAt"]) == ("person", "2026-10-25T10:00:00Z")

    def test_asked_adds_the_question_the_person_will_see(self) -> None:
        payload = _events.payload(_events.ASKED, _escalation())
        assert payload["prompt"] == "Which store?"
        assert payload["options"] == ["redis", "sqlite"]
        assert (payload["causedBy"], payload["onExpiry"]) == ("implementer", "block")
        assert payload["expiresAt"] == "2026-10-25T11:00:00Z"

    def test_an_asked_without_a_deadline_omits_it(self) -> None:
        assert "expiresAt" not in _events.payload(_events.ASKED, _escalation(expiresAt=None))

    def test_only_asked_carries_the_options(self) -> None:
        for event_type in _events.EVENT_TYPES - {_events.ASKED}:
            assert "options" not in _events.payload(event_type, _escalation())

    def test_a_settlement_repeats_the_question_for_the_process_that_settles_it(self) -> None:
        for event_type in (_events.RESOLVED, _events.EXPIRED, _events.DECIDED):
            assert _events.payload(event_type, _escalation())["prompt"] == "Which store?"
        assert "prompt" not in _events.payload(_events.DELIVERED, _escalation())

    def test_delivered_names_its_channel(self) -> None:
        payload = _events.payload(_events.DELIVERED, _escalation(), channel="telegram")
        assert payload["channel"] == "telegram"

    def test_resolved_names_the_option_and_channel_of_the_resolution(self) -> None:
        e = _escalation(
            state="resolved",
            resolution=Resolution(
                optionId="redis", by="alice", channel="cli", at="2026-10-25T10:05:00Z"
            ),
        )
        payload = _events.payload(_events.RESOLVED, e)
        assert (payload["by"], payload["optionId"], payload["channel"]) == (
            "person",
            "redis",
            "cli",
        )
        assert "alice" not in json.dumps(payload)

    def test_expired_is_by_the_timeout_and_decided_by_the_policy(self) -> None:
        assert _events.payload(_events.EXPIRED, _escalation())["by"] == "timeout"
        decided = _events.payload(_events.DECIDED, _escalation(), option_id="sqlite")
        assert (decided["by"], decided["optionId"]) == ("policy", "sqlite")


class TestEmit:
    def test_an_event_lands_in_the_task_session_with_the_task_id(self) -> None:
        e = _escalation()
        _events.emit(_events.ASKED, e)

        (event,) = [r for r in trace_events("demo") if r["event_type"] == "escalation_asked"]
        assert event["session_id"] == "agent:demo:t-1"
        assert (event["task_id"], event["agent_role"]) == ("t-1", "implementer")
        assert event["payload"]["escalation"] == e.id

    def test_a_pause_with_no_task_goes_to_the_pod_approval_session(self) -> None:
        _events.emit(_events.ASKED, _escalation(task="", role=""))

        (event,) = trace_events("demo")
        assert (event["session_id"], event["agent_role"]) == ("demo-approval", "operator")

    def test_a_session_can_be_named(self) -> None:
        _events.emit(_events.DECIDED, _escalation(), session_id="task:t-1", option_id="sqlite")

        (event,) = trace_events("demo")
        assert event["session_id"] == "task:t-1"

    def test_the_trace_redacts_a_secret_in_the_prompt(self) -> None:
        _events.emit(_events.ASKED, _escalation(prompt="use api_key=sk-abc123def456ghi789"))

        (event,) = trace_events("demo")
        assert "sk-abc123def456ghi789" not in json.dumps(event)

    def test_a_failing_tracer_never_breaks_the_caller(self) -> None:
        class Failing:
            def trace_event(self, *_a: Any, **_k: Any) -> str:
                raise RuntimeError("disk full")

            def capture_classes(self) -> frozenset[str]:
                return frozenset()

        with tracer_port.use(Failing()):
            _events.emit(_events.ASKED, _escalation())
