"""GET /tasks/<project> — the pod queue as JSON over HTTP.

Phase 22 (P22-2): exposes `core.dispatch.read_tasks` — already the exact
normalized shape `docket pod <p> tasks` renders from — behind the same
Bearer auth as `/runs`. No new behaviour: this route adds no filtering,
no reshaping, and no 404 that `read_tasks` itself does not express (a
project with no pod is `[]`, not an error).

Covers:
  - auth rejection (401, no token / wrong token)
  - missing project segment -> 400 (both "/tasks" and "/tasks/")
  - a project with no pod -> 200, {"tasks": []} (read_tasks' own contract)
  - a seeded pod's queue comes back with the same fields `read_tasks` returns
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-tasks-p22-2"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    _point_at(home, monkeypatch)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _get(url: str, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url)
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
    approvals_dir = tmp_path / "approvals"
    approvals_dir.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", approvals_dir, raising=True)

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


class TestAuth:
    def test_no_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, body = _get(f"{url}/tasks/demo")
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, _body = _get(f"{url}/tasks/demo", token="not-the-real-token")
        assert status == 401

    def test_correct_token_accepted(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/tasks/demo", token=token)
        assert status == 200
        assert body == {"tasks": []}


class TestMissingProject:
    def test_bare_path_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/tasks", token=token)
        assert status == 400
        assert body["ok"] is False

    def test_trailing_slash_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/tasks/", token=token)
        assert status == 400
        assert body["ok"] is False

    def test_missing_project_checked_before_needing_auth_bypass(
        self, live_server: tuple[str, str]
    ) -> None:
        """Even the empty-project 400 stays behind auth -- no unauthenticated
        request should be able to distinguish a missing project from any
        other route without a valid token."""
        url, _token = live_server
        status, _body = _get(f"{url}/tasks")
        assert status == 401


class TestNoPodIsEmptyList:
    def test_unknown_project_returns_empty_list_not_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/tasks/no-such-pod", token=token)
        assert status == 200
        assert body == {"tasks": []}


class TestQueueShapeMatchesReadTasks:
    def test_http_response_matches_read_tasks_directly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, project="demo")
        _dispatch.enqueue_task("demo", "Ship the read API")
        _dispatch.enqueue_task("demo", "Add a second task")

        expected = _dispatch.read_tasks("demo")
        assert len(expected) == 2

        approvals_dir = tmp_path / "approvals"
        approvals_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(_cfg, "APPROVALS_DIR", approvals_dir, raising=True)

        class _Handler(_DocketHandler):
            serve_token = _TEST_TOKEN

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, body = _get(f"http://127.0.0.1:{port}/tasks/demo", token=_TEST_TOKEN)
        finally:
            srv.shutdown()

        assert status == 200
        assert body["tasks"] == expected
        for task in body["tasks"]:
            assert task["status"] == "pending"
            assert task["priority"] == "normal"
            assert "id" in task and "created" in task
