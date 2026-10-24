"""TaskRepository: the pod's queue as TaskRecords, changed under the lock, ledger kept in step."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import pods as _support_pods

from docket.kernel.home import current_home
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain.task import HopResult, TaskRecord
from docket.teams import agent_memory as _mem
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.application.repository"

pod_home = _support_pods.pod_home_bare


@pytest.fixture
def repo(pod_home: Path) -> TaskRepository:
    _support_pods.seed_lean_pod("demo")
    return TaskRepository.for_pod("demo")


def _ledger_ids(project: str = "demo") -> list[str]:
    return _mem.read_dispatch_task_ids(current_home().workspace_dir(f"{project}-lead"))


def _stored() -> list[dict[str, object]]:
    path = _settings.pod_task_list_path("demo")
    tasks: list[dict[str, object]] = json.loads(path.read_text())["tasks"]
    return tasks


class TestAdd:
    def test_a_new_task_is_queued_and_created(self, repo: TaskRepository) -> None:
        record, created = repo.add(TaskRecord(id="task-1", description="a"))
        assert created is True
        assert [r.id for r in repo.list()] == ["task-1"]
        assert repo.get("task-1") == record

    def test_the_same_idempotency_key_twice_queues_one_task(self, repo: TaskRepository) -> None:
        first, created_first = repo.add(TaskRecord(description="a", idempotency_key="k"))
        again, created_again = repo.add(TaskRecord(description="b", idempotency_key="k"))
        assert (created_first, created_again) == (True, False)
        assert again.id == first.id
        assert [r.description for r in repo.list()] == ["a"]

    def test_tasks_without_a_key_are_never_deduplicated(self, repo: TaskRepository) -> None:
        repo.add(TaskRecord(description="a"))
        _, created = repo.add(TaskRecord(description="a"))
        assert created is True
        assert len(repo.list()) == 2


class TestUpdate:
    def test_a_function_changes_one_task_and_the_change_is_stored(
        self, repo: TaskRepository
    ) -> None:
        repo.add(TaskRecord(id="task-1", description="a"))
        repo.add(TaskRecord(id="task-2", description="b"))

        def _rename(record: TaskRecord) -> None:
            record.description = "renamed"

        changed = repo.update("task-2", _rename)
        assert changed is not None and changed.description == "renamed"
        assert [t["description"] for t in _stored()] == ["a", "renamed"]

    def test_an_unknown_id_is_none_and_writes_nothing(self, repo: TaskRepository) -> None:
        repo.add(TaskRecord(id="task-1", description="a"))
        path = _settings.pod_task_list_path("demo")
        before = path.read_bytes()
        assert repo.update("task-9", lambda record: None) is None
        assert path.read_bytes() == before

    def test_after_an_update_the_ledger_lists_the_running_task(self, repo: TaskRepository) -> None:
        repo.add(TaskRecord(id="task-1", description="a"))
        assert _ledger_ids() == []
        repo.update("task-1", lambda r: setattr(r, "status", _state.Status.running))
        assert _ledger_ids() == ["task-1"]
        repo.update("task-1", lambda r: setattr(r, "status", _state.Status.done))
        assert _ledger_ids() == []


class TestUpdateEach:
    def test_one_write_for_every_task_the_function_changed(self, repo: TaskRepository) -> None:
        for i in range(3):
            repo.add(TaskRecord(id=f"task-{i}", description="a", priority="low" if i else "high"))

        def _raise(record: TaskRecord) -> bool:
            if record.priority != "low":
                return False
            record.priority = "high"
            return True

        changed = repo.update_each(_raise)
        assert [r.id for r in changed] == ["task-1", "task-2"]
        assert {t["priority"] for t in _stored()} == {"high"}

    def test_a_function_that_changes_nothing_writes_nothing(self, repo: TaskRepository) -> None:
        repo.add(TaskRecord(id="task-1", description="a"))
        path = _settings.pod_task_list_path("demo")
        before = path.read_bytes()
        assert repo.update_each(lambda record: False) == []
        assert path.read_bytes() == before


class TestClaimNext:
    def test_the_highest_priority_pending_task_is_claimed_and_listed_in_the_ledger(
        self, repo: TaskRepository
    ) -> None:
        repo.add(TaskRecord(id="task-low", description="a", priority="low"))
        repo.add(TaskRecord(id="task-high", description="b", priority="high"))
        claim = repo.claim_next(resume=False)
        assert claim is not None
        assert claim.record.id == "task-high"
        assert claim.record.status == _state.Status.running
        assert claim.record.claim_pid is not None and claim.record.started_at
        stored = repo.get("task-high")
        assert stored is not None and stored.status == _state.Status.running
        stored_low = repo.get("task-low")
        assert stored_low is not None and stored_low.status == _state.Status.pending
        assert _ledger_ids() == ["task-high"]

    def test_the_override_is_handed_back_and_cleared_from_the_stored_record(
        self, repo: TaskRepository
    ) -> None:
        repo.add(TaskRecord(id="task-1", description="a", gate_override_pipeline_index=2))
        claim = repo.claim_next(resume=False)
        assert claim is not None and claim.gate_override_index == 2
        assert claim.record.gate_override_pipeline_index is None
        stored = repo.get("task-1")
        assert stored is not None and stored.gate_override_pipeline_index is None
        assert _stored()[0]["gateOverridePipelineIndex"] is None

    def test_a_claim_carries_the_recorded_hops_to_resume_from(self, repo: TaskRepository) -> None:
        hop = HopResult(role="lead", member_id="demo-lead", ok=True, output="plan")
        repo.add(TaskRecord(id="task-1", description="a", hops=[hop]))
        claim = repo.claim_next(resume=False)
        assert claim is not None
        assert [h.output for h in claim.resume_hops] == ["plan"]

    def test_skip_hides_a_task_this_run_already_claimed(self, repo: TaskRepository) -> None:
        repo.add(TaskRecord(id="task-1", description="a"))
        assert repo.claim_next(resume=False, skip=frozenset({"task-1"})) is None

    def test_only_a_resumable_failure_is_claimed_and_only_on_resume(
        self, repo: TaskRepository
    ) -> None:
        repo.add(
            TaskRecord(
                id="task-1",
                description="a",
                status=_state.Status.failed,
                failure_kind=_state.FailureKind.stale_claim.value,
            )
        )
        repo.add(
            TaskRecord(
                id="task-2",
                description="b",
                status=_state.Status.failed,
                failure_kind="gate_failed",
            )
        )
        assert repo.claim_next(resume=False) is None
        claim = repo.claim_next(resume=True)
        assert claim is not None and claim.record.id == "task-1"
        assert claim.record.failure_kind is None

    def test_nothing_eligible_is_none_and_writes_nothing(self, repo: TaskRepository) -> None:
        repo.add(TaskRecord(id="task-1", description="a", status=_state.Status.done))
        path = _settings.pod_task_list_path("demo")
        before = path.read_bytes()
        assert repo.claim_next(resume=True) is None
        assert path.read_bytes() == before
