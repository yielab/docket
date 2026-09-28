"""Real pod dispatch — the pipeline driver (hermetic).

``core.dispatch`` is exercised two ways: with an injected runner (fast, deterministic) for
pipeline semantics (hop order, budget gating, failure-stops, no-cross-pod), and end to end
(``TestEndToEnd``) with no injected runner -- a real pod-dispatch hop executes through the real
production ``DocketDriver``, with only its `ChatBackend` scripted.

Also covers the task-state-machine suites: ``TestConcurrentDispatch`` (the thread-race
regression this exists to close), ``TestCrashRecovery`` (stale-claim sweep + resume-from-last-
hop), ``TestBlockedStaysBlocked`` (kills a blocked-to-pending auto-retry), and
``TestLegacyQueueLoads`` (a legacy TASK_LIST.json with none of the newer fields still dispatches).
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _pod
from docket.core import answers as _answers
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import operator_contract as _oc
from docket.core import pipeline as _pipeline
from docket.core import resources as _res
from docket.core import runtime_driver as _rd
from docket.core import secrets as _secrets
from docket.core import session as _session
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.core"

# ── hermetic environment (mirrors test_pod_provisioning) ─────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] = _pod.pod.DEFAULT_POD_ROLES,
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod(project, roles, codebase=f"/src/{project}")
    return home


# ── public delegation boundary ──────────────────────────────────────────────────


class TestDelegateCliBoundary:
    def test_quoted_and_split_task_text_reach_the_queue_losslessly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        _seed_pod(tmp_path, monkeypatch)
        runner = CliRunner()
        description = "create a file called test.md"

        quoted = runner.invoke(app, ["pod", "demo", "delegate", description])
        split = runner.invoke(app, ["pod", "demo", "delegate", *description.split()])

        assert quoted.exit_code == 0, quoted.output
        assert split.exit_code == 0, split.output
        assert [task["description"] for task in _dispatch.read_tasks("demo")] == [
            description,
            description,
        ]

    @pytest.mark.parametrize(
        "args",
        [
            ["pod", "demo", "delegate"],
            ["pod", "demo", "delegate", ""],
            ["pod", "demo", "delegate", "task", "--priority"],
            ["pod", "demo", "delegate", "task", "--priority", "urgent"],
        ],
    )
    def test_invalid_input_does_not_enqueue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        _seed_pod(tmp_path, monkeypatch)

        result = CliRunner().invoke(app, args)

        assert result.exit_code == 1
        assert _dispatch.read_tasks("demo") == []

    def test_length_limit_applies_to_reconstructed_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        _seed_pod(tmp_path, monkeypatch)

        result = CliRunner().invoke(
            app,
            ["pod", "demo", "delegate", "a" * 250, "b" * 250],
        )

        assert result.exit_code == 1
        assert "501 chars" in result.output
        assert _dispatch.read_tasks("demo") == []


class TestEnqueueTaskPreBrief:
    def test_a_valid_brief_folds_into_the_description_and_is_stored_on_the_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        task = _dispatch.enqueue_task(
            "demo",
            "add rate limiting",
            brief={"objective": "add rate limiting", "acceptance": ["429 after 100 req/min"]},
        )

        assert "## Pre-brief" in task["description"]
        assert "429 after 100 req/min" in task["description"]
        assert task["brief"]["objective"] == "add rate limiting"
        stored = _dispatch.read_tasks("demo")[0]
        assert stored["brief"]["objective"] == "add rate limiting"

    def test_an_invalid_brief_raises_and_persists_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        try:
            _dispatch.enqueue_task("demo", "add rate limiting", brief={"objective": ""})
        except _dispatch.DispatchError:
            pass
        else:
            raise AssertionError("an empty objective should have raised DispatchError")
        assert _dispatch.read_tasks("demo") == []

    def test_no_brief_leaves_the_description_and_task_shape_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        task = _dispatch.enqueue_task("demo", "plain task, no brief")

        assert task["description"] == "plain task, no brief"
        assert "brief" not in task


# The pipeline-semantics tests below inject `FakeDriver` (the one
# RuntimeDriver test double, tests/fakes.py) as dispatch.py's Runner —
# it is callable with agent_run's exact signature, so it drops in unchanged
# wherever a `runner=` kwarg is passed.


# There is no daemon-facing driver, no subprocess-backed `agent_run`, and no
# daemon JSON shape to shell out to any more. The equivalent coverage lives
# in `edges/adapters/llm.py`'s `OpenAIChatClient` (response parsing, see
# test_llm_port.py) and `edges/adapters/docket_runtime.py`'s
# `DocketDriver` (env passed through to a tool call, see
# test_docket_driver.py's `test_env_kwarg_reaches_a_tool_call` and
# `test_on_spawn_is_accepted_and_ignored`).


# ── pipeline driver (injected runner) ────────────────────────────────────────────


class TestPipeline:
    def test_lean_pod_runs_lead_then_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Fix the bug")
        runner = FakeDriver()
        results = _dispatch.dispatch_pod("demo", runner=runner)
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

    def test_downstream_hops_receive_implementer_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=_pod.pod.FULL_POD_ROLES)
        worktree = tmp_path / "implementer-worktree"
        worktree.mkdir()
        _fleet.meta_set("demo-implementer", "worktreeDir", str(worktree))
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

        task: dict[str, Any] = {"id": "wt1", "description": "work", "status": "pending"}
        result = _dispatch.dispatch_task("demo", task, runner=runner)

        assert result.status == "done", result.reason
        downstream = [call for call in calls if call[0].endswith(("-reviewer", "-tester"))]
        assert len(downstream) == 2
        for _agent_id, message, env in downstream:
            assert (
                f"Effective implementation checkout for this downstream hop: `{worktree}`"
                in message
            )
            assert (
                "one distinct recognized verdict marker at the start of a complete line" in message
            )
            assert env == {_rd.PIPELINE_WORKTREE_ENV: str(worktree)}

    def test_default_approval_mode_leaves_every_hop_env_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin: with no `approvalMode` configured, DOCKET_APPROVAL_MODE never reaches a hop's
        env -- today's "wait" behavior is byte-identical."""
        _seed_pod(tmp_path, monkeypatch)
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

        task: dict[str, Any] = {"id": "am1", "description": "work", "status": "pending"}
        result = _dispatch.dispatch_task("demo", task, runner=runner)

        assert result.status == "done", result.reason
        assert len(calls) == 2
        assert all(env is None or _rd.DOCKET_APPROVAL_MODE not in env for _agent_id, env in calls)

    def test_refuse_approval_mode_threads_into_every_hop_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pod's `approvalMode: refuse` setting reaches every hop's tool env the same
        internal-coordinate way PIPELINE_WORKTREE_ENV does -- popped by DocketDriver before
        ToolContext ever sees it."""
        _seed_pod(tmp_path, monkeypatch)
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

        task: dict[str, Any] = {"id": "am2", "description": "work", "status": "pending"}
        result = _dispatch.dispatch_task("demo", task, runner=runner)

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

    def test_task_persisted_with_status_and_hops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Ship it")
        _dispatch.dispatch_pod("demo", runner=FakeDriver(cost=0.05))
        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"
        assert [h["role"] for h in tasks[0]["hops"]] == ["lead", "implementer"]
        assert tasks[0]["costUsd"] == pytest.approx(0.10)

    def test_traces_written_per_hop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Trace me")
        _dispatch.dispatch_pod("demo", runner=FakeDriver())
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

    def test_failed_hop_stops_pipeline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=_pod.pod.FULL_POD_ROLES)
        _dispatch.enqueue_task("demo", "Break early")
        runner = FakeDriver(fail_role="implementer")
        res = _dispatch.dispatch_pod("demo", runner=runner)[0]
        assert res.status == "failed"
        # Lead + Implementer ran; Reviewer + Tester never got dispatched.
        roles_called = [c[0].rsplit("-", 1)[-1] for c in runner.calls]
        assert roles_called == ["lead", "implementer"]

    def test_typed_run_cancellation_cancels_task_and_stops_pipeline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "Stop cleanly")
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

        result = _dispatch.dispatch_pod("demo", runner=runner)[0]

        assert calls == 1
        assert result.task_id == task["id"]
        assert result.status == "cancelled"
        persisted = _dispatch.read_tasks("demo")[0]
        assert persisted["status"] == "cancelled"
        assert persisted["completedAt"]

    def test_budget_blocks_before_first_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
        runner = FakeDriver()
        res = _dispatch.dispatch_pod("demo", runner=runner)[0]
        assert res.status == "blocked"
        assert runner.calls == []  # nothing dispatched
        # A blocked task stays blocked (it is never silently rewritten back
        # to pending) — it only re-enters pending via unblock_pod/retry_task.
        assert _dispatch.read_tasks("demo")[0]["status"] == "blocked"

    def test_no_cross_pod_dispatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Two pods exist; dispatching 'demo' must never touch 'other'.
        oc_dir = _seed_pod(tmp_path, monkeypatch, project="demo")
        _pod.build_pod("other", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/other")
        _dispatch.enqueue_task("demo", "Stay in my lane")
        runner = FakeDriver()
        _dispatch.dispatch_pod("demo", runner=runner)
        assert runner.calls, "expected dispatch to run"
        assert all(c[0].startswith("demo-") for c in runner.calls)
        assert (oc_dir / "traces" / "other").exists() is False

    def test_no_lead_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        # Remove the lead from the fleet registry → no dispatchable pod.
        _fleet.remove_agent("demo-lead")
        with pytest.raises(_dispatch.DispatchError):
            _dispatch.dispatch_pod("demo", runner=FakeDriver())


# ── pod port range / scratch dir reach the implementer hop's real env ───────────


class TestHopEnvInjection:
    """The pod's allocated resources reach the implementer subprocess's
    actual env, not just TOOLS.md prose."""

    def test_hop_env_none_for_lead(self) -> None:
        assert _dispatch._hop_env("demo-lead", "lead") is None

    def test_hop_env_none_for_reviewer_and_tester(self) -> None:
        assert _dispatch._hop_env("demo-reviewer", "reviewer") is None
        assert _dispatch._hop_env("demo-tester", "tester") is None

    def test_hop_env_none_for_implementer_without_allocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        # build_pod always allocates ports for an implementer; simulate a member
        # with no allocation by clearing the meta fields directly.
        path = _cfg.meta_path("demo-implementer")
        raw = json.loads(path.read_text())
        raw.pop("portRangeStart", None)
        raw.pop("portRangeCount", None)
        raw.pop("scratchDir", None)
        path.write_text(json.dumps(raw))
        assert _dispatch._hop_env("demo-implementer", "implementer") is None

    def test_hop_env_set_for_implementer_with_allocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        env = _dispatch._hop_env("demo-implementer", "implementer")
        assert env is not None
        assert env["DOCKET_PORT_BASE"] == str(_res.PORT_BASE)
        assert env["DOCKET_PORT_COUNT"] == str(_res.PORT_RANGE_SIZE)
        assert env["DOCKET_SCRATCH_DIR"]

    def test_dispatch_pod_env_only_overridden_on_implementer_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Integration: dispatch_pod passes env=<dict> to the implementer hop's
        runner call and env=None to the lead hop — the acceptance gate end to end."""
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Use my env")
        runner = FakeDriver()
        _dispatch.dispatch_pod("demo", runner=runner)
        by_role = {c[0].rsplit("-", 1)[-1]: c[4] for c in runner.calls}
        assert by_role["lead"] is None
        impl_env = by_role["implementer"]
        assert impl_env is not None
        assert impl_env["DOCKET_PORT_BASE"] == str(_res.PORT_BASE)
        assert impl_env["DOCKET_PORT_COUNT"] == str(_res.PORT_RANGE_SIZE)
        assert impl_env["DOCKET_SCRATCH_DIR"]

    def test_dispatch_pod_no_env_override_for_implementer_without_allocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        path = _cfg.meta_path("demo-implementer")
        raw = json.loads(path.read_text())
        raw.pop("portRangeStart", None)
        raw.pop("portRangeCount", None)
        raw.pop("scratchDir", None)
        path.write_text(json.dumps(raw))
        _dispatch.enqueue_task("demo", "No allocation here")
        runner = FakeDriver()
        _dispatch.dispatch_pod("demo", runner=runner)
        by_role = {c[0].rsplit("-", 1)[-1]: c[4] for c in runner.calls}
        assert by_role["implementer"] is None


