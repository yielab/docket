"""Every dispatch path yields a queryable run record.

Covers the four ways a pod dispatch can be triggered — CLI (`docket pod <p>
dispatch`), the serve webhook (`POST /dispatch/<project>`), a due schedule
(`serve._check_schedules`), and the sweep loop (`serve._run_sweeps(dispatch=True)`)
— and proves each one:

  1. creates a run record in ``core.runs`` (queryable via ``get_run``/``list_runs``)
  2. records a success outcome when dispatch succeeds
  3. records a failure outcome (with the exception text) when dispatch raises,
     WITHOUT the exception propagating out and killing the caller (CLI prints
     an error and exits 1 like any other command failure; webhook/schedule/
     sweep never crash their thread/loop)

``docket.core.dispatch.dispatch_pod`` is monkeypatched directly at each call
site (the same technique ``test_cd6_dispatch_triggers.py`` already uses) so
these tests stay fast and hermetic — the pipeline's own internals (hop order,
budget gating, ...) are covered by ``test_dispatch.py``; this file is only
about "did the invocation get recorded".
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import typer

import docket.config as _cfg
import docket.serve as _serve
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import runs as _runs
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-r3-runs"


# ── hermetic pod fixture (mirrors test_dispatch.py's _seed_pod) ──────────────


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
    monkeypatch.setattr(_cfg, "RUNS_FILE", home / "docket-runs.json", raising=True)
    monkeypatch.setattr(_cfg, "SCHEDULE_FILE", home / "docket-schedules.json", raising=True)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _wait_for_terminal_run(run_id: str, timeout: float = 3.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rec = _runs.get_run(run_id)
        if rec is not None and rec["state"] in ("succeeded", "failed"):
            return rec
        time.sleep(0.02)
    raise AssertionError(f"run {run_id!r} never reached a terminal state")


# ── CLI dispatch path ─────────────────────────────────────────────────────────


class TestCliDispatchPath:
    def test_success_creates_a_succeeded_run_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _dispatch.enqueue_task("demo", "do the thing")

        def _fake_dispatch_pod(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            return [_dispatch.TaskResult(task_id="task-x", status="done")]

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

        _pod.dispatch("demo", "dispatch", [])

        records = _runs.list_runs("demo")
        assert len(records) == 1
        assert records[0]["source"] == "cli"
        assert records[0]["state"] == "succeeded"
        assert records[0]["taskIds"] == ["task-x"]

    def test_exception_is_recorded_and_cli_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _dispatch.enqueue_task("demo", "do the thing")

        def _boom(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            raise RuntimeError("daemon exploded")

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _boom)

        with pytest.raises(typer.Exit) as excinfo:
            _pod.dispatch("demo", "dispatch", [])
        assert excinfo.value.exit_code == 1

        records = _runs.list_runs("demo")
        assert len(records) == 1
        assert records[0]["source"] == "cli"
        assert records[0]["state"] == "failed"
        assert "daemon exploded" in records[0]["error"]


# ── serve webhook dispatch path ───────────────────────────────────────────────


def _post(
    url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    _point_at(tmp_path / ".docket", monkeypatch)
    (tmp_path / ".docket").mkdir(exist_ok=True)
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d, raising=True)

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


class TestWebhookDispatchPath:
    def test_response_carries_run_id_and_run_succeeds(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server

        def _fake_dispatch_pod(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            return [_dispatch.TaskResult(task_id="task-web", status="done")]

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

        status, body = _post(f"{url}/dispatch/myproject", token=token)
        assert status == 200
        assert body["ok"] is True
        assert body["project"] == "myproject"
        run_id = body["run"]
        assert isinstance(run_id, str) and run_id.startswith("run-")

        rec = _wait_for_terminal_run(run_id)
        assert rec["state"] == "succeeded"
        assert rec["source"] == "webhook"
        assert rec["taskIds"] == ["task-web"]

    def test_exception_is_recorded_without_crashing_the_thread(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server

        def _boom(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            raise RuntimeError("webhook dispatch exploded")

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _boom)

        status, body = _post(f"{url}/dispatch/myproject", token=token)
        assert status == 200  # webhook still returns immediately
        run_id = body["run"]

        rec = _wait_for_terminal_run(run_id)
        assert rec["state"] == "failed"
        assert "webhook dispatch exploded" in rec["error"]

        # The dispatch thread's exception must not have taken the server down.
        with urllib.request.urlopen(f"{url}/health", timeout=5) as resp:
            assert resp.status == 200

    def test_no_auth_rejected_before_any_run_is_created(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        before = len(_runs.list_runs())
        status, body = _post(f"{url}/dispatch/myproject")
        assert status == 401
        assert body["ok"] is False
        assert len(_runs.list_runs()) == before


# ── GET /runs endpoints ───────────────────────────────────────────────────────


class TestRunsReadEndpoints:
    def test_get_runs_by_id_requires_auth(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        req = urllib.request.Request(f"{url}/runs/run-whatever")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 401

    def test_get_runs_by_id_returns_record(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        rec = _runs.create_run("cli", "someproj")
        req = urllib.request.Request(f"{url}/runs/{rec['id']}")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
        assert body["id"] == rec["id"]
        assert body["project"] == "someproj"

    def test_get_runs_by_id_unknown_is_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        req = urllib.request.Request(f"{url}/runs/run-does-not-exist")
        req.add_header("Authorization", f"Bearer {token}")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 404

    def test_get_runs_list_requires_auth(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        req = urllib.request.Request(f"{url}/runs")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 401

    def test_get_runs_list_filters_by_project_query_param(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _runs.create_run("cli", "alpha")
        _runs.create_run("cli", "beta")

        req = urllib.request.Request(f"{url}/runs?project=alpha")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
        assert all(r["project"] == "alpha" for r in body["runs"])
        assert len(body["runs"]) == 1


# ── schedule-triggered dispatch path ──────────────────────────────────────────


class TestScheduleDispatchPath:
    def test_due_schedule_creates_a_run_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        _cfg.SCHEDULE_FILE.write_text(json.dumps({"schedules": {"projA": "@every 1s"}}))

        def _fake_dispatch_pod(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            return [_dispatch.TaskResult(task_id="task-sched", status="done")]

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

        _serve._check_schedules(time.time())

        deadline = time.time() + 2
        records: list[dict[str, Any]] = []
        while time.time() < deadline:
            records = _runs.list_runs("projA")
            if records and records[0]["state"] in ("succeeded", "failed"):
                break
            time.sleep(0.02)

        assert len(records) == 1
        assert records[0]["source"] == "schedule"
        assert records[0]["state"] == "succeeded"

    def test_exception_in_scheduled_dispatch_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _point_at(tmp_path / ".docket", monkeypatch)
        (tmp_path / ".docket").mkdir(exist_ok=True)
        _cfg.SCHEDULE_FILE.write_text(json.dumps({"schedules": {"projB": "@every 1s"}}))

        def _boom(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            raise RuntimeError("schedule dispatch exploded")

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _boom)

        _serve._check_schedules(time.time())

        deadline = time.time() + 2
        records: list[dict[str, Any]] = []
        while time.time() < deadline:
            records = _runs.list_runs("projB")
            if records and records[0]["state"] == "failed":
                break
            time.sleep(0.02)

        assert len(records) == 1
        assert "schedule dispatch exploded" in records[0]["error"]


# ── sweep loop dispatch path ──────────────────────────────────────────────────


class TestSweepDispatchPath:
    def test_sweep_dispatches_every_pod_and_records_a_run_each(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="sweepdemo")
        monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)

        def _fake_dispatch_pod(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            return [_dispatch.TaskResult(task_id="task-sweep", status="done")]

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

        _serve._run_sweeps(dispatch=True)

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
        _seed_pod(tmp_path, monkeypatch, project="pod-a")
        _pod.build_pod("pod-b", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/pod-b")
        monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)

        def _selective_boom(proj: str, **kw: object) -> list[_dispatch.TaskResult]:
            if proj == "pod-a":
                raise RuntimeError("pod-a exploded")
            return [_dispatch.TaskResult(task_id="task-b", status="done")]

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _selective_boom)

        _serve._run_sweeps(dispatch=True)  # must not raise

        a_records = _runs.list_runs("pod-a")
        b_records = _runs.list_runs("pod-b")
        assert len(a_records) == 1 and a_records[0]["state"] == "failed"
        assert "pod-a exploded" in a_records[0]["error"]
        assert len(b_records) == 1 and b_records[0]["state"] == "succeeded"
