"""ROADMAP Phase 16 W-2: cancellation — `docket runs cancel <id>` actually
kills the in-flight hop's process group.

Layers covered:
  * ``edges.adapters.system.kill_process_group`` — the raw OS mechanics: a
    real process group (leader + a child it spawned) both die, and an
    already-dead pid is a harmless no-op.
  * ``edges.adapters.openclaw.agent_run``'s ``on_spawn`` hook — fires with
    the real subprocess pid before blocking, and a timeout kills the whole
    group (not just the immediate ``openclaw`` process) via the same
    mechanism.
  * ``core/runs.py``'s registry additions — ``current_run_id()``/
    ``add_hop_pid``/``remove_hop_pid`` (the pid-tracking side channel
    ``execute()`` and a parallel group's worker threads share via
    contextvars), ``cancel_run`` (unknown run, already-terminal run, a real
    kill), and that a concurrent cancel is never clobbered back to
    "succeeded" by the run's own normal completion.
  * End to end: a real dispatch run wrapped in ``runs.execute()``, cancelled
    mid-flight from another thread, actually kills the hop's subprocess and
    the task surfaces the failure through the ordinary R-1 state machine —
    no new task-status vocabulary needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import runs as _runs
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# ── edges.adapters.system.kill_process_group: raw OS mechanics ───────────────


class TestKillProcessGroup:
    def test_kills_the_leader_and_a_child_it_spawned(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "child.pid"
        proc = subprocess.Popen(
            ["bash", "-c", f"sleep 30 & echo $! > {pid_file}; wait"],
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        child_pid = int(pid_file.read_text().strip())

        assert _sys.kill_process_group(proc.pid) is True
        proc.wait(timeout=5)
        assert proc.returncode is not None and proc.returncode != 0

        # The child ("sleep 30") must not survive as an orphan.
        deadline = time.monotonic() + 3
        child_alive = True
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                child_alive = False
                break
            time.sleep(0.05)
        assert not child_alive, "the child process outlived the process-group kill"

    def test_already_dead_pid_is_a_harmless_noop(self) -> None:
        proc = subprocess.Popen(["true"], start_new_session=True)
        proc.wait(timeout=5)
        assert _sys.kill_process_group(proc.pid) is False


# ── agent_run's on_spawn hook ─────────────────────────────────────────────────


class TestAgentRunSpawnHook:
    def test_on_spawn_fires_with_a_real_pid_before_blocking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        script = bindir / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'output': 'ok', 'cost': 0.0}))\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

        seen: list[int] = []
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 30, on_spawn=seen.append)
        assert res.ok
        assert len(seen) == 1
        assert seen[0] > 0

    def test_no_on_spawn_kwarg_behaves_exactly_as_before(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        script = bindir / "openclaw"
        script.write_text(
            "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'output': 'ok', 'cost': 0.01}))\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 30)
        assert res.ok
        assert res.output == "ok"
        assert res.cost_usd == 0.01


class _FakeTimeoutPopen:
    """Mirrors test_r2_retries.py's fake — communicate() times out once."""

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        self.pid = 999_888_777
        self._calls = 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self._calls += 1
        if self._calls == 1:
            raise subprocess.TimeoutExpired(cmd=["openclaw"], timeout=timeout or 1)
        return "", ""


class TestAgentRunTimeoutKillsWholeGroup:
    def test_timeout_calls_kill_process_group_with_the_spawned_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/openclaw")
        monkeypatch.setattr(subprocess, "Popen", _FakeTimeoutPopen)
        killed: list[int] = []
        monkeypatch.setattr(
            _sys, "kill_process_group", lambda pid, **_kw: killed.append(pid) or True
        )
        res = _oc.agent_run("demo-lead", "agent:demo:t1", "plan", 1)
        assert res.failure_kind == "timeout"
        assert killed == [999_888_777]


# ── core/runs.py: pid tracking + cancel_run ───────────────────────────────────


@pytest.fixture(autouse=True)
def _hermetic_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)