# ── end-to-end: driver → real agent_loop → real gated tool chokepoint ────────────
#
# No injected runner means `dispatch_pod` resolves
# `edges.adapters.docket_runtime.default_driver()`: docket's own
# `core/agent_loop.py`, dispatching every tool call through `core/tools.py`'s
# gated chokepoint. `TestEndToEnd` below proves a real dispatch actually
# executes through it.


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- see test_docket_driver.py
    for the identical pattern; redefined locally per this suite's convention
    of self-contained per-file test doubles rather than a shared fake."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


def _final_response(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


class TestEndToEnd:
    def test_full_stack_through_docket_driver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No injected runner -> a real pod-dispatch hop executes through `DocketDriver`."""
        oc_dir = _seed_pod(tmp_path, monkeypatch)

        backend = _ScriptedBackend(
            [_final_response("lead plan"), _final_response("implementer done")]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "End to end")
        results = _dispatch.dispatch_pod("demo")
        assert results[0].status == "done"
        # cost_usd stays 0.0 through DocketDriver — CLAUDE.md's standing rule
        # against turning a measured-token estimate into a billing claim.
        assert results[0].cost_usd == 0.0
        assert len(backend.calls) == 2  # one turn per pod hop (lead, implementer)
        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"
        assert (oc_dir / "traces" / "demo").is_dir()

    def test_agent_loop_trace_records_carry_the_claimed_tasks_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every record the real agent loop writes for a hop is filed under the claimed
        task's id; dispatch's own task-level session_start/session_end bookkeeping records
        (written directly by core/dispatch.py, untouched by this card) carry no task_id."""
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        backend = _ScriptedBackend(
            [_final_response("lead plan"), _final_response("implementer done")]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        task = _dispatch.enqueue_task("demo", "Trace task id")
        results = _dispatch.dispatch_pod("demo")
        assert results[0].status == "done"

        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        assert len(trace_files) == 1
        events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
        llm_events = [e for e in events if e["event_type"] == "llm_call"]
        assert len(llm_events) == 2  # one per hop (lead, implementer)
        assert all(e.get("task_id") == task["id"] for e in llm_events)
        session_events = [e for e in events if e["event_type"] in ("session_start", "session_end")]
        assert session_events
        assert all("task_id" not in e for e in session_events)

    def test_refuse_approval_mode_fails_a_gated_hop_immediately_instead_of_waiting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measured trigger this card closes: a real policy-gated `bash` call, through the
        real `DocketDriver`, ends the hop well under `TOOL_APPROVAL_TIMEOUT` and fails the task
        with the `approval_unavailable` reason recorded, instead of blocking on nobody."""
        from docket.core.policy import install_policies

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 2, raising=True)
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "refuse")

        # "lead" denies the `bash` tool outright (core/archetypes.py); the gated call has
        # to be the Implementer's, so the Lead's turn gets an ordinary final response first.
        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        backend = _ScriptedBackend(
            [
                _final_response("lead plan"),
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "clean the build dir")
        started = time.monotonic()
        results = _dispatch.dispatch_pod("demo")
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, f"took {elapsed:.2f}s -- refuse mode should not wait"
        assert results[0].status == "failed"
        assert "approval_unavailable" in results[0].reason
        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "failed"
        assert "approval_unavailable" in tasks[0]["reason"]
        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        assert trace_files
        trace_events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
        assert any(
            ev["event_type"] == "error" and "approval_unavailable" in ev["payload"].get("text", "")
            for ev in trace_events
        )

    def test_park_approval_mode_parks_a_gated_hop_immediately_instead_of_waiting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real policy-gated `bash` call, through the real `DocketDriver`, ends the hop
        well under `TOOL_APPROVAL_TIMEOUT` and parks the task, token recorded."""
        from docket.core.policy import install_policies

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 2, raising=True)
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "park")

        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        backend = _ScriptedBackend(
            [
                _final_response("lead plan"),
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "clean the build dir")
        started = time.monotonic()
        results = _dispatch.dispatch_pod("demo")
        elapsed = time.monotonic() - started

        assert elapsed < 1.0, f"took {elapsed:.2f}s -- park mode should not wait"
        assert results[0].status == "waiting_approval", results[0].reason
        assert results[0].approval_token
        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "waiting_approval"
        assert tasks[0]["approvalToken"] == results[0].approval_token
        # The parked hop is persisted (audit/trace history stays true) --
        # `parked: true`, not silently dropped.
        assert tasks[0]["hops"][-1]["role"] == "implementer"
        assert tasks[0]["hops"][-1]["parked"] is True
        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        assert trace_files
        trace_events = [
            json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
        ]
        assert any(
            ev["event_type"] == "approval_required"
            and ev["payload"].get("token") == results[0].approval_token
            for ev in trace_events
        )

    def test_park_grant_resumes_the_parked_hop_with_a_single_use_pregrant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resume path: `docket approve <t>` then `docket pod <p> dispatch` re-runs the
        implementer hop (not the lead's already-persisted one) at its own index, and the exact
        same tool call the human approved passes once via a single-use pre-grant."""
        from docket.core import approval as _approval_mod
        from docket.core.policy import install_policies

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 2, raising=True)
        _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "park")

        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        park_backend = _ScriptedBackend(
            [
                _final_response("lead plan"),
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: park_backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "clean the build dir")
        parked = _dispatch.dispatch_pod("demo")
        token = parked[0].approval_token
        assert token

        # docket approve <token>
        _approval_mod.approval_grant(token, channel="cli")
        assert _dispatch.resolve_waiting_approval(token, "granted") is True
        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "pending"
        assert len(task["pregrants"]) == 1
        assert task["pregrants"][0]["token"] == token
        assert task["pregrants"][0]["tool"] == "bash"
        assert task["pregrants"][0]["argsDigest"]
        # The override-index field is for skipping a pre-hop approval *gate*,
        # never reused to re-run an already-attempted hop.
        assert task.get("gateOverridePipelineIndex") is None

        # docket pod demo dispatch -- the implementer's identical call is
        # re-issued by the model and this time passes via the pre-grant, then
        # the hop finishes normally.
        resume_backend = _ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
                _final_response("implementer done"),
            ]
        )
        driver2 = DocketDriver(backend_factory=lambda model: resume_backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver2)

        second = _dispatch.dispatch_pod("demo")

        assert second[0].status == "done", second[0].reason
        final = _dispatch.read_tasks("demo")[0]
        # Lead's already-persisted hop was not re-run; the implementer step
        # appears twice -- the parked attempt and the real one -- exactly the
        # same "each attempt is its own audit record" shape a rework cycle's
        # repeated reviewer hop already has, never overwritten in place.
        assert [h["role"] for h in final["hops"]] == ["lead", "implementer", "implementer"]
        assert final["hops"][1]["parked"] is True
        assert final["hops"][1]["ok"] is False
        assert final["hops"][-1]["parked"] is False
        assert final["hops"][-1]["ok"] is True

    def test_park_deny_fails_the_task_approval_denied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import approval as _approval_mod
        from docket.core.policy import install_policies

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 2, raising=True)
        _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "park")

        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        backend = _ScriptedBackend(
            [
                _final_response("lead plan"),
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "clean the build dir")
        parked = _dispatch.dispatch_pod("demo")
        token = parked[0].approval_token

        _approval_mod.approval_deny(token, channel="cli")
        assert _dispatch.resolve_waiting_approval(token, "denied") is True

        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"

    def test_park_expiry_past_deadline_denies_via_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parked approval's own `expiresAt` (not the default APPROVAL_TIMEOUT) governs it,
        and the fail-closed sweep denies it once past that deadline -- same resolution path as
        an explicit human deny."""
        from docket.core import approval as _approval_mod
        from docket.core.policy import install_policies

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 2, raising=True)
        _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "park")

        call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
        backend = _ScriptedBackend(
            [
                _final_response("lead plan"),
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=[call]),
                    finish_reason="tool_calls",
                    usage=TokenUsage(10, 5),
                ),
            ]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "clean the build dir")
        parked = _dispatch.dispatch_pod("demo")
        token = parked[0].approval_token
        assert token

        # Force this record's own expiresAt into the past -- the parked
        # record carries its own deadline (core/tools.py's `_park_call`),
        # never the generic APPROVAL_TIMEOUT.
        rec_path = _cfg.APPROVALS_DIR / f"{token}.json"
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        assert rec["expiresAt"]
        rec["expiresAt"] = "2000-01-01T00:00:00Z"
        rec_path.write_text(json.dumps(rec), encoding="utf-8")

        swept = _approval_mod.approval_sweep_expired()
        assert swept == 1

        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"

    def test_each_step_replays_only_its_history_and_receives_typed_handoff_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The production dispatch -> driver -> loop path must not give the
        Implementer both Lead's raw assistant turn and the handoff that already
        carries it."""
        home = _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setattr(_cfg, "SESSIONS_DIR", home / "sessions", raising=True)

        backend = _ScriptedBackend(
            [_final_response("LEAD_RAW_PLAN_SENTINEL"), _final_response("implementation done")]
        )
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        task = _dispatch.enqueue_task("demo", "Keep context bounded")
        legacy_task_key = f"agent:demo:{task['id']}"
        legacy_message = assistant("LEGACY_TASK_WIDE_HISTORY")
        _session.append_messages(legacy_task_key, [legacy_message])
        result = _dispatch.dispatch_pod("demo")[0]
        assert result.status == "done"

        lead_key = _dispatch.step_session_key("demo-lead", "demo", task["id"], "lead")
        implementer_key = _dispatch.step_session_key(
            "demo-implementer", "demo", task["id"], "implementer"
        )
        assert lead_key != implementer_key

        lead_history = _session.load_messages(lead_key)
        implementer_history = _session.load_messages(implementer_key)
        assert any(
            m.role == "assistant" and m.content == "LEAD_RAW_PLAN_SENTINEL" for m in lead_history
        )
        assert not any(
            m.role == "assistant" and m.content == "LEAD_RAW_PLAN_SENTINEL"
            for m in implementer_history
        )

        implementer_backend_messages = backend.calls[1]
        assert sum("LEAD_RAW_PLAN_SENTINEL" in m.content for m in implementer_backend_messages) == 1
        assert all("LEGACY_TASK_WIDE_HISTORY" not in m.content for m in backend.calls[0])
        assert all(
            "LEGACY_TASK_WIDE_HISTORY" not in m.content for m in implementer_backend_messages
        )
        assert any(
            m.role == "user" and "LEAD_RAW_PLAN_SENTINEL" in m.content
            for m in implementer_backend_messages
        )

        assert [s.session_id for s in driver.list_sessions("demo-lead")] == [lead_key]
        assert [s.session_id for s in driver.list_sessions("demo-implementer")] == [implementer_key]
        assert _session.load_messages(legacy_task_key) == [legacy_message]
        assert [s.session_id for s in driver.list_sessions("demo")] == [legacy_task_key]

        trace_files = list((home / "traces" / "demo").glob("*.jsonl"))
        assert len(trace_files) == 1
        trace_events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
        assert trace_events[0]["session_id"] == f"agent:demo:{task['id']}"
        assert all(e["session_id"] == f"agent:demo:{task['id']}" for e in trace_events)
        assert sum(e["event_type"] == "session_compaction" for e in trace_events) == 2
        assert {path.name for path in (home / "traces").iterdir()} == {"demo"}

    def test_step_history_key_encodes_custom_step_ids_without_collisions(self) -> None:
        colon = _dispatch.step_session_key("member", "demo", "task-1", "review:security")
        slash = _dispatch.step_session_key("member", "demo", "task-1", "review/security")

        assert colon.endswith(":step:review%3Asecurity")
        assert slash.endswith(":step:review%2Fsecurity")
        assert colon != slash

    def test_parallel_children_with_one_role_receive_distinct_step_histories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        spec = _pipeline.PipelineSpec(
            name="parallel-repeat",
            steps=[
                _pipeline.Step(
                    id="fanout",
                    parallel=[
                        _pipeline.Step(id="implement-a", role="implementer"),
                        _pipeline.Step(id="implement-b", role="implementer"),
                    ],
                )
            ],
        )
        runner = FakeDriver()
        task = {"id": "task-parallel", "description": "compare", "status": "pending"}

        result = _dispatch.dispatch_task("demo", task, runner=runner, spec=spec)

        assert result.status == "done"
        assert {call[1] for call in runner.calls} == {
            _dispatch.step_session_key("demo-implementer", "demo", "task-parallel", "implement-a"),
            _dispatch.step_session_key("demo-implementer", "demo", "task-parallel", "implement-b"),
        }


# ── task state machine v2 — locked claims close the concurrent-dispatch race ─


class TestConcurrentDispatch:
    """The double-run regression this exists to close: an unlocked ``dispatch_pod`` could let
    two concurrent callers both run the same ``pending`` task from a stale queue snapshot.
    ``_claim_next_task``'s locked read-modify-write prevents this: never the same task twice."""

    def test_two_concurrent_dispatch_pod_calls_never_double_run_a_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        n_tasks = 8
        for i in range(n_tasks):
            _dispatch.enqueue_task("demo", f"task {i}")

        calls: list[str] = []
        calls_lock = threading.Lock()

        class _SlowRunner:
            """Sleeps on every hop so concurrent claim attempts actually overlap."""

            def __call__(
                self,
                agent_id: str,
                session_key: str,
                message: str,
                timeout: int,
                env: dict[str, str] | None = None,
            ) -> _rd.TurnResult:
                time.sleep(0.02)
                with calls_lock:
                    calls.append(session_key)
                return _rd.TurnResult(True, f"done by {agent_id}", 0.0, {"output": "x"})

        runner = _SlowRunner()
        errors: list[BaseException] = []

        def _run() -> None:
            try:
                _dispatch.dispatch_pod("demo", runner=runner)
            except BaseException as exc:  # surfaced via `errors`, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=_run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"dispatch_pod raised in a worker thread: {errors}"
        # Each task is a 2-hop pipeline (lead, implementer) with two distinct
        # step-history keys. Group by the embedded task component: exactly two
        # calls per task means no claim ran twice and no task was skipped.
        task_ids = [key.split(":task:", 1)[1].split(":step:", 1)[0] for key in calls]
        counts = Counter(task_ids)
        assert len(counts) == n_tasks, f"expected {n_tasks} distinct tasks, got {counts}"
        assert all(c == 2 for c in counts.values()), counts
        assert len(set(calls)) == n_tasks * 2
        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == n_tasks
        assert all(t["status"] == "done" for t in tasks)
        assert len({t["id"] for t in tasks}) == n_tasks  # uuid4 ids never collide


