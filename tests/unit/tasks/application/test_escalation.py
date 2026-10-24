"""Escalation metrics: task counts, question outcomes, and decision latency.

Counts are lifetime-of-storage based on persisted task records (answers[])
and trace events (task_claim), not monotonic totals.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.support.tasks import put_task
from tests.support.tasks import task as _make_task

from docket.kernel.home import Home, use_home
from docket.kernel.operator_contract import Question, QuestionV11
from docket.observability import trace as _trace
from docket.tasks.application import escalation as _escalation
from docket.tasks.domain.parts import Answer

SUBJECT = "docket.tasks.application.escalation"


@pytest.fixture()
def home(tmp_path: Path) -> Iterator[Path]:
    """Temp DOCKET_HOME with all docket-owned store paths repointed."""
    d = tmp_path / ".docket"
    d.mkdir()
    # Register a pod member so _all_projects() finds it
    # Use "myproj-lead" as the member id so pod_of() parses it correctly
    (d / "fleet.json").write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "id": "myproj-lead",
                        "schemaVersion": 1,
                        "kind": "project",
                        "type": "repo",
                    }
                ],
                "bindings": [],
            }
        )
    )
    # Create the pod's workspace directory so we can write tasks
    workspace = d / "workspaces" / "projects" / "myproj-lead"
    workspace.mkdir(parents=True, exist_ok=True)
    with use_home(Home(d)):
        yield d


def _question(task_id: str, question_id: str, message: str, created_at: str) -> Question:
    """A plain question as a pod parks it."""
    return Question(
        id=question_id,
        task_id=task_id,
        pod="myproj",
        step="input",
        message=message,
        created_at=created_at,
        requested_schema={"type": "object", "properties": {"a": {"type": "string"}}},
    )


def _answer(
    question: Question,
    action: str,
    answered_at: str,
    channel: str,
    content: dict[str, Any] | None = None,
) -> Answer:
    """The answer record ``answer_task`` keeps: the question's kind and createdAt travel with it."""
    return Answer(
        question_id=question.id,
        step=question.step,
        message=question.message,
        action=action,
        channel=channel,
        actor="user",
        answered_at=answered_at,
        kind=question.kind if isinstance(question, QuestionV11) else "clarification",
        created_at=question.created_at,
        content=content,
    )


class TestEscalationMetrics:
    def test_empty_home_yields_zeros(self, home: Path) -> None:
        metrics = _escalation.count_escalation_metrics()
        assert metrics.tasks_started_total == 0
        assert metrics.questions_total == {}
        assert metrics.decision_latency_seconds_sum == 0.0
        assert metrics.decision_latency_seconds_count == 0

    def test_task_started_from_trace_session_start(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        # Write a session_start trace event (what dispatch_task writes on claim)
        _trace.trace_event(
            "myproj",
            "agent:myproj:task1",
            "lead",
            "session_start",
            json.dumps({"source": "dispatch", "task": "task1", "resumed": False}),
        )
        metrics = _escalation.count_escalation_metrics()
        assert metrics.tasks_started_total == 1

    def test_a_resumed_claim_is_not_a_new_start(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        for resumed in (False, True):
            _trace.trace_event(
                "myproj",
                "agent:myproj:task1",
                "lead",
                "session_start",
                json.dumps({"source": "dispatch", "task": "task1", "resumed": resumed}),
            )
        assert _escalation.count_escalation_metrics().tasks_started_total == 1

    def test_approvals_are_counted_from_the_real_audit_and_pending_list(self, home: Path) -> None:
        from docket.governance import approval as _approval

        granted = _approval.approval_create("myproj", "implementer", "deploy")
        denied = _approval.approval_create("myproj", "implementer", "deploy")
        _approval.approval_create("myproj", "implementer", "deploy")
        _approval.approval_grant(granted, channel="cli")
        _approval.approval_deny(denied, channel="cli")
        questions = _escalation.count_escalation_metrics().questions_total
        assert questions[("approval", "granted")] == 1
        assert questions[("approval", "denied")] == 1
        assert questions[("approval", "pending")] == 1

    def test_questions_with_latency(self, home: Path) -> None:
        """Test latency from question createdAt to answer answeredAt."""
        now = datetime.now(UTC)
        question_created = now - timedelta(seconds=30)
        answer_time = now

        question = _question(
            "t1", "q-abc123456789", "Do you approve?", question_created.isoformat()
        )
        put_task(
            "myproj",
            _make_task(
                id="t1",
                status="done",
                question=question,
                answers=[_answer(question, "accept", answer_time.isoformat(), "http", {})],
            ),
        )

        metrics = _escalation.count_escalation_metrics()
        assert ("clarification", "accept") in metrics.questions_total
        assert metrics.questions_total[("clarification", "accept")] == 1
        assert metrics.decision_latency_seconds_count == 1
        assert 29 < metrics.decision_latency_seconds_sum < 31

    def test_question_kinds(self, home: Path) -> None:
        """Test that question kind field is used when present."""
        now = datetime.now(UTC)

        question = QuestionV11(
            id="q-kind-test",
            task_id="t2",
            pod="myproj",
            step="input",
            message="Proceed?",
            kind="decision",
            created_at=now.isoformat(),
            requested_schema={"type": "object", "properties": {"a": {"type": "string"}}},
        )
        put_task(
            "myproj",
            _make_task(
                id="t2",
                status="done",
                question=question,
                answers=[_answer(question, "decline", now.isoformat(), "cli")],
            ),
        )

        metrics = _escalation.count_escalation_metrics()
        assert ("decision", "decline") in metrics.questions_total
        assert metrics.questions_total[("decision", "decline")] == 1

    def test_multiple_answers_with_latency(self, home: Path) -> None:
        """Test multiple answers with different latencies."""
        now = datetime.now(UTC)

        question = _question(
            "t4", "q-multi", "Question?", (now - timedelta(seconds=50)).isoformat()
        )
        put_task(
            "myproj",
            _make_task(
                id="t4",
                status="done",
                question=question,
                answers=[
                    _answer(
                        question,
                        "accept",
                        (now - timedelta(seconds=20)).isoformat(),
                        "http",
                        {},
                    ),
                    _answer(question, "decline", now.isoformat(), "cli"),
                ],
            ),
        )

        metrics = _escalation.count_escalation_metrics()
        assert metrics.questions_total.get(("clarification", "accept"), 0) == 1
        assert metrics.questions_total.get(("clarification", "decline"), 0) == 1
        # Two answers, so two latency measurements
        assert metrics.decision_latency_seconds_count == 2
        # Question created at now-50s, first answer at now-20s (30s latency),
        # second answer at now (50s latency), total 80s
        assert 75 < metrics.decision_latency_seconds_sum < 85
