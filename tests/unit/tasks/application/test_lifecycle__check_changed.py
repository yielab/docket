"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.domain import task as _task

SUBJECT = "docket.tasks.application.lifecycle"


def test_a_stale_check_changed_is_cleared_by_a_result_that_does_not_set_it() -> None:
    task = _task.TaskRecord(
        id="t", description="x", status="running", checkChanged=["package.json"]
    )
    _lifecycle._apply_result(task, _task.TaskResult(task_id="t", status="done"))
    assert task.check_changed == []
    parked = _task.TaskResult(task_id="t", status="waiting_approval", check_changed=["a"])
    _lifecycle._apply_result(task, parked)
    assert task.check_changed == ["a"] and task.status == "waiting_approval"
