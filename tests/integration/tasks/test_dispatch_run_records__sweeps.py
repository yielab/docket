"""The sweep loop dispatch path records a run (``serve._run_sweeps(dispatch=True)``).

Split from ``test_dispatch_run_records.py``, which covers the CLI, webhook and schedule paths.
``dispatch_pod`` is monkeypatched at the call site to stay hermetic -- pipeline internals are
covered by ``test_dispatch.py``; this file only checks the invocation got recorded.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.pods import build_pod
from tests.support.pods import seed_pod as _seed_pod

from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http import server as _server
from docket.interfaces.http import sweeps as _sweeps
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import new_thread
from docket.tasks.application import runs as _runs
from docket.tasks.domain import task as _task

SUBJECT = "docket.tasks.application.runs"


# ── sweep loop dispatch path ──────────────────────────────────────────────────


@pytest.fixture
def _every_pod_has_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sweep tests fake ``dispatch_pod``; a pod with no queued task would be skipped first."""
    monkeypatch.setattr("docket.tasks.application.queue.has_claimable_work", lambda _p: True)


@pytest.mark.usefixtures("_every_pod_has_work")
class TestSweepDispatchPath:
    def test_sweep_dispatches_every_pod_and_records_a_run_each(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with (
            _seed_pod(tmp_path, project="sweepdemo"),
            use_home(
                dataclasses.replace(current_home(), approvals_dir_override=tmp_path / "approvals")
            ),
        ):

            def _fake_dispatch_pod(proj: str, **kw: object) -> list[_task.TaskResult]:
                return [_task.TaskResult(task_id="task-sweep", status="done")]

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake_dispatch_pod)

            _server._run_sweeps(dispatch=True)
            assert _sweeps._drain_sweeps(timeout=10)

            records = _runs.list_runs("sweepdemo")
            assert len(records) == 1
            assert records[0]["source"] == "sweep"
            assert records[0]["state"] == "succeeded"

    def test_one_pod_exploding_does_not_stop_the_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A per-pod exception must not abort dispatch for other pods, and the
        sweep call itself must never raise (it runs on a daemon thread with no
        one to catch it)."""
        with _seed_pod(tmp_path, project="pod-a"):
            build_pod("pod-b", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/pod-b")
            with use_home(
                dataclasses.replace(current_home(), approvals_dir_override=tmp_path / "approvals")
            ):

                def _selective_boom(proj: str, **kw: object) -> list[_task.TaskResult]:
                    if proj == "pod-a":
                        raise RuntimeError("pod-a exploded")
                    return [_task.TaskResult(task_id="task-b", status="done")]

                monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _selective_boom)

                _server._run_sweeps(dispatch=True)
                assert _sweeps._drain_sweeps(timeout=10)  # must not raise

                a_records = _runs.list_runs("pod-a")
                b_records = _runs.list_runs("pod-b")
                assert len(a_records) == 1 and a_records[0]["state"] == "failed"
                assert "pod-a exploded" in a_records[0]["error"]
                assert len(b_records) == 1 and b_records[0]["state"] == "succeeded"


@pytest.mark.usefixtures("_every_pod_has_work")
class TestSweepWorkers:
    """The real ``_run_sweeps`` with a fake per-pod dispatch that blocks on an Event."""

    @staticmethod
    @contextmanager
    def _two_pods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        with _seed_pod(tmp_path, project="pod-a"):
            build_pod("pod-b", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/pod-b")
            monkeypatch.setattr(
                "docket.tasks.application.queue.dispatchable_pods",
                lambda: ["pod-a", "pod-b"],
                raising=True,
            )
            with use_home(
                dataclasses.replace(current_home(), approvals_dir_override=tmp_path / "approvals")
            ):
                yield

    def test_a_blocked_pod_does_not_stall_the_others(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with self._two_pods(tmp_path, monkeypatch):
            release = threading.Event()
            b_done = threading.Event()

            def _fake(proj: str, **kw: object) -> list[_task.TaskResult]:
                if proj == "pod-a":
                    assert release.wait(10)
                else:
                    b_done.set()
                return [_task.TaskResult(task_id=f"t-{proj}", status="done")]

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake)
            try:
                _server._run_sweeps(dispatch=True)
                assert b_done.wait(10), "pod-b never ran while pod-a was blocked"
                assert _sweeps._drain_sweeps(timeout=0.05) is False
            finally:
                release.set()
            assert _sweeps._drain_sweeps(timeout=10)
            assert _runs.list_runs("pod-a")[0]["state"] == "succeeded"
            assert _runs.list_runs("pod-b")[0]["state"] == "succeeded"

    def test_a_second_tick_skips_a_pod_still_in_flight(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with self._two_pods(tmp_path, monkeypatch):
            release = threading.Event()
            started = threading.Event()
            calls: list[str] = []

            def _fake(proj: str, **kw: object) -> list[_task.TaskResult]:
                calls.append(proj)
                if proj == "pod-a":
                    started.set()
                    assert release.wait(10)
                return []

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake)
            try:
                _server._run_sweeps(dispatch=True)
                assert started.wait(10)
                _server._run_sweeps(dispatch=True)
            finally:
                release.set()
            assert _sweeps._drain_sweeps(timeout=10)
            assert calls.count("pod-a") == 1
            assert len(_runs.list_runs("pod-a")) == 1

    def test_one_worker_is_serial(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with (
            self._two_pods(tmp_path, monkeypatch),
            use_home(dataclasses.replace(current_home(), dispatch_sweep_workers=1)),
        ):
            release = threading.Event()
            started: list[str] = []
            a_started = threading.Event()

            def _fake(proj: str, **kw: object) -> list[_task.TaskResult]:
                started.append(proj)
                if proj == "pod-a":
                    a_started.set()
                    assert release.wait(10)
                return []

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake)
            try:
                _server._run_sweeps(dispatch=True)
                assert a_started.wait(10)
                assert _sweeps._drain_sweeps(timeout=0.2) is False
                assert started == ["pod-a"]
            finally:
                release.set()
            assert _sweeps._drain_sweeps(timeout=10)
            assert started == ["pod-a", "pod-b"]

    def test_stop_waits_for_in_flight_sweeps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with self._two_pods(tmp_path, monkeypatch):
            release = threading.Event()
            started = threading.Event()
            finished = threading.Event()

            def _fake(proj: str, **kw: object) -> list[_task.TaskResult]:
                if proj == "pod-a":
                    started.set()
                    assert release.wait(10)
                    finished.set()
                return []

            monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake)
            monkeypatch.setattr(_sweeps, "check_schedules", lambda _now: None)
            stop = threading.Event()
            loop = new_thread(target=_server._sweep_loop, args=(0.01, stop, True), daemon=True)
            loop.start()
            try:
                assert started.wait(10)
                stop.set()
                loop.join(timeout=0.3)
                assert loop.is_alive(), "stop returned while a sweep was in flight"
            finally:
                release.set()
            loop.join(timeout=10)
            assert not loop.is_alive()
            assert finished.is_set()
