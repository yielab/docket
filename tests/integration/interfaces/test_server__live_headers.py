"""The HTTP server's cache-control header and bare POST paths over a real loopback socket."""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from tests.support.http import post as _post

from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import ContextHTTPServer

SUBJECT = "docket.interfaces.http.server"


_TEST_TOKEN = "test-serve-token-contract-gaps"


@pytest.fixture()
def live_server(tmp_path: Path):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    with use_home(Home(home)):
        approvals_dir = tmp_path / "approvals"
        approvals_dir.mkdir()
        with use_home(dataclasses.replace(current_home(), approvals_dir_override=approvals_dir)):

            class _Handler(_DocketHandler):
                serve_token = _TEST_TOKEN

            srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            yield f"http://127.0.0.1:{port}", _TEST_TOKEN
            srv.shutdown()


def _get(url: str, token: str | None = None) -> tuple[int, dict[str, Any], Any]:
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read()), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), exc.headers


class TestCacheControlHeader:
    def test_status_json_is_marked_no_store(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        _status, _body, headers = _get(f"{url}/status.json")
        assert headers.get("Cache-Control") == "no-store"

    def test_health_is_marked_no_store(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        _status, _body, headers = _get(f"{url}/health")
        assert headers.get("Cache-Control") == "no-store"

    def test_an_auth_error_response_is_marked_no_store_too(
        self, live_server: tuple[str, str]
    ) -> None:
        url, _token = live_server
        _status, _body, headers = _get(f"{url}/escalations")
        assert headers.get("Cache-Control") == "no-store"

    def test_a_404_is_marked_no_store(self, live_server: tuple[str, str]) -> None:
        # The plain-404 fallback in do_GET sends text, not JSON -- read the
        # headers directly rather than through the JSON-decoding `_get`.
        url, _token = live_server
        req = urllib.request.Request(f"{url}/nowhere")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                headers = resp.headers
        except urllib.error.HTTPError as exc:
            headers = exc.headers
        assert headers.get("Cache-Control") == "no-store"


class TestBarePostPaths:
    @pytest.mark.parametrize("path", ["/escalations", "/tasks", "/dispatch"])
    def test_unauthenticated_bare_path_is_401_not_404(
        self, live_server: tuple[str, str], path: str
    ) -> None:
        url, _token = live_server
        status, body = _post(f"{url}{path}")
        assert status == 401
        assert body["ok"] is False

    def test_authenticated_bare_escalations_names_the_missing_id(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _post(f"{url}/escalations", token=token)
        assert status == 400
        assert "escalation id" in body["error"].lower()

    def test_authenticated_bare_tasks_names_the_missing_project(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks", token=token)
        assert status == 400
        assert "project" in body["error"].lower()

    def test_authenticated_bare_dispatch_names_the_missing_project(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _post(f"{url}/dispatch", token=token)
        assert status == 400
        assert "project" in body["error"].lower()
