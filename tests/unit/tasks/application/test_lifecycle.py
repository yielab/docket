"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.support import pods as _support_pods
from tests.support.pods import seed_lean_pod as _seed_lean_pod
from tests.support.tasks import update_task

from docket.kernel.operator_contract import Question
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.domain import task as _task

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.tasks.application.lifecycle"


# ── fixtures ──────────────────────────────────────────────────────────────────


class TestCancelTask:
    def _seed(self, status: str, **fields: Any) -> str:
        _seed_lean_pod()
        task = _queue.enqueue_task_once("myapp", "work", channel="cli")[0]
        update_task("myapp", task.id, status=status, **fields)
        return str(task.id)

    def test_a_running_task_cancels_its_live_run_and_audits_once(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An in-flight run with no task ids is the running task's: it is cancelled, one audit."""
        from docket.governance import audit as _audit
        from docket.tasks.application import run_cancellation as _run_cancellation
        from docket.tasks.application import runs as _runs

        task_id = self._seed("running")
        monkeypatch.setattr(
            _runs,
            "list_runs",
            lambda project=None: [
                {"id": "run-a", "state": "running", "taskIds": []},
                {"id": "run-b", "state": "done", "taskIds": []},
                {"id": "run-c", "state": "running", "taskIds": ["other"]},
            ],
        )
        asked: list[str] = []
        sources: list[str] = []

        def _cancel(run_id: str, *, source: str = "cli") -> _run_cancellation.CancelOutcome:
            asked.append(run_id)
            sources.append(source)
            return _run_cancellation.CancelOutcome(ok=True, message=f"asked {run_id}")

        monkeypatch.setattr(_runs, "cancel_run", _cancel)

        outcome = _lifecycle.cancel_task("myapp", task_id, channel="http", reason="why")

        assert asked == ["run-a"]
        assert sources == ["http"]
        assert outcome.status == "cancelled"
        assert outcome.cancelled_runs == ("run-a",)
        assert outcome.messages == ("asked run-a",)
        cancels = [e for e in _audit.read_audit() if e.get("action") == "task.cancel"]
        assert len(cancels) == 1
        assert "channel=http" in cancels[0]["detail"] and "reason=why" in cancels[0]["detail"]

    def test_a_refused_run_cancel_is_a_warning_not_a_cancellation(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run that will not cancel leaves the task unchanged and reports why."""
        from docket.tasks.application import run_cancellation as _run_cancellation
        from docket.tasks.application import runs as _runs

        task_id = self._seed("pending")
        monkeypatch.setattr(
            _runs,
            "list_runs",
            lambda project=None: [{"id": "run-a", "state": "queued", "taskIds": [task_id]}],
        )
        monkeypatch.setattr(
            _runs,
            "cancel_run",
            lambda run_id, *, source="cli": _run_cancellation.CancelOutcome(
                ok=False, message="nope"
            ),
        )

        outcome = _lifecycle.cancel_task("myapp", task_id, channel="cli")

        assert not outcome.cancelled
        assert outcome.status == "pending"
        assert outcome.warnings == ("nope",)

    def test_a_parked_task_is_cancelled_through_the_parked_path(self, pod_home: Path) -> None:
        """A task waiting for input ends cancelled and names where it was parked."""
        task_id = self._seed(
            "waiting_input",
            question=Question(
                id="q-1",
                task_id="t",
                pod="myapp",
                step="s",
                message="which?",
                requested_schema={"type": "object", "properties": {"a": {"type": "string"}}},
                created_at="2026-10-24T00:00:00+00:00",
            ),
        )

        outcome = _lifecycle.cancel_task("myapp", task_id, channel="cli")

        assert (outcome.status, outcome.parked_from) == ("cancelled", "waiting_input")

    def test_a_stale_claim_is_settled_not_cancelled(self, pod_home: Path) -> None:
        """A running task whose claimant is gone ends failed and is reported as reclaimed."""
        task_id = self._seed("running", claim_pid=2**22 + 1)

        outcome = _lifecycle.cancel_task("myapp", task_id, channel="cli")

        assert outcome.reclaimed and outcome.cancelled
        assert outcome.status == "failed"

    def test_nothing_to_cancel_reports_the_status_and_unknown_raises(self, pod_home: Path) -> None:
        """A done task has nothing in flight; an unknown id is a TaskNotFoundError."""
        task_id = self._seed("done")

        outcome = _lifecycle.cancel_task("myapp", task_id, channel="cli")

        assert not outcome.cancelled and outcome.status == "done"
        with pytest.raises(_task.TaskNotFoundError):
            _lifecycle.cancel_task("myapp", "task-nope", channel="cli")
