"""Pod dispatch: queueing a task, the pipeline driver and what each hop receives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.pods import build_pod
from tests.support.pods import seed_pod_isolation_off as _seed_pod

from docket.agent import ports as _rd
from docket.governance import secrets as _secrets
from docket.hops.application import executor as _executor
from docket.hops.application import steps as _steps_c
from docket.hops.application import sweep as _sweep
from docket.hops.application import usage as _usage
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import current_home
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import task as _task
from docket.tasks.domain.parts import Worktree
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import resources as _res
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.application.queue"


class TestTaskAddCliBoundary:
    def test_quoted_task_text_reaches_the_queue_losslessly(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        with _seed_pod(tmp_path):
            description = "create a file called test.md"

            result = CliRunner().invoke(app, ["task", "add", description, "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert [task.description for task in TaskRepository.for_pod("demo").list()] == [
                description
            ]

    @pytest.mark.parametrize(
        ("args", "code"),
        [
            (["task", "add", "--pod", "demo"], 2),
            (["task", "add", "", "--pod", "demo"], 1),
            (["task", "add", "task", "--priority", "--pod", "demo"], 2),
            (["task", "add", "task", "--priority", "urgent", "--pod", "demo"], 2),
        ],
    )
    def test_invalid_input_does_not_enqueue(
        self, tmp_path: Path, args: list[str], code: int
    ) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        with _seed_pod(tmp_path):
            result = CliRunner().invoke(app, args)

            assert result.exit_code == code
            assert TaskRepository.for_pod("demo").list() == []

    def test_length_limit_applies_to_the_text(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        with _seed_pod(tmp_path):
            result = CliRunner().invoke(app, ["task", "add", "a" * 501, "--pod", "demo"])

            assert result.exit_code == 1
            assert "501 chars" in result.output
            assert TaskRepository.for_pod("demo").list() == []


class TestEnqueueTaskPreBrief:
    def test_a_valid_brief_folds_into_the_description_and_is_stored_on_the_task(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once(
                "demo",
                "add rate limiting",
                brief={"objective": "add rate limiting", "acceptance": ["429 after 100 req/min"]},
                channel="cli",
            )[0]

            assert "## Pre-brief" in task.description
            assert "429 after 100 req/min" in task.description
            assert task.brief.objective == "add rate limiting"
            stored = TaskRepository.for_pod("demo").list()[0]
            assert stored.brief.objective == "add rate limiting"

    def test_an_invalid_brief_raises_and_persists_nothing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            try:
                _queue.enqueue_task_once(
                    "demo", "add rate limiting", brief={"objective": ""}, channel="cli"
                )
            except _task.DispatchError:
                pass
            else:
                raise AssertionError("an empty objective should have raised DispatchError")
            assert TaskRepository.for_pod("demo").list() == []

    def test_no_brief_leaves_the_description_and_task_shape_unchanged(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "plain task, no brief", channel="cli")[0]

            assert task.description == "plain task, no brief"
            assert "brief" not in task


class TestPipeline:
    def test_lean_pod_runs_lead_then_implementer(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Fix the bug", channel="cli")
            runner = FakeDriver()
            results = _sweep.dispatch_pod("demo", runner=runner)
            assert len(results) == 1
            res = results[0]
            assert res.status == "done"
            assert [r for r, _ in [(c[0], c) for c in runner.calls]] == [
                "demo-lead",
                "demo-implementer",
            ]
            # Each hop owns a per-step history in its member namespace.
            assert runner.calls[0][1].startswith("agent:demo-lead:demo:task:")
            assert runner.calls[0][1].endswith(":step:lead")
            assert runner.calls[1][1].startswith("agent:demo-implementer:demo:task:")
            assert runner.calls[1][1].endswith(":step:implementer")

    def test_every_non_lead_hop_receives_the_task_worktree(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=_pod.pod.FULL_POD_ROLES):
            worktree = current_home().projects_dir / "demo-implementer" / "tasks" / "wt1"
            worktree.mkdir(parents=True)
            calls: list[tuple[str, str, dict[str, str] | None]] = []

            def runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                calls.append((agent_id, message, env))
                output = "APPROVE" if agent_id.endswith("-reviewer") else "PASS"
                if agent_id.endswith(("-lead", "-implementer")):
                    output = "done"
                return _rd.TurnResult(True, output, 0.0, {})

            task = TaskRecord(
                id="wt1",
                description="work",
                worktree=Worktree(dir=str(worktree), branch="docket/demo/wt1", base_commit="abc"),
            )
            result = _executor.dispatch_task("demo", task, runner=runner)

            assert result.status == "done", result.reason
            by_agent = {agent_id: (message, env) for agent_id, message, env in calls}
            lead_message, lead_env = by_agent["demo-lead"]
            assert "checkout" not in lead_message
            assert lead_env is None
            impl_message, impl_env = by_agent["demo-implementer"]
            assert f"Working directory: {worktree}" in impl_message
            assert "origin codebase" not in impl_message
            assert impl_env is not None
            assert impl_env[_rd.PIPELINE_WORKTREE_ENV] == str(worktree)
            downstream = [call for call in calls if call[0].endswith(("-reviewer", "-tester"))]
            assert len(downstream) == 2
            for _agent_id, message, env in downstream:
                assert f"Working directory: {worktree}" in message
                assert "must still end with the verdict marker as its LAST line" in message
                assert env is not None
                assert env[_rd.PIPELINE_WORKTREE_ENV] == str(worktree)
                assert set(env) == {_rd.PIPELINE_WORKTREE_ENV, _rd.DOCKET_VERDICT_VALUES}

    def test_default_approval_mode_leaves_every_hop_env_unchanged(self, tmp_path: Path) -> None:
        """Pin: with no `approvalMode` configured, DOCKET_APPROVAL_MODE never reaches a hop's
        env -- today's "wait" behavior is byte-identical."""
        with _seed_pod(tmp_path):
            calls: list[tuple[str, dict[str, str] | None]] = []

            def runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                calls.append((agent_id, env))
                return _rd.TurnResult(True, "done", 0.0, {})

            task = TaskRecord(id="am1", description="work")
            result = _executor.dispatch_task("demo", task, runner=runner)

            assert result.status == "done", result.reason
            assert len(calls) == 2
            assert all(
                env is None or _rd.DOCKET_APPROVAL_MODE not in env for _agent_id, env in calls
            )

    def test_approval_timeout_threads_into_every_hop_env(self, tmp_path: Path) -> None:
        """A caller's approval wait bound reaches every hop's env, and is absent when unset."""
        with _seed_pod(tmp_path):
            calls: list[dict[str, str] | None] = []

            def runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                calls.append(env)
                return _rd.TurnResult(True, "done", 0.0, {})

            task = TaskRecord(id="at1", description="work")
            result = _executor.dispatch_task("demo", task, runner=runner, approval_timeout=9)

            assert result.status == "done", result.reason
            assert len(calls) == 2
            assert all(env is not None and env[_rd.DOCKET_APPROVAL_TIMEOUT] == "9" for env in calls)
            calls.clear()
            again = TaskRecord(id="at2", description="work")
            _executor.dispatch_task("demo", again, runner=runner)
            assert all(env is None or _rd.DOCKET_APPROVAL_TIMEOUT not in env for env in calls)

    def test_refuse_approval_mode_threads_into_every_hop_env(self, tmp_path: Path) -> None:
        """The pod's `approvalMode: refuse` setting reaches every hop's tool env the same
        internal-coordinate way PIPELINE_WORKTREE_ENV does -- popped by DocketDriver before
        ToolContext ever sees it."""
        with _seed_pod(tmp_path):
            _fleet.meta_set("demo-lead", "approvalMode", "refuse")
            calls: list[tuple[str, dict[str, str] | None]] = []

            def runner(
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                calls.append((agent_id, env))
                return _rd.TurnResult(True, "done", 0.0, {})

            task = TaskRecord(id="am2", description="work")
            result = _executor.dispatch_task("demo", task, runner=runner)

            assert result.status == "done", result.reason
            assert len(calls) == 2
            for agent_id, env in calls:
                assert env is not None
                assert env[_rd.DOCKET_APPROVAL_MODE] == "refuse"
                if agent_id.endswith("-lead"):
                    assert env == {_rd.DOCKET_APPROVAL_MODE: "refuse"}
                else:
                    # The Implementer's port-range env (real DOCKET_PORT_*/
                    # DOCKET_SCRATCH_DIR vars from provisioning) is merged with,
                    # not replaced by, the approval-mode coordinate.
                    assert "DOCKET_PORT_BASE" in env

    def test_task_persisted_with_status_and_hops(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver(cost=0.05))
            tasks = TaskRepository.for_pod("demo").list()
            assert tasks[0].status == "done"
            assert [h.role for h in tasks[0].hops] == ["lead", "implementer"]
            assert tasks[0].cost_usd == pytest.approx(0.10)

    def test_traces_written_per_hop(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            _queue.enqueue_task_once("demo", "Trace me", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            assert len(trace_files) == 1
            events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
            types = [e["event_type"] for e in events]
            assert "session_start" in types
            assert types.count("tool_call") == 2
            # 3, not 2 — lead's turn, implementer's turn, plus a third
            # `tool_result` for the implementer's mechanical gate itself (no
            # `verifyCmd` set on this seeded pod, so it is the "skipped" outcome,
            # traced for parity with the "passed" case — see
            # test_verify_gate.py's TestDispatchVerifyGate for both outcomes).
            assert types.count("tool_result") == 3
            assert "session_end" in types

    def test_failed_hop_stops_pipeline(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=_pod.pod.FULL_POD_ROLES):
            _queue.enqueue_task_once("demo", "Break early", channel="cli")
            runner = FakeDriver(fail_role="implementer")
            res = _sweep.dispatch_pod("demo", runner=runner)[0]
            assert res.status == "failed"
            # Lead + Implementer ran; Reviewer + Tester never got dispatched.
            roles_called = [c[0].rsplit("-", 1)[-1] for c in runner.calls]
            assert roles_called == ["lead", "implementer"]

    def test_typed_run_cancellation_cancels_task_and_stops_pipeline(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "Stop cleanly", channel="cli")[0]
            calls = 0

            def runner(*_args: object, **_kwargs: object) -> _rd.TurnResult:
                nonlocal calls
                calls += 1
                return _rd.TurnResult(
                    False,
                    "",
                    0.0,
                    {},
                    "run cancellation requested",
                    failure_kind="run_cancelled",
                )

            result = _sweep.dispatch_pod("demo", runner=runner)[0]

            assert calls == 1
            assert result.task_id == task.id
            assert result.status == "cancelled"
            persisted = TaskRepository.for_pod("demo").list()[0]
            assert persisted.status == "cancelled"
            assert persisted.completed_at

    def test_budget_blocks_before_first_hop(
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
            res = _sweep.dispatch_pod("demo", runner=runner)[0]
            assert res.status == "blocked"
            assert runner.calls == []  # nothing dispatched
            # A blocked task stays blocked (it is never silently rewritten back
            # to pending) — it only re-enters pending via unblock_pod/retry_task.
            assert TaskRepository.for_pod("demo").list()[0].status == "blocked"

    def test_no_cross_pod_dispatch(self, tmp_path: Path) -> None:
        # Two pods exist; dispatching 'demo' must never touch 'other'.
        with _seed_pod(tmp_path, project="demo") as oc_dir:
            build_pod("other", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/other")
            _queue.enqueue_task_once("demo", "Stay in my lane", channel="cli")
            runner = FakeDriver()
            _sweep.dispatch_pod("demo", runner=runner)
            assert runner.calls, "expected dispatch to run"
            assert all(c[0].startswith("demo-") for c in runner.calls)
            assert (oc_dir / "traces" / "other").exists() is False

    def test_no_lead_raises(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            # Remove the lead from the fleet registry → no dispatchable pod.
            _fleet.remove_agent("demo-lead")
            with pytest.raises(_task.DispatchError):
                _sweep.dispatch_pod("demo", runner=FakeDriver())


class TestHopEvidence:
    """A mechanical gate's real command, exit code, duration, and redacted output tail are
    persisted on the hop record itself (`HopResult.verify`), not just traced on failure."""

    def test_passing_verify_persists_real_evidence(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
            _fleet.meta_set("demo-implementer", "verifyCmd", "echo ok")
            _queue.enqueue_task_once("demo", "Ship it", channel="cli")

            res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

            assert res.status == "done"
            persisted = TaskRepository.for_pod("demo").list()[0]
            implementer_rec = next(h for h in persisted.hops if h.role == "implementer")
            verify = implementer_rec.verify
            assert verify is not None
            assert verify["cmd"] == "echo ok"
            assert verify["exitCode"] == 0
            assert "ok" in verify["outputTail"]
            assert verify["durationS"] >= 0

    def test_failing_verify_persists_redacted_evidence_without_leaking_a_secret(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
            secret_value = "zzqx-unleakable-canary-9000"
            _secrets.save_secrets({"LEAKY_KEY": secret_value})
            _fleet.meta_set("demo-implementer", "verifyCmd", f"echo {secret_value}; exit 1")
            _queue.enqueue_task_once("demo", "Ship it", channel="cli")

            res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

            assert res.status == "failed"
            persisted = TaskRepository.for_pod("demo").list()[0]
            implementer_rec = next(h for h in persisted.hops if h.role == "implementer")
            verify = implementer_rec.verify
            assert verify is not None
            assert verify["exitCode"] == 1
            # The genuine canary: the stored secret's real value never survives into the
            # persisted record, even though the verify command echoed it verbatim.
            assert secret_value not in verify["outputTail"]
            assert "[REDACTED]" in verify["outputTail"]

    def test_no_verify_cmd_leaves_verify_unset(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "no verify configured", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            persisted = TaskRepository.for_pod("demo").list()[0]
            implementer_rec = next(h for h in persisted.hops if h.role == "implementer")
            assert implementer_rec.verify is None


class TestHopEnvInjection:
    """The pod's allocated resources reach the implementer subprocess's
    actual env, not just TOOLS.md prose."""

    def test_hop_env_none_for_lead(self) -> None:
        assert _record.hop_env("demo-lead", "lead") is None

    def test_hop_env_none_for_reviewer_and_tester(self) -> None:
        assert _record.hop_env("demo-reviewer", "reviewer") is None
        assert _record.hop_env("demo-tester", "tester") is None

    def test_hop_env_none_for_implementer_without_allocation(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            # build_pod always allocates ports for an implementer; simulate a member
            # with no allocation by clearing the meta fields directly.
            path = current_home().meta_path("demo-implementer")
            raw = json.loads(path.read_text())
            raw.pop("portRangeStart", None)
            raw.pop("portRangeCount", None)
            raw.pop("scratchDir", None)
            path.write_text(json.dumps(raw))
            assert _record.hop_env("demo-implementer", "implementer") is None

    def test_hop_env_set_for_implementer_with_allocation(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            env = _record.hop_env("demo-implementer", "implementer")
            assert env is not None
            assert env["DOCKET_PORT_BASE"] == str(_res.PORT_BASE)
            assert env["DOCKET_PORT_COUNT"] == str(_res.PORT_RANGE_SIZE)
            assert env["DOCKET_SCRATCH_DIR"]

    def test_dispatch_pod_env_only_overridden_on_implementer_hop(self, tmp_path: Path) -> None:
        """Integration: dispatch_pod passes env=<dict> to the implementer hop's
        runner call and env=None to the lead hop — the acceptance gate end to end."""
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "Use my env", channel="cli")
            runner = FakeDriver()
            _sweep.dispatch_pod("demo", runner=runner)
            by_role = {c[0].rsplit("-", 1)[-1]: c[4] for c in runner.calls}
            assert by_role["lead"] is None
            impl_env = by_role["implementer"]
            assert impl_env is not None
            assert impl_env["DOCKET_PORT_BASE"] == str(_res.PORT_BASE)
            assert impl_env["DOCKET_PORT_COUNT"] == str(_res.PORT_RANGE_SIZE)
            assert impl_env["DOCKET_SCRATCH_DIR"]

    def test_dispatch_pod_no_env_override_for_implementer_without_allocation(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            path = current_home().meta_path("demo-implementer")
            raw = json.loads(path.read_text())
            raw.pop("portRangeStart", None)
            raw.pop("portRangeCount", None)
            raw.pop("scratchDir", None)
            path.write_text(json.dumps(raw))
            _queue.enqueue_task_once("demo", "No allocation here", channel="cli")
            runner = FakeDriver()
            _sweep.dispatch_pod("demo", runner=runner)
            by_role = {c[0].rsplit("-", 1)[-1]: c[4] for c in runner.calls}
            assert by_role["implementer"] is None
