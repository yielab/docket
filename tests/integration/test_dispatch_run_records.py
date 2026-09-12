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
site (the same technique ``test_scheduled_and_webhook_dispatch.py`` already uses) so
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
from docket.edges import store as _store
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
        if rec is not None and rec["state"] in ("succeeded", "failed", "cancelled"):
            return rec
        time.sleep(0.02)
    raise AssertionError(f"run {run_id!r} never reached a terminal state")


# ── shared returned-result fold ──────────────────────────────────────────────


class TestReturnedResultFold:
    def test_returned_failed_task_marks_run_failed_and_emits_error_trace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        trace_calls: list[tuple[object, ...]] = []

        def _capture_trace(*args: object, **_kwargs: object) -> str:
            trace_calls.append(args)
            return "written"

        monkeypatch.setattr("docket.core.trace.trace_event", _capture_trace)
        record = _runs.create_run("cli", "demo")
        task = _dispatch.TaskResult(
            task_id="task-failed",
            status="failed",
            reason="turn budget exhausted",
        )

        returned = _runs.execute(record["id"], lambda: [task])

        assert returned == [task]
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "failed"
        assert persisted["taskIds"] == ["task-failed"]
        assert "task-failed" in persisted["error"]
        assert "turn budget exhausted" in persisted["error"]
        assert len(trace_calls) == 1
        assert trace_calls[0][3] == "error"
        assert json.loads(str(trace_calls[0][4]))["error"] == persisted["error"]

    def test_failed_wins_a_mixed_result_and_preserves_every_task_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        record = _runs.create_run("webhook", "demo")
        results = [
            _dispatch.TaskResult(task_id="task-done", status="done"),
            _dispatch.TaskResult(task_id="task-wait", status="waiting_approval"),
            _dispatch.TaskResult(
                task_id="task-failed", status="failed", reason="verify gate\nfailed"
            ),
            _dispatch.TaskResult(task_id="task-blocked", status="blocked"),
        ]

        returned = _runs.execute(record["id"], lambda: results)

        assert returned == results
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "failed"
        assert persisted["taskIds"] == [result.task_id for result in results]
        assert "task-failed: verify gate failed" in persisted["error"]

    @pytest.mark.parametrize(
        "results",
        [
            [],
            [
                _dispatch.TaskResult(task_id="task-done", status="done"),
                _dispatch.TaskResult(task_id="task-wait", status="waiting_approval"),
                _dispatch.TaskResult(task_id="task-blocked", status="blocked"),
            ],
        ],
    )
    def test_nonfailed_returned_statuses_keep_invocation_successful(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        results: list[_dispatch.TaskResult],
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        record = _runs.create_run("cli", "demo")

        returned = _runs.execute(record["id"], lambda: results)

        assert returned == results
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "succeeded"
        assert persisted["taskIds"] == [result.task_id for result in results]
        assert persisted["error"] == ""

    def test_failure_summary_is_bounded_and_a_concurrent_cancel_still_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        record = _runs.create_run("cli", "demo")
        results = [
            _dispatch.TaskResult(
                task_id=f"task-{index}",
                status="failed",
                reason=f"reason {index} " + ("x" * 2_000) + " RAW_TAIL_SENTINEL",
            )
            for index in range(20)
        ]

        def _cancel_then_return() -> list[_dispatch.TaskResult]:
            _runs.cancel_run(record["id"])
            return results

        returned = _runs.execute(record["id"], _cancel_then_return)

        assert returned == results
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "cancelled"
        assert persisted["error"] == "cancelled by operator"

        uncancelled = _runs.create_run("cli", "demo")
        _runs.execute(uncancelled["id"], lambda: results)
        failed = _runs.get_run(uncancelled["id"])
        assert failed is not None
        assert failed["state"] == "failed"
        assert failed["taskIds"] == [result.task_id for result in results]
        assert len(failed["error"]) <= 1_024
        assert "RAW_TAIL_SENTINEL" not in failed["error"]
        assert "more" in failed["error"]

    def test_execute_folds_the_returned_list_exactly_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        record = _runs.create_run("cli", "demo")

        class CountingResults(list[_dispatch.TaskResult]):
            iterations = 0

            def __iter__(self):  # type: ignore[no-untyped-def]
                self.iterations += 1
                return super().__iter__()

        results = CountingResults(
            [_dispatch.TaskResult(task_id="task-failed", status="failed", reason="broken")]
        )

        _runs.execute(record["id"], lambda: results)

        assert results.iterations == 1

    def test_cancel_between_fold_and_terminal_write_cannot_be_clobbered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        record = _runs.create_run("cli", "demo")
        real_read_modify_write = _store.read_modify_write
        writes = 0

        def _inject_cancel_before_second_write(path: Path, fn: Any) -> dict[str, Any]:
            nonlocal writes
            writes += 1
            if writes == 2:  # mark_running is first; terminal transition is second

                def _cancel(doc: dict[str, Any]) -> dict[str, Any]:
                    for candidate in doc.get("runs", []):
                        if candidate.get("id") == record["id"]:
                            candidate["state"] = "cancelled"
                            candidate["error"] = "cancelled by operator"
                    return doc

                real_read_modify_write(path, _cancel)
            return real_read_modify_write(path, fn)

        monkeypatch.setattr(_store, "read_modify_write", _inject_cancel_before_second_write)
        trace_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            "docket.core.trace.trace_event",
            lambda *args, **_kwargs: trace_calls.append(args) or "written",
        )

        returned = _runs.execute(
            record["id"],
            lambda: [
                _dispatch.TaskResult(
                    task_id="task-failed", status="failed", reason="must lose to cancel"
                )
            ],
        )

        assert returned is not None
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "cancelled"
        assert persisted["error"] == "cancelled by operator"
        assert trace_calls == []

    def test_execute_never_revives_a_run_cancelled_while_queued(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / ".docket"
        home.mkdir()
        _point_at(home, monkeypatch)
        record = _runs.create_run("webhook", "demo")
        assert _runs.cancel_run(record["id"]).ok
        invoked = False

        def _must_not_run() -> list[_dispatch.TaskResult]:
            nonlocal invoked
            invoked = True
            return [_dispatch.TaskResult(task_id="task-late", status="failed", reason="late")]

        returned = _runs.execute(record["id"], _must_not_run)

        assert returned is None
        assert invoked is False
        persisted = _runs.get_run(record["id"])
        assert persisted is not None
        assert persisted["state"] == "cancelled"
        assert persisted["error"] == "cancelled by operator"


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

    def test_get_runs_exposes_requested_then_stopped_cancellation_lifecycle(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        rec = _runs.create_run("cli", "someproj")
        _runs.mark_running(rec["id"])
        _runs.cancel_run(rec["id"])

        req = urllib.request.Request(f"{url}/runs/{rec['id']}")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            requested = json.loads(resp.read())
        assert requested["state"] == "running"
        assert requested["cancellation"]["requestedAt"] is not None
        assert requested["cancellation"]["stoppedAt"] is None

        assert (
            _runs._finish_run_transition(rec["id"], state="succeeded", task_ids=["task-cancelled"])
            is False
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            stopped = json.loads(resp.read())
        assert stopped["state"] == "cancelled"
        assert stopped["taskIds"] == ["task-cancelled"]
        assert stopped["cancellation"]["observedAt"] is not None
        assert stopped["cancellation"]["stoppedAt"] is not None

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
