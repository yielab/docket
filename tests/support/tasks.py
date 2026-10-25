"""Task records for tests: a valid record with defaults, and a queue file seeded from records."""

from __future__ import annotations

from typing import Any

from docket.governance.approval_pregrant import create_pregrant
from docket.tasks.application.json_store import JsonTaskStore
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams.settings import pod_task_list_path


def task(**fields: Any) -> TaskRecord:
    """A pending task with a fresh id; a test sets only the fields it asserts on."""
    return TaskRecord(**{"description": "do the thing", **fields})


def put_tasks(project: str, *records: TaskRecord) -> None:
    """Make *records* the whole queue of *project*."""

    def _replace(current: list[TaskRecord]) -> bool:
        current[:] = records
        return True

    JsonTaskStore(pod_task_list_path(project)).modify(_replace)


def put_task(project: str, record: TaskRecord) -> None:
    put_tasks(project, record)


def update_task(project: str, task_id: str, **fields: Any) -> None:
    """Set *fields* on the stored task *task_id* of *project*, through the repository."""

    def _set(record: TaskRecord) -> None:
        for name, value in fields.items():
            setattr(record, name, value)

    assert TaskRepository.for_pod(project).update(task_id, _set) is not None


def stored_task(project: str, task_id: str) -> TaskRecord:
    """The task *task_id* as the queue of *project* holds it."""
    record = TaskRepository.for_pod(project).get(task_id)
    assert record is not None
    return record


def pregrant(project: str, task_id: str, *, tool: str = "bash", digest: str = "d") -> str:
    """Record a single-use pre-grant for *task_id* of *project*, as `task approve --for` did; its token."""
    return create_pregrant(project, "implementer", tool, digest, task_id=task_id, channel="cli")
