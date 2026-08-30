"""Real pod dispatch — the pipeline driver (hermetic).

``core.dispatch`` is exercised two ways:
  * with an injected runner (fast, deterministic) for the pipeline
    semantics: hop order, budget gating, failure-stops, no-cross-pod.
  * end to end (``TestEndToEnd``) with no injected runner at all -- a real
    pod-dispatch hop executes through the real production ``DocketDriver``,
    with only its `ChatBackend` scripted.

The task-state-machine-v2 suites: ``TestConcurrentDispatch`` (the
thread-race regression this exists to close), ``TestCrashRecovery``
(stale-claim sweep + resume-from-last-hop), ``TestBlockedStaysBlocked``
(kills a blocked→pending auto-retry), and ``TestLegacyQueueLoads``
(a legacy TASK_LIST.json with none of the newer fields still
loads/dispatches).
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pipeline as _pipeline
from docket.core import resources as _res
from docket.core import runtime_driver as _rd
from docket.core import session as _session
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

from .fakes import FakeDriver

# ── hermetic environment (mirrors test_pod_provisioning) ─────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] = _pod.pod.DEFAULT_POD_ROLES,
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
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


# The pipeline-semantics tests below inject `FakeDriver` (the one
# RuntimeDriver test double, tests/python/fakes.py) as dispatch.py's Runner —
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
    """The regression this exists to close.

    An unlocked ``dispatch_pod`` would read the queue, decide what to run
    from that snapshot, and only write back after each task — so two
    concurrent callers on the same pod could both see the same task
    ``pending`` and both run it. Claiming (``_claim_next_task``) is a
    locked read-modify-write, so this cannot happen: concurrent callers
    may run *different* tasks at once, but never the *same* one twice.
    """

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
    """Simulates a hard crash (process death) partway through a role's hop.

    Records the role it was called for *before* raising, matching what really
    happens: the request went out (recorded), but the process died before a
    result — and therefore a persisted terminal status — ever came back.
    """

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
