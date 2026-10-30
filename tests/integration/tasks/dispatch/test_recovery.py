"""Pod dispatch under failure: stalls, crashes, refusals and blocked tasks."""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

import pytest
from tests.support.dispatch_harness import (
    _ScriptedBackend,
)
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off
from tests.support.llm import final_response as _final_response
from tests.support.pods import build_pod
from tests.support.pods import seed_pod_isolation_off as _seed_pod
from tests.support.tasks import claims_gone_stale

from docket.agent import ports as _rd
from docket.agent.ports import ChatResponse, TokenUsage, ToolCall, assistant
from docket.governance import audit as _audit
from docket.hops.application import driver as _dr
from docket.hops.application import executor as _executor
from docket.hops.application import steps as _steps_c
from docket.hops.application import sweep as _sweep
from docket.hops.application import usage as _usage
from docket.hops.application.driver import DocketDriver
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings
from docket.teams.models import AgentMeta as _AgentMeta

SUBJECT = "docket.tasks.application.queue"


def _endpoint_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """`docket run` refuses without a model endpoint; these tests drive a FakeDriver."""
    from docket.interfaces.cli.commands.setup import Piece, Readiness

    ready = Readiness(endpoint=Piece("model endpoint", True, "", ""))
    monkeypatch.setattr("docket.interfaces.cli.commands.run.readiness", lambda: ready)


class _CrashOnRoleRunner:
    """Simulates a hard crash (process death) partway through a role's hop: records the role
    before raising, matching reality -- the request went out, but the process died before a
    result (and a persisted terminal status) came back."""

    def __init__(self, crash_role: str):
        self.calls: list[str] = []
        self.crash_role = crash_role

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        if role == self.crash_role:
            raise RuntimeError("simulated crash")
        return _rd.TurnResult(True, f"done by {agent_id}", 0.01, {"output": "x"})


