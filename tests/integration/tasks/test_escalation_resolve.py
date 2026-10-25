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
from tests.support.pods import seed_parked_task
from tests.support.tasks import stored_task, update_task
from tests.support.trace import audit_entries, trace_events

from docket.governance import approval as _ap
from docket.governance import approval_pregrant as _pregrants
from docket.governance import policy as _policy
from docket.kernel.operator_contract import Escalation
from docket.platform import list_escalations, read_escalation, settle_escalation
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue
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
    assert [g.token for g in _pregrants.pending_pregrants(task.id)] == [esc.legacy["token"]]
    assert _ap.approval_get(esc.legacy["token"])["state"] == "granted"


def _granted_for_the_task(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [(g.tool, g.args_digest) for g in _pregrants.task_grants(task.id)] == [("bash", _DIGEST)]
    assert _ap.approval_get(esc.legacy["token"])["state"] == "granted"


def _gate_passed(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert _ap.approval_get(esc.legacy["token"])["state"] == "granted"
    # The position the gate fired at is left for the claim to apply.
    stored = read_escalation(esc.id)
    assert stored is not None and stored.resolution is not None
    assert stored.resolution.applied_at is None


def _denied_with_reason(task: Any, esc: Escalation) -> None:
    assert task.status == "failed"
    assert (task.failure_kind, task.reason) == ("approval_denied", "approval denied: not today")
    assert _ap.approval_get(esc.legacy["token"])["state"] == "denied"


def _changed_check_accepted(task: Any, esc: Escalation) -> None:
    assert (task.status, task.reason) == ("done", "check_changed approved")


def _changed_check_denied(task: Any, esc: Escalation) -> None:
    assert (task.status, task.failure_kind) == ("failed", "check_changed")


def _consult_chose_redis(task: Any, esc: Escalation) -> None:
    assert (task.status, task.question) == ("pending", None)
    assert [(a.question_id, a.action, a.option_id) for a in task.answers] == [
        ("q-1", "accept", "redis")
    ]
    # The note the re-run hop reads is set by the claim of the task, not by the answer.
    assert task.consult_answer is None


def _consult_declined(task: Any, esc: Escalation) -> None:
    assert (task.status, task.question) == ("pending", None)
    assert [(a.action, a.option_id) for a in task.answers] == [("decline", None)]


def _input_answered(task: Any, esc: Escalation) -> None:
    assert task.status == "pending"
    assert [(a.action, a.content) for a in task.answers] == [("accept", {"answer": "ship it"})]


def _input_declined(task: Any, esc: Escalation) -> None:
    assert [a.action for a in task.answers] == ["decline"]


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

        _esc.resolve(escalation.id, case.option, case.content, by="alice", channel="http")

        (line,) = audit_entries("escalation.resolve")
        for needle in (escalation.id, escalation.kind, "channel=http", "actor=alice"):
            assert needle in line["detail"]
        for secret in ("ship it", "not today", "hot path", str(escalation.legacy.get("token"))):
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
        _esc.resolve(escalation.id, case.option, case.content, by="alice", channel="http")
        settled = read_escalation(escalation.id)

        with pytest.raises(EscalationNotPending) as caught:
            _esc.resolve(escalation.id, case.option, case.content, by="bob", channel="mcp")

        assert read_escalation(escalation.id) == settled
        assert str(escalation.legacy.get("token")) not in str(caught.value)
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

        assert _ap.approval_get(escalation.legacy["token"])["state"] == "pending"

    def test_a_pause_that_ended_without_the_record_is_not_pending(self) -> None:
        escalation = _approval("gate")
        _ap.approval_grant(escalation.legacy["token"], channel="cli")

        with pytest.raises(EscalationNotPending):
            _esc.resolve(escalation.id, "approve_once", None, by="a", channel="cli")

        assert read_escalation(escalation.id) == escalation


class TestTheOlderVerbsAreAdapters:
    def test_an_approval_token_with_a_record_resolves_the_record(self) -> None:
        escalation = _approval("gate")

        note = _esc.resolve_approval_token(
            escalation.legacy["token"], "approve_once", channel="cli", actor="alice", reason=""
        )

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.state == "resolved"
        assert stored.resolution is not None and stored.resolution.channel == "cli"
        assert note == ""
        assert _task(escalation).status == "pending"

    def test_a_task_wide_choice_on_a_gate_is_a_plain_grant(self) -> None:
        escalation = _approval("gate")

        _esc.resolve_approval_token(
            escalation.legacy["token"], "approve_task", channel="cli", actor="", reason=""
        )

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.option_id == "approve_once"

    def test_an_approval_with_no_record_keeps_the_direct_path(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "older", channel="cli")[0]
        token = _ap.approval_create(PROJECT, "implementer", "ask", context={"taskId": task.id})
        update_task(
            PROJECT,
            task.id,
            status="waiting_approval",
            approval_token=token,
            pending_approval_index=0,
        )

        _esc.resolve_approval_token(token, "approve_once", channel="mcp", actor="", reason="")

        assert stored_task(PROJECT, task.id).status == "pending"
        assert _ap.approval_get(token)["state"] == "granted"
        assert list_escalations() == []
        assert audit_entries("escalation.resolve") == []

    def test_a_repeat_on_a_direct_path_says_it_already_ended_that_way(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "older", channel="cli")[0]
        token = _ap.approval_create(PROJECT, "implementer", "ask", context={"taskId": task.id})
        _esc.resolve_approval_token(token, "approve_once", channel="cli", actor="", reason="")

        with pytest.raises(EscalationNotPending) as same:
            _esc.resolve_approval_token(token, "approve_once", channel="cli", actor="", reason="")
        with pytest.raises(EscalationNotPending) as opposite:
            _esc.resolve_approval_token(token, "deny", channel="cli", actor="", reason="")

        assert same.value.already_so is True
        assert opposite.value.already_so is False
        assert "Already granted" in str(same.value)

    def test_an_unknown_token_is_not_found(self) -> None:
        with pytest.raises(EscalationNotFound):
            _esc.resolve_approval_token("apr-0", "approve_once", channel="cli", actor="", reason="")

    def test_a_question_with_a_record_resolves_the_record(self) -> None:
        escalation = _consult()

        _esc.resolve_question(
            PROJECT,
            escalation.task,
            "accept",
            {"optionId": "redis", "note": "hot path"},
            channel="http",
            actor="alice",
        )

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.state == "resolved"
        assert stored.resolution is not None
        assert stored.resolution.option_id == "redis"
        assert stored.resolution.content == {"note": "hot path"}
        _consult_chose_redis(_task(escalation), escalation)

    def test_a_decline_resolves_the_record_as_decline(self) -> None:
        escalation = _input()

        _esc.resolve_question(
            PROJECT, escalation.task, "decline", None, channel="cli", actor="alice"
        )

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.option_id == "decline"

    def test_a_question_with_no_record_is_answered_directly(self) -> None:
        parked = seed_parked_task(PROJECT)
        for record in list_escalations():
            settle_escalation("questionId", record.legacy["questionId"], "expired")

        _esc.resolve_question(
            PROJECT, parked.id, "accept", {"answer": "ship it"}, channel="cli", actor="alice"
        )

        assert stored_task(PROJECT, parked.id).status == "pending"
        assert audit_entries("escalation.resolve") == []

    def test_a_task_that_is_not_waiting_is_not_pending(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "plain", channel="cli")[0]

        with pytest.raises(EscalationNotPending):
            _esc.resolve_question(
                PROJECT, task.id, "accept", {"answer": "x"}, channel="cli", actor="a"
            )

    def test_an_unknown_task_is_not_found(self) -> None:
        with pytest.raises(EscalationNotFound):
            _esc.resolve_question(
                PROJECT, "no-such-task", "accept", {"answer": "x"}, channel="cli", actor="a"
            )
