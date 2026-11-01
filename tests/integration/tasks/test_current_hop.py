"""A running task's ``current`` ends in the same write that records the hop it named."""

from __future__ import annotations

from tests.support.pods import build_pod
from tests.support.tasks import stored_task

from docket.interfaces.cli.commands import pod as _pod
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.domain.state import Status
from docket.tasks.domain.task import CurrentHop, HopResult

SUBJECT = "docket.tasks.application.record"


def _running_inside(step: str) -> str:
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    task, _ = _queue.enqueue_task_once("demo", "work", channel="http")
    _queue.apply_transition("demo", task.id, Status.running)
    current = CurrentHop(
        step_id=step, role="lead", member="demo-lead", model="m", started_at="t", cycle=0
    )
    _record.set_current_hop("demo", task.id, current)
    return task.id


def test_the_finished_hop_and_the_end_of_current_are_one_change() -> None:
    task_id = _running_inside("lead")
    before = stored_task("demo", task_id)
    assert before.current is not None

    _record.persist_hop("demo", task_id, HopResult(role="lead", ok=True, step_id="lead"))

    after = stored_task("demo", task_id)
    assert (after.current, len(after.hops)) == (None, 1)
    assert after.rev == before.rev + 1


def test_a_hop_of_another_step_leaves_current_alone() -> None:
    task_id = _running_inside("review")

    _record.persist_hop("demo", task_id, HopResult(role="lead", ok=True, step_id="lead"))

    current = stored_task("demo", task_id).current
    assert current is not None and current.step_id == "review"
