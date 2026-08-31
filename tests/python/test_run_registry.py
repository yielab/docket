"""The persisted run registry — one record per dispatch invocation.

Unit-level coverage of ``core/runs.py``'s CRUD primitives and its ``execute()``
safe-wrapper, hermetic against a tmp ``RUNS_FILE``. Integration coverage (every
real dispatch call site — CLI/webhook/schedule/sweep — actually creates and
finishes a record) lives in ``test_dispatch_run_records.py``.

Acceptance criteria this file covers:
  - create_run/mark_running/finish_run/get_run/list_runs round-trip correctly
  - list_runs filters by project and orders newest first
  - execute() records a success (state, taskIds) and never raises
  - execute() records a failure (state, error text) and never raises
  - concurrent create_run calls never clobber each other (locked read-modify-write)
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import runs as _runs


@pytest.fixture()
def runs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "docket-runs.json"
    monkeypatch.setattr(_cfg, "RUNS_FILE", f, raising=True)
    return f


class _FakeTaskResult:
    """Minimal stand-in for dispatch.TaskResult (duck-typed by core/runs.py)."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


class TestCreateRun:
    def test_create_run_defaults_to_queued(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        assert rec["state"] == "queued"
        assert rec["source"] == "cli"
        assert rec["project"] == "demo"
        assert rec["id"].startswith("run-")
        assert rec["taskIds"] == []
        assert rec["error"] == ""
        assert rec["startedAt"] is None
        assert rec["finishedAt"] is None
        assert rec["cancellation"] == {
            "requestedAt": None,
            "observedAt": None,
            "stoppedAt": None,
            "reason": "",
            "source": "",
        }

    def test_create_run_persists(self, runs_file: Path) -> None:
        rec = _runs.create_run("webhook", "demo")
        assert _runs.get_run(rec["id"]) == rec

    def test_unknown_source_rejected(self, runs_file: Path) -> None:
        with pytest.raises(_runs.RunError):
            _runs.create_run("carrier-pigeon", "demo")  # type: ignore[arg-type]

    def test_missing_project_rejected(self, runs_file: Path) -> None:
        with pytest.raises(_runs.RunError):
            _runs.create_run("cli", "")

    def test_ids_are_unique(self, runs_file: Path) -> None:
        ids = {_runs.create_run("cli", "demo")["id"] for _ in range(20)}
        assert len(ids) == 20


class TestLifecycle:
    def test_mark_running_stamps_started_at(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        updated = _runs.get_run(rec["id"])
        assert updated is not None
        assert updated["state"] == "running"
        assert updated["startedAt"] is not None

    def test_mark_running_unknown_id_is_noop(self, runs_file: Path) -> None:
        _runs.mark_running("run-does-not-exist")  # must not raise

    def test_finish_run_succeeded(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=["task-1", "task-2"])
        updated = _runs.get_run(rec["id"])
        assert updated is not None
        assert updated["state"] == "succeeded"
        assert updated["taskIds"] == ["task-1", "task-2"]
        assert updated["error"] == ""
        assert updated["finishedAt"] is not None

    def test_finish_run_failed_carries_error(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="failed", error="boom")
        updated = _runs.get_run(rec["id"])
        assert updated is not None
        assert updated["state"] == "failed"
        assert updated["error"] == "boom"

    def test_finish_run_invalid_state_rejected(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        with pytest.raises(_runs.RunError):
            _runs.finish_run(rec["id"], state="queued")  # type: ignore[arg-type]

    def test_finish_run_unknown_id_is_noop(self, runs_file: Path) -> None:
        _runs.finish_run("run-does-not-exist", state="succeeded")  # must not raise


class TestGetAndList:
    def test_get_run_unknown_returns_none(self, runs_file: Path) -> None:
        assert _runs.get_run("run-nope") is None

    def test_list_runs_empty(self, runs_file: Path) -> None:
        assert _runs.list_runs() == []

    def test_list_runs_filters_by_project(self, runs_file: Path) -> None:
        _runs.create_run("cli", "alpha")
        _runs.create_run("cli", "beta")
        _runs.create_run("webhook", "alpha")
        alpha_runs = _runs.list_runs("alpha")
        assert len(alpha_runs) == 2
        assert all(r["project"] == "alpha" for r in alpha_runs)

    def test_list_runs_newest_first(self, runs_file: Path) -> None:
        first = _runs.create_run("cli", "demo")
        second = _runs.create_run("cli", "demo")
        records = _runs.list_runs("demo")
        assert [r["id"] for r in records] == [second["id"], first["id"]]


class TestExecute:
    def test_success_records_state_and_task_ids(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        results = _runs.execute(
            rec["id"], lambda: [_FakeTaskResult("task-a"), _FakeTaskResult("task-b")]
        )
        assert results is not None
        assert [r.task_id for r in results] == ["task-a", "task-b"]
        updated = _runs.get_run(rec["id"])
        assert updated is not None
        assert updated["state"] == "succeeded"
        assert updated["taskIds"] == ["task-a", "task-b"]
        assert updated["error"] == ""

    def test_failure_never_raises_and_records_error(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")

        def _boom() -> list[object]:
            raise RuntimeError("dispatch exploded")

        results = _runs.execute(rec["id"], _boom)
        assert results is None  # execute() itself never raises
        updated = _runs.get_run(rec["id"])
        assert updated is not None
        assert updated["state"] == "failed"
        assert "dispatch exploded" in updated["error"]
        assert "RuntimeError" in updated["error"]

    def test_execute_marks_running_before_invoking_fn(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        seen_state: list[str] = []

        def _observe() -> list[object]:
            mid = _runs.get_run(rec["id"])
            assert mid is not None
            seen_state.append(str(mid["state"]))
            return []

        _runs.execute(rec["id"], _observe)
        assert seen_state == ["running"]


class TestConcurrentCreate:
    def test_concurrent_create_run_never_loses_a_record(self, runs_file: Path) -> None:
        """A locked read-modify-write: N threads creating runs concurrently must
        all land in the file — the same race that was closed for the task
        queue, applied to the run registry."""
        n = 20
        barrier = threading.Barrier(n)

        def _create(i: int) -> None:
            barrier.wait(timeout=5)
            _runs.create_run("sweep", f"proj-{i}")

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(_runs.list_runs()) == n
