"""AA-7: real pod dispatch — ACL agent_run + the pipeline driver (hermetic).

Two layers are exercised:
  * ``openclaw.agent_run`` against a *fake* ``openclaw`` binary on PATH (proves the
    real subprocess wrapper + JSON parsing) — the card's "faked daemon" gate.
  * ``core.dispatch`` with an injected runner (fast, deterministic) for the
    pipeline semantics: hop order, budget gating, failure-stops, no-cross-pod.
A final end-to-end test wires the driver through the REAL agent_run + fake binary.

CD-0 adds ``TestAgentRunRealShape`` — canned real daemon JSON confirming the
confirmed schema (result.payloads[0].text, no USD cost field).

R-1 adds the task-state-machine-v2 suites: ``TestConcurrentDispatch`` (the
thread-race regression this whole card exists to close), ``TestCrashRecovery``
(stale-claim sweep + resume-from-last-hop), ``TestBlockedStaysBlocked``
(kills the old blocked→pending auto-retry), and ``TestLegacyQueueLoads``
(a pre-R-1 TASK_LIST.json with none of the new fields still loads/dispatches).
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
from docket.core import resources as _res
from docket.core import runtime_driver as _rd
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

from .fakes import FakeDriver

# ── hermetic environment (mirrors test_pod_provisioning) ─────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
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


# Phase 18 L-1: the pipeline-semantics tests below inject `FakeDriver` (the one
# RuntimeDriver test double, tests/python/fakes.py) as dispatch.py's Runner —
# it is callable with agent_run's exact signature, so it drops in unchanged
# wherever a `runner=` kwarg is passed. Replaces this file's former ad-hoc
# `FakeDriver` shim.


# Phase 19 P19-7b deleted the daemon-facing driver whose real subprocess-backed
# `agent_run` `TestAgentRun`/`TestAgentRunEnv`/`TestAgentRunRealShape` used to
# exercise (against a fake `openclaw` binary on PATH, and canned real daemon
# JSON per CD-0). The successor path is `edges/adapters/llm.py`'s
# `OpenAIChatClient` (response parsing, already covered by
# test_p19_1_llm_port.py) and `edges/adapters/docket_runtime.py`'s
# `DocketDriver` (env passed through to a tool call, covered by
# test_p19_5_docket_driver.py's `test_env_kwarg_reaches_a_tool_call` and
# `test_on_spawn_is_accepted_and_ignored`) -- neither reads a daemon JSON
# shape or shells out at all, so those classes are not re-created here.


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
        # Each hop ran on the per-task session within the project namespace.
        assert all(c[1].startswith("agent:demo:") for c in runner.calls)

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
        # W-5: 3, not 2 — lead's turn, implementer's turn, plus a third
        # `tool_result` for the implementer's mechanical gate itself (no
        # `verifyCmd` set on this seeded pod, so it is the "skipped" outcome,
        # traced for parity with the "passed" case — see
        # test_cd2_verify.py's TestDispatchVerifyGate for both outcomes).
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
        # R-1: a blocked task stays blocked (it is never silently rewritten back
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
        # Remove the lead from the fleet registry → no dispatchable pod
        # (P19-6: registration lives in fleet.json now, not openclaw.json).
        _fleet.remove_agent("demo-lead")
        with pytest.raises(_dispatch.DispatchError):
            _dispatch.dispatch_pod("demo", runner=FakeDriver())


# ── FD-0: pod port range / scratch dir reach the implementer hop's real env ──────


class TestHopEnvInjection:
    """completes P1: the implementer subprocess's actual env, not just TOOLS.md prose."""

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
    """Replays a fixed script of `ChatResponse`s -- see test_p19_5_docket_driver.py
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


# ── R-1: task state machine v2 — locked claims close the concurrent-dispatch race ─


class TestConcurrentDispatch:
    """The regression this whole card exists to close.

    Before R-1, ``dispatch_pod`` read the queue unlocked, decided what to run
    from that snapshot, and only wrote back after each task — so two
    concurrent callers on the same pod could both see the same task
    ``pending`` and both run it. Claiming (``_claim_next_task``) is now a
    locked read-modify-write, so this can no longer happen: concurrent callers
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
        # Each task is a 2-hop pipeline (lead, implementer) on its own session id
        # (agent:demo:<task-id>) — exactly 2 calls per task, never more (a task
        # claimed twice would show up as 4+ calls on its session) and every task
        # still completes (never 0, i.e. never left unclaimed).
        counts = Counter(calls)
        assert len(counts) == n_tasks, f"expected {n_tasks} distinct task sessions, got {counts}"
        assert all(c == 2 for c in counts.values()), counts
        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == n_tasks
        assert all(t["status"] == "done" for t in tasks)
        assert len({t["id"] for t in tasks}) == n_tasks  # uuid4 ids never collide


# ── R-1: crash recovery — stale-claim sweep + resume from the last persisted hop ──


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
    full pod can finish `done` (R-4 parses the Reviewer's APPROVE/REQUEST-CHANGES
    first line the same way FD-2 parses the Tester's PASS/FAIL)."""

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


# ── R-1: a budget-blocked task is never silently rewritten back to pending ────────


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
        # let alone re-attempted forever, which was the R-1 bug).
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
        # R-5: the first cap breach also pauses the Lead, so a second dispatch
        # call is refused outright at claim time — task Two is never even
        # attempted (still "pending"). Clear the pause (what a real
        # `docket profile <lead> --resume`/`--budget` would do) so the second
        # call can claim and block it too, exercising the same
        # `unblock_pod` contract the original (pre-R-5) test covered.
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


# ── R-1: backward compatibility — a pre-R-1 TASK_LIST.json still loads/dispatches ─


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
                            # Pre-R-1 shape: epoch-ms id, no claimId/claimedAt/failureKind.
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