# ── crash recovery — stale-claim sweep + resume from the last persisted hop ──


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
    """Like FakeDriver, but Reviewer/Tester hops carry a real verdict so a
    full pod can finish `done` (the Reviewer's APPROVE/REQUEST-CHANGES first
    line is parsed the same way the Tester's PASS/FAIL is)."""

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
        if role == "tester":
            output = "PASS - looks good"
        elif role == "reviewer":
            output = "APPROVE - looks good"
        else:
            output = f"done by {agent_id}"
        return _rd.TurnResult(True, output, 0.01, {"output": output})


class TestSweepDoesNotStallOnAParkedPod:
    """ADR 0016 SS2: an unset ``approvalMode`` resolves to "park" under the sweep, so one
    pod's gated call no longer stalls every other dispatchable pod in the same call."""

    def test_sweep_parks_one_pod_and_still_finishes_another_in_the_same_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import docket.serve as _serve
        from docket.core.policy import install_policies

        # Deliberately slow -- if the sweep's "park" default did not fire, alpha's
        # `wait`-mode ask would block on nobody for up to this long, and beta's
        # task would not even start within this test's own timeout.
        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 60, raising=True)

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        repoint_docket_home(monkeypatch, home)
        _pod.build_pod("alpha", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/alpha")
        _pod.build_pod("beta", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/beta")
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

        _dispatch.enqueue_task("alpha", "gated work")
        _dispatch.enqueue_task("beta", "plain work")

        started = time.monotonic()
        _serve._run_sweeps(True)
        elapsed = time.monotonic() - started

        assert elapsed < 5.0, f"took {elapsed:.2f}s -- alpha parking must not block beta"
        alpha_task = _dispatch.read_tasks("alpha")[0]
        beta_task = _dispatch.read_tasks("beta")[0]
        assert alpha_task["status"] == "waiting_approval", alpha_task.get("reason")
        assert beta_task["status"] == "done", beta_task.get("reason")


class TestCrashRecovery:
    def test_resume_skips_already_completed_hops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=_pod.pod.FULL_POD_ROLES)
        _dispatch.enqueue_task("demo", "Resume me")

        crasher = _CrashOnRoleRunner(crash_role="reviewer")
        with pytest.raises(RuntimeError, match="simulated crash"):
            _dispatch.dispatch_pod("demo", runner=crasher)
        # lead + implementer completed (and were persisted incrementally);
        # reviewer's request went out but the process "died" before a result.
        assert crasher.calls == ["lead", "implementer", "reviewer"]

        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["status"] == "running"  # never got to a terminal status
        assert [h["role"] for h in tasks[0]["hops"]] == ["lead", "implementer"]

        # Force the claim stale — simulate enough wall-clock time having passed.
        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)

        resumer = _VerdictAwareRunner()
        results = _dispatch.dispatch_pod("demo", runner=resumer, resume=True)
        assert len(results) == 1
        assert results[0].status == "done"
        # Only the hops that hadn't completed before the crash run again —
        # lead and implementer are NOT re-invoked.
        roles_called = [c[0].rsplit("-", 1)[-1] for c in resumer.calls]
        assert roles_called == ["reviewer", "tester"]

        final = _dispatch.read_tasks("demo")[0]
        assert final["status"] == "done"
        assert [h["role"] for h in final["hops"]] == ["lead", "implementer", "reviewer", "tester"]
        assert final["claimId"] is None

    def test_stale_claim_without_resume_is_not_reclaimed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default (non-resume) dispatch never auto-retries a crashed task."""
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Crash me")
        crasher = _CrashOnRoleRunner(crash_role="implementer")
        with pytest.raises(RuntimeError):
            _dispatch.dispatch_pod("demo", runner=crasher)

        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)
        runner = FakeDriver()
        results = _dispatch.dispatch_pod("demo", runner=runner)  # resume defaults to False
        assert results == []  # nothing eligible without --resume
        assert runner.calls == []
        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "stale_claim"

    def test_stale_claim_sweep_emits_trace_event(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Crash me too")
        crasher = _CrashOnRoleRunner(crash_role="implementer")
        with pytest.raises(RuntimeError):
            _dispatch.dispatch_pod("demo", runner=crasher)

        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)
        _dispatch.dispatch_pod("demo", runner=FakeDriver())

        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        events = [json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()]
        assert any(e["event_type"] == "stale_claim" for e in events)


# ── a deterministic refusal (e.g. cross-pod) fails only that task ────────────


def _alien_step_spec() -> _pipeline.PipelineSpec:
    """Lead, then a step targeting a member id that belongs to no real pod -- deterministically
    trips the cross-pod refusal in ``_execute_unit`` mid-task, after the lead hop persists."""
    return _pipeline.PipelineSpec(
        name="alien-step",
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(id="alien", agent="ghost-lead"),
        ],
    )


class TestDeterministicRefusalSettlesTheClaim:
    """A DispatchError reached mid-task (after an earlier hop already persisted) fails that one
    task and settles its claim instead of raising out of ``dispatch_pod`` -- see
    pod-dispatch.spec.md, "Deterministic refusal inside a claimed task"."""

    def test_refusal_fails_the_task_not_the_whole_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "task one")
        _dispatch.enqueue_task("demo", "task two")

        results = _dispatch.dispatch_pod("demo", runner=FakeDriver(), spec=_alien_step_spec())

        # Both queued tasks are attempted — the first task's deterministic refusal does not
        # abort the dispatch_pod loop before the second is even claimed.
        assert len(results) == 2
        assert [r.status for r in results] == ["failed", "failed"]
        assert all("refusing cross-pod dispatch" in r.reason for r in results)

        tasks = _dispatch.read_tasks("demo")
        assert [t["status"] for t in tasks] == ["failed", "failed"]
        assert all(t["claimId"] is None for t in tasks)  # settled, not orphaned
        assert all(t["failureKind"] == "dispatch_refused" for t in tasks)
        assert [h["role"] for h in tasks[0]["hops"]] == ["lead"]

    def test_resume_reclaims_a_dispatch_refused_task_once_the_pipeline_is_fixed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No CLAIM_STALE_TIMEOUT override and no decoy task needed — unlike a swept crash, a
        settled deterministic refusal is immediately resumable once its cause is fixed."""
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "fix me")

        first = _dispatch.dispatch_pod("demo", runner=FakeDriver(), spec=_alien_step_spec())
        assert first[0].status == "failed"
        assert _dispatch.read_tasks("demo")[0]["failureKind"] == "dispatch_refused"

        fixed_spec = _pipeline.PipelineSpec(
            name="fixed",
            steps=[
                _pipeline.Step(id="lead", role="lead"),
                _pipeline.Step(id="implementer", role="implementer"),
            ],
        )
        resumer = FakeDriver()

        second = _dispatch.dispatch_pod("demo", runner=resumer, resume=True, spec=fixed_spec)

        assert len(second) == 1
        assert second[0].status == "done"
        # The lead hop persisted before the refusal is not re-run.
        assert [c[0].rsplit("-", 1)[-1] for c in resumer.calls] == ["implementer"]
        final = _dispatch.read_tasks("demo")[0]
        assert final["status"] == "done"
        assert [h["role"] for h in final["hops"]] == ["lead", "implementer"]
        assert "failureKind" not in final

    def test_a_crash_mid_hop_still_leaves_the_task_running_for_the_stale_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin the non-goal: only a deterministic DispatchError is caught. An actual crash (any
        other exception) is unaffected — the task stays 'running', recoverable only through the
        existing stale-claim sweep, never settled outright."""
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "crash me")
        crasher = _CrashOnRoleRunner(crash_role="implementer")

        with pytest.raises(RuntimeError, match="simulated crash"):
            _dispatch.dispatch_pod("demo", runner=crasher)

        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "running"
        assert task["claimId"] is not None


class TestResumeGateCountsRunningTasksTowardRecovery:
    """``docket pod <p> dispatch --resume``'s "anything to do?" gate must not require a decoy
    pending task just to let ``dispatch_pod``'s own stale-claim sweep run over an orphaned
    `running` task — see pod-dispatch.spec.md, "Claiming"."""

    def test_resume_recovers_a_crashed_task_with_no_pending_task_queued(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "crash me")
        crasher = _CrashOnRoleRunner(crash_role="implementer")
        with pytest.raises(RuntimeError):
            _dispatch.dispatch_pod("demo", runner=crasher)

        # Orphaned: `running`, no decoy `pending` task exists, and it hasn't been swept yet
        # (the sweep only runs at the top of a `dispatch_pod` call).
        tasks_before = _dispatch.read_tasks("demo")
        assert tasks_before[0]["status"] == "running"
        assert not any(t.get("status") == "pending" for t in tasks_before)

        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)
        monkeypatch.setattr(_dr, "default_driver", lambda: FakeDriver())

        result = CliRunner().invoke(app, ["pod", "demo", "dispatch", "--resume"])

        assert "No pending tasks" not in result.output
        assert _dispatch.read_tasks("demo")[0]["status"] == "done"

    def test_resume_still_warns_with_nothing_pending_resumable_or_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        _seed_pod(tmp_path, monkeypatch)

        result = CliRunner().invoke(app, ["pod", "demo", "dispatch", "--resume"])

        assert "No pending tasks" in result.output


# ── a budget-blocked task is never silently rewritten back to pending ────────


class TestBlockedStaysBlocked:
    def test_blocked_task_survives_repeated_dispatch_pod_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
        runner = FakeDriver()

        first = _dispatch.dispatch_pod("demo", runner=runner)
        assert first[0].status == "blocked"
        # Once blocked, a `blocked` task is not even eligible to claim again —
        # repeated dispatch_pod calls find nothing to do (never re-attempted,
        # let alone re-attempted forever).
        for _ in range(3):
            assert _dispatch.dispatch_pod("demo", runner=runner) == []
        assert runner.calls == []  # never actually dispatched
        assert _dispatch.read_tasks("demo")[0]["status"] == "blocked"

    def test_retry_task_unblocks_a_single_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
        _dispatch.dispatch_pod("demo", runner=FakeDriver())
        assert _dispatch.read_tasks("demo")[0]["status"] == "blocked"

        assert _dispatch.retry_task("demo", task["id"]) is True
        assert _dispatch.read_tasks("demo")[0]["status"] == "pending"
        # Retrying a task that isn't blocked is a no-op.
        assert _dispatch.retry_task("demo", task["id"]) is False
        assert _dispatch.retry_task("demo", "no-such-task") is False

    def test_unblock_pod_unblocks_every_blocked_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "One")
        _dispatch.enqueue_task("demo", "Two")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)
        lead_id = _pod.pod.member_id("demo", "lead")

        _dispatch.dispatch_pod("demo", runner=FakeDriver())
        # The first cap breach also pauses the Lead, so a second dispatch
        # call is refused outright at claim time — task Two is never even
        # attempted (still "pending"). Clear the pause (what a real
        # `docket profile <lead> --resume`/`--budget` would do) so the second
        # call can claim and block it too, exercising the same
        # `unblock_pod` contract the original test covered.
        _fleet.meta_set(lead_id, "paused", False)
        _dispatch.dispatch_pod("demo", runner=FakeDriver())
        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 2
        assert all(t["status"] == "blocked" for t in tasks)
        assert _fleet.meta_read(lead_id).is_paused()  # re-paused by the second breach

        assert _dispatch.unblock_pod("demo") == 2
        tasks = _dispatch.read_tasks("demo")
        assert all(t["status"] == "pending" for t in tasks)
        # Nothing left blocked — a second call is a no-op.
        assert _dispatch.unblock_pod("demo") == 0


# ── backward compatibility — a legacy-shape TASK_LIST.json still loads/dispatches ─


class TestLegacyQueueLoads:
    def test_legacy_task_without_v2_fields_loads_and_dispatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        legacy_path = _dispatch.pod_task_list_path("demo")
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            # Legacy shape: epoch-ms id, no claimId/claimedAt/failureKind.
                            "id": "task-1700000000000",
                            "description": "Old-style task",
                            "priority": "normal",
                            "status": "pending",
                            "created": "2024-01-01T00:00:00+00:00",
                            "startedAt": None,
                            "completedAt": None,
                            "source": "operator",
                            "hops": [],
                        }
                    ]
                }
            )
        )

        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["id"] == "task-1700000000000"  # id format is not migrated, just tolerated
        assert tasks[0]["claimId"] is None
        assert tasks[0]["claimedAt"] is None

        results = _dispatch.dispatch_pod("demo", runner=FakeDriver())
        assert results[0].status == "done"
        assert _dispatch.read_tasks("demo")[0]["status"] == "done"

    def test_legacy_queue_missing_tasks_key_loads_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        legacy_path = _dispatch.pod_task_list_path("demo")
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text(json.dumps({}))
        assert _dispatch.read_tasks("demo") == []


# ── `docket pod <p> dispatch`'s prologue names the resolved pipeline's roles ──


class TestPodDispatchCliPrologue:
    """The "Dispatching N pending task(s) through: <roles>" prologue must name the pod's
    own resolved pipeline, not the legacy four-role ``PIPELINE_ORDER`` filter a
    non-``software`` pod never matches past "lead"."""

    def test_research_pod_prologue_names_its_blueprint_roles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        repoint_docket_home(monkeypatch, home)

        _pod.build_pod_from_blueprint("rsch", "research", location="", description="")
        _dispatch.enqueue_task("rsch", "look into it")
        monkeypatch.setattr(_dr, "default_driver", lambda: FakeDriver(ok=True, cost=0.0))

        result = CliRunner().invoke(app, ["pod", "rsch", "dispatch"])

        assert "through: lead → researcher → analyst → writer → critic" in result.output


# ── operator `input` steps execute: park, answer, resume (ADR 0016 SS4/SS8) ──

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
  - id: implementer
    role: implementer
"""

