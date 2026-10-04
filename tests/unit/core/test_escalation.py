"""Escalation metrics: task counts, question outcomes, and decision latency.

Counts are lifetime-of-storage based on persisted task records (answers[])
and trace events (task_claim), not monotonic totals.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.core import dispatch as _dispatch
from docket.core import escalation as _escalation
from docket.core import trace as _trace
from docket.edges import store as _store

SUBJECT = "docket.core.escalation"


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    repoint_docket_home(monkeypatch, d)
    return d


def _write_task(project: str, task_data: dict) -> None:
    """Helper to write a task to the TASK_LIST.json file."""
    task_list_path = _dispatch.pod_task_list_path(project)
    doc = _store.read_json(task_list_path)
    if doc is None:
        doc = {"tasks": []}
    tasks = doc.get("tasks", [])
    tasks.append(task_data)
    doc["tasks"] = tasks
    _store.write_json(task_list_path, doc)


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

    def test_multiple_session_starts_counted(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        for i in range(3):
            _trace.trace_event(
                "myproj",
                f"agent:myproj:task{i}",
                "lead",
                "session_start",
                json.dumps({"source": "dispatch", "task": f"task{i}", "resumed": False}),
            )
        metrics = _escalation.count_escalation_metrics()
        assert metrics.tasks_started_total == 3

    def test_question_with_answer_accept(self, home: Path) -> None:
        # Create a task with a question answered "accept"
        now = datetime.now(timezone.utc)
        answer_time = now.isoformat()

        task = {
            "id": "t1",
            "pod": "myproj",
            "status": "done",
            "answers": [
                {
                    "questionId": "q-abc123456789",
                    "step": "input",
                    "message": "Do you approve?",
                    "action": "accept",
                    "content": {},
                    "channel": "http",
                    "actor": "user",
                    "answeredAt": answer_time,
                }
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        # The question is a "clarification" by default (no kind field in the question record)
        assert ("clarification", "accept") in metrics.questions_total
        assert metrics.questions_total[("clarification", "accept")] == 1

    def test_question_with_answer_decline(self, home: Path) -> None:
        now = datetime.now(timezone.utc)
        answer_time = now.isoformat()

        task = {
            "id": "t2",
            "pod": "myproj",
            "status": "done",
            "answers": [
                {
                    "questionId": "q-xyz789012345",
                    "step": "input",
                    "message": "Proceed?",
                    "action": "decline",
                    "content": None,
                    "channel": "cli",
                    "actor": "user",
                    "answeredAt": answer_time,
                }
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        assert ("clarification", "decline") in metrics.questions_total
        assert metrics.questions_total[("clarification", "decline")] == 1

    def test_decision_latency_seconds(self, home: Path) -> None:
        now = datetime.now(timezone.utc)
        answer_time = now.isoformat()

        task = {
            "id": "t3",
            "pod": "myproj",
            "status": "done",
            "answers": [
                {
                    "questionId": "q-latency123456",
                    "step": "input",
                    "message": "Question?",
                    "action": "accept",
                    "content": {},
                    "channel": "http",
                    "actor": "user",
                    "answeredAt": answer_time,
                }
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        # For now, latency is 0 since we don't have createdAt in answer records
        assert metrics.decision_latency_seconds_count == 0
        assert metrics.decision_latency_seconds_sum == 0.0

    def test_multiple_answers_on_one_task(self, home: Path) -> None:
        now = datetime.now(timezone.utc)

        task = {
            "id": "t4",
            "pod": "myproj",
            "status": "done",
            "answers": [
                {
                    "questionId": "q-first",
                    "step": "input",
                    "message": "Q1?",
                    "action": "accept",
                    "content": {},
                    "channel": "http",
                    "actor": "user",
                    "answeredAt": (now - timedelta(seconds=20)).isoformat(),
                },
                {
                    "questionId": "q-second",
                    "step": "input",
                    "message": "Q2?",
                    "action": "decline",
                    "content": None,
                    "channel": "cli",
                    "actor": "user",
                    "answeredAt": (now - timedelta(seconds=10)).isoformat(),
                },
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        assert metrics.questions_total.get(("clarification", "accept"), 0) == 1
        assert metrics.questions_total.get(("clarification", "decline"), 0) == 1
        assert metrics.decision_latency_seconds_count == 0
