"""A ``wait`` step through real dispatch and the escalation sweep: the task parks with a ``wait``
escalation, the sweep wakes it when its time or its probe comes, and the claim continues from the
step after the wait. See pod-dispatch.spec.md ("Wait steps")."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.pods import bind_pipeline as _bind_pipeline
from tests.support.pods import seed_pod_isolation_off as _seed_pod
from tests.support.tasks import SkewedClock

from docket.hops.application import sweep as _sweep
from docket.kernel.clock import use_clock
from docket.operator import inbox as _inbox
from docket.operator import render as _render
from docket.platform import list_escalations
from docket.tasks.application import escalation_sweep as _escalation_sweep
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.resolution import EscalationInvalid, EscalationNotPending
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.escalation_sweep"

_TIMER = """\
name: nap
steps:
  - lead: lead
  - hold: {wait: 1s}
  - implementer: implementer
"""


def _probe_pipeline(probe: str, on: str = "") -> str:
    return f"""\
name: poll
steps:
  - lead: lead
  - hold:
      wait: 1h
      until: {{run: "{probe}", every: 1s}}
{on}  - implementer: implementer
"""


def _demo_task() -> TaskRecord:
    (task,) = TaskRepository.for_pod("demo").list()
    return task


def _park(text: str) -> TaskRecord:
    """Bind *text*, queue one task and dispatch it until the wait step parks it."""
    _bind_pipeline("demo", text)
    _queue.enqueue_task_once("demo", "wait for it", channel="cli")
    (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())
    assert result.status == "waiting_input"
    return _demo_task()


def _tick(seconds: float) -> int:
    """One sweep tick *seconds* in the future: the wait sweep that dispatching runs first."""
    with use_clock(SkewedClock(seconds)):
        return len(_sweep.dispatch_pod("demo", runner=FakeDriver()))


class TestATimer:
    def test_the_step_parks_the_task_with_a_machine_escalation_and_no_hop(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            task = _park(_TIMER)

            assert [h.role for h in task.hops] == ["lead"]
            (wait,) = list_escalations(state="pending")
            assert (wait.kind, wait.policy, wait.step) == ("wait", "machine", "hold")
            assert [o.id for o in wait.options] == ["resume"]
            assert wait.expires_at is not None
            assert wait.id in task.escalations
            assert task.wait is not None
            assert (task.wait.step, task.wait.due_at) == ("hold", wait.expires_at)
            assert task.wait.outcome is None

    def test_a_sweep_before_the_time_changes_nothing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)

            assert _escalation_sweep.sweep_escalations() == 0
            assert _tick(0) == 0

            assert _demo_task().status == "waiting_input"
            assert len(list_escalations(state="pending")) == 1

    def test_a_sweep_after_the_time_lets_the_next_claim_run_the_step_after_the_wait(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)

            with use_clock(SkewedClock(5)):
                assert _escalation_sweep.sweep_escalations() == 1
            woken = _demo_task()
            assert woken.status == "pending"
            assert woken.wait is not None
            assert woken.wait.outcome == "resumed"
            assert [h.role for h in woken.hops] == ["lead"]

            with use_clock(SkewedClock(5)):
                (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())
            assert result.status == "done"
            final = _demo_task()
            assert [h.role for h in final.hops] == ["lead", "hold", "implementer"]
            assert final.hops[1].output == "waited: resumed"
            assert final.hops[1].step_id == "hold"
            assert final.wait is None
            assert list_escalations(state="pending") == []
            (settled,) = list_escalations(state="expired")
            assert settled.kind == "wait"

    def test_dispatch_alone_wakes_and_finishes_a_due_wait(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)

            assert _tick(5) == 1

            assert _demo_task().status == "done"

    def test_a_second_sweep_over_the_same_wait_adds_nothing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)

            with use_clock(SkewedClock(5)):
                assert _escalation_sweep.sweep_escalations() == 1
                assert _escalation_sweep.sweep_escalations() == 0
            assert [h.role for h in _demo_task().hops] == ["lead"]

    def test_a_person_resumes_it_early(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)
            (wait,) = list_escalations(state="pending")

            resolved = _escalations.resolve(wait.id, "resume", by="alice", channel="cli")

            assert resolved.escalation.state == "resolved"
            assert _demo_task().status == "pending"
            (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())
            assert result.status == "done"
            assert [h.role for h in _demo_task().hops] == ["lead", "hold", "implementer"]

    def test_only_resume_is_an_option(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)
            (wait,) = list_escalations(state="pending")

            with pytest.raises(EscalationInvalid, match="not offered"):
                _escalations.resolve(wait.id, "approve_once", by="alice", channel="cli")
            assert _demo_task().status == "waiting_input"

    def test_a_cancelled_task_ends_its_wait_with_no_side_effect(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _park(_TIMER)

            assert _lifecycle.cancel_parked_task("demo", task.id, channel="cli")

            with use_clock(SkewedClock(5)):
                _escalation_sweep.sweep_escalations()
            assert _demo_task().status == "cancelled"
            assert list_escalations(state="pending") == []


class TestAProbe:
    def _marker(self, tmp_path: Path) -> Path:
        _fleet.meta_set("demo-lead", "codebase", str(tmp_path))
        return tmp_path / "ready"

    def test_a_probe_that_fails_twice_then_passes_resumes_on_the_third_tick(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            marker = self._marker(tmp_path)
            _park(_probe_pipeline(f"test -f {marker}"))

            assert _tick(2) == 0
            assert _tick(4) == 0
            waiting = _demo_task()
            assert waiting.status == "waiting_input"
            assert waiting.wait is not None
            assert waiting.wait.probes == 2

            marker.write_text("up")
            assert _tick(6) == 1

            final = _demo_task()
            assert final.status == "done"
            assert [h.role for h in final.hops] == ["lead", "hold", "implementer"]
            (settled,) = list_escalations(state="resolved")
            assert (settled.kind, settled.resolution.by) == ("wait", "probe")  # type: ignore[union-attr]

    def test_a_probe_waits_for_its_interval(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            marker = self._marker(tmp_path)
            marker.write_text("up")
            _park(_probe_pipeline(f"test -f {marker}"))

            assert _tick(0) == 0
            assert _demo_task().wait.probes == 0  # type: ignore[union-attr]

    def test_a_timer_that_expires_with_no_route_blocks_wait_expired(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            marker = self._marker(tmp_path)
            _park(_probe_pipeline(f"test -f {marker}"))

            with use_clock(SkewedClock(7200)):
                assert _escalation_sweep.sweep_escalations() == 1

            blocked = _demo_task()
            assert (blocked.status, blocked.blocked_reason) == ("blocked", "wait_expired")
            assert "never exited 0" in blocked.reason
            assert blocked.wait is None
            assert [e.state for e in list_escalations()] == ["expired"]

    def test_a_blocked_wait_parks_afresh_when_the_task_is_retried(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            marker = self._marker(tmp_path)
            task = _park(_probe_pipeline(f"test -f {marker}"))
            with use_clock(SkewedClock(7200)):
                _escalation_sweep.sweep_escalations()

            assert _lifecycle.retry_task("demo", task.id)
            (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())

            assert result.status == "waiting_input"
            assert len(list_escalations(state="pending")) == 1
            assert [h.role for h in _demo_task().hops] == ["lead"]

    def test_a_timeout_route_decides_the_task_at_the_next_claim(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            marker = self._marker(tmp_path)
            _park(_probe_pipeline(f"test -f {marker}", on="      on: {timeout: stop}\n"))

            with use_clock(SkewedClock(7200)):
                assert _escalation_sweep.sweep_escalations() == 1
                assert _demo_task().status == "pending"
                (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())

            assert result.status == "done"
            final = _demo_task()
            assert [h.role for h in final.hops] == ["lead", "hold"]
            assert final.hops[1].output == "waited: timeout"

    def test_a_timeout_route_to_fail_fails_the_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            marker = self._marker(tmp_path)
            _park(_probe_pipeline(f"test -f {marker}", on="      on: {timeout: fail}\n"))

            with use_clock(SkewedClock(7200)):
                _escalation_sweep.sweep_escalations()
                (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())

            assert result.status == "failed"

    def test_a_probe_the_classifier_does_not_allow_is_gated_like_a_run_step(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            self._marker(tmp_path)
            _bind_pipeline("demo", _probe_pipeline("rm -rf /"))
            _queue.enqueue_task_once("demo", "wait for it", channel="cli")

            (result,) = _sweep.dispatch_pod("demo", runner=FakeDriver())

            assert result.status == "waiting_approval"
            (gate,) = list_escalations(state="pending")
            assert gate.kind == "gate"
            assert _demo_task().wait is None


def test_a_task_that_no_longer_waits_cannot_be_resumed(tmp_path: Path) -> None:
    with _seed_pod(tmp_path):
        task = _park(_TIMER)
        (wait,) = list_escalations(state="pending")
        _lifecycle.cancel_parked_task("demo", task.id, channel="cli")

        with pytest.raises(EscalationNotPending):
            _escalations.resolve(wait.id, "resume", by="alice", channel="cli")


class TestSurfaces:
    def test_a_waiting_task_is_in_no_inbox_list_and_its_wait_is_under_escalations(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)

            inbox = _inbox.build_inbox(now="2026-10-30T00:00:00+00:00")

            assert inbox.needs_you == []
            assert inbox.running == []
            (wait,) = inbox.escalations
            assert (wait.kind, wait.policy) == ("wait", "machine")

    def test_the_task_view_asks_for_nothing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _park(_TIMER)
            (wait,) = list_escalations(state="pending")

            view = _inbox.task_view("demo", task.model_dump(by_alias=True, mode="json"))

            assert (view.status, view.a2a_state, view.escalation) == (
                "waiting_input",
                "WORKING",
                wait.id,
            )

    def test_a_question_still_reads_input_required(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = {"id": "t1", "status": "waiting_input"}

            assert _inbox.task_view("demo", record).a2a_state == "INPUT_REQUIRED"

    def test_the_title_is_fixed_text_and_the_option_is_resume(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _park(_TIMER)
            (view,) = _inbox.escalation_views()

            rendered = _render.render_escalation(view, "minimal")

            assert rendered.title == "waiting"
            assert rendered.prompt is None
            assert [o.id for o in rendered.options] == ["resume"]
