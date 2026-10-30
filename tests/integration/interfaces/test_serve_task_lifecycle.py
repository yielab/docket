"""POST cancel and retry, GET diff on /tasks/<pod>/<id>: the real handler, a real git codebase."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.support import home as _support_home
from tests.support.home import record_isolation_off, register_local_provider
from tests.support.model_server import call, say
from tests.support.pods import build_pod

from docket.governance import audit as _audit
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application import worktree_prune as _worktree_prune
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet

_hermetic = _support_home.trace_on_env

SUBJECT = "docket.interfaces.http.server"

_TOKEN = "test-serve-token-lifecycle"
_IMPLEMENTER_ONLY = "name: implementer-only\nsteps:\n  - implementer: implementer\n"


@contextmanager
def _live_server() -> Iterator[str]:
    """Built inside the seeded home: the server serves the home it was built in."""

    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _call(
    method: str, url: str, token: str | None = _TOKEN, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None
    )
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@contextmanager
def _seed_pod(tmp_path: Path, base_url: str = "") -> Iterator[Path]:
    codebase = tmp_path / "code"
    codebase.mkdir()
    subprocess.run(["git", "init", str(codebase)], check=True, capture_output=True)
    _git(codebase, "config", "user.email", "t@t.test")
    _git(codebase, "config", "user.name", "T")
    (codebase / "README.md").write_text("hello\n")
    _git(codebase, "add", ".")
    _git(codebase, "commit", "-m", "init")
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        if base_url:
            register_local_provider(
                home, "local", [{"id": "stub"}], base_url=base_url, toolSurface="full"
            )
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(codebase))
        if base_url:
            for role in ("lead", "implementer"):
                _fleet.meta_set(_pod.pod.member_id("demo", role), "model", "local/stub")
            path = _pod.pod.bound_pipeline_path("demo")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_IMPLEMENTER_ONLY, encoding="utf-8")
            digest = hashlib.sha256(_IMPLEMENTER_ONLY.encode("utf-8")).hexdigest()
            _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)
        yield codebase


def _set_task(task_id: str, **fields: Any) -> None:
    def _apply(record: TaskRecord) -> None:
        for name, value in fields.items():
            setattr(record, name, value)

    TaskRepository.for_pod("demo").update(task_id, _apply)


def _status(task_id: str) -> str:
    stored = TaskRepository.for_pod("demo").get(task_id)
    assert stored is not None
    return stored.status


def test_diff_reports_the_task_branch_against_its_base(tmp_path: Path, fake_model: Any) -> None:
    """The patch names the committed file, untracked lists a loose one, and it survives pruning."""
    server = fake_model(
        sequence=[
            call("write", path="out.txt", content="made\n"),
            say("done"),
        ]
    )
    with _seed_pod(tmp_path, server.base_url) as codebase, _live_server() as live_server:
        task = _queue.enqueue_task_once("demo", "write a file", channel="cli")[0]
        (result,) = _sweep.dispatch_pod("demo", max_tasks=1)
        assert result.status == "done", result.reason
        stored = TaskRepository.for_pod("demo").get(task.id)
        assert stored is not None and stored.worktree is not None
        record = stored.worktree
        (Path(record.dir) / "loose.txt").write_text("not added\n")
        url = f"{live_server}/tasks/demo/{task.id}/diff"

        status, body = _call("GET", url)

        assert status == 200, body
        assert body["task"] == task.id
        assert body["branch"] == record.branch
        assert body["baseCommit"] == record.base_commit
        assert body["head"] == _git(codebase, "rev-parse", record.branch)
        assert "out.txt" in body["patch"] and "+made" in body["patch"]
        assert body["untracked"] == ["loose.txt"]
        assert body["worktreePresent"] is True

        entries = _worktree_prune.prune_task_worktrees("demo", force=True)
        assert [e.action for e in entries] == ["removed"]
        status, after = _call("GET", url)

        assert status == 200
        assert after["worktreePresent"] is False
        assert after["untracked"] == []
        assert after["patch"] == body["patch"]
        assert after["head"] == body["head"]


def test_diff_of_an_in_place_task_is_a_conflict_with_a_reason(tmp_path: Path) -> None:
    """A task with no worktree branch answers 409 and says it ran in place."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        task = _queue.enqueue_task_once("demo", "plain", channel="cli")[0]

        status, body = _call("GET", f"{live_server}/tasks/demo/{task.id}/diff")

        assert status == 409
        assert body["reason"] == "task ran in place"


