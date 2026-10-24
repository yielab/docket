"""SUBJECT: interfaces.http.server.run_serve -- a second stop signal abandons a blocked sweep (subprocess)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import record_isolation_off, register_local_provider
from tests.support.llm import _final_response, _ScriptedLLMServer
from tests.support.pods import build_pod

from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http import server as _server
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

SUBJECT = "docket.interfaces.http.server"

_DRIVER = textwrap.dedent(
    """
    import threading
    import docket.tasks.application.queue as q
    import docket.hops.application.sweep as d
    from docket.interfaces.http import server

    release = threading.Event()
    q.dispatchable_pods = lambda: ["pod-x"]
    q.has_claimable_work = lambda project: True

    def _blocked(project, **kw):
        print("SWEEP-BLOCKED", flush=True)
        release.wait(60)
        return []

    d.dispatch_pod = _blocked
    server.run_serve(port=0, interval=3600, dispatch=True)
    """
)


def _read_until(proc: subprocess.Popen[str], needle: str) -> list[str]:
    seen: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        seen.append(line.rstrip())
        if needle in line:
            return seen
    raise AssertionError(f"never saw {needle!r}; got {seen}")


def test_second_sigint_abandons_a_blocked_sweep(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "DOCKET_HOME": str(home),
        "DOCKET_SERVE_TOKEN": "t",
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", _DRIVER],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _read_until(proc, "SWEEP-BLOCKED")
        proc.send_signal(signal.SIGINT)
        _read_until(proc, "signal again to abandon")
        time.sleep(1)
        assert proc.poll() is None, "the first signal must wait for the in-flight sweep"
        proc.send_signal(signal.SIGINT)
        code = proc.wait(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert code == 130
    runs = json.loads((home / "docket-runs.json").read_text())["runs"]
    assert len(runs) == 1
    assert runs[0]["cancellation"]["requestedAt"]


_SOLO = "name: solo\nsteps:\n  - kickoff: lead\n"
_TWO = "name: two\nsteps:\n  - kickoff: lead\n  - assemble: implementer\n"


@pytest.fixture()
def sweep_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / ".docket"
    (root / "workspaces" / "projects").mkdir(parents=True)
    (root / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(root)):
        record_isolation_off(root)
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(tmp_path))
        _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
        _fleet.meta_set("demo-implementer", "verifyCmd", "")
        pipelines = current_home().pod_config_dir("demo") / "pipelines"
        pipelines.mkdir(parents=True, exist_ok=True)
        (pipelines / "solo.yaml").write_text(_SOLO, encoding="utf-8")
        (pipelines / "two.yaml").write_text(_TWO, encoding="utf-8")
        yield root


def _wire(home: Path, server: _ScriptedLLMServer) -> None:
    register_local_provider(
        home, "local", [{"id": "stub", "contextWindow": 16384, "maxTokens": 4096}], server.base_url
    )
    for member in ("demo-lead", "demo-implementer"):
        _fleet.meta_set(member, "model", "local/stub")


def _write_tasks(tasks: list[dict[str, Any]]) -> None:
    from docket.platform import store as _store

    _store.write_json(_settings.pod_task_list_path("demo"), {"tasks": tasks})


def test_first_signal_finishes_only_the_running_task(
    sweep_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the stop set during the first hop, one task ends terminal and two stay pending."""
    stop = threading.Event()
    monkeypatch.setattr(_server, "sweep_stop", stop)
    server = _ScriptedLLMServer([_final_response("done")], on_request=lambda _r: stop.set())
    try:
        _wire(sweep_home, server)
        _write_tasks(
            [
                {"id": f"task-{i}", "description": "x", "status": "pending", "pipeline": "solo"}
                for i in (1, 2, 3)
            ]
        )

        _server._sweep_one_pod("demo")
    finally:
        server.stop()

    statuses = sorted(t["status"] for t in _queue.read_tasks("demo"))
    assert statuses == ["done", "pending", "pending"]
    assert len(server.requests) == 1


def test_a_dead_claim_is_reclaimed_by_the_next_sweep_and_resumes_after_its_first_hop(
    sweep_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running task with a dead claimant is settled stale and continued from hop two."""
    monkeypatch.setattr(_server, "sweep_stop", threading.Event())
    server = _ScriptedLLMServer([_final_response("done")])
    try:
        _wire(sweep_home, server)
        hop = _task.HopResult(
            role="lead", member_id="demo-lead", ok=True, output="plan", step_id="kickoff"
        )
        _write_tasks(
            [
                {
                    "id": "task-1",
                    "description": "x",
                    "status": "running",
                    "pipeline": "two",
                    "claimPid": 2**22 + 12345,
                    "claimedAt": _clock.iso(),
                    "hops": [hop.model_dump(by_alias=True, mode="json")],
                }
            ]
        )

        _server._sweep_one_pod("demo")
    finally:
        server.stop()

    task = _queue.read_tasks("demo")[0]
    assert task["status"] == "done", task.get("reason")
    assert [h["stepId"] for h in task["hops"]] == ["kickoff", "assemble"]
    assert len(server.requests) == 1


def test_an_idle_sweep_records_no_run(sweep_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sweep with nothing to claim writes no run record; one with a pending task writes one."""
    monkeypatch.setattr(_server, "sweep_stop", threading.Event())
    _write_tasks([{"id": "task-1", "description": "x", "status": "done", "pipeline": "solo"}])

    for _ in range(10):
        _server._sweep_one_pod("demo")

    assert _runs.list_runs() == []
    _write_tasks([{"id": "task-2", "description": "x", "status": "pending", "pipeline": "nope"}])
    _server._sweep_one_pod("demo")
    assert [r["source"] for r in _runs.list_runs()] == ["sweep"]
