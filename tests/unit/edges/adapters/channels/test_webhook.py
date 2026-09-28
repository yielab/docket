"""Standard Webhooks delivery (`edges/adapters/channels/webhook.py`).

Placed under `tests/unit/edges/adapters/channels/` -- not the flatter
`tests/unit/edges/test_channel_webhook.py` path a plain reading of the card text suggests --
so `tests/guards/test_layout.py`'s SUBJECT-mirrors-module convention resolves this file to the
real module without a guard-file exemption; see the card handoff for the reasoning.
"""

from __future__ import annotations

import base64
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

from docket.core.operator_contract import make_event
from docket.edges.adapters.channels import webhook

SUBJECT = "docket.edges.adapters.channels.webhook"


class _ChannelSpecLike:
    def __init__(self, url: str) -> None:
        self.config = {"url": url}


def _event() -> Any:
    return make_event(
        "approval.requested",
        "alpha",
        "approval:tok-1",
        {"pod": "alpha", "token": "tok-1"},
        time="2026-09-28T00:00:00Z",
        version="pending:tok-1",
    )


class TestSignature:
    def test_matches_the_standard_webhooks_test_vector(self) -> None:
        secret_value = "whsec_" + base64.b64encode(b"test-secret").decode()
        body = b'{"a":1}'
        expected_digest = hmac.new(b"test-secret", b"msg_1.1700000000." + body, "sha256").digest()
        expected = "v1," + base64.b64encode(expected_digest).decode()

        actual = webhook._sign(secret_value, "msg_1", "1700000000", body)
        assert actual == expected


class _RecordingHandler(BaseHTTPRequestHandler):
    responses: ClassVar[list[int]] = []
    requests: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        # urllib.request.Request.add_header() title-cases every header key before sending
        # (HTTP headers are case-insensitive, but a plain-dict comparison is not) -- store
        # them lower-cased so the assertions below don't depend on that transport detail.
        headers_ci = {k.lower(): v for k, v in self.headers.items()}
        type(self).requests.append({"headers": headers_ci, "body": json.loads(body)})
        status = type(self).responses.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:  # keep test output quiet
        return


def _server(responses: list[int]) -> tuple[ThreadingHTTPServer, str]:
    class _Handler(_RecordingHandler):
        pass

    _Handler.responses = responses
    _Handler.requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{port}/hook"


class TestDeliverSuccess:
    def test_posts_cloudevents_json_with_the_signature_headers(self) -> None:
        srv, url = _server([200])
        try:
            handler_cls = srv.RequestHandlerClass
            secret_value = "whsec_" + base64.b64encode(b"test-secret").decode()
            event = _event()
            result = webhook.deliver(_ChannelSpecLike(url), event, secret=secret_value, timeout=5.0)
            assert result.ok is True
            assert result.status == 200
            req = handler_cls.requests[0]
            assert req["headers"]["webhook-id"] == event.id
            assert req["headers"]["content-type"] == "application/cloudevents+json"
            assert req["headers"]["webhook-signature"].startswith("v1,")
            ts = req["headers"]["webhook-timestamp"]
            body = json.dumps(req["body"], sort_keys=True).encode()
            expected = webhook._sign(secret_value, event.id, ts, body)
            assert req["headers"]["webhook-signature"] == expected
        finally:
            srv.shutdown()

    def test_no_secret_omits_the_signature_header(self) -> None:
        srv, url = _server([200])
        try:
            handler_cls = srv.RequestHandlerClass
            result = webhook.deliver(_ChannelSpecLike(url), _event(), secret=None, timeout=5.0)
            assert result.ok is True
            assert "webhook-signature" not in handler_cls.requests[0]["headers"]
        finally:
            srv.shutdown()


class TestDeliverFailure:
    def test_missing_url_never_raises(self) -> None:
        result = webhook.deliver(_ChannelSpecLike(""), _event(), secret=None, timeout=5.0)
        assert result.ok is False
        assert "config.url" in result.error

    def test_a_dead_port_records_an_error_and_returns_within_the_timeout(self) -> None:
        import socket

        # A bound-but-unlistened socket refuses the connection immediately -- deterministic
        # and fast, unlike a routed-but-silent address that would actually wait out the
        # timeout.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()

        result = webhook.deliver(
            _ChannelSpecLike(f"http://127.0.0.1:{dead_port}/hook"),
            _event(),
            secret=None,
            timeout=2.0,
        )
        assert result.ok is False
        assert result.error

    def test_non_2xx_status_is_a_failure(self) -> None:
        srv, url = _server([500])
        try:
            result = webhook.deliver(_ChannelSpecLike(url), _event(), secret=None, timeout=5.0)
            assert result.ok is False
            assert result.status == 500
        finally:
            srv.shutdown()
