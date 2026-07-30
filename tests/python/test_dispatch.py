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
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import resources as _res
from docket.edges.adapters import openclaw as _oc

# ── hermetic environment (mirrors test_pod_provisioning) ─────────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = oc_dir / "openclaw.json"
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _fake_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register/unregister mutate agents.list directly (no real openclaw)."""
    monkeypatch.setattr(_pod.shutil, "which", lambda _name: "/usr/bin/openclaw")

    def _register(agent_id: str, workspace: str, model: str) -> tuple[bool, str]:
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw.setdefault("agents", {}).setdefault("list", []).append(
            {"id": agent_id, "model": model, "metadata": {}}
        )
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        return (True, "")

    monkeypatch.setattr(_oc, "register_agent_cli", _register)


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] = _pod.pod.DEFAULT_POD_ROLES,
) -> Path:
    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    (oc_dir / "openclaw.json").write_text(
        json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}})
    )
    _point_at(oc_dir, monkeypatch)
    _fake_daemon(monkeypatch)
    _pod.build_pod(project, roles, codebase=f"/src/{project}")
    return oc_dir


class _RecordingRunner:
    """Stub matching agent_run's signature; records calls, returns canned results."""

    def __init__(self, *, ok: bool = True, cost: float = 0.02, fail_role: str | None = None):
        self.calls: list[tuple[str, str, str, int, dict[str, str] | None]] = []
        self.ok = ok
        self.cost = cost
        self.fail_role = fail_role

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _oc.AgentRunResult:
        self.calls.append((agent_id, session_key, message, timeout, env))
        role = agent_id.rsplit("-", 1)[-1]
        if self.fail_role and role == self.fail_role:
            return _oc.AgentRunResult(False, "", 0.0, {}, "boom")
        return _oc.AgentRunResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})


# ── ACL agent_run against a fake binary ──────────────────────────────────────────


def _write_fake_openclaw(bindir: Path, mode: str = "ok") -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "openclaw"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        f"mode = {mode!r}\n"
        "if mode == 'fail':\n"
        "    sys.stderr.write('boom'); sys.exit(1)\n"
        "if mode == 'nonjson':\n"
        "    sys.stdout.write('plain reply'); sys.exit(0)\n"
        "agent = ''\n"
        "a = sys.argv\n"
        "for i, t in enumerate(a):\n"
        "    if t == '--agent' and i + 1 < len(a):\n"
        "        agent = a[i + 1]\n"
        "print(json.dumps({'output': 'done by ' + agent, 'cost': 0.02}))\n"
    )
    script.chmod(0o755)
    return script


class TestAgentRun:
    def test_success_parses_output_and_cost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindir = tmp_path / "bin"
        _write_fake_openclaw(bindir, "ok")
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        res = _oc.agent_run("demo-implementer", "agent:demo:t1", "do it", 30)
        assert res.ok
        assert res.output == "done by demo-implementer"
        assert res.cost_usd == 0.02
        assert res.raw.get("output")

    def test_nonzero_exit_is_not_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bindir = tmp_path / "bin"
        _write_fake_openclaw(bindir, "fail")
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 30)
        assert not res.ok
        assert "boom" in res.error

    def test_non_json_output_still_surfaces_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindir = tmp_path / "bin"
        _write_fake_openclaw(bindir, "nonjson")
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 30)
        assert res.ok
        assert res.output == "plain reply"

    def test_missing_cli_is_not_ok(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))  # no openclaw anywhere
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 30)
        assert not res.ok
        assert "not found" in res.error


# ── FD-0: env override actually reaches the real subprocess ──────────────────────


class TestAgentRunEnv:
    def test_env_kwarg_merges_into_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of FD-0: env=... is not just plumbed, it lands in the child."""
        bindir = tmp_path / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        script = bindir / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import os, json\n"
            "print(json.dumps({\n"
            "    'output': 'env seen',\n"
            "    'cost': 0.0,\n"
            "    'port_base': os.environ.get('DOCKET_PORT_BASE'),\n"
            "    'scratch': os.environ.get('DOCKET_SCRATCH_DIR'),\n"
            "}))\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        res = _oc.agent_run(
            "demo-implementer",
            "agent:demo:t1",
            "do it",
            30,
            env={"DOCKET_PORT_BASE": "3000", "DOCKET_SCRATCH_DIR": "/tmp/demo-scratch"},
        )
        assert res.ok
        assert res.raw.get("port_base") == "3000"
        assert res.raw.get("scratch") == "/tmp/demo-scratch"

    def test_no_env_kwarg_inherits_parent_env_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No env override (the default) behaves exactly as before FD-0."""
        bindir = tmp_path / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        script = bindir / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import os, json\n"
            "print(json.dumps({'output': 'x', 'cost': 0.0, "
            "'marker': os.environ.get('DOCKET_TEST_MARKER', '')}))\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("DOCKET_TEST_MARKER", "inherited")
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 30)
        assert res.ok
        assert res.raw.get("marker") == "inherited"


# ── pipeline driver (injected runner) ────────────────────────────────────────────