_ASK_DECLINE_CAP_PIPELINE_YAML = """\
name: ask-decline-cap
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
    on:
      declined:
        goto: lead
        max: 1
  - id: implementer
    role: implementer
"""


def _ask_spec(on: dict[str, Any] | None = None) -> _pipeline.PipelineSpec:
    """Lead, then an `input` step asking about the Lead's own output, then Implementer."""
    return _pipeline.PipelineSpec(
        name="ask",
        steps=[
            _pipeline.Step(id="lead", role="lead"),
            _pipeline.Step(id="ask", input=_pipeline.InputSpec(from_="lead"), on=on),
            _pipeline.Step(id="implementer", role="implementer"),
        ],
    )


def _bind_pipeline(project: str, text: str) -> None:
    """Bind *text* as *project*'s own pipeline, so ``answer_task``'s own
    ``effective_pipeline(project, None)`` resolves the same steps a test's own
    ``dispatch_pod`` call ran through."""
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


class TestOperatorInputStepsPark:
    def test_reaching_an_input_step_parks_with_no_hop_and_a_default_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "needs a decision")

        results = _dispatch.dispatch_pod("demo", runner=FakeDriver(), spec=_ask_spec())

        assert len(results) == 1
        assert results[0].status == "waiting_input"
        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "waiting_input"
        # Only the Lead's real hop is persisted -- the park itself leaves no hop, the same
        # posture as the pre-hop require_approval gate's `waiting_approval`.
        assert [h["role"] for h in task["hops"]] == ["lead"]
        question = task["question"]
        assert question["step"] == "ask"
        assert question["requestedSchema"]["properties"] == {"answer": {"type": "string"}}
        assert question["requestedSchema"]["required"] == ["answer"]

        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        events = [json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()]
        requested = [e for e in events if e["event_type"] == "input_requested"]
        assert len(requested) == 1
        assert requested[0]["payload"]["step"] == "ask"
        assert requested[0]["payload"]["questionId"] == question["id"]

    def test_a_waiting_input_task_is_never_reclaimed_by_a_plain_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "needs a decision")
        _dispatch.dispatch_pod("demo", runner=FakeDriver(), spec=_ask_spec())
        assert _dispatch.read_tasks("demo")[0]["status"] == "waiting_input"

        for _ in range(3):
            assert _dispatch.dispatch_pod("demo", runner=FakeDriver(), spec=_ask_spec()) == []
        assert _dispatch.read_tasks("demo")[0]["status"] == "waiting_input"


