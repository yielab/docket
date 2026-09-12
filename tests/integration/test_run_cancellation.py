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

The production ``DocketDriver`` makes in-process HTTP calls and never fires
``on_spawn`` (see its own docstring), so cooperative checkpoints stop its turn
at safe boundaries while already-running backend computation returns. A
running record therefore persists a request and stays nonterminal until its
owning executor returns; PID signalling alone is not a truthful full-stop
oracle. The whole driver/dispatch path is covered in
``test_cooperative_run_cancellation.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import runs as _runs
from docket.edges import store as _store
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
        signals: list[_runs.RunCancellationSignal | None] = []

        class _Result:
            task_id = "t1"

        def _fn() -> list[Any]:
            seen.append(_runs.current_run_id())
            signals.append(_runs.current_cancellation_signal())
            return [_Result()]

        _runs.execute(record["id"], _fn)
        assert seen == [record["id"]]
        assert signals == [_runs.RunCancellationSignal(record["id"])]
        assert signals[0] is not None and signals[0].is_requested() is False
        assert _runs.current_run_id() is None  # reset after execute() returns
        assert _runs.current_cancellation_signal() is None

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

    @pytest.mark.parametrize("terminal_state", ["succeeded", "failed", "cancelled"])
    def test_already_terminal_run_is_a_noop(self, terminal_state: str) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.finish_run(
            record["id"],
            state=terminal_state,  # type: ignore[arg-type]
            task_ids=[],
        )
        outcome = _runs.cancel_run(record["id"])
        assert outcome.ok is False
        assert f"already {terminal_state}" in outcome.message
        # Not double-finished into "cancelled".
        assert _runs.get_run(record["id"])["state"] == terminal_state

    def test_queued_cancel_is_fully_stopped_in_one_persisted_transition(self) -> None:
        record = _runs.create_run("cli", "myapp")

        def _add_unknown_field(doc: dict[str, Any]) -> dict[str, Any]:
            doc["runs"][0]["futureField"] = {"preserve": True}
            return doc

        _store.read_modify_write(_cfg.RUNS_FILE, _add_unknown_field)
        outcome = _runs.cancel_run(record["id"])

        assert outcome.ok is True
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "cancelled"
        lifecycle = persisted["cancellation"]
        assert lifecycle["requestedAt"] is not None
        assert lifecycle["observedAt"] is not None
        assert lifecycle["stoppedAt"] is not None
        assert lifecycle["reason"] == "operator request"
        assert lifecycle["source"] == "cli"
        assert persisted["futureField"] == {"preserve": True}

    def test_running_cancel_with_no_pids_remains_requested_not_stopped(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        outcome = _runs.cancel_run(record["id"])
        assert outcome.ok is True
        assert outcome.killed_pids == []
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "running"
        assert persisted["finishedAt"] is None
        assert persisted["cancellation"]["requestedAt"] is not None
        assert persisted["cancellation"]["observedAt"] is None
        assert persisted["cancellation"]["stoppedAt"] is None

    def test_repeated_running_request_does_not_resignal_or_reaudit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        _runs.add_hop_pid(record["id"], 4242)
        killed: list[int] = []
        audited: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _sys,
            "kill_process_group",
            lambda pid: killed.append(pid) or True,
        )
        monkeypatch.setattr(
            _runs,
            "audit_log",
            lambda action, detail: audited.append((action, detail)),
        )

        first = _runs.cancel_run(record["id"])
        after_first = _runs.get_run(record["id"])
        second = _runs.cancel_run(record["id"])
        after_second = _runs.get_run(record["id"])

        assert first.ok is True
        assert second.ok is False
        assert killed == [4242]
        assert len(audited) == 1
        assert after_first == after_second
        assert after_second is not None
        assert after_second["state"] == "running"
        assert after_second["cancellation"]["requestedAt"] is not None
        assert after_second["cancellation"]["observedAt"] is None
        assert after_second["cancellation"]["stoppedAt"] is None

    def test_signal_observation_is_persisted_and_idempotent(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        assert _runs.cancel_run(record["id"]).ok is True
        signal = _runs.RunCancellationSignal(record["id"])

        assert signal.is_requested() is True
        assert signal.observe() is True
        observed = _runs.get_run(record["id"])
        assert observed is not None
        assert observed["state"] == "running"
        assert observed["cancellation"]["observedAt"] is not None
        assert observed["cancellation"]["stoppedAt"] is None

        assert signal.observe() is True
        assert _runs.get_run(record["id"]) == observed

    def test_observation_and_stop_emit_each_lifecycle_trace_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        events: list[str] = []
        monkeypatch.setattr(
            "docket.core.trace.trace_event",
            lambda _project, _session, _role, event, _payload: events.append(event) or "written",
        )
        assert _runs.cancel_run(record["id"]).ok is True
        signal = _runs.RunCancellationSignal(record["id"])

        assert signal.observe() is True
        assert signal.observe() is True
        assert _runs._finish_run_transition(record["id"], state="succeeded") is False
        assert _runs._finish_run_transition(record["id"], state="succeeded") is False

        assert events.count("run_cancellation_observed") == 1
        assert events.count("run_cancelled") == 1

    def test_terminal_finish_wins_when_it_commits_before_cancel_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        real_read_modify_write = _store.read_modify_write
        cancel_reached_transition = threading.Event()
        release_cancel = threading.Event()
        staged = False

        def _stage_cancel_transition(path: Path, fn: Any) -> dict[str, Any]:
            nonlocal staged
            if threading.current_thread().name == "cancel-worker" and not staged:
                staged = True
                cancel_reached_transition.set()
                assert release_cancel.wait(timeout=5)
            return real_read_modify_write(path, fn)

        monkeypatch.setattr(_store, "read_modify_write", _stage_cancel_transition)
        outcomes: list[_runs.CancelOutcome] = []
        worker = threading.Thread(
            target=lambda: outcomes.append(_runs.cancel_run(record["id"])),
            name="cancel-worker",
        )
        worker.start()
        try:
            assert cancel_reached_transition.wait(timeout=5)
            assert _runs._finish_run_transition(record["id"], state="succeeded") is True
        finally:
            release_cancel.set()
            worker.join(timeout=5)

        assert not worker.is_alive()
        assert len(outcomes) == 1
        assert outcomes[0].ok is False
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "succeeded"
        assert persisted.get("cancellation", {}).get("requestedAt") is None

    def test_separate_process_request_stays_visible_until_execute_stops(
        self, tmp_path: Path
    ) -> None:
        record = _runs.create_run("cli", "myapp")
        body_started = threading.Event()
        release_body = threading.Event()
        body_observed: list[bool] = []

        def _blocked_body() -> list[Any]:
            signal = _runs.current_cancellation_signal()
            assert signal is not None
            body_started.set()
            assert release_body.wait(timeout=10)
            body_observed.append(signal.is_requested())
            return []

        executor = threading.Thread(
            target=lambda: _runs.execute(record["id"], _blocked_body),
            name="run-executor",
        )
        executor.start()
        try:
            assert body_started.wait(timeout=5)
            env = os.environ.copy()
            env["DOCKET_HOME"] = str(tmp_path)
            env["RUNS_FILE"] = str(_cfg.RUNS_FILE)
            code = (
                "import json; from dataclasses import asdict; "
                "from docket.core.runs import cancel_run; "
                f"print(json.dumps(asdict(cancel_run({record['id']!r}))))"
            )
            completed = subprocess.run(
                [sys.executable, "-c", code],
                check=True,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            assert json.loads(completed.stdout)["ok"] is True

            requested = _runs.get_run(record["id"])
            assert requested is not None
            assert requested["state"] == "running"
            assert requested["cancellation"]["requestedAt"] is not None
            assert requested["cancellation"]["observedAt"] is None
            assert requested["cancellation"]["stoppedAt"] is None
        finally:
            release_body.set()
            executor.join(timeout=10)

        assert not executor.is_alive()
        assert body_observed == [True]
        stopped = _runs.get_run(record["id"])
        assert stopped is not None
        assert stopped["state"] == "cancelled"
        assert stopped["cancellation"]["observedAt"] is not None
        assert stopped["cancellation"]["stoppedAt"] is not None

    def test_malformed_lifecycle_fails_closed_without_a_stopped_claim(self) -> None:
        record = _runs.create_run("cli", "myapp")
        _runs.mark_running(record["id"])
        malformed = {
            "requestedAt": ["not", "a", "timestamp"],
            "observedAt": None,
            "stoppedAt": None,
            "reason": "operator request",
            "source": "cli",
        }

        def _corrupt(doc: dict[str, Any]) -> dict[str, Any]:
            doc["runs"][0]["cancellation"] = malformed
            return doc

        _store.read_modify_write(_cfg.RUNS_FILE, _corrupt)
        signal = _runs.RunCancellationSignal(record["id"])
        assert signal.is_requested() is True
        assert signal.observe() is True
        assert _runs.get_run(record["id"])["cancellation"] == malformed
        outcome = _runs.cancel_run(record["id"])

        assert outcome.ok is False
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "running"
        assert persisted["finishedAt"] is None
        assert persisted["cancellation"] == malformed

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
        requested = _runs.get_run(record["id"])
        assert requested is not None
        assert requested["state"] == "running"
        assert requested["pids"] == []
        assert requested["cancellation"]["requestedAt"] is not None
        assert requested["cancellation"]["stoppedAt"] is None

        # PID death is not the full-stop oracle; the owner records stop while
        # folding its eventual return/exception.
        assert _runs._finish_run_transition(record["id"], state="failed") is False
        stopped = _runs.get_run(record["id"])
        assert stopped is not None
        assert stopped["state"] == "cancelled"
        assert stopped["cancellation"]["observedAt"] is not None
        assert stopped["cancellation"]["stoppedAt"] is not None

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
