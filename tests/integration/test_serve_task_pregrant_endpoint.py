"""POST /tasks/<id>/pregrants — recording a single-use pre-grant over HTTP.

The HTTP counterpart of `docket task approve <id> --for` and the MCP `task_pregrant` tool: same
`core.interruptions.record_pregrant` call (`channel="http"`), so the recorded pre-grant is
byte-for-byte identical to every other surface. Covers auth, the happy path (the token, and the
task's own `pregrants` list), and the error mappings (`404`/`400`).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.serve import _DocketHandler

SUBJECT = "docket.core"

_TEST_TOKEN = "test-serve-token-task-pregrant-p34-15"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@pytest.fixture()
def pod_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "approvals").mkdir()
    repoint_docket_home(monkeypatch, home)
    return home


@pytest.fixture()
def live_server(pod_home: Path):  # type: ignore[no-untyped-def]
    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _post(
    url: str, body: dict[str, Any] | None = None, token: str | None = None
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body if body is not None else {}).encode()
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


class TestAuth:
    def test_no_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, body = _post(f"{url}/tasks/task-does-not-exist/pregrants", {"pod": "demo"})
        assert status == 401
        assert body["ok"] is False


class TestHappyPath:
    def test_records_a_pregrant_and_returns_a_token(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        task = _dispatch.enqueue_task("demo", "ship it")

        status, body = _post(
            f"{url}/tasks/{task['id']}/pregrants",
            {"pod": "demo", "command": "git push origin main"},
            token=token,
        )

        assert status == 200
        assert body["ok"] is True
        assert body["token"]
        stored = _dispatch.read_tasks("demo")[0]
        assert stored["pregrants"][0]["token"] == body["token"]
        assert stored["pregrants"][0]["tool"] == "bash"

    def test_custom_tool_is_honoured(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        task = _dispatch.enqueue_task("demo", "ship it")

        status, _body = _post(
            f"{url}/tasks/{task['id']}/pregrants",
            {"pod": "demo", "command": "echo hi", "tool": "write", "actor": "tack"},
            token=token,
        )

        assert status == 200
        stored = _dispatch.read_tasks("demo")[0]
        assert stored["pregrants"][0]["tool"] == "write"


class TestErrorMapping:
    def test_unknown_task_is_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(
            f"{url}/tasks/no-such-task/pregrants",
            {"pod": "demo", "command": "git push origin main"},
            token=token,
        )
        assert status == 404
        assert "not found" in body["error"]

    def test_missing_pod_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(
            f"{url}/tasks/some-task/pregrants", {"command": "git push origin main"}, token=token
        )
        assert status == 400
        assert "pod is required" in body["error"]

    def test_missing_command_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/some-task/pregrants", {"pod": "demo"}, token=token)
        assert status == 400
        assert "command is required" in body["error"]
