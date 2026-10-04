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

    def test_questions_with_latency(self, home: Path) -> None:
        """Test latency from question createdAt to answer answeredAt."""
        now = datetime.now(timezone.utc)
        question_created = now - timedelta(seconds=30)
        answer_time = now

        task = {
            "id": "t1",
            "pod": "myproj",
            "status": "done",
            "question": {
                "id": "q-abc123456789",
                "taskId": "t1",
                "pod": "myproj",
                "step": "input",
                "message": "Do you approve?",
                "createdAt": question_created.isoformat(),
                "expiresAt": None,
                "requestedSchema": {"type": "object", "properties": {}},
            },
            "answers": [
                {
                    "questionId": "q-abc123456789",
                    "step": "input",
                    "message": "Do you approve?",
                    "action": "accept",
                    "content": {},
                    "channel": "http",
                    "actor": "user",
                    "answeredAt": answer_time.isoformat(),
                }
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        assert ("clarification", "accept") in metrics.questions_total
        assert metrics.questions_total[("clarification", "accept")] == 1
        assert metrics.decision_latency_seconds_count == 1
        assert 29 < metrics.decision_latency_seconds_sum < 31

    def test_question_kinds(self, home: Path) -> None:
        """Test that question kind field is used when present."""
        now = datetime.now(timezone.utc)

        task = {
            "id": "t2",
            "pod": "myproj",
            "status": "done",
            "question": {
                "id": "q-kind-test",
                "taskId": "t2",
                "pod": "myproj",
                "step": "input",
                "message": "Proceed?",
                "kind": "decision",
                "createdAt": now.isoformat(),
                "expiresAt": None,
                "requestedSchema": {"type": "object", "properties": {}},
            },
            "answers": [
                {
                    "questionId": "q-kind-test",
                    "step": "input",
                    "message": "Proceed?",
                    "action": "decline",
                    "content": None,
                    "channel": "cli",
                    "actor": "user",
                    "answeredAt": now.isoformat(),
                }
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        assert ("decision", "decline") in metrics.questions_total
        assert metrics.questions_total[("decision", "decline")] == 1

    def test_multiple_answers_with_latency(self, home: Path) -> None:
        """Test multiple answers with different latencies."""
        now = datetime.now(timezone.utc)

        task = {
            "id": "t4",
            "pod": "myproj",
            "status": "done",
            "question": {
                "id": "q-multi",
                "taskId": "t4",
                "pod": "myproj",
                "step": "input",
                "message": "Question?",
                "createdAt": (now - timedelta(seconds=50)).isoformat(),
                "expiresAt": None,
                "requestedSchema": {"type": "object", "properties": {}},
            },
            "answers": [
                {
                    "questionId": "q-multi",
                    "step": "input",
                    "message": "Question?",
                    "action": "accept",
                    "content": {},
                    "channel": "http",
                    "actor": "user",
                    "answeredAt": (now - timedelta(seconds=20)).isoformat(),
                },
                {
                    "questionId": "q-multi",
                    "step": "input",
                    "message": "Question?",
                    "action": "decline",
                    "content": None,
                    "channel": "cli",
                    "actor": "user",
                    "answeredAt": now.isoformat(),
                },
            ],
        }

        _write_task("myproj", task)

        metrics = _escalation.count_escalation_metrics()
        assert metrics.questions_total.get(("clarification", "accept"), 0) == 1
        assert metrics.questions_total.get(("clarification", "decline"), 0) == 1
        # Two answers, so two latency measurements
        assert metrics.decision_latency_seconds_count == 2
        # Question created at now-50s, first answer at now-20s (30s latency),
        # second answer at now (50s latency), total 80s
        assert 75 < metrics.decision_latency_seconds_sum < 85
