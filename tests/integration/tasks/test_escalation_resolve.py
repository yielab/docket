"""`resolve`: one verb settles an escalation of any kind and runs the continuation that kind always
had (operator-loop.spec.md area 10).

Real pods and tasks, real approval records and the real continuations; only the pause is seeded,
by the same openers the sites call. The oracle for each kind is the task and approval a surface
read before `resolve` existed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from tests.support import escalations as _support_escalations
from tests.support.escalations import (
    DIGEST,
    approval_escalation,
    consult_escalation,
    input_escalation,
    parked_approval,
)
from tests.support.tasks import stored_task
from tests.support.trace import audit_entries, trace_events

from docket.governance import approval as _ap
from docket.governance import approval_pregrant as _pregrants
from docket.governance import policy as _policy
from docket.kernel.home import current_home
from docket.kernel.operator_contract import Escalation
from docket.platform import read_escalation
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import escalations as _esc
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application.answers import answers_of, consult_note
from docket.tasks.domain.resolution import (
    EscalationInvalid,
    EscalationNotFound,
    EscalationNotPending,
    EscalationRefused,
)

SUBJECT = "docket.tasks.application.escalations"

PROJECT = "demo"
_DIGEST = DIGEST


demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("demo_pod")


_approval = approval_escalation
_parked_approval = parked_approval
_consult = consult_escalation
_input = input_escalation


def _task(escalation: Escalation) -> Any:
    return stored_task(PROJECT, escalation.task)


@dataclass(frozen=True)
class Case:
    seed: Callable[[], Escalation]
    option: str | None
    content: dict[str, Any] | None
    check: Callable[[Any, Escalation], None]


def _granted_once(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [g.token for g in _pregrants.pending_pregrants(task.id)] == [_ap.approval_of(esc.id)]
    assert _ap.approval_get(_ap.approval_of(esc.id))["state"] == "granted"


def _granted_for_the_task(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [(g.tool, g.args_digest) for g in _pregrants.task_grants(task.id)] == [("bash", _DIGEST)]
    assert _ap.approval_get(_ap.approval_of(esc.id))["state"] == "granted"


def _gate_passed(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert _ap.approval_get(_ap.approval_of(esc.id))["state"] == "granted"
    # The position the gate fired at is left for the claim to apply.
    stored = read_escalation(esc.id)
    assert stored is not None and stored.resolution is not None
    assert stored.resolution.applied_at is None


def _denied_with_reason(task: Any, esc: Escalation) -> None:
    assert task.status == "failed"
    assert (task.failure_kind, task.reason) == ("approval_denied", "approval denied: not today")
    assert _ap.approval_get(_ap.approval_of(esc.id))["state"] == "denied"


def _changed_check_accepted(task: Any, esc: Escalation) -> None:
    assert (task.status, task.reason) == ("done", "check_changed approved")


def _changed_check_denied(task: Any, esc: Escalation) -> None:
    assert (task.status, task.failure_kind) == ("failed", "check_changed")


def _consult_chose_redis(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [(a.question_id, a.action, a.option_id) for a in answers_of(task)] == [
        (esc.id, "accept", "redis")
    ]
    # The re-run hop reads the answer from the record; nothing is copied onto the task.
    assert "option redis (Redis)" in consult_note(task, esc.step)


def _consult_declined(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [(a.action, a.option_id) for a in answers_of(task)] == [("decline", None)]


def _input_answered(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [(a.action, a.content) for a in answers_of(task)] == [("accept", {"answer": "ship it"})]


def _input_declined(task: Any, esc: Escalation) -> None:
    assert [a.action for a in answers_of(task)] == ["decline"]


CASES = {
    "approval approve_once": Case(_parked_approval, "approve_once", None, _granted_once),
    "approval approve_task": Case(_parked_approval, "approve_task", None, _granted_for_the_task),
    "approval deny": Case(_parked_approval, "deny", {"reason": "not today"}, _denied_with_reason),
    "gate approve_once": Case(lambda: _approval("gate"), "approve_once", None, _gate_passed),
    "gate deny": Case(
        lambda: _approval("gate"), "deny", {"reason": "not today"}, _denied_with_reason
    ),
    "check_changed approve_once": Case(
        lambda: _approval("check_changed"), "approve_once", None, _changed_check_accepted
    ),
    "check_changed deny": Case(
        lambda: _approval("check_changed"), "deny", None, _changed_check_denied
    ),
    "consult option": Case(_consult, "redis", {"note": "hot path"}, _consult_chose_redis),
    "consult decline": Case(_consult, "decline", None, _consult_declined),
    "consult cancel is decline": Case(_consult, "cancel", None, _consult_declined),
    "input answer": Case(_input, None, {"answer": "ship it"}, _input_answered),
    "input decline": Case(_input, "decline", None, _input_declined),
}


class TestResolveEveryKind:
    @pytest.mark.parametrize("name", CASES)
    def test_the_task_and_the_record_end_where_the_older_verb_left_them(self, name: str) -> None:
        case = CASES[name]
        escalation = case.seed()

        resolved = _esc.resolve(
            escalation.id, case.option, case.content, by="alice", channel="http"
        )

        case.check(_task(escalation), escalation)
        stored = read_escalation(escalation.id)
        assert stored is not None and resolved.escalation == stored
        assert stored.state == "resolved"
        assert stored.resolution is not None
        chosen = "decline" if case.option == "cancel" else case.option
        assert (stored.resolution.option_id, stored.resolution.by, stored.resolution.channel) == (
            chosen,
            "alice",
            "http",
        )

    @pytest.mark.parametrize("name", CASES)
    def test_the_audit_and_the_event_name_the_choice_and_never_the_text(self, name: str) -> None:
        case = CASES[name]
        escalation = case.seed()
        token = _ap.approval_of(escalation.id)

        _esc.resolve(escalation.id, case.option, case.content, by="alice", channel="http")

        (line,) = audit_entries("escalation.resolve")
        for needle in (escalation.id, escalation.kind, "channel=http", "actor=alice"):
            assert needle in line["detail"]
        for secret in ("ship it", "not today", "hot path", token or "apr-none"):
            assert secret not in line["detail"]
        (event,) = [
            e["payload"] for e in trace_events(PROJECT) if e["event_type"] == "escalation_resolved"
        ]
        assert (event["escalation"], event["by"], event["channel"]) == (
            escalation.id,
            "person",
            "http",
        )
        assert event.get("optionId", None) == (
            "decline" if case.option == "cancel" else case.option
        )

    @pytest.mark.parametrize("name", CASES)
    def test_a_second_resolve_is_refused_and_changes_nothing(self, name: str) -> None:
        case = CASES[name]
        escalation = case.seed()
        token = _ap.approval_of(escalation.id)
        _esc.resolve(escalation.id, case.option, case.content, by="alice", channel="http")
        settled = read_escalation(escalation.id)

        with pytest.raises(EscalationNotPending) as caught:
            _esc.resolve(escalation.id, case.option, case.content, by="bob", channel="mcp")

        assert read_escalation(escalation.id) == settled
        assert (token or "apr-none") not in str(caught.value)
        assert len(audit_entries("escalation.resolve")) == 1


class TestResolveRefuses:
    def test_an_unknown_id_is_not_found(self) -> None:
        with pytest.raises(EscalationNotFound):
            _esc.resolve("esc-000000000000", "deny", None, by="a", channel="cli")

    def test_an_unknown_option_names_the_ids_and_writes_nothing(self) -> None:
        escalation = _consult()

        with pytest.raises(EscalationInvalid, match="redis, sqlite, decline"):
            _esc.resolve(escalation.id, "mongo", None, by="a", channel="cli")

        assert _task(escalation).status == "waiting_input"
        assert read_escalation(escalation.id) == escalation

    def test_an_option_is_required_when_the_question_has_options(self) -> None:
        escalation = _consult()

        with pytest.raises(EscalationInvalid, match="option"):
            _esc.resolve(escalation.id, None, {"note": "x"}, by="a", channel="cli")

        assert _task(escalation).status == "waiting_input"

    def test_an_approval_does_not_offer_what_a_gate_cannot_grant(self) -> None:
        escalation = _approval("gate")

        with pytest.raises(EscalationInvalid, match="approve_once, deny"):
            _esc.resolve(escalation.id, "approve_task", None, by="a", channel="cli")

        assert _task(escalation).status == "waiting_approval"

    def test_content_that_breaks_the_schema_writes_nothing(self) -> None:
        escalation = _input()

        with pytest.raises(EscalationInvalid, match="answer"):
            _esc.resolve(escalation.id, None, {}, by="a", channel="cli")

        assert _task(escalation).status == "waiting_input"
        assert read_escalation(escalation.id) == escalation

    def test_content_a_policy_blocks_is_refused_naming_the_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        escalation = _input()
        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: _policy.PolicyHit(action="block", policy_id="canary"),
        )

        with pytest.raises(EscalationRefused) as caught:
            _esc.resolve(escalation.id, None, {"answer": "x"}, by="a", channel="cli")

        assert caught.value.policy_id == "canary"
        assert _task(escalation).status == "waiting_input"
        assert read_escalation(escalation.id) == escalation

    def test_a_denial_reason_a_policy_blocks_leaves_the_approval_pending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        escalation = _approval("gate")
        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: _policy.PolicyHit(action="block", policy_id="canary"),
        )

        with pytest.raises(EscalationRefused):
            _esc.resolve(escalation.id, "deny", {"reason": "x"}, by="a", channel="cli")

        assert _ap.approval_get(_ap.approval_of(escalation.id))["state"] == "pending"

    def test_a_pause_that_ended_without_the_record_is_not_pending(self) -> None:
        escalation = _approval("gate")
        _ap.approval_grant(_ap.approval_of(escalation.id), channel="cli")

        with pytest.raises(EscalationNotPending):
            _esc.resolve(escalation.id, "approve_once", None, by="a", channel="cli")

        assert read_escalation(escalation.id) == escalation


class TestARepeat:
    def test_the_same_decision_says_it_already_ended_that_way_and_the_opposite_does_not(
        self,
    ) -> None:
        escalation = _approval("gate")
        _esc.resolve(escalation.id, "approve_once", None, by="a", channel="cli")

        with pytest.raises(EscalationNotPending) as same:
            _esc.resolve(escalation.id, "approve_once", None, by="a", channel="cli")
        with pytest.raises(EscalationNotPending) as opposite:
            _esc.resolve(escalation.id, "deny", None, by="a", channel="cli")

        assert same.value.already_so is True
        assert opposite.value.already_so is False
        assert len(audit_entries("escalation.resolve")) == 1

    def test_a_question_whose_task_was_cancelled_is_not_pending(self) -> None:
        escalation = _consult()
        _lifecycle.cancel_parked_task(PROJECT, escalation.task, channel="cli")

        with pytest.raises(EscalationNotPending):
            _esc.resolve(escalation.id, "redis", None, by="a", channel="cli")

        assert _task(escalation).status == "cancelled"

    def test_an_approval_left_with_no_record_is_not_found(self) -> None:
        escalation = _approval("gate")
        for path in (current_home().approvals_dir).glob("*.json"):
            path.unlink()

        with pytest.raises(EscalationNotFound):
            _esc.resolve(escalation.id, "approve_once", None, by="a", channel="cli")


class TestAnAnswerToAParkedQuestion:
    def test_it_audits_the_answer_without_its_content(self) -> None:
        escalation = _input()

        _esc.resolve(escalation.id, None, {"answer": "ship it"}, by="alice", channel="http")

        (line,) = audit_entries("task.answer")
        assert f"task={escalation.task}" in line["detail"] and "actor=alice" in line["detail"]
        assert "ship it" not in line["detail"]

    def test_it_keeps_the_kind_and_age_of_the_question_for_the_prompts_that_render_it(self) -> None:
        escalation = _consult()

        _esc.resolve(escalation.id, "redis", None, by="alice", channel="http")

        (answer,) = answers_of(_task(escalation))
        assert (answer.kind, answer.created_at) == ("decision", escalation.asked_at)
        assert (answer.question_id, answer.message) == (escalation.id, escalation.prompt)

    def test_a_decline_screens_nothing_and_records_a_correction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        escalation = _input()
        screened: list[object] = []
        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: screened.append(a) or _policy.PolicyHit(action="allow", policy_id=""),
        )

        _esc.resolve(escalation.id, "decline", None, by="alice", channel="cli")

        assert screened == []
        assert [c["kind"] for c in _corrections.read(PROJECT)] == ["declined_answer"]
