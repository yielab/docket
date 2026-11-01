"""A ``wait`` step ends when its time comes, not at the next periodic sweep, and the woken task
is dispatched in the same pass; a pod whose sweep is still running sweeps again when it ends."""

from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from tests.support.pods import build_pod
from tests.support.tasks import put_task, task

from docket.interfaces.http import server as _server
from docket.kernel import clock as _clock
from docket.kernel import threads as _threads
from docket.kernel.home import Home, use_home
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskWait

SUBJECT = "docket.interfaces.http.server"

# A periodic sweep that never comes within a test: only the wait's own deadline can wake the task.
_LONG_INTERVAL = 600


@pytest.fixture()
def home(tmp_path: Path) -> Iterator[None]:
    root = tmp_path / ".docket"
    (root / "state" / "workspaces" / "projects").mkdir(parents=True)
    (root / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(root)):
        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        yield


def _park(due_in_s: float, **wait: object) -> str:
    due = (_dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=due_in_s)).isoformat()
    put_task(
        "demo",
        task(
            id="task-w",
            status="waiting_input",
            created=_clock.iso(),
            wait=TaskWait(step="hold", dueAt=due, **wait),  # type: ignore[arg-type]
        ),
    )
    _escalations.open_for_wait(pod="demo", task_id="task-w", step="hold", prompt="x", due_at=due)
    return "task-w"


def _until(check: Callable[[], bool], within_s: float = 1.8) -> bool:
    end = time.monotonic() + within_s
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


def _status(task_id: str) -> str:
    record = TaskRepository.for_pod("demo").get(task_id)
    return record.status.value if record else ""


@pytest.fixture()
def sweep_loop() -> Iterator[Callable[[bool], None]]:
    stop = threading.Event()
    threads: list[threading.Thread] = []

    def _start(dispatch: bool) -> None:
        threads.append(_threads.start_thread(_server._sweep_loop, (_LONG_INTERVAL, stop, dispatch)))

    yield _start
    stop.set()
    for thread in threads:
        thread.join(timeout=5)


def test_a_wait_ends_at_its_deadline_between_periodic_sweeps(
    home: None, sweep_loop: Callable[[bool], None]
) -> None:
    task_id = _park(0.4)

    sweep_loop(False)

    assert _until(lambda: _status(task_id) == "pending")


def test_a_woken_wait_dispatches_its_pod_in_the_same_pass(
    home: None, sweep_loop: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted: list[str] = []
    monkeypatch.setattr(_server, "_submit_pod_sweep", lambda p, **_kw: submitted.append(p) or True)
    task_id = _park(0.4)

    sweep_loop(True)

    assert _until(lambda: _status(task_id) == "pending")
    assert _until(lambda: "demo" in submitted)


def test_a_pod_sweep_asked_for_while_one_runs_sweeps_again_when_it_ends(
    home: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    first_running, release = threading.Event(), threading.Event()

    def _claimable(project: str) -> bool:
        calls.append(project)
        if len(calls) == 1:
            first_running.set()
            assert release.wait(5)
        return False

    monkeypatch.setattr(_queue, "has_claimable_work", _claimable)

    assert _server._submit_pod_sweep("demo")
    assert first_running.wait(5)
    assert not _server._submit_pod_sweep("demo", rerun=True)
    release.set()

    assert _until(lambda: len(calls) == 2)
    assert _server._drain_sweeps(timeout=5)


def test_a_manual_dispatch_refused_for_a_running_sweep_does_not_queue_another(
    home: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    first_running, release = threading.Event(), threading.Event()

    def _claimable(project: str) -> bool:
        calls.append(project)
        first_running.set()
        assert release.wait(5)
        return False

    monkeypatch.setattr(_queue, "has_claimable_work", _claimable)

    assert _server._submit_pod_sweep("demo")
    assert first_running.wait(5)
    assert not _server._submit_pod_sweep("demo")
    release.set()

    assert _server._drain_sweeps(timeout=5)
    assert calls == ["demo"]


def test_a_probe_that_is_due_is_work_for_a_dispatching_sweep(home: None) -> None:
    past = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(seconds=5)).isoformat()
    _park(600, until="test -f ready", everyS=10, nextProbeAt=past)

    assert _queue.has_claimable_work("demo")


def test_a_probe_not_yet_due_is_no_work(home: None) -> None:
    future = (_dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=500)).isoformat()
    _park(600, until="test -f ready", everyS=10, nextProbeAt=future)

    assert not _queue.has_claimable_work("demo")