class TestAnswerTaskResumesDispatch:
    """An answered `input` step's synthetic hop carries its own `nextStep`, so the resume
    builder (and its `route_counts` rebuild) continues correctly across a resume boundary."""

    def test_an_accepted_answer_resumes_straight_through_to_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _bind_pipeline("demo", _ASK_PIPELINE_YAML)
        task = _dispatch.enqueue_task("demo", "needs a decision")
        _dispatch.dispatch_pod("demo", runner=FakeDriver())
        assert _dispatch.read_tasks("demo")[0]["status"] == "waiting_input"

        result = _answers.answer_task(
            "demo", task["id"], "accept", {"answer": "go ahead"}, channel="cli", actor="op"
        )
        assert result.action == "accept"

        parked = _dispatch.read_tasks("demo")[0]
        assert parked["status"] == "pending"
        assert parked["answers"][0]["content"] == {"answer": "go ahead"}
        assert [h["role"] for h in parked["hops"]] == ["lead", "operator"]
        assert parked["hops"][-1]["nextStep"] is None  # no `on:` route -- ordinary advance

        # The crash/resume boundary: a fresh `dispatch_pod` call (as `serve --dispatch`'s
        # next sweep would make) claims the re-opened task and must continue past `ask`
        # straight to `implementer`, never re-asking.
        final_results = _dispatch.dispatch_pod("demo", runner=FakeDriver())
        assert final_results[0].status == "done"
        final = _dispatch.read_tasks("demo")[0]
        assert [h["role"] for h in final["hops"]] == ["lead", "operator", "implementer"]

    def test_a_declined_answer_routes_backward_and_a_second_decline_exhausts_its_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`max: 1` -- proves `route_counts` is rebuilt from the persisted hop's `nextStep`
        on resume: the second decline, a brand new `answer_task` call, must still see it."""
        _seed_pod(tmp_path, monkeypatch)
        _bind_pipeline("demo", _ASK_DECLINE_CAP_PIPELINE_YAML)
        task = _dispatch.enqueue_task("demo", "needs a decision")
        _dispatch.dispatch_pod("demo", runner=FakeDriver())
        assert _dispatch.read_tasks("demo")[0]["status"] == "waiting_input"

        _answers.answer_task("demo", task["id"], "decline", None, channel="cli", actor="op")
        after_first = _dispatch.read_tasks("demo")[0]
        assert after_first["status"] == "pending"
        assert after_first["hops"][-1]["nextStep"] == "lead"

        # Resume: replays back to `lead`, re-runs it (a fresh hop), reaches `ask` again and
        # parks with a brand new question -- `route_counts` for ("ask", "declined") is now 1,
        # rebuilt purely from the first operator hop's own persisted `nextStep`.
        _dispatch.dispatch_pod("demo", runner=FakeDriver())
        reparked = _dispatch.read_tasks("demo")[0]
        assert reparked["status"] == "waiting_input"
        assert [h["role"] for h in reparked["hops"]] == ["lead", "operator", "lead"]

        # A second decline exhausts the `max: 1` budget -- `answer_task` settles the task
        # `failed` right here (no live dispatch context exists to do it for it).
        _answers.answer_task("demo", task["id"], "decline", None, channel="cli", actor="op")
        final = _dispatch.read_tasks("demo")[0]
        assert final["status"] == "failed"
        assert final["hops"][-1]["nextStep"] is None
        assert final["hops"][-1]["role"] == "operator"


# ── the Lead's intake: TaskBrief, the intake recipe, resource checks (ADR 0016 §4) ──


def _bind_intake_pipeline(project: str) -> None:
    """Bind the real shipped ``intake`` recipe's pipeline so ``dispatch_pod`` and
    ``answer_task`` resolve the same steps (see ``_bind_pipeline`` above)."""
    text = (_cfg.recipes_dir() / "intake" / "pipeline.yaml").read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    assert result.spec is not None, result.errors
    _bind_pipeline(project, text)


_LEAD_NEEDS_INPUT_SENTINEL = "SENTINEL_FIRST_LEAD_HOP"
_LEAD_READY_SENTINEL = "SENTINEL_SECOND_LEAD_HOP"

_LEAD_NEEDS_INPUT_REPLY = f"""{_LEAD_NEEDS_INPUT_SENTINEL}: I need two decisions before I can start.