class _VerdictAwareRunner:
    """Like FakeDriver, but Reviewer hops carry a real verdict so a
    full pod can finish `done` (the Reviewer's APPROVE/REQUEST-CHANGES first
    line is parsed the same way the Reviewer's APPROVE is)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int, dict[str, str] | None]] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        self.calls.append((agent_id, session_key, message, timeout, env))
        role = agent_id.rsplit("-", 1)[-1]
        output = "APPROVE - looks good" if role == "reviewer" else f"done by {agent_id}"
        return _rd.TurnResult(True, output, 0.01, {"output": output})


def _alien_step_spec() -> _pipeline.PipelineSpec:
    """Lead, then a step targeting a member id that belongs to no real pod -- deterministically
    trips the cross-pod refusal in ``execute_unit`` mid-task, after the lead hop persists."""
    return _pipeline.PipelineSpec(
        name="alien-step",
        steps=[
            _step.Step(id="lead", role="lead"),
            _step.Step(id="alien", agent="ghost-lead"),
        ],
    )


class TestSweepDoesNotStallOnAParkedPod:
    """ADR 0016 SS2: an unset ``approvalMode`` resolves to "park" under the sweep, so one
    pod's gated call no longer stalls every other dispatchable pod in the same call."""

    def test_sweep_parks_one_pod_and_still_finishes_another_in_the_same_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.governance.policy import install_policies
        from docket.interfaces.http import server as _server
        from docket.interfaces.http import sweeps as _sweeps

        # Deliberately slow -- if the sweep's "park" default did not fire, alpha's
        # `wait`-mode ask would block on nobody for up to this long, and beta's
        # task would not even start within this test's own timeout.
        # The scripted turns below are one shared queue consumed in pod order, so the
        # sweep runs serially here; concurrency is TestSweepWorkers' subject.
        home = tmp_path / ".docket"
        (home / "state" / "workspaces" / "projects").mkdir(parents=True)
        (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with (
            use_home(Home(home)),
            use_home(
                dataclasses.replace(
                    current_home(), tool_approval_timeout=60, dispatch_sweep_workers=1
                )
            ),
        ):
            record_isolation_off(home)
            build_pod("alpha", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/alpha")
            build_pod("beta", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/beta")
            install_policies()

            # dispatchable_pods() walks fleet.json's own agent order -- alpha's Lead
            # was registered first, so the sweep reaches alpha before beta and these
            # four scripted turns are consumed in this exact order.
            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            backend = _ScriptedBackend(
                [
                    _final_response("alpha lead plan"),
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                    _final_response("beta lead plan"),
                    _final_response("beta implementer done"),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("alpha", "gated work", channel="cli")
            _queue.enqueue_task_once("beta", "plain work", channel="cli")

            started = time.monotonic()
            _server._run_sweeps(True)
            assert _sweeps._drain_sweeps(timeout=30)
            elapsed = time.monotonic() - started

            assert elapsed < 5.0, f"took {elapsed:.2f}s -- alpha parking must not block beta"
            alpha_task = TaskRepository.for_pod("alpha").list()[0]
            beta_task = TaskRepository.for_pod("beta").list()[0]
            assert alpha_task.status == "waiting_approval", alpha_task.reason
            assert beta_task.status == "done", beta_task.reason


class TestCrashRecovery:
    def test_resume_skips_already_completed_hops(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=_pod.pod.FULL_POD_ROLES):
            _queue.enqueue_task_once("demo", "Resume me", channel="cli")

            crasher = _CrashOnRoleRunner(crash_role="reviewer")
            with pytest.raises(RuntimeError, match="simulated crash"):
                _sweep.dispatch_pod("demo", runner=crasher)
            # lead + implementer completed (and were persisted incrementally);
            # reviewer's request went out but the process "died" before a result.
            assert crasher.calls == ["lead", "implementer", "reviewer"]

            tasks = TaskRepository.for_pod("demo").list()
            assert len(tasks) == 1
            assert tasks[0].status == "running"  # never got to a terminal status
            assert [h.role for h in tasks[0].hops] == ["lead", "implementer"]

            # Force the claim stale — simulate enough wall-clock time having passed.
            with claims_gone_stale():
                resumer = _VerdictAwareRunner()
                results = _sweep.dispatch_pod("demo", runner=resumer, resume=True)
                assert len(results) == 1
                assert results[0].status == "done"
                # Only the hops that hadn't completed before the crash run again —
                # lead and implementer are NOT re-invoked.
                roles_called = [c[0].rsplit("-", 1)[-1] for c in resumer.calls]
                assert roles_called == ["reviewer"]

                final = TaskRepository.for_pod("demo").list()[0]
                assert final.status == "done"
                assert [h.role for h in final.hops] == [
                    "lead",
                    "implementer",
                    "reviewer",
                ]
                assert final.claim_pid is None

    def test_stale_claim_without_resume_is_not_reclaimed(self, tmp_path: Path) -> None:
        """The default (non-resume) dispatch never auto-retries a crashed task."""
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Crash me", channel="cli")
            crasher = _CrashOnRoleRunner(crash_role="implementer")
            with pytest.raises(RuntimeError):
                _sweep.dispatch_pod("demo", runner=crasher)

            with claims_gone_stale():
                runner = FakeDriver()
                results = _sweep.dispatch_pod("demo", runner=runner)  # resume defaults to False
                assert results == []  # nothing eligible without --resume
                assert runner.calls == []
                task = TaskRepository.for_pod("demo").list()[0]
                assert task.status == "failed"
                assert task.failure_kind == "stale_claim"

    def test_stale_claim_sweep_emits_trace_event(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            _queue.enqueue_task_once("demo", "Crash me too", channel="cli")
            crasher = _CrashOnRoleRunner(crash_role="implementer")
            with pytest.raises(RuntimeError):
                _sweep.dispatch_pod("demo", runner=crasher)

            with claims_gone_stale():
                _sweep.dispatch_pod("demo", runner=FakeDriver())

                trace_files = list((oc_dir / "state" / "traces" / "demo").glob("*.jsonl"))
                events = [
                    json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
                ]
                assert any(e["event_type"] == "stale_claim" for e in events)


class TestDeterministicRefusalSettlesTheClaim:
    """A DispatchError reached mid-task (after an earlier hop already persisted) fails that one
    task and settles its claim instead of raising out of ``dispatch_pod`` -- see
    pod-dispatch.spec.md, "Deterministic refusal inside a claimed task"."""

    def test_refusal_fails_the_task_not_the_whole_dispatch(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "task one", channel="cli")
            _queue.enqueue_task_once("demo", "task two", channel="cli")

            results = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_alien_step_spec())

            # Both queued tasks are attempted — the first task's deterministic refusal does not
            # abort the dispatch_pod loop before the second is even claimed.
            assert len(results) == 2
            assert [r.status for r in results] == ["failed", "failed"]
            assert all("refusing cross-pod dispatch" in r.reason for r in results)

            tasks = TaskRepository.for_pod("demo").list()
            assert [t.status for t in tasks] == ["failed", "failed"]
            assert all(t.claim_pid is None for t in tasks)  # settled, not orphaned
            assert all(t.failure_kind == "dispatch_refused" for t in tasks)
            assert [h.role for h in tasks[0].hops] == ["lead"]

    def test_resume_reclaims_a_dispatch_refused_task_once_the_pipeline_is_fixed(
        self, tmp_path: Path
    ) -> None:
        """No CLAIM_STALE_TIMEOUT override and no decoy task needed — unlike a swept crash, a
        settled deterministic refusal is immediately resumable once its cause is fixed."""
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "fix me", channel="cli")

            first = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_alien_step_spec())
            assert first[0].status == "failed"
            assert TaskRepository.for_pod("demo").list()[0].failure_kind == "dispatch_refused"

            fixed_spec = _pipeline.PipelineSpec(
                name="fixed",
                steps=[
                    _step.Step(id="lead", role="lead"),
                    _step.Step(id="implementer", role="implementer"),
                ],
            )
            resumer = FakeDriver()

            second = _sweep.dispatch_pod("demo", runner=resumer, resume=True, spec=fixed_spec)

            assert len(second) == 1
            assert second[0].status == "done"
            # The lead hop persisted before the refusal is not re-run.
            assert [c[0].rsplit("-", 1)[-1] for c in resumer.calls] == ["implementer"]
            final = TaskRepository.for_pod("demo").list()[0]
            assert final.status == "done"
            assert [h.role for h in final.hops] == ["lead", "implementer"]
            assert final.failure_kind is None

    @pytest.mark.parametrize("posture", ["network", "isolation"])
    def test_a_refused_posture_is_one_attempt_one_audit_and_resumable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, posture: str
    ) -> None:
        with _seed_pod(tmp_path) as home:
            if posture == "network":
                _fleet.set_network_mode("none")
                action = "network.refused"
            else:
                _fleet.set_sandbox_isolation(mode="non-main")
                monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
                action = "isolation.refused"
            slept: list[float] = []
            calls: list[str] = []

            def _never(model: str) -> Any:
                calls.append(model)
                raise AssertionError("the model backend must not be reached")

            monkeypatch.setattr(_dr, "default_driver", lambda: DocketDriver(backend_factory=_never))
            _queue.enqueue_task_once("demo", "refused posture", channel="cli")

            results = _sweep.dispatch_pod("demo", sleep=slept.append)

            assert [r.status for r in results] == ["failed"]
            task = TaskRepository.for_pod("demo").list()[0]
            assert task.status == "failed"
            assert task.failure_kind == "dispatch_refused"
            assert not calls
            assert slept == []
            assert len([e for e in _audit.read_audit() if e["action"] == action]) == 1

            if posture == "network":
                _fleet.set_network_mode("open")
            else:
                record_isolation_off(home)
            backend = _ScriptedBackend(
                [_final_response("lead plan"), _final_response("implementer done")]
            )
            monkeypatch.setattr(
                _dr, "default_driver", lambda: DocketDriver(backend_factory=lambda model: backend)
            )

            resumed = _sweep.dispatch_pod("demo", resume=True)

            assert [r.status for r in resumed] == ["done"]

    def test_a_crash_mid_hop_still_leaves_the_task_running_for_the_stale_sweep(
        self, tmp_path: Path
    ) -> None:
        """Pin the non-goal: only a deterministic DispatchError is caught. An actual crash (any
        other exception) is unaffected — the task stays 'running', recoverable only through the
        existing stale-claim sweep, never settled outright."""
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "crash me", channel="cli")
            crasher = _CrashOnRoleRunner(crash_role="implementer")

            with pytest.raises(RuntimeError, match="simulated crash"):
                _sweep.dispatch_pod("demo", runner=crasher)

            task = TaskRepository.for_pod("demo").list()[0]
            assert task.status == "running"
            assert task.claim_pid


class TestResumeGateCountsRunningTasksTowardRecovery:
    """``docket run --resume``'s "anything to do?" gate must not require a decoy
    pending task just to let ``dispatch_pod``'s own stale-claim sweep run over an orphaned
    `running` task — see pod-dispatch.spec.md, "Claiming"."""

    def test_resume_recovers_a_crashed_task_with_no_pending_task_queued(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "crash me", channel="cli")
            crasher = _CrashOnRoleRunner(crash_role="implementer")
            with pytest.raises(RuntimeError):
                _sweep.dispatch_pod("demo", runner=crasher)

            # Orphaned: `running`, no decoy `pending` task exists, and it hasn't been swept yet
            # (the sweep only runs at the top of a `dispatch_pod` call).
            tasks_before = TaskRepository.for_pod("demo").list()
            assert tasks_before[0].status == "running"
            assert not any(t.status == "pending" for t in tasks_before)

            with claims_gone_stale():
                monkeypatch.setattr(_dr, "default_driver", lambda: FakeDriver())

                _endpoint_ready(monkeypatch)
                result = CliRunner().invoke(app, ["run", "--pod", "demo", "--resume"])

                assert "No pending tasks" not in result.output
                assert TaskRepository.for_pod("demo").list()[0].status == "done"

    def test_resume_still_warns_with_nothing_pending_resumable_or_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        with _seed_pod(tmp_path):
            _endpoint_ready(monkeypatch)
            result = CliRunner().invoke(app, ["run", "--pod", "demo", "--resume"])

            assert "No pending tasks" in result.output


class TestBlockedStaysBlocked:
    def test_blocked_task_survives_repeated_dispatch_pod_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Too expensive", channel="cli")
            monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_steps_c, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_executor, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_usage, "pod_recorded_cost", lambda _p: 5.0)
            monkeypatch.setattr(_pre_hop, "pod_recorded_cost", lambda _p: 5.0)
            runner = FakeDriver()

            first = _sweep.dispatch_pod("demo", runner=runner)
            assert first[0].status == "blocked"
            # Once blocked, a `blocked` task is not even eligible to claim again —
            # repeated dispatch_pod calls find nothing to do (never re-attempted,
            # let alone re-attempted forever).
            for _ in range(3):
                assert _sweep.dispatch_pod("demo", runner=runner) == []
            assert runner.calls == []  # never actually dispatched
            assert TaskRepository.for_pod("demo").list()[0].status == "blocked"

    def test_retry_task_unblocks_a_single_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "Too expensive", channel="cli")[0]
            monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_steps_c, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_executor, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_usage, "pod_recorded_cost", lambda _p: 5.0)
            monkeypatch.setattr(_pre_hop, "pod_recorded_cost", lambda _p: 5.0)
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            assert TaskRepository.for_pod("demo").list()[0].status == "blocked"

            assert _lifecycle.retry_task("demo", task.id) is True
            assert TaskRepository.for_pod("demo").list()[0].status == "pending"
            # Retrying a task that isn't blocked is a no-op.
            assert _lifecycle.retry_task("demo", task.id) is False
            assert _lifecycle.retry_task("demo", "no-such-task") is False

    def test_unblock_pod_unblocks_every_blocked_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "One", channel="cli")
            _queue.enqueue_task_once("demo", "Two", channel="cli")
            monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_steps_c, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_executor, "pod_budget", lambda _p: 1.0)
            monkeypatch.setattr(_usage, "pod_recorded_cost", lambda _p: 5.0)
            monkeypatch.setattr(_pre_hop, "pod_recorded_cost", lambda _p: 5.0)
            lead_id = _pod.pod.member_id("demo", "lead")

            _sweep.dispatch_pod("demo", runner=FakeDriver())
            # The first cap breach also pauses the Lead, so a second dispatch
            # call is refused outright at claim time — task Two is never even
            # attempted (still "pending"). Clear the pause (what a real
            # `docket run --resume`/`--budget` would do) so the second
            # call can claim and block it too, exercising the same
            # `unblock_pod` contract the original test covered.
            _fleet.meta_set(lead_id, "paused", False)
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            tasks = TaskRepository.for_pod("demo").list()
            assert len(tasks) == 2
            assert all(t.status == "blocked" for t in tasks)
            assert _AgentMeta.coerce_paused(
                _fleet.meta_get(lead_id, "paused", "")
            )  # re-paused by the second breach

            assert _lifecycle.unblock_pod("demo") == 2
            tasks = TaskRepository.for_pod("demo").list()
            assert all(t.status == "pending" for t in tasks)
            # Nothing left blocked — a second call is a no-op.
            assert _lifecycle.unblock_pod("demo") == 0


class TestRunCliPrologue:
    """The "Dispatching N pending task(s) through: <roles>" prologue must name the pod's
    own resolved pipeline, not the legacy four-role ``PIPELINE_ORDER`` filter a
    non-``software`` pod never matches past "lead"."""

    def test_research_pod_prologue_names_its_blueprint_roles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        home = tmp_path / ".docket"
        (home / "state" / "workspaces" / "projects").mkdir(parents=True)
        (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)):
            record_isolation_off(home)

            _pod.build_pod_from_blueprint("rsch", "research", location="", description="")
            _queue.enqueue_task_once("rsch", "look into it", channel="cli")
            monkeypatch.setattr(_dr, "default_driver", lambda: FakeDriver(ok=True, cost=0.0))

            _endpoint_ready(monkeypatch)
            result = CliRunner().invoke(app, ["run", "--pod", "rsch"])

            assert "through: lead → researcher → analyst → writer → reviewer" in result.output
