"""`resolve` receives an answer to a question; the claim of the task applies it, exactly once.

Real pods and tasks, a real dispatch to park a task on an `input` step and the real `resolve`; only
the model is a double. The oracle for the applied answer is the task a surface reads: the
synthetic operator hop and its route, the consult note the re-run hop reads.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.support import escalations as _support_escalations
from tests.support.escalations import approval_escalation, consult_escalation, parked_approval
from tests.support.fakes import FakeDriver
from tests.support.pods import bind_pipeline, build_pod
from tests.support.tasks import stored_task

from docket.hops.application import executor as _executor
from docket.hops.application import resolutions as _resolutions
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.operator_contract import Escalation
from docket.platform import (
    list_escalations,
    read_escalation,
    settle_escalation,
    write_escalation,
)
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue
from docket.tasks.application.answers import answers_of, consult_note
from docket.tasks.application.record import persist_hop
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult

SUBJECT = "docket.hops.application.resolutions"

PROJECT = "demo"
ASK = """\
name: ask
steps:
  - lead: lead
  - ask:
      input:
        from: lead
  - implementer: implementer
"""
ASK_STOP = """\
name: ask-stop
steps:
  - lead: lead
  - ask:
      input:
        from: lead
      on:
        answered: stop
  - implementer: implementer
