"""Cancellation — `docket runs cancel <id>` actually kills the in-flight
hop's process group.

Layers covered:
  * ``edges.adapters.system.kill_process_group`` — the raw OS mechanics: a
    real process group (leader + a child it spawned) both die, and an
    already-dead pid is a harmless no-op.
  * ``core/runs.py``'s registry additions — ``current_run_id()``/
    ``add_hop_pid``/``remove_hop_pid`` (the pid-tracking side channel
    ``execute()`` and a parallel group's worker threads share via
    contextvars), ``cancel_run`` (unknown run, already-terminal run, a real
    kill), and that a concurrent cancel is never clobbered back to
    "succeeded" by the run's own normal completion.

There is no driver that spawns an OS process per hop: the production
``DocketDriver`` makes in-process HTTP calls and never fires ``on_spawn``
(see its own docstring), so a dispatch hop cannot be killed mid-flight by
`docket runs cancel` today — the run registry still marks it "cancelled"
honestly ("nothing in flight to kill"), but no in-flight call is
interrupted. That is a named, permanent capability gap (there is no
subprocess-spawning driver to prove otherwise against), not something to
paper over by inventing a fake one. ``TestKillProcessGroup`` and
``TestCancelRun`` below still prove the OS-level kill primitive and the
run-registry bookkeeping work correctly in isolation — the only gap is that
no production code path currently connects a real pid to them.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import runs as _runs
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
