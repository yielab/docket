"""docket task: approve, deny and answer settling an escalation through `resolve`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.support.pods import seed_pod_isolation_off as _seed_pod
from tests.support.task_unit_harness import invoke_task as _task
from tests.support.tasks import put_task, task

from docket.governance import approval as _ap
from docket.kernel.operator_contract import Escalation, Option, QuestionV11, Recommendation
from docket.platform import read_escalation
from docket.tasks.application import escalations as _escalations
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status

SUBJECT = "docket.interfaces.cli.commands.task"


def _held_approval() -> tuple[Escalation, str]:
    """A task parked on a pipeline gate with its approval and escalation; the token."""
    record = task()
    token = _ap.approval_create("demo", "implementer", "deploy", context={"taskId": record.id})
    record.status = Status.waiting_approval
    record.approval_token = token
    record.pending_approval_index = 1
    put_task("demo", record)
    escalation = _escalations.open_for_approval(
        token, kind="gate", task_id=record.id, caused_by="call-1"
    )
    return escalation, token


def _held_question() -> Escalation:
    record = task()
    question = QuestionV11.model_validate(
        {
            "id": "q-cli-1",
            "taskId": record.id,
            "pod": "demo",
            "step": "implementer",
            "message": "Which store?",
            "requestedSchema": {"type": "object", "properties": {"note": {"type": "string"}}},
            "createdAt": "2026-10-25T00:00:00+00:00",
            "kind": "decision",
            "options": [Option(id="redis", label="Redis", description="fast").model_dump()],
            "recommendation": Recommendation(option_id="redis", rationale="r").model_dump(
                by_alias=True
            ),
        }
    )
    record.status = Status.waiting_input
    record.question = question
    put_task("demo", record)
    return _escalations.open_for_question(
        question, kind="consult", role="implementer", caused_by="c1"
    )


def _waiting_consult() -> Escalation:
    """A consult a running turn blocks on: the approval record it waits for and the escalation
    carrying its token; the task stays `running` with no parked question."""
    record = task(status=Status.running)
    put_task("demo", record)
    token = _ap.approval_create("demo", "implementer", "Which store?", context={"kind": "consult"})
    question = QuestionV11.model_validate(
        {
            "id": "q-cli-2",
            "taskId": record.id,
            "pod": "demo",
            "step": "implementer",
            "message": "Which store?",
            "requestedSchema": {"type": "object", "properties": {"note": {"type": "string"}}},
            "createdAt": "2026-10-25T00:00:00+00:00",
            "kind": "decision",
            "options": [Option(id="redis", label="Redis", description="fast").model_dump()],
        }
    )
    return _escalations.open_for_question(
        question, kind="consult", role="implementer", caused_by="c1", token=token
    )


def _only_task() -> Any:
    return TaskRepository.for_pod("demo").list()[0]


class TestApproveAndDenySettleTheRecord:
    def test_approve_resolves_the_escalation_as_cli(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, _token = _held_approval()

            result = _task("approve", escalation.task)

            assert result.exit_code == 0, result.output
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.state == "resolved"
            assert stored.resolution is not None
            assert (stored.resolution.option_id, stored.resolution.channel) == (
                "approve_once",
                "cli",
            )
            assert _only_task().gate_override_pipeline_index == 1

    def test_deny_resolves_the_escalation_with_the_reason_on_the_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, _token = _held_approval()

            result = _task("deny", escalation.task, "--reason", "not today")

            assert result.exit_code == 0, result.output
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.resolution is not None
            assert stored.resolution.option_id == "deny"
            assert _only_task().reason == "approval denied: not today"

    def test_a_repeat_is_a_warning_and_exit_zero(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, _token = _held_approval()
            _task("approve", escalation.task)

            result = _task("approve", escalation.task)

            assert result.exit_code == 1  # the task no longer waits for approval
            again = _task("approve", _token)
            assert again.exit_code == 0, again.output
            assert "Already granted" in again.output + again.stderr

    def test_the_opposite_decision_after_a_decision_is_an_error(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, token = _held_approval()
            _task("approve", escalation.task)

            result = _task("deny", token)

            assert result.exit_code == 1


class TestAnswerSettlesAnEscalation:
    def test_an_option_on_a_waiting_task_grants_its_approval(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, token = _held_approval()

            result = _task("answer", escalation.task, "--option", "approve_once")

            assert result.exit_code == 0, result.output
            assert _ap.approval_get(token)["state"] == "granted"
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.state == "resolved"
            assert _only_task().status == Status.pending

    def test_deny_by_escalation_id_fails_the_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, token = _held_approval()

            result = _task("answer", escalation.id, "--option", "deny")

            assert result.exit_code == 0, result.output
            assert _ap.approval_get(token)["state"] == "denied"
            assert _only_task().status == Status.failed

    def test_a_repeat_by_escalation_id_is_a_warning_not_a_failure(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, _token = _held_approval()
            _task("answer", escalation.id, "--option", "approve_once")

            result = _task("answer", escalation.id, "--option", "approve_once")

            assert result.exit_code == 0, result.output

    def test_an_option_that_is_not_an_approval_option_names_the_ones_that_are(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            escalation, token = _held_approval()

            result = _task("answer", escalation.id, "--option", "maybe")

            assert result.exit_code == 1
            assert "approve_once|approve_task|deny" in result.output + result.stderr
            assert _ap.approval_get(token)["state"] == "pending"

    def test_a_task_wide_choice_on_a_gate_is_a_plain_grant(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, token = _held_approval()

            result = _task("answer", escalation.id, "--option", "approve_task")

            assert result.exit_code == 0, result.output
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.resolution is not None
            assert stored.resolution.option_id == "approve_once"
            assert _ap.approval_get(token)["state"] == "granted"

    def test_an_approval_needs_an_option_and_takes_no_text(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation, token = _held_approval()

            bare = _task("answer", escalation.id)
            texted = _task("answer", escalation.id, "yes", "please")

            assert (bare.exit_code, texted.exit_code) == (1, 1)
            assert _ap.approval_get(token)["state"] == "pending"

    def test_a_question_is_answered_by_its_escalation_id(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation = _held_question()

            result = _task("answer", escalation.id, "--option", "redis")

            assert result.exit_code == 0, result.output
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.resolution is not None
            assert (stored.resolution.option_id, stored.resolution.channel) == ("redis", "cli")
            assert _only_task().answers[0].option_id == "redis"

    def test_an_unknown_escalation_id_is_refused(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _task("answer", "esc-000000000000", "--option", "deny")

            assert result.exit_code == 1


class TestAnswerAConsultWaitingInTheTurn:
    def test_it_is_answered_by_its_escalation_id(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation = _waiting_consult()

            result = _task("answer", escalation.id, "--option", "redis")

            assert result.exit_code == 0, result.output
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.state == "resolved"
            assert stored.resolution is not None
            assert (stored.resolution.option_id, stored.resolution.channel) == ("redis", "cli")
            assert _ap.approval_get(str(escalation.legacy["token"]))["state"] == "granted"

    def test_it_is_answered_by_its_task_and_can_be_declined(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            escalation = _waiting_consult()

            result = _task("answer", escalation.task, "--decline")

            assert result.exit_code == 0, result.output
            stored = read_escalation(escalation.id)
            assert stored is not None and stored.resolution is not None
            assert stored.resolution.option_id == "decline"
            assert _ap.approval_get(str(escalation.legacy["token"]))["state"] == "denied"

    def test_a_running_task_with_no_consult_still_has_no_pending_question(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            record = task(status=Status.running)
            put_task("demo", record)

            result = _task("answer", record.id, "--option", "redis")

            assert result.exit_code == 1
            assert "no pending question" in result.output + result.stderr
