"""``hops.application.waits`` -- what a claim does with a task whose wait was not ended yet, or
whose pipeline no longer holds the step it parked on. Parking, waking and applying a real outcome
run through dispatch in ``tests/integration/tasks/dispatch/test_wait_step.py``."""

from __future__ import annotations

import pytest

from docket.hops.application import waits as _waits
from docket.kernel.errors import DispatchError
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain.spec import load_pipeline
from docket.tasks.domain.task import HopResult, TaskRecord, TaskWait
from docket.teams import roles as _archetypes

SUBJECT = "docket.hops.application.waits"

_PIPELINE = """\
name: nap
steps:
  - lead: lead
  - hold: {wait: 1h}
  - implementer: implementer
"""


def _plan() -> tuple[tuple[_orch.PlannedNode, ...], dict[str, int]]:
    spec = load_pipeline(_PIPELINE).spec
    assert spec is not None
    roster = {"lead": "demo-lead", "implementer": "demo-implementer"}
    steps = _orch.resolve_plan(spec, roster, registry=_archetypes.load_registry()).runnable_nodes()
    return steps, {node.step_id: i for i, node in enumerate(steps)}


def _task(**wait: object) -> TaskRecord:
    fields: dict[str, object] = {"step": "hold", "dueAt": "2999-01-01T00:00:00+00:00", **wait}
    return TaskRecord(description="x", wait=TaskWait.model_validate(fields))


def _lead_hop() -> HopResult:
    return HopResult(role="lead", member_id="demo-lead", ok=True, step_id="lead")


class TestApplyWait:
    def test_a_task_with_no_wait_is_left_as_it_is(self) -> None:
        steps, index = _plan()
        hops = [_lead_hop()]

        applied = _waits.apply_wait("demo", TaskRecord(description="x"), hops, steps, index)

        assert applied.hops == hops
        assert applied.ended is None

    def test_a_wait_that_was_not_woken_is_left_for_the_sweep(self) -> None:
        steps, index = _plan()

        applied = _waits.apply_wait("demo", _task(), [_lead_hop()], steps, index)

        assert [h.step_id for h in applied.hops] == ["lead"]

    def test_an_outcome_for_a_step_the_pipeline_no_longer_has_is_refused(self) -> None:
        steps, index = _plan()
        task = _task(step="gone", outcome="resumed")

        with pytest.raises(DispatchError, match="gone"):
            _waits.apply_wait("demo", task, [_lead_hop()], steps, index)

    def test_an_outcome_for_a_step_that_is_not_a_wait_is_refused(self) -> None:
        steps, index = _plan()
        task = _task(step="lead", outcome="resumed")

        with pytest.raises(DispatchError, match="lead"):
            _waits.apply_wait("demo", task, [], steps, index)

    def test_an_outcome_when_the_hops_do_not_reach_the_step_is_refused(self) -> None:
        steps, index = _plan()
        task = _task(outcome="resumed")

        with pytest.raises(DispatchError, match="not parked at step 'hold'"):
            _waits.apply_wait("demo", task, [], steps, index)


class TestProbeWait:
    def test_a_wait_with_no_probe_never_passes(self) -> None:
        assert _waits.probe_wait("demo", _task()) is False
        assert _waits.probe_wait("demo", TaskRecord(description="x")) is False
