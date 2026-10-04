"""The operator-v1 contract (`core/operator_contract.py`).

Pure-function/model tests: the A2A 1.0.0 task-state mapping, `TaskBrief`'s field
validation, the MCP-elicitation-shaped question/answer pair, the operator-facing
views, the CloudEvents 1.0 envelope and `canonical_args_digest`'s stability. No I/O.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.core.operator_contract import (
    A2A_STATES,
    EVENT_KINDS,
    AnswerResult,
    AnswerResultV11,
    ApprovalView,
    CloudEvent,
    InboxView,
    Option,
    Question,
    QuestionSchema,
    QuestionV11,
    TaskBrief,
    TaskView,
    a2a_state,
    canonical_args_digest,
    make_event,
    new_question_id,
    validate_answer,
    validate_answer_v11,
    validate_requested_schema,
)

SUBJECT = "docket.core.operator_contract"

_SCHEMA = {
    "type": "object",
    "properties": {
        "env": {"type": "string", "enum": ["staging", "prod"]},
        "count": {"type": "integer"},
        "ok": {"type": "boolean"},
    },
    "required": ["env"],
}


def _question(**overrides: object) -> Question:
    fields: dict[str, object] = {
        "id": "q-0123456789ab",
        "task_id": "t-1",
        "pod": "alpha",
        "step": "ask",
        "message": "Which environment?",
        "requested_schema": _SCHEMA,
        "created_at": "2026-09-28T00:00:00Z",
    }
    fields.update(overrides)
    return Question(**fields)


# ── a2a_state ─────────────────────────────────────────────────────────────────


class TestA2aState:
    def test_a2a_states_is_the_eight_names_in_order(self) -> None:
        assert A2A_STATES == (
            "SUBMITTED",
            "WORKING",
            "INPUT_REQUIRED",
            "AUTH_REQUIRED",
            "COMPLETED",
            "FAILED",
            "CANCELED",
            "REJECTED",
        )

    @pytest.mark.parametrize(
        ("status", "blocked_reason", "failure_kind", "expected"),
        [
            ("pending", None, None, "SUBMITTED"),
            ("running", None, None, "WORKING"),
            ("waiting_input", None, None, "INPUT_REQUIRED"),
            ("waiting_approval", None, None, "INPUT_REQUIRED"),
            ("blocked", "resources", None, "AUTH_REQUIRED"),
            ("blocked", "budget", None, "INPUT_REQUIRED"),
            ("blocked", None, None, "INPUT_REQUIRED"),
            ("done", None, None, "COMPLETED"),
            ("failed", None, "rejected", "REJECTED"),
            ("failed", None, "verification_failed", "FAILED"),
            ("failed", None, None, "FAILED"),
            ("cancelled", None, None, "CANCELED"),
        ],
    )
    def test_maps_every_documented_status(
        self, status: str, blocked_reason: str | None, failure_kind: str | None, expected: str
    ) -> None:
        assert a2a_state(status, blocked_reason, failure_kind) == expected
        assert expected in A2A_STATES

    def test_unknown_status_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown task status"):
            a2a_state("sleeping")


# ── TaskBrief ─────────────────────────────────────────────────────────────────


class TestTaskBrief:
    def test_minimal_brief_defaults_every_list(self) -> None:
        brief = TaskBrief(objective="ship the thing")
        assert brief.acceptance == []
        assert brief.resources == []
        assert brief.expected_risky_actions == []

    def test_empty_objective_rejected(self) -> None:
        with pytest.raises(ValidationError, match="objective"):
            TaskBrief(objective="   ")

    def test_expected_risky_actions_alias_round_trips(self) -> None:
        brief = TaskBrief.model_validate({"objective": "x", "expectedRiskyActions": ["rm -rf /"]})
        assert brief.expected_risky_actions == ["rm -rf /"]
        assert brief.model_dump(by_alias=True)["expectedRiskyActions"] == ["rm -rf /"]

    @pytest.mark.parametrize("value", ["secret:API_KEY", "path:/tmp/x", "verify"])
    def test_valid_resource_prefixes_accepted(self, value: str) -> None:
        assert TaskBrief(objective="x", resources=[value]).resources == [value]

    def test_bad_resource_prefix_rejected(self) -> None:
        with pytest.raises(ValidationError, match="resource must be"):
            TaskBrief(objective="x", resources=["nonsense"])

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskBrief.model_validate({"objective": "x", "surprise": True})


# ── requestedSchema validation ─────────────────────────────────────────────────


class TestValidateRequestedSchema:
    def test_valid_schema_returned_unchanged(self) -> None:
        assert validate_requested_schema(_SCHEMA) == _SCHEMA
        assert validate_requested_schema(_SCHEMA) is _SCHEMA

    def test_non_object_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="type must be 'object'"):
            validate_requested_schema({"type": "array", "properties": {}})

    def test_empty_properties_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            validate_requested_schema({"type": "object", "properties": {}})

    def test_non_primitive_property_type_rejected(self) -> None:
        schema = {"type": "object", "properties": {"nested": {"type": "object"}}}
        with pytest.raises(ValueError, match="must be one of"):
            validate_requested_schema(schema)

    def test_required_naming_undefined_property_rejected(self) -> None:
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a", "ghost"],
        }
        with pytest.raises(ValueError, match="ghost"):
            validate_requested_schema(schema)

    def test_question_model_runs_validation_on_construction(self) -> None:
        with pytest.raises(ValidationError, match="non-empty"):
            _question(requested_schema={"type": "object", "properties": {}})


# ── Question / new_question_id ─────────────────────────────────────────────────


class TestQuestion:
    def test_new_question_id_shape(self) -> None:
        qid = new_question_id()
        assert qid.startswith("q-")
        assert len(qid) == len("q-") + 12

    def test_two_minted_ids_differ(self) -> None:
        assert new_question_id() != new_question_id()

    def test_wire_aliases_round_trip(self) -> None:
        q = _question()
        dumped = q.model_dump(by_alias=True)
        assert dumped["taskId"] == "t-1"
        assert dumped["requestedSchema"] == _SCHEMA
        assert Question.model_validate(dumped) == q

    def test_schema_wrapper_renders_json_schema(self) -> None:
        schema = QuestionSchema.model_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


# ── AnswerResult / validate_answer ──────────────────────────────────────────────


class TestValidateAnswer:
    def test_accept_with_every_required_property_present_passes(self) -> None:
        q = _question()
        result = AnswerResult(action="accept", content={"env": "staging"})
        assert validate_answer(q, result) is result

    def test_accept_missing_required_property_raises(self) -> None:
        q = _question()
        result = AnswerResult(action="accept", content={})
        with pytest.raises(ValueError, match="missing required property: 'env'"):
            validate_answer(q, result)

    def test_accept_wrong_type_raises(self) -> None:
        q = _question()
        result = AnswerResult(action="accept", content={"env": "staging", "count": "not-a-number"})
        with pytest.raises(ValueError, match="does not match type"):
            validate_answer(q, result)

    def test_accept_enum_violation_raises(self) -> None:
        q = _question()
        result = AnswerResult(action="accept", content={"env": "canary"})
        with pytest.raises(ValueError, match="is not one of"):
            validate_answer(q, result)

    def test_accept_boolean_type_matches(self) -> None:
        q = _question()
        result = AnswerResult(action="accept", content={"env": "prod", "ok": True})
        assert validate_answer(q, result) is result

    @pytest.mark.parametrize("action", ["decline", "cancel"])
    def test_decline_and_cancel_ignore_content(self, action: str) -> None:
        q = _question()
        result = AnswerResult(action=action, content={"env": "nonsense", "count": "nan"})
        assert validate_answer(q, result) is result


# ── ApprovalView / TaskView / InboxView ─────────────────────────────────────────


class TestViews:
    def test_approval_view_defaults_to_input_required(self) -> None:
        view = ApprovalView(
            token="apr-1",
            pod="alpha",
            role="implementer",
            state="pending",
            created_at="2026-09-28T00:00:00Z",
        )
        assert view.a2a_state == "INPUT_REQUIRED"
        assert view.model_dump(by_alias=True)["a2aState"] == "INPUT_REQUIRED"

    def test_task_view_holds_a_nested_question_and_brief(self) -> None:
        view = TaskView(
            id="t-1",
            pod="alpha",
            status="waiting_input",
            a2a_state=a2a_state("waiting_input"),
            question=_question(),
            brief=TaskBrief(objective="ship it"),
        )
        assert view.question is not None
        assert view.question.pod == "alpha"
        assert view.brief is not None
        assert view.brief.objective == "ship it"

    def test_inbox_view_needs_you_accepts_task_or_approval(self) -> None:
        task = TaskView(id="t-1", pod="alpha", status="pending", a2a_state="SUBMITTED")
        approval = ApprovalView(
            token="apr-1",
            pod="alpha",
            role="implementer",
            state="pending",
            created_at="2026-09-28T00:00:00Z",
        )
        inbox = InboxView(needs_you=[task, approval], next="2026-09-28T00:00:01Z")
        assert len(inbox.needs_you) == 2
        assert inbox.model_dump(by_alias=True)["needsYou"][0]["id"] == "t-1"

    def test_unknown_field_rejected_on_every_view(self) -> None:
        with pytest.raises(ValidationError):
            TaskView.model_validate(
                {
                    "id": "t-1",
                    "pod": "a",
                    "status": "pending",
                    "a2aState": "SUBMITTED",
                    "surprise": True,
                }
            )


# ── CloudEvent / make_event ──────────────────────────────────────────────────────


class TestMakeEvent:
    def test_kind_not_in_event_kinds_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown event kind"):
            make_event("task.exploded", "alpha", "t-1", {}, time="t0", version="v1")

    def test_every_declared_kind_is_constructible(self) -> None:
        for kind in EVENT_KINDS:
            ev = make_event(kind, "alpha", "t-1", {}, time="t0", version="v1")
            assert ev.type == f"dev.docket.{kind}"
            assert ev.source == "urn:docket:pod:alpha"
            assert ev.specversion == "1.0"
            assert ev.datacontenttype == "application/json"

    def test_id_is_stable_for_the_same_transition(self) -> None:
        first = make_event("approval.requested", "alpha", "apr-1", {}, time="t0", version="v1")
        again = make_event("approval.requested", "alpha", "apr-1", {}, time="t1", version="v1")
        assert first.id == again.id

    def test_id_changes_when_version_changes(self) -> None:
        first = make_event("approval.requested", "alpha", "apr-1", {}, time="t0", version="v1")
        second = make_event("approval.requested", "alpha", "apr-1", {}, time="t0", version="v2")
        assert first.id != second.id

    def test_wire_shape_is_extra_forbid(self) -> None:
        ev = make_event("channel.test", "alpha", "x", {}, time="t0", version="v1")
        with pytest.raises(ValidationError):
            CloudEvent.model_validate({**ev.model_dump(), "extra": "nope"})


# ── canonical_args_digest ─────────────────────────────────────────────────────


class TestCanonicalArgsDigest:
    def test_same_tool_and_args_same_digest(self) -> None:
        a = canonical_args_digest("bash", {"command": "git push origin main"})
        b = canonical_args_digest("bash", {"command": "git push origin main"})
        assert a == b

    def test_key_order_does_not_matter(self) -> None:
        a = canonical_args_digest("write", {"path": "x", "content": "y"})
        b = canonical_args_digest("write", {"content": "y", "path": "x"})
        assert a == b

    def test_different_tool_different_digest(self) -> None:
        a = canonical_args_digest("bash", {"command": "ls"})
        b = canonical_args_digest("read", {"command": "ls"})
        assert a != b

    def test_different_args_different_digest(self) -> None:
        a = canonical_args_digest("bash", {"command": "ls"})
        b = canonical_args_digest("bash", {"command": "pwd"})
        assert a != b

    def test_digest_is_sixteen_hex_chars(self) -> None:
        digest = canonical_args_digest("bash", {"command": "ls"})
        assert len(digest) == 16
        int(digest, 16)


# ── operator-v1.1 ─────────────────────────────────────────────────────────────

_V11_SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}}}


def _opt(oid: str) -> Option:
    return Option(id=oid, label=oid.upper(), description=f"do {oid}")


def _question_v11(**overrides: object) -> QuestionV11:
    fields: dict[str, object] = {
        "id": "q-0123456789ab",
        "taskId": "t-1",
        "pod": "alpha",
        "step": "ask",
        "message": "Which way?",
        "requestedSchema": _V11_SCHEMA,
        "createdAt": "2026-10-04T00:00:00Z",
        "kind": "decision",
        "options": [_opt("a"), _opt("b")],
    }
    fields.update(overrides)
    return QuestionV11(**fields)


class TestQuestionV11:
    def test_valid_with_recommendation(self) -> None:
        q = _question_v11(recommendation={"optionId": "a", "rationale": "cheaper"})
        assert q.recommendation is not None
        assert q.recommendation.option_id == "a"
        assert q.recommendation.evidence_refs == []
        assert q.options[0].risks == [] and q.options[0].estimated_tokens is None

    def test_unknown_recommendation_option_id(self) -> None:
        with pytest.raises(ValidationError, match="recommendation"):
            _question_v11(recommendation={"optionId": "zzz", "rationale": "x"})

    def test_duplicate_option_ids(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _question_v11(options=[_opt("a"), _opt("a")])

    def test_bad_kind(self) -> None:
        with pytest.raises(ValidationError):
            _question_v11(kind="chat")

    def test_inherits_requested_schema_validation(self) -> None:
        with pytest.raises(ValidationError):
            _question_v11(requestedSchema={"type": "array"})


class TestValidateAnswerV11:
    def test_accept_without_option_id_when_options_exist(self) -> None:
        with pytest.raises(ValueError, match="optionId"):
            validate_answer_v11(_question_v11(), AnswerResultV11(action="accept"))

    def test_accept_with_unknown_option_id(self) -> None:
        answer = AnswerResultV11(action="accept", optionId="nope")
        with pytest.raises(ValueError, match="nope"):
            validate_answer_v11(_question_v11(), answer)

    def test_accept_with_known_option_id(self) -> None:
        answer = AnswerResultV11(action="accept", optionId="b")
        assert validate_answer_v11(_question_v11(), answer) is answer

    def test_decline_without_option_id_is_fine(self) -> None:
        answer = AnswerResultV11(action="decline")
        assert validate_answer_v11(_question_v11(), answer) is answer

    def test_accept_without_options_needs_no_option_id(self) -> None:
        answer = AnswerResultV11(action="accept")
        assert validate_answer_v11(_question_v11(options=[]), answer) is answer

    def test_content_still_validated_against_schema(self) -> None:
        answer = AnswerResultV11(action="accept", optionId="a", content={"note": 3})
        with pytest.raises(ValueError, match="note"):
            validate_answer_v11(_question_v11(), answer)