class TestPipeline:
    def test_lean_pod_runs_lead_then_implementer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Fix the bug")
        runner = _RecordingRunner()
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
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner(cost=0.05))
        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"
        assert [h["role"] for h in tasks[0]["hops"]] == ["lead", "implementer"]
        assert tasks[0]["costUsd"] == pytest.approx(0.10)

    def test_traces_written_per_hop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "Trace me")
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
        assert len(trace_files) == 1
        events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
        types = [e["event_type"] for e in events]
        assert "session_start" in types
        assert types.count("tool_call") == 2
        assert types.count("tool_result") == 2
        assert "session_end" in types

    def test_failed_hop_stops_pipeline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=_pod.pod.FULL_POD_ROLES)
        _dispatch.enqueue_task("demo", "Break early")
        runner = _RecordingRunner(fail_role="implementer")
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
        runner = _RecordingRunner()
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
        runner = _RecordingRunner()
        _dispatch.dispatch_pod("demo", runner=runner)
        assert runner.calls, "expected dispatch to run"
        assert all(c[0].startswith("demo-") for c in runner.calls)
        assert (oc_dir / "traces" / "other").exists() is False

    def test_no_lead_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        # Remove the lead from the registry → no dispatchable pod.
        raw = json.loads(_cfg.CONFIG_FILE.read_text())
        raw["agents"]["list"] = [a for a in raw["agents"]["list"] if a["id"] != "demo-lead"]
        _cfg.CONFIG_FILE.write_text(json.dumps(raw))
        with pytest.raises(_dispatch.DispatchError):
            _dispatch.dispatch_pod("demo", runner=_RecordingRunner())


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
        runner = _RecordingRunner()
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
        runner = _RecordingRunner()
        _dispatch.dispatch_pod("demo", runner=runner)
        by_role = {c[0].rsplit("-", 1)[-1]: c[4] for c in runner.calls}
        assert by_role["implementer"] is None


# ── CD-0: canned real daemon JSON shape ──────────────────────────────────────────

# Captured 2026-06-25 from daemon v2026.2.23 using agent `knowledge`
# (opencode-go/glm-5.2). sessionId and runId are redacted. systemPromptReport
# omitted — irrelevant to parsing. See internal-docs/POD-DAEMON-NOTES.md §CD-0.
_REAL_DAEMON_RESPONSE: dict[str, Any] = {
    "runId": "<redacted-uuid>",
    "status": "ok",
    "summary": "completed",
    "result": {
        "payloads": [{"text": "OK", "mediaUrl": None}],
        "meta": {
            "durationMs": 21258,
            "agentMeta": {
                "sessionId": "<redacted-uuid>",
                "provider": "opencode-go",
                "model": "glm-5.2",
                "usage": {
                    "input": 14010,
                    "output": 3,
                    "cacheRead": 128,
                    "total": 14141,
                },
                "promptTokens": 14138,
            },
            "aborted": False,
        },
    },
}


class TestAgentRunRealShape:
    """Verify parsing against the confirmed real daemon JSON schema (CD-0)."""

    def test_real_shape_extracts_text_from_payloads(self) -> None:
        output = _oc._extract_run_output(_REAL_DAEMON_RESPONSE)
        assert output == "OK"

    def test_real_shape_cost_is_zero(self) -> None:
        # Daemon v2026.2.23 returns token counts only — no USD cost field.
        cost = _oc._extract_run_cost(_REAL_DAEMON_RESPONSE)
        assert cost == 0.0

    def test_full_agent_run_with_real_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fake binary emitting the real daemon shape yields the correct result."""
        bindir = tmp_path / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        script = bindir / "openclaw"
        script.write_text(
            f"#!/usr/bin/env python3\nimport json\nprint(json.dumps({_REAL_DAEMON_RESPONSE!r}))\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        res = _oc.agent_run("knowledge", "docket-schema-probe", "OK", 30)
        assert res.ok
        assert res.output == "OK"
        assert res.cost_usd == 0.0

    def test_flat_fallback_still_works(self) -> None:
        """Old flat shape (used in test shims) still parses via the fallback."""
        flat: dict[str, Any] = {"output": "flat reply", "cost": 0.02}
        assert _oc._extract_run_output(flat) == "flat reply"
        assert _oc._extract_run_cost(flat) == pytest.approx(0.02)


# ── end-to-end: driver → real agent_run → fake binary ────────────────────────────


class TestEndToEnd:
    def test_full_stack_through_fake_binary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        oc_dir = _seed_pod(tmp_path, monkeypatch)
        bindir = tmp_path / "bin"
        _write_fake_openclaw(bindir, "ok")
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        _dispatch.enqueue_task("demo", "End to end")
        # No injected runner → uses the real ACL agent_run, which shells the fake.
        results = _dispatch.dispatch_pod("demo")
        assert results[0].status == "done"
        assert results[0].cost_usd == pytest.approx(0.04)  # 2 hops x 0.02
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
            ) -> _oc.AgentRunResult:
                time.sleep(0.02)
                with calls_lock:
                    calls.append(session_key)
                return _oc.AgentRunResult(True, f"done by {agent_id}", 0.0, {"output": "x"})

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
    ) -> _oc.AgentRunResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        if role == self.crash_role:
            raise RuntimeError("simulated crash")
        return _oc.AgentRunResult(True, f"done by {agent_id}", 0.01, {"output": "x"})


class _VerdictAwareRunner:
    """Like _RecordingRunner, but Reviewer/Tester hops carry a real verdict so a
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
    ) -> _oc.AgentRunResult:
        self.calls.append((agent_id, session_key, message, timeout, env))
        role = agent_id.rsplit("-", 1)[-1]
        if role == "tester":
            output = "PASS - looks good"
        elif role == "reviewer":
            output = "APPROVE - looks good"
        else:
            output = f"done by {agent_id}"
        return _oc.AgentRunResult(True, output, 0.01, {"output": output})


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
        runner = _RecordingRunner()
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
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())

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
        runner = _RecordingRunner()

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
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
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
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 2
        assert all(t["status"] == "blocked" for t in tasks)

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

        results = _dispatch.dispatch_pod("demo", runner=_RecordingRunner())
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