def test_diff_of_an_unknown_task_is_not_found(tmp_path: Path) -> None:
    """An id the pod never queued answers 404 on diff, cancel and retry."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        assert _call("GET", f"{live_server}/tasks/demo/task-nope/diff")[0] == 404
        assert _call("POST", f"{live_server}/tasks/demo/task-nope/cancel")[0] == 404
        assert _call("POST", f"{live_server}/tasks/demo/task-nope/retry")[0] == 404


def test_lifecycle_routes_need_the_bearer_token(tmp_path: Path) -> None:
    """No token is 401 before anything else is looked at."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        task = _queue.enqueue_task_once("demo", "plain", channel="cli")[0]
        base = f"{live_server}/tasks/demo/{task.id}"

        assert _call("GET", f"{base}/diff", token=None)[0] == 401
        assert _call("POST", f"{base}/cancel", token=None)[0] == 401
        assert _call("POST", f"{base}/retry", token="wrong")[0] == 401


def test_cancel_stops_the_live_run_of_a_running_task_and_audits_the_channel(tmp_path: Path) -> None:
    """A running task with a live run is cancelled over HTTP; the audit names channel and reason."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        task = _queue.enqueue_task_once("demo", "long", channel="cli")[0]
        _set_task(task.id, status="running", claim_pid=os.getpid())
        run = _runs.create_run("cli", "demo")
        assert _runs.mark_running(run["id"])

        status, body = _call(
            "POST", f"{live_server}/tasks/demo/{task.id}/cancel", body={"reason": "wrong repo"}
        )

        assert status == 200, body
        assert body == {"ok": True, "task": task.id, "status": "cancelled"}
        assert _runs.get_run(run["id"])["cancellation"]["requestedAt"]
        cancels = [e for e in _audit.read_audit() if e.get("action") == "task.cancel"]
        assert len(cancels) == 1
        assert "channel=http" in cancels[0]["detail"] and "wrong repo" in cancels[0]["detail"]


def test_cancel_with_nothing_in_flight_is_a_conflict(tmp_path: Path) -> None:
    """A terminal task has nothing to cancel: 409 and the status unchanged."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        task = _queue.enqueue_task_once("demo", "done already", channel="cli")[0]
        _set_task(task.id, status="done")

        status, _body = _call("POST", f"{live_server}/tasks/demo/{task.id}/cancel")

        assert status == 409
        assert _status(task.id) == "done"


def test_cancel_of_a_parked_task_ends_it_cancelled(tmp_path: Path) -> None:
    """A task waiting for an answer is cancelled over HTTP and audited with the channel."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        task = _queue.enqueue_task_once("demo", "ask", channel="cli")[0]
        _set_task(task.id, status="waiting_input")

        status, body = _call("POST", f"{live_server}/tasks/demo/{task.id}/cancel")

        assert status == 200, body
        assert body["status"] == "cancelled"
        assert _status(task.id) == "cancelled"
        assert any(
            e.get("action") == "task.cancel" and "channel=http" in e["detail"]
            for e in _audit.read_audit()
        )


def test_retry_requeues_a_failed_task_and_refuses_a_done_one(tmp_path: Path) -> None:
    """Retry flips failed to pending (200) and answers 409 on a done task."""
    with _seed_pod(tmp_path), _live_server() as live_server:
        failed = _queue.enqueue_task_once("demo", "broke", channel="cli")[0]
        done = _queue.enqueue_task_once("demo", "fine", channel="cli")[0]
        _set_task(failed.id, status="failed")
        _set_task(done.id, status="done")

        status, body = _call("POST", f"{live_server}/tasks/demo/{failed.id}/retry")

        assert (status, body) == (200, {"ok": True, "task": failed.id, "status": "pending"})
        assert _status(failed.id) == "pending"
        assert _call("POST", f"{live_server}/tasks/demo/{done.id}/retry")[0] == 409
        assert _status(done.id) == "done"
