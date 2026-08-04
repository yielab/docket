"""The Telegram Bot API adapter.

``edges/adapters/telegram.py`` is the only module that knows the Bot API's
wire format. A real local HTTP server (stdlib ``http.server``) backs every
network-shaped test here, exactly the discipline
``test_p19_11_fetch_tool.py`` set for ``edges/adapters/fetch.py`` -- **no
test in this module ever contacts the real Telegram API or needs a token**;
``API_ROOT`` is monkeypatched to the local server's base URL.

What this pins, in order of how much it matters:

1. **The bot token never appears in a returned error string** -- proven
   against a real HTTP 401 response and a real connection failure, not
   assumed.
2. Long-poll semantics: an empty result is success, not a failure; the
   caller's offset is echoed back verbatim (this module never computes the
   next offset itself -- that is ``core/telegram.py``'s job).
3. A network failure (timeout, refused connection, malformed body) degrades
   to a typed ``ok=False`` result and never raises.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docket.edges.adapters import telegram as _tg

_FAKE_TOKEN = "123456:AAFAKE-TEST-TOKEN-not-real-do-not-flag"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet test output
        pass

    def _reply_json(self, status: int, body: dict[str, object]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if "/getUpdates" in self.path:
            if "offset=999" in self.path:
                self._reply_json(200, {"ok": True, "result": []})
                return
            if "unauthorized-token" in self.path:
                self._reply_json(
                    401, {"ok": False, "error_code": 401, "description": "Unauthorized"}
                )
                return
            if "slow-token" in self.path:
                time.sleep(2)
                self._reply_json(200, {"ok": True, "result": []})
                return
            if "malformed-token" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                body = b"not json"
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # default: one real update
            self._reply_json(
                200,
                {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 42,
                            "message": {
                                "chat": {"id": -100123},
                                "from": {"id": 555},
                                "text": "/status",
                            },
                        },
                        {
                            # non-message update -- must be skipped, not error
                            "update_id": 43,
                            "edited_message": {"chat": {"id": -100123}, "text": "edited"},
                        },
                    ],
                },
            )
            return
        self._reply_json(404, {"ok": False, "description": "not found"})

    def do_POST(self) -> None:
        if "/sendMessage" in self.path:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw)
            if payload.get("chat_id") == "fail-me":
                self._reply_json(400, {"ok": False, "description": "chat not found"})
                return
            self._reply_json(200, {"ok": True, "result": {"message_id": 1}})
            return
        self._reply_json(404, {"ok": False, "description": "not found"})


@pytest.fixture
def server() -> Iterator[str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = srv.server_address[0], srv.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _point_at_local_server(server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tg, "API_ROOT", server, raising=True)


class TestGetUpdatesHappyPath:
    def test_decodes_a_real_message_update(self) -> None:
        result = _tg.get_updates(_FAKE_TOKEN, offset=0, timeout=1, request_timeout=5)
        assert result.ok
        assert len(result.updates) == 1  # the edited_message entry is skipped
        upd = result.updates[0]
        assert upd.update_id == 42
        assert upd.chat_id == "-100123"
        assert upd.user_id == "555"
        assert upd.text == "/status"

    def test_empty_long_poll_result_is_success_not_failure(self) -> None:
        result = _tg.get_updates(_FAKE_TOKEN, offset=999, timeout=1, request_timeout=5)
        assert result.ok
        assert result.updates == ()
        assert result.error == ""

    def test_no_token_is_refused_before_any_request(self) -> None:
        result = _tg.get_updates("", offset=0)
        assert not result.ok
        assert "no bot token" in result.error


class TestTokenNeverLeaks:
    """The security property this module's docstring promises: whatever goes
    wrong, the token is never in the returned error text. Proven against a
    real HTTP 401 and a real connection failure -- not assumed."""

    def test_http_error_body_does_not_echo_the_token(self) -> None:
        result = _tg.get_updates(
            "unauthorized-token-marker", offset=0, timeout=1, request_timeout=5
        )
        assert not result.ok
        assert "unauthorized-token-marker" not in result.error
        assert "Unauthorized" in result.error

    def test_connection_failure_does_not_echo_the_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_tg, "API_ROOT", "http://127.0.0.1:1", raising=True)
        result = _tg.get_updates(
            "super-secret-token-marker", offset=0, timeout=1, request_timeout=2
        )
        assert not result.ok
        assert "super-secret-token-marker" not in result.error

    def test_send_message_never_raises_and_never_needs_the_token_in_a_result(self) -> None:
        # send_message returns a bare bool -- there is no error string to
        # leak into in the first place, which is itself part of the
        # guarantee: the one function that could echo transport detail
        # (get_updates) is the one tested above.
        ok = _tg.send_message("whatever-token-marker", "fail-me", "hi")
        assert ok is False


class TestTimeouts:
    def test_a_slow_endpoint_times_out_without_raising(self) -> None:
        result = _tg.get_updates("slow-token", offset=0, timeout=1, request_timeout=1)
        assert not result.ok
        assert "timed out" in result.error


class TestMalformedResponses:
    def test_non_json_body_degrades_to_a_typed_error(self) -> None:
        result = _tg.get_updates("malformed-token", offset=0, timeout=1, request_timeout=5)
        assert not result.ok
        assert "non-JSON" in result.error

    def test_unreachable_host_degrades_to_a_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_tg, "API_ROOT", "http://127.0.0.1:1", raising=True)
        result = _tg.get_updates(_FAKE_TOKEN, offset=0, timeout=1, request_timeout=2)
        assert not result.ok
        assert result.error  # some transport error, never raised


class TestSendMessage:
    def test_successful_send_returns_true(self) -> None:
        assert _tg.send_message(_FAKE_TOKEN, "-100123", "hello") is True

    def test_failed_send_returns_false_not_an_exception(self) -> None:
        assert _tg.send_message(_FAKE_TOKEN, "fail-me", "hello") is False

    def test_empty_chat_id_is_refused_before_any_request(self) -> None:
        assert _tg.send_message(_FAKE_TOKEN, "", "hello") is False

    def test_empty_token_is_refused_before_any_request(self) -> None:
        assert _tg.send_message("", "-100123", "hello") is False