class TestRunsPidTracking:
    def test_current_run_id_is_none_outside_execute(self) -> None:
        assert _runs.current_run_id() is None

    def test_execute_publishes_current_run_id_for_the_duration_of_fn(self) -> None:
        record = _runs.create_run("cli", "myapp")
        seen: list[str | None] = []

        class _Result:
            task_id = "t1"

        def _fn() -> list[Any]:
            seen.append(_runs.current_run_id())
            return [_Result()]

        _runs.execute(record["id"], _fn)
        assert seen == [record["id"]]
        assert _runs.current_run_id() is None  # reset after execute() returns

    def test_add_and_remove_hop_pid_round_trip(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.add_hop_pid(record["id"], 111)
        _runs.add_hop_pid(record["id"], 222)
        assert _runs.get_run(record["id"])["pids"] == [111, 222]

        _runs.remove_hop_pid(record["id"], 111)
        assert _runs.get_run(record["id"])["pids"] == [222]

    def test_add_hop_pid_is_idempotent(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.add_hop_pid(record["id"], 111)
        _runs.add_hop_pid(record["id"], 111)
        assert _runs.get_run(record["id"])["pids"] == [111]

    def test_add_remove_hop_pid_noop_for_unknown_run(self) -> None:
        # Must not raise -- a stale/racing caller is harmless.
        _runs.add_hop_pid("run-does-not-exist", 111)
        _runs.remove_hop_pid("run-does-not-exist", 111)


class TestCancelRun:
    def test_unknown_run_is_an_error_result(self) -> None:
        outcome = _runs.cancel_run("run-does-not-exist")
        assert outcome.ok is False
        assert "unknown run" in outcome.message

    def test_already_terminal_run_is_a_noop(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.finish_run(record["id"], state="succeeded", task_ids=[])
        outcome = _runs.cancel_run(record["id"])
        assert outcome.ok is False
        assert "already succeeded" in outcome.message
        # Not double-finished into "cancelled".
        assert _runs.get_run(record["id"])["state"] == "succeeded"

    def test_cancel_with_no_pids_still_marks_the_run_cancelled(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        outcome = _runs.cancel_run(record["id"])
        assert outcome.ok is True
        assert outcome.killed_pids == []
        assert _runs.get_run(record["id"])["state"] == "cancelled"

    def test_cancel_kills_a_real_recorded_process_group(self, tmp_path: Path) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
        _runs.add_hop_pid(record["id"], proc.pid)

        outcome = _runs.cancel_run(record["id"])
        assert outcome.ok is True
        assert outcome.killed_pids == [proc.pid]

        proc.wait(timeout=5)
        assert proc.returncode is not None
        assert _runs.get_run(record["id"])["state"] == "cancelled"
        assert _runs.get_run(record["id"])["pids"] == []

    def test_execute_does_not_clobber_a_concurrent_cancel(self) -> None:
        """If `cancel_run` marks the run cancelled while `fn()` is still in
        flight, `execute()`'s own normal completion must not flip it back to
        "succeeded" -- the whole point of a cancel outliving the run."""
        record = _runs.create_run("cli", "myapp")

        class _Result:
            task_id = "t1"

        def _fn() -> list[Any]:
            _runs.cancel_run(record["id"])  # simulates a concurrent cancel
            return [_Result()]

        results = _runs.execute(record["id"], _fn)
        assert results is not None  # execute() still returns fn()'s results
        assert _runs.get_run(record["id"])["state"] == "cancelled"


# ── end to end: a real dispatch run, cancelled mid-flight ────────────────────


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.rsplit("-", 1)[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _oc.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


@pytest.fixture(autouse=True)
def _hermetic_dispatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


class TestDispatchCancellationIntegration:
    def test_cancel_run_kills_the_in_flight_hop_and_the_task_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        script = bindir / "openclaw"
        # Sleeps well past the time this test needs to detect + cancel it.
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import time, json\n"
            "time.sleep(20)\n"
            "print(json.dumps({'output': 'too late', 'cost': 0.0}))\n"
        )
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

        _write_meta("myapp-lead")
        _dispatch.enqueue_task("myapp", "a slow task")
        record = _runs.create_run("cli", "myapp")

        outcome_holder: list[Any] = []

        def _go() -> None:
            outcome_holder.append(
                _runs.execute(record["id"], lambda: _dispatch.dispatch_pod("myapp"))
            )

        t = threading.Thread(target=_go)
        t.start()

        # Bounded wait for the hop's real subprocess pid to show up.
        deadline = time.monotonic() + 10
        pid: int | None = None
        while time.monotonic() < deadline:
            rec = _runs.get_run(record["id"])
            pids = rec.get("pids") if rec else []
            if pids:
                pid = pids[0]
                break
            time.sleep(0.05)
        assert pid is not None, "the hop's subprocess never recorded a pid in time"

        cancel_outcome = _runs.cancel_run(record["id"])
        assert cancel_outcome.ok is True
        assert pid in cancel_outcome.killed_pids

        t.join(timeout=15)
        assert not t.is_alive(), "dispatch thread never noticed the kill"

        # The subprocess itself is actually dead.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

        assert _runs.get_run(record["id"])["state"] == "cancelled"
        # The killed subprocess surfaces as an ordinary hop failure through
        # the existing R-1 state machine -- no new task-status vocabulary.
        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "failed"