"""

demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("demo_pod")


def _roles(driver: FakeDriver) -> list[str]:
    return [call[0].rsplit("-", 1)[-1] for call in driver.calls]


def _park_on_input(pipeline: str = ASK) -> Escalation:
    """A task parked on the `ask` step by a real dispatch; returns its `input` escalation."""
    build_pod(PROJECT, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{PROJECT}")
    bind_pipeline(PROJECT, pipeline)
    _queue.enqueue_task_once(PROJECT, "needs a decision", channel="cli")
    _sweep.dispatch_pod(PROJECT, runner=FakeDriver())
    (record,) = list_escalations()
    assert record.kind == "input"
    return record


def _answer(escalation: Escalation, **content: Any) -> None:
    _esc.resolve(escalation.id, None, content or {"answer": "ship it"}, by="alice", channel="http")


def _apply(task_id: str) -> _resolutions.Applied:
    """What the claim does for *task_id* before it computes the resume position."""
    task = TaskRepository.for_pod(PROJECT).get(task_id)
    assert task is not None
    steps, ids, _ = _executor.resolve_pipeline_steps(PROJECT, None)
    return _resolutions.apply_resolutions(PROJECT, task, list(task.hops), steps, ids)


def _operator_hops(task_id: str) -> list[Any]:
    return [h for h in stored_task(PROJECT, task_id).hops if h.role == "operator"]


class TestResolveOnlyReceives:
    def test_an_input_answer_adds_no_hop_and_leaves_the_resolution_unapplied(self) -> None:
        escalation = _park_on_input()
        hops_before = stored_task(PROJECT, escalation.task).hops

        _answer(escalation)

        task = stored_task(PROJECT, escalation.task)
        assert task.status == "pending"
        assert [a.action for a in answers_of(task)] == ["accept"]
        assert task.hops == hops_before
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is None

    def test_a_consult_answer_sets_no_consult_note_yet(self) -> None:
        escalation = consult_escalation()

        _esc.resolve(escalation.id, "redis", {"note": "hot path"}, by="alice", channel="http")

        task = stored_task(PROJECT, escalation.task)
        assert task.status == "pending"
        assert [(a.option_id, a.action) for a in answers_of(task)] == [("redis", "accept")]
        # The answer is read from the record by the re-run hop; nothing is applied to the task.
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is None
        assert _apply(escalation.task).hops == task.hops
        assert "option redis (Redis) hot path" in consult_note(task, escalation.step)

    def test_no_update_of_the_pipeline_or_the_hops_and_no_pipeline_is_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        escalation = _park_on_input()
        touched: list[tuple[Any, Any, Any]] = []
        real_update = TaskRepository.update

        def _spy(self: TaskRepository, task_id: str, fn: Any) -> Any:
            def _wrapped(record: Any) -> Any:
                before = (list(record.hops), record.pipeline, record.pipeline_spec)
                outcome = fn(record)
                after = (list(record.hops), record.pipeline, record.pipeline_spec)
                if before != after:
                    touched.append((before, after, task_id))
                return outcome

            return real_update(self, task_id, _wrapped)

        def _no_pipeline(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("resolve resolved a pipeline")

        monkeypatch.setattr(TaskRepository, "update", _spy)
        monkeypatch.setattr(_executor, "resolve_pipeline_steps", _no_pipeline)

        _answer(escalation)

        assert touched == []


class TestTheClaimApplies:
    def test_an_input_answer_becomes_one_operator_hop_and_the_pipeline_goes_on(self) -> None:
        escalation = _park_on_input()
        _answer(escalation)
        driver = FakeDriver()

        _sweep.dispatch_pod(PROJECT, runner=driver)

        task = stored_task(PROJECT, escalation.task)
        assert task.status == "done"
        assert [h.role for h in task.hops] == ["lead", "operator", "implementer"]
        assert _roles(driver) == ["implementer"]
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is not None

    def test_a_stop_route_settles_the_task_done_without_running_a_hop(self) -> None:
        escalation = _park_on_input(ASK_STOP)
        _answer(escalation)
        assert stored_task(PROJECT, escalation.task).status == "pending"
        driver = FakeDriver()

        _sweep.dispatch_pod(PROJECT, runner=driver)

        task = stored_task(PROJECT, escalation.task)
        assert task.status == "done" and driver.calls == []
        assert [h.role for h in task.hops] == ["lead", "operator"]
        assert task.completed_at

    def test_a_consult_answer_is_the_note_the_re_run_hop_reads(self) -> None:
        escalation = consult_escalation()
        _esc.resolve(escalation.id, "redis", {"note": "hot path"}, by="alice", channel="http")
        driver = FakeDriver()

        _sweep.dispatch_pod(PROJECT, runner=driver)

        implementer = next(c for c in driver.calls if c[0].endswith("implementer"))
        assert (
            f"Operator answered your consultation {escalation.id}: option redis (Redis) hot path"
            in implementer[2]
        )
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is not None

    def test_a_declined_consult_tells_the_hop_to_decide_itself(self) -> None:
        escalation = consult_escalation()
        _esc.resolve(escalation.id, "decline", None, by="alice", channel="http")
        driver = FakeDriver()

        _sweep.dispatch_pod(PROJECT, runner=driver)

        implementer = next(c for c in driver.calls if c[0].endswith("implementer"))
        assert "declined. Decide yourself." in implementer[2]


class TestAppliedOnce:
    def test_a_task_claimed_twice_gains_one_operator_hop(self) -> None:
        escalation = _park_on_input()
        _answer(escalation)

        first = _apply(escalation.task)
        second = _apply(escalation.task)

        assert [h.role for h in first.hops] == ["lead", "operator"]
        assert [h.role for h in second.hops] == ["lead", "operator"]
        assert len(_operator_hops(escalation.task)) == 1

    def test_a_crash_between_the_hop_and_the_stamp_does_not_double_the_hop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        escalation = _park_on_input()
        _answer(escalation)
        monkeypatch.setattr(_resolutions, "mark_escalation_applied", lambda *a, **k: False)
        _apply(escalation.task)
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is None
        monkeypatch.undo()

        again = _apply(escalation.task)

        assert [h.role for h in again.hops] == ["lead", "operator"]
        assert len(_operator_hops(escalation.task)) == 1
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is not None

    def test_a_terminal_route_still_ends_the_task_when_the_claim_is_repeated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        escalation = _park_on_input(ASK_STOP)
        _answer(escalation)
        monkeypatch.setattr(_resolutions, "mark_escalation_applied", lambda *a, **k: False)
        assert _apply(escalation.task).ended is not None
        monkeypatch.undo()

        again = _apply(escalation.task)

        assert again.ended is not None and again.ended[0] == "done"
        assert len(_operator_hops(escalation.task)) == 1

    def test_a_consult_note_is_read_until_a_hop_of_its_step_is_persisted_and_then_not_again(
        self,
    ) -> None:
        escalation = consult_escalation()
        _esc.resolve(escalation.id, "redis", None, by="alice", channel="http")
        task = stored_task(PROJECT, escalation.task)
        assert consult_note(task, escalation.step) == consult_note(task, escalation.step) != ""

        persist_hop(PROJECT, task.id, HopResult(role="implementer", ok=True, step_id="implementer"))

        assert consult_note(stored_task(PROJECT, task.id), escalation.step) == ""
        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is not None

    def test_a_note_for_another_step_is_not_delivered_by_a_hop_of_this_one(self) -> None:
        escalation = consult_escalation()
        _esc.resolve(escalation.id, "redis", None, by="alice", channel="http")

        persist_hop(PROJECT, escalation.task, HopResult(role="lead", ok=True, step_id="lead"))

        assert consult_note(stored_task(PROJECT, escalation.task), escalation.step) != ""


class TestWhatIsNeverApplied:
    @pytest.mark.parametrize("state", ["expired", "decided", "pending"])
    def test_a_record_that_is_not_resolved_changes_nothing(self, state: str) -> None:
        escalation = _park_on_input()
        _answer(escalation)
        stored = read_escalation(escalation.id)
        assert stored is not None
        # A record another path moved on: written back in the state under test.
        write_escalation(stored.model_copy(update={"state": state}))

        _apply(escalation.task)

        assert _operator_hops(escalation.task) == []

    def test_an_expired_question_is_not_applied_after_the_sweep(self) -> None:
        escalation = _park_on_input()
        settle_escalation(escalation.id, "expired")

        _apply(escalation.task)

        assert _operator_hops(escalation.task) == []


class TestAGrantedGateIsHandedToTheClaim:
    def test_resolve_leaves_the_position_unapplied_and_the_claim_hands_it_back_once(self) -> None:
        escalation = approval_escalation("gate")

        _esc.resolve(escalation.id, "approve_once", None, by="alice", channel="http")

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is None
        first = _apply(escalation.task)
        second = _apply(escalation.task)
        assert (first.gate_override_index, second.gate_override_index) == (1, None)
        stamped = read_escalation(escalation.id)
        assert stamped is not None and stamped.resolution is not None
        assert stamped.resolution.applied_at is not None

    def test_the_enqueue_screen_is_handed_back_like_a_gate(self) -> None:
        escalation = approval_escalation("approval", pipelineIndex=0)

        _esc.resolve(escalation.id, "approve_once", None, by="alice", channel="http")

        assert _apply(escalation.task).gate_override_index == 0

    def test_a_denial_hands_back_nothing_and_is_stamped_when_it_is_resolved(self) -> None:
        escalation = approval_escalation("gate")

        _esc.resolve(escalation.id, "deny", None, by="alice", channel="http")

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is not None
        assert _apply(escalation.task).gate_override_index is None

    def test_a_parked_call_is_stamped_when_resolved_and_names_no_position(self) -> None:
        escalation = parked_approval()

        _esc.resolve(escalation.id, "approve_once", None, by="alice", channel="http")

        stored = read_escalation(escalation.id)
        assert stored is not None and stored.resolution is not None
        assert stored.resolution.applied_at is not None
        assert _apply(escalation.task).gate_override_index is None

    @pytest.mark.parametrize("state", ["expired", "decided", "pending"])
    def test_a_gate_that_is_not_resolved_hands_back_nothing(self, state: str) -> None:
        escalation = approval_escalation("gate")
        _esc.resolve(escalation.id, "approve_once", None, by="alice", channel="http")
        stored = read_escalation(escalation.id)
        assert stored is not None
        write_escalation(stored.model_copy(update={"state": state}))

        assert _apply(escalation.task).gate_override_index is None
