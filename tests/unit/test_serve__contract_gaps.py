"""Small HTTP contract gaps in the serve control plane, all pinned by
specs/data/serve-read-api.spec.md:

- Every response, success or error, carries `Cache-Control: no-store`
  ("Structure").
- A bare write path (`/approvals`, `/tasks`, `/dispatch`, no trailing
  segment) reaches the auth check before its handler's own `400`, instead of
  a pre-auth `404` ("Validation").
- A POST body over `serve.MAX_POST_BODY_BYTES` is rejected `413` without
  `rfile.read` ever being called ("Validation").
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

import docket.config as _cfg
import docket.serve as serve
from docket.serve import _DocketHandler

SUBJECT = "docket.serve"

_TEST_TOKEN = "test-serve-token-contract-gaps"


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    repoint_docket_home(monkeypatch, home)
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


def _get(url: str, token: str | None = None) -> tuple[int, dict[str, Any], Any]:
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read()), resp.headers
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), exc.headers


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


# ── every response carries Cache-Control: no-store ──────────────────────────


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
        _status, _body, headers = _get(f"{url}/approvals")
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


# ── a bare write path reaches auth before its handler's own 400 ─────────────


class TestBarePostPaths:
    @pytest.mark.parametrize("path", ["/approvals", "/tasks", "/dispatch"])
    def test_unauthenticated_bare_path_is_401_not_404(
        self, live_server: tuple[str, str], path: str
    ) -> None:
        url, _token = live_server
        status, body = _post(f"{url}{path}")
        assert status == 401
        assert body["ok"] is False

    def test_authenticated_bare_approvals_names_the_missing_token(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _post(f"{url}/approvals", token=token)
        assert status == 400
        assert "approval token" in body["error"].lower()

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


# ── an oversized POST body is rejected before it is read ────────────────────


class _FakeRFile:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.read_called = False

    def read(self, n: int) -> bytes:
        self.read_called = True
        return self._data[:n]


class TestReadBodyCap:
    """Direct seam test for `_DocketHandler._read_body` -- a real oversized
    upload would only make the same point more slowly."""

    def _bare_handler(self, content_length: str, data: bytes = b"") -> _DocketHandler:
        handler = _DocketHandler.__new__(_DocketHandler)
        handler.headers = {"Content-Length": content_length}  # type: ignore[assignment]
        handler.rfile = _FakeRFile(data)  # type: ignore[assignment]
        handler._sent = []  # type: ignore[attr-defined]

        def _send_json_error(msg: str, status: int = 400) -> None:
            handler._sent.append((msg, status))  # type: ignore[attr-defined]

        handler._send_json_error = _send_json_error  # type: ignore[method-assign]
        return handler

    def test_over_cap_sends_413_without_touching_rfile(self) -> None:
        handler = self._bare_handler(str(serve.MAX_POST_BODY_BYTES + 1))
        result = handler._read_body()
        assert result is None
        assert handler.rfile.read_called is False  # type: ignore[attr-defined]
        assert handler._sent == [("Request body too large", 413)]  # type: ignore[attr-defined]

    def test_small_body_is_read_normally(self) -> None:
        payload = b"{}"
        handler = self._bare_handler(str(len(payload)), data=payload)
        result = handler._read_body()
        assert result == payload
        assert handler.rfile.read_called is True  # type: ignore[attr-defined]

    def test_exactly_at_the_cap_is_still_read_not_rejected(self) -> None:
        payload = b"x" * serve.MAX_POST_BODY_BYTES
        handler = self._bare_handler(str(serve.MAX_POST_BODY_BYTES), data=payload)
        result = handler._read_body()
        assert result == payload
        assert handler.rfile.read_called is True  # type: ignore[attr-defined]

    def test_no_content_length_reads_as_empty_object(self) -> None:
        handler = self._bare_handler("0")
        result = handler._read_body()
        assert result == b"{}"


class TestSocketTimeoutBound:
    def test_handler_declares_a_positive_read_timeout(self) -> None:
        assert isinstance(_DocketHandler.timeout, (int, float))
        assert _DocketHandler.timeout > 0