```json
{{"objective": "add a widget", "acceptance": ["widget renders"], "questions": ["Which color?", "Which size?"]}}
```
NEEDS-INPUT"""

_LEAD_READY_REPLY = f"""{_LEAD_READY_SENTINEL}: thanks, now I have everything I need.

```json
{{"objective": "add a widget", "acceptance": ["widget renders", "matches spec"]}}
```
READY"""

_LEAD_READY_MISSING_SECRET_REPLY = """Needs one credential.

```json
{"objective": "call the API", "acceptance": ["call succeeds"], "resources": ["secret:MISSING_KEY"]}
```
READY"""

_LEAD_READY_NO_BRIEF_REPLY = "Nothing fancy, just doing it.\nREADY"

_LEAD_REJECT_REPLY = """This should not be attempted.

```json
{"objective": "delete production", "acceptance": []}
```
REJECT"""


class _IntakeRunner:
    """A scripted runner keyed by role, not call order -- the Lead may run more than once
    (NEEDS-INPUT -> answered -> re-run), so its replies are consumed in order, one per call,
    while every other role answers the same way every time."""

    def __init__(self, lead_replies: list[str], reviewer_reply: str = "APPROVE") -> None:
        self._lead_replies = list(lead_replies)
        self._reviewer_reply = reviewer_reply
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append((role, message))
        if role == "lead":
            reply = self._lead_replies.pop(0) if self._lead_replies else "READY"
            return _rd.TurnResult(True, reply, 0.0, {})
        if role == "reviewer":
            return _rd.TurnResult(True, self._reviewer_reply, 0.0, {})
        return _rd.TurnResult(True, "done", 0.0, {})


class TestCheckBriefResources:
    """Direct, dispatch-free coverage of `_check_brief_resources`'s three resource kinds --
    the intake-recipe integration tests above exercise `secret:` end to end through a real
    pipeline; these isolate `path:` and `verify` (and `secret:` again, for symmetry)."""

    def test_an_unconfigured_secret_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief = _oc.TaskBrief(objective="x", resources=["secret:NOPE"])
        assert _dispatch._check_brief_resources("demo", brief) == ["secret:NOPE"]

    def test_a_configured_secret_is_not_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _secrets.save_secrets({"YES": "shh"})
        brief = _oc.TaskBrief(objective="x", resources=["secret:YES"])
        assert _dispatch._check_brief_resources("demo", brief) == []

    def test_a_missing_path_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        missing = str(tmp_path / "does-not-exist.txt")
        brief = _oc.TaskBrief(objective="x", resources=[f"path:{missing}"])
        assert _dispatch._check_brief_resources("demo", brief) == [f"path:{missing}"]

    def test_an_existing_path_is_not_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        present = tmp_path / "exists.txt"
        present.write_text("x")
        brief = _oc.TaskBrief(objective="x", resources=[f"path:{present}"])
        assert _dispatch._check_brief_resources("demo", brief) == []

    def test_verify_is_missing_with_no_configured_verify_cmd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief = _oc.TaskBrief(objective="x", resources=["verify"])
        assert _dispatch._check_brief_resources("demo", brief) == ["verify"]

    def test_verify_is_not_missing_once_the_implementer_has_a_verify_cmd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set(_pod.pod.member_id("demo", "implementer"), "verifyCmd", "pytest -q")
        brief = _oc.TaskBrief(objective="x", resources=["verify"])
        assert _dispatch._check_brief_resources("demo", brief) == []

    def test_a_brief_with_no_resources_has_nothing_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _dispatch._check_brief_resources("demo", _oc.TaskBrief(objective="x")) == []


class TestIntakeRecipeTaskBrief:
    def test_needs_input_then_ready_reaches_the_implementer_with_a_brief_view(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        _bind_intake_pipeline("demo")
        task = _dispatch.enqueue_task("demo", "build the widget")
        runner = _IntakeRunner([_LEAD_NEEDS_INPUT_REPLY, _LEAD_READY_REPLY])

        first = _dispatch.dispatch_pod("demo", runner=runner)
        assert first[0].status == "waiting_input"
        question = _dispatch.read_tasks("demo")[0]["question"]
        assert question["requestedSchema"]["properties"]["q1"]["title"] == "Which color?"
        assert question["requestedSchema"]["properties"]["q2"]["title"] == "Which size?"
        assert question["requestedSchema"]["required"] == ["q1", "q2"]
        assert question["message"] == "The Lead needs answers before starting: add a widget"

        _answers.answer_task(
            "demo",
            task["id"],
            "accept",
            {"q1": "blue", "q2": "large"},
            channel="cli",
            actor="op",
        )

        final = _dispatch.dispatch_pod("demo", runner=runner)
        assert final[0].status == "done"

        implementer_messages = [msg for role, msg in runner.calls if role == "implementer"]
        assert len(implementer_messages) == 1
        implementer_message = implementer_messages[0]
        assert "## Brief" in implementer_message
        assert "widget renders" in implementer_message
        assert "matches spec" in implementer_message
        # The READY reply is the *latest* brief-bearing hop -- its own prose preamble is
        # replaced by "## Brief" entirely. The earlier NEEDS-INPUT hop's prose is still
        # carried forward as ordinary prior-hop context (unaffected by this feature).
        assert _LEAD_READY_SENTINEL not in implementer_message

    def test_a_brief_naming_a_missing_secret_blocks_with_resources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        _bind_intake_pipeline("demo")
        _dispatch.enqueue_task("demo", "call the API")
        runner = _IntakeRunner([_LEAD_READY_MISSING_SECRET_REPLY])

        results = _dispatch.dispatch_pod("demo", runner=runner)

        assert results[0].status == "blocked"
        task = _dispatch.read_tasks("demo")[0]
        assert task["status"] == "blocked"
        assert task["blockedReason"] == "resources"
        assert "secret:MISSING_KEY" in task["reason"]
        assert _oc.a2a_state("blocked", blocked_reason=task["blockedReason"]) == "AUTH_REQUIRED"
        # No Implementer hop was ever attempted -- the check happens before that turn.
        assert [h["role"] for h in task["hops"]] == ["lead"]

    def test_a_configured_secret_is_not_reported_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        _bind_intake_pipeline("demo")
        _secrets.save_secrets({"MISSING_KEY": "shh"})
        _dispatch.enqueue_task("demo", "call the API")
        runner = _IntakeRunner([_LEAD_READY_MISSING_SECRET_REPLY])

        results = _dispatch.dispatch_pod("demo", runner=runner)

        assert results[0].status == "done"

    def test_a_reply_with_no_parseable_brief_but_a_ready_marker_still_advances(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        _bind_intake_pipeline("demo")
        _dispatch.enqueue_task("demo", "do the plain thing")
        runner = _IntakeRunner([_LEAD_READY_NO_BRIEF_REPLY])

        results = _dispatch.dispatch_pod("demo", runner=runner)

        assert results[0].status == "done"
        task = _dispatch.read_tasks("demo")[0]
        assert [h["role"] for h in task["hops"]] == ["lead", "implementer", "reviewer"]

    def test_reject_fails_the_task_as_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer", "reviewer"))
        _bind_intake_pipeline("demo")
        _dispatch.enqueue_task("demo", "delete production")
        runner = _IntakeRunner([_LEAD_REJECT_REPLY])

        results = _dispatch.dispatch_pod("demo", runner=runner)

        assert results[0].status == "failed"
        task = _dispatch.read_tasks("demo")[0]
        assert task["failureKind"] == "rejected"
        assert _oc.a2a_state("failed", failure_kind=task["failureKind"]) == "REJECTED"
