"""``sweep_escalations``: the one sweep that ends every pause nobody answered by its own deadline
and by the ``onExpiry`` its record carries (operator-loop.spec.md "Escalations" item 13)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home
from tests.support.pods import build_pod
from tests.support.tasks import task as _make_task
from tests.support.trace import trace_events

from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _approval_pregrant
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import current_home
from docket.kernel.operator_contract import Question
from docket.platform import list_escalations
from docket.platform import store as _store
from docket.tasks.application import escalation_sweep as _sweep
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application.repository import TaskRepository

approvals_dir = _support_home.approvals_dir

SUBJECT = "docket.tasks.application.escalation_sweep"

LATER = "2999-01-01T00:00:00+00:00"
EARLIER = "2000-01-01T00:00:00Z"


def _events(event_type: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in trace_events("demo") if e["event_type"] == event_type]


def _question(expires_at: str | None = None) -> Question:
    return Question(
        id="q-1",
        task_id="t1",
        pod="demo",
        step="s",
        message="m",
        requested_schema={"type": "object", "properties": {"a": {"type": "string"}}},
        created_at="2020-01-01T00:00:00+00:00",
        expires_at=expires_at,
    )


def _waiting_task(expires_at: str | None, **fields: Any) -> None:
    TaskRepository.for_pod("demo").add(
        _make_task(id="t1", status="waiting_input", question=_question(expires_at), **fields)
    )


class TestApprovals:
    def test_a_pending_approval_past_its_own_deadline_is_denied_not_expired(
        self, approvals_dir: Path
    ) -> None:
        token = _approval.approval_create("demo", "implementer", "x", expires_at=EARLIER)

        assert _sweep.sweep_escalations() == 1

        assert _approval.approval_get(token)["state"] == "denied"

    def test_a_recent_approval_is_left_alone(self, approvals_dir: Path) -> None:
        token = _approval.approval_create("demo", "implementer", "x")

        assert _sweep.sweep_escalations() == 0

        assert _approval.approval_get(token)["state"] == "pending"

    def test_the_default_timeout_applies_when_no_deadline_was_given(
        self, approvals_dir: Path
    ) -> None:
        token = _approval.approval_create("demo", "implementer", "x")
        record = _approval.approval_get(token)
        old = _dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=current_home().approval_timeout + 1)
        record["expiresAt"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        _store.write_json(current_home().approvals_dir / f"{token}.json", record)

        assert _sweep.sweep_escalations() == 1

        assert _approval.approval_get(token)["state"] == "denied"

    def test_the_escalation_of_an_expired_approval_moves_once_and_is_traced_once(
        self, approvals_dir: Path
    ) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        token = _approval.approval_create("demo", "implementer", "rm -rf x", expires_at=EARLIER)
        _escalations.open_for_approval(token, kind="approval", task_id="", caused_by="c1")

        assert _sweep.sweep_escalations() == 1
        assert _sweep.sweep_escalations() == 0

        (stored,) = list_escalations()
        assert stored.state == "expired"
        (event,) = _events("escalation_expired")
        assert (event["escalation"], event["by"]) == (stored.id, "timeout")


class TestPreGrants:
    def _pregrant(self, **kw: str) -> str:
        return _approval_pregrant.create_pregrant(
            "proj", "implementer", "bash", "deadbeef", channel="cli", **kw
        )

    def test_an_unconsumed_pregrant_past_its_expiry_is_denied(self, approvals_dir: Path) -> None:
        token = self._pregrant(expires_at=EARLIER)

        assert _sweep.sweep_escalations() == 1

        assert _approval.approval_get(token)["state"] == "denied"
        assert _approval_pregrant.consume_pregrant(token) is False

    def test_an_unexpired_pregrant_is_left_alone(self, approvals_dir: Path) -> None:
        token = self._pregrant()

        assert _sweep.sweep_escalations() == 0

        assert _approval.approval_get(token)["state"] == "granted"

    def test_a_consumed_pregrant_is_left_alone(self, approvals_dir: Path) -> None:
        token = self._pregrant()
        assert _approval_pregrant.consume_pregrant(token) is True

        assert _sweep.sweep_escalations() == 0

        assert _approval.approval_get(token)["state"] == "granted"


class TestQuestions:
    def test_an_expired_question_blocks_the_task_never_fails_it(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _waiting_task("2020-01-01T00:00:00+00:00")

        assert _sweep.sweep_escalations("2026-01-01T00:00:00+00:00") == 1

        task = TaskRepository.for_pod("demo").list()[0]
        assert (task.status, task.blocked_reason, task.question) == (
            "blocked",
            "input_expired",
            None,
        )
        assert len(_events("input_expired")) == 1
        # A blocked task is reopened like any other: an unanswered question never fails it.
        assert _lifecycle.retry_task("demo", "t1") is True
        assert TaskRepository.for_pod("demo").list()[0].status == "pending"

    def test_a_question_not_yet_expired_or_without_a_deadline_is_left_alone(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _waiting_task("2030-01-01T00:00:00+00:00")

        assert _sweep.sweep_escalations("2026-01-01T00:00:00+00:00") == 0
        assert TaskRepository.for_pod("demo").list()[0].status == "waiting_input"

    def test_a_question_with_no_expiry_is_never_swept(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _waiting_task(None)

        assert _sweep.sweep_escalations("2099-01-01T00:00:00+00:00") == 0

    def test_only_waiting_input_tasks_are_considered(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        TaskRepository.for_pod("demo").add(_make_task(id="t1", status="pending"))
        TaskRepository.for_pod("demo").add(_make_task(id="t2", status="done"))

        assert _sweep.sweep_escalations("2026-01-01T00:00:00+00:00") == 0

    def test_the_record_of_an_expired_question_moves_once_and_the_second_sweep_adds_nothing(
        self,
    ) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        _waiting_task("2020-01-01T00:00:00+00:00")
        _escalations.open_for_question(
            _question("2020-01-01T00:00:00+00:00"), kind="consult", role="lead", caused_by="s"
        )

        assert _sweep.sweep_escalations("2026-01-01T00:00:00+00:00") == 1
        assert _sweep.sweep_escalations("2026-01-01T00:00:00+00:00") == 0

        (stored,) = list_escalations()
        assert stored.state == "expired"
        assert len(_events("escalation_expired")) == 1
        assert len(_events("input_expired")) == 1


class TestEachRecordsOwnOnExpiry:
    def test_a_denying_record_denies_its_approval_and_a_blocking_one_blocks_its_task(
        self, approvals_dir: Path
    ) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        token = _approval.approval_create("demo", "implementer", "x", expires_at=EARLIER)
        denying = _escalations.open_for_approval(token, kind="approval", task_id="", caused_by="c")
        _waiting_task("2020-01-01T00:00:00+00:00")
        blocking = _escalations.open_for_question(
            _question("2020-01-01T00:00:00+00:00"), kind="input", role="lead", caused_by="s"
        )
        assert (denying.on_expiry, blocking.on_expiry) == ("deny", "block")

        assert _sweep.sweep_escalations("2026-01-01T00:00:00+00:00") == 2

        assert _approval.approval_get(token)["state"] == "denied"
        assert TaskRepository.for_pod("demo").list()[0].status == "blocked"
        assert {e.state for e in list_escalations()} == {"expired"}


@pytest.mark.parametrize("now", [None])
def test_an_empty_home_sweeps_to_zero(now: str | None) -> None:
    assert _sweep.sweep_escalations(now) == 0
