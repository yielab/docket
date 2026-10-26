"""OTLP/HTTP delivery against a real loopback collector: success, retry, transport failure and probe."""

from __future__ import annotations

import base64
import dataclasses
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

from tests.support.otlp_harness import (
    _projected_spans,
)

from docket.kernel.home import current_home, use_home
from docket.observability.adapters import otlp_http

SUBJECT = "docket.observability.adapters.otlp_http"


class _RecordingHandler(BaseHTTPRequestHandler):
    responses: ClassVar[list[tuple[int, dict[str, str]]]] = []
    requests: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append(
            {"headers": dict(self.headers), "body": json.loads(body.decode())}
        )
        status, extra_headers = type(self).responses.pop(0)
        self.send_response(status)
        for name, value in extra_headers.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:  # keep test output quiet
        return


def _server(responses: list[tuple[int, dict[str, str]]]) -> tuple[ThreadingHTTPServer, str]:
    class _Handler(_RecordingHandler):
        pass

    _Handler.responses = responses
    _Handler.requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{port}/v1/traces"


class TestEmitSuccess:
    def test_basic_auth_post_is_accepted_and_round_trips(self) -> None:
        srv, url = _server([(200, {})])
        try:
            handler_cls = srv.RequestHandlerClass
            token = base64.b64encode(b"user:pass").decode()
            sink = otlp_http.OtlpHttpSink(
                endpoint=url,
                auth_header=("Authorization", f"Basic {token}"),
                resource={"service.name": "docket"},
                aliases={},
            )
            spans = _projected_spans()
            result = sink.emit(spans)
            assert result.accepted == len(spans)
            assert result.status == 200
            assert result.error == ""

            [request] = handler_cls.requests
            assert request["headers"]["Content-Type"] == "application/json"
            assert request["headers"]["Authorization"] == f"Basic {token}"
            expected = otlp_http.encode(spans, resource={"service.name": "docket"}, aliases={})
            assert request["body"] == expected
        finally:
            srv.shutdown()


class TestEmitRetry:
    def test_429_with_retry_after_then_200_retries_once(self) -> None:
        srv, url = _server([(429, {"Retry-After": "1"}), (200, {})])
        try:
            handler_cls = srv.RequestHandlerClass
            sleeps: list[float] = []
            sink = otlp_http.OtlpHttpSink(
                endpoint=url,
                auth_header=None,
                sleep=sleeps.append,
            )
            spans = _projected_spans()
            result = sink.emit(spans)
            assert len(handler_cls.requests) == 2
            assert result.accepted == len(spans)
            assert result.status == 200
            assert sleeps == [1.0]
        finally:
            srv.shutdown()

    def test_the_wait_is_capped_by_the_current_home(self) -> None:
        srv, url = _server([(429, {"Retry-After": "30"}), (200, {})])
        try:
            sleeps: list[float] = []
            sink = otlp_http.OtlpHttpSink(endpoint=url, auth_header=None, sleep=sleeps.append)
            with use_home(dataclasses.replace(current_home(), dispatch_retry_max_wait_s=2.5)):
                sink.emit(_projected_spans())
            assert sleeps == [2.5]
        finally:
            srv.shutdown()

    def test_400_is_not_retried_and_reports_zero_accepted(self) -> None:
        srv, url = _server([(400, {})])
        try:
            handler_cls = srv.RequestHandlerClass
            sleeps: list[float] = []
            sink = otlp_http.OtlpHttpSink(endpoint=url, auth_header=None, sleep=sleeps.append)
            result = sink.emit(_projected_spans())
            assert len(handler_cls.requests) == 1
            assert result.accepted == 0
            assert result.status == 400
            assert sleeps == []
        finally:
            srv.shutdown()


class TestEmitTransportFailure:
    def test_closed_port_reports_no_status_and_never_raises(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens on this port now
        sink = otlp_http.OtlpHttpSink(
            endpoint=f"http://127.0.0.1:{port}/v1/traces", auth_header=None
        )
        result = sink.emit(_projected_spans())
        assert result.status is None
        assert result.error != ""
        assert result.accepted == 0


class TestProbe:
    def test_posts_an_empty_resource_spans_document(self) -> None:
        srv, url = _server([(200, {})])
        try:
            handler_cls = srv.RequestHandlerClass
            result = otlp_http.probe(url, None, {})
            assert result.status == 200
            assert result.error == ""
            [request] = handler_cls.requests
            assert request["body"] == {"resourceSpans": []}
        finally:
            srv.shutdown()
