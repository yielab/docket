"""Credential-bearing outbound calls never follow a redirect off their origin.

A real local server stands in for each endpoint. A 302 from the origin names a second
server on another port, and that second server records what reaches it. A same-origin
redirect must still be followed.
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from docket.agent.ports import Endpoint
from docket.models.adapters import openai_http as llm
from docket.observability.adapters import otlp_http
from docket.operator.adapters import ntfy, webhook
from docket.operator.channel import ChannelSpec
from docket.operator.contract import make_event

SUBJECT = "docket.platform.redirects"

_MODELS = json.dumps({"data": [{"id": "served-model"}]}).encode()


class _Server:
    """Answers 200 with a model list, except for paths in *redirects* (a 302 to the value)."""

    def __init__(self, redirects: dict[str, str]) -> None:
        self.redirects = redirects
        self.seen: list[dict[str, str]] = []
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                headers = {k.lower(): v for k, v in self.headers.items()}
                server.seen.append(headers | {"path": self.path})
                location = server.redirects.get(self.path)
                if location is not None:
                    self.send_response(302)
                    self.send_header("Location", location)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(_MODELS)))
                self.end_headers()
                self.wfile.write(_MODELS)

            do_GET = _serve
            do_POST = _serve

            def log_message(self, *args: object) -> None:
                return None

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self._httpd.server_port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def target() -> Iterator[_Server]:
    server = _Server({})
    yield server
    server.close()


def _origin_redirecting_to(target: _Server, paths: list[str]) -> _Server:
    origin = _Server({path: target.url + path for path in paths})
    return origin


def test_probe_models_does_not_send_its_key_to_a_redirect_target(target: _Server) -> None:
    """The chat probe's bearer key stays with the origin when the origin redirects away."""
    origin = _origin_redirecting_to(target, ["/v1/models"])
    try:
        endpoint = Endpoint(
            base_url=origin.url + "/v1", model_id="m", api_key="sek-probe", auth_type="bearer"
        )
        llm.probe_models(endpoint, timeout=5.0)
    finally:
        origin.close()
    assert target.seen == []


def test_otlp_probe_does_not_send_its_auth_header_to_a_redirect_target(target: _Server) -> None:
    """The OTLP exporter's auth header stays with the origin when the origin redirects away."""
    origin = _origin_redirecting_to(target, ["/v1/traces"])
    try:
        otlp_http.probe(
            origin.url + "/v1/traces",
            ("Authorization", "Bearer sek-otlp"),
            {},
            timeout_s=5.0,
        )
    finally:
        origin.close()
    assert target.seen == []


def test_webhook_does_not_send_its_signature_to_a_redirect_target(target: _Server) -> None:
    """A signed webhook delivery is not re-sent to another host by a redirect."""
    origin = _origin_redirecting_to(target, ["/hook"])
    try:
        spec = ChannelSpec(
            kind="channel", name="hook", dialect="webhook", config={"url": origin.url + "/hook"}
        )
        event = make_event(
            "approval.requested",
            "alpha",
            "approval:tok-1",
            {"pod": "alpha", "token": "tok-1"},
            time="2026-10-12T00:00:00Z",
            version="pending:tok-1",
        )
        secret = "whsec_" + base64.b64encode(b"test-secret").decode()
        webhook.deliver(spec, event, secret=secret, timeout=5.0)
    finally:
        origin.close()
    assert target.seen == []


def test_ntfy_does_not_send_its_bearer_token_to_a_redirect_target(target: _Server) -> None:
    """An ntfy bearer token is not re-sent to another host by a redirect."""
    origin = _origin_redirecting_to(target, ["/topic"])
    try:
        spec = ChannelSpec(
            kind="channel",
            name="pings",
            dialect="ntfy",
            config={"server": origin.url, "topic": "topic"},
        )
        event = make_event(
            "approval.requested",
            "alpha",
            "approval:tok-2",
            {"pod": "alpha", "token": "tok-2"},
            time="2026-10-12T00:00:00Z",
            version="pending:tok-2",
        )
        ntfy.deliver(spec, event, secret="ntfy-secret", timeout=5.0)
    finally:
        origin.close()
    assert target.seen == []


def test_same_origin_redirect_is_still_followed(target: _Server) -> None:
    """A redirect that stays on the same origin is followed, credential included."""
    origin = _Server({"/v1/models": "/v1/models-moved"})
    try:
        endpoint = Endpoint(
            base_url=origin.url + "/v1", model_id="m", api_key="sek-same", auth_type="bearer"
        )
        result: Any = llm.probe_models(endpoint, timeout=5.0)
    finally:
        origin.close()
    assert result.model_ids == ["served-model"]
    moved = [seen for seen in origin.seen if seen["path"] == "/v1/models-moved"]
    assert moved and moved[0]["authorization"] == "Bearer sek-same"
