"""POST /tasks/<id>/pregrants — recording a single-use pre-grant over HTTP.

The HTTP counterpart of `docket task approve <id> --for` and the MCP `task_pregrant` tool: same
`hops.application.interruptions.record_pregrant` call (`channel="http"`), so the recorded pre-grant is
byte-for-byte identical to every other surface. Covers auth, the happy path (the token, and the
task's own `pregrants` list), and the error mappings (`404`/`400`).
"""

from __future__ import annotations

from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import post_3 as _post
from tests.support.pods import build_pod

from docket.interfaces.cli.commands import pod as _pod
from docket.tasks.application import queue as _queue

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token"


class TestAuth:
    def test_no_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, body = _post(f"{url}/tasks/task-does-not-exist/pregrants", {"pod": "demo"})
        assert status == 401
        assert body["ok"] is False


class TestHappyPath:
    def test_records_a_pregrant_and_returns_a_token(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        task = _queue.enqueue_task_once("demo", "ship it", channel="cli")[0]

        status, body = _post(
            f"{url}/tasks/{task['id']}/pregrants",
            {"pod": "demo", "command": "git push origin main"},
            token=token,
        )

        assert status == 200
        assert body["ok"] is True
        assert body["token"]
        stored = _queue.read_tasks("demo")[0]
        assert stored["pregrants"][0]["token"] == body["token"]
        assert stored["pregrants"][0]["tool"] == "bash"

    def test_custom_tool_is_honoured(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        task = _queue.enqueue_task_once("demo", "ship it", channel="cli")[0]

        status, _body = _post(
            f"{url}/tasks/{task['id']}/pregrants",
            {"pod": "demo", "command": "echo hi", "tool": "write", "actor": "tack"},
            token=token,
        )

        assert status == 200
        stored = _queue.read_tasks("demo")[0]
        assert stored["pregrants"][0]["tool"] == "write"


class TestErrorMapping:
    def test_unknown_task_is_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
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
