"""A required pipeline variable that only the queued tasks supply does not stop the dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.fakes import FakeDriver
from tests.support.pods import build_pod

from docket.hops.application import sweep as _sweep
from docket.kernel.errors import DispatchError
from docket.pipeline.domain.spec import PipelineSpec, load_pipeline
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository

pod_home = _support_pods.pod_home

SUBJECT = "docket.hops.application.sweep"

NEEDS_TICKET = """name: needs-ticket
variables:
  TICKET:
    required: true
steps:
  - plan: lead
    instructions: "Triage ${TICKET}."
"""


def _spec() -> PipelineSpec:
    spec = load_pipeline(NEEDS_TICKET).spec
    assert spec is not None
    return spec


@pytest.fixture()
def queue_pod(pod_home: Path) -> str:
    build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
    return "demo"


def test_a_task_that_supplies_the_variable_is_dispatched(queue_pod: str) -> None:
    _queue.enqueue_task_once(queue_pod, "triage", channel="cli", variables={"TICKET": "T-1"})

    results = _sweep.dispatch_pod(queue_pod, runner=FakeDriver(), spec=_spec())

    assert [r.status for r in results] == ["done"]


def test_a_task_that_does_not_is_refused_with_the_same_reason_and_the_next_one_runs(
    queue_pod: str,
) -> None:
    _queue.enqueue_task_once(queue_pod, "no ticket", channel="cli")
    _queue.enqueue_task_once(queue_pod, "ticketed", channel="cli", variables={"TICKET": "T-2"})

    _sweep.dispatch_pod(queue_pod, runner=FakeDriver(), spec=_spec())

    stored = {t.description: t for t in TaskRepository.for_pod(queue_pod).list()}
    assert (stored["no ticket"].status, stored["no ticket"].failure_kind) == ("failed", "pipeline")
    assert "TICKET" in stored["no ticket"].reason
    assert stored["ticketed"].status == "done"


def test_a_queue_with_no_task_supplying_it_is_still_refused_up_front(queue_pod: str) -> None:
    _queue.enqueue_task_once(queue_pod, "no ticket", channel="cli")

    with pytest.raises(DispatchError, match="TICKET"):
        _sweep.dispatch_pod(queue_pod, runner=FakeDriver(), spec=_spec())
