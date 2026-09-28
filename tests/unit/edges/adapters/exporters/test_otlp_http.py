"""OTLP/HTTP JSON encoding and transport (edges/adapters/exporters/otlp_http.py)."""

from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

from docket.core import telemetry
from docket.edges.adapters.exporters import otlp_http

SUBJECT = "docket.edges.adapters.exporters.otlp_http"

_TRACE_FIXTURE = (
    Path(__file__).resolve().parents[4] / "fixtures" / "traces" / "dispatch-3-hops.jsonl"
)
_GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "otlp-v1" / "dispatch-3-hops.json"


def _projected_spans() -> list[telemetry.Span]:
    records = [json.loads(line) for line in _TRACE_FIXTURE.read_text().splitlines() if line.strip()]
    state = telemetry.ProjectionState()
    spans: list[telemetry.Span] = []
    for record in records:
        spans.extend(telemetry.project(record, state))
    spans.extend(telemetry.flush_open(state))
    return spans


class TestEncodeGolden:
    def test_matches_the_committed_wire_fixture(self) -> None:
        doc = otlp_http.encode(
            _projected_spans(),
            resource={"service.name": "docket"},
            aliases={"session.id": "langfuse.session.id"},
        )
        rendered = json.dumps(doc, sort_keys=True, indent=2) + "\n"
        assert rendered == _GOLDEN.read_text()

    def test_gen_ai_chat_span_shape(self) -> None:
        doc = otlp_http.encode(
            _projected_spans(), resource={}, aliases={"session.id": "langfuse.session.id"}
        )
        spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
        chat = next(s for s in spans if s["name"] == "gen_ai.chat")
        assert chat["kind"] == 3
        attrs = {a["key"]: a["value"] for a in chat["attributes"]}
        assert attrs["gen_ai.usage.input_tokens"] == {"intValue": "120"} or attrs[
            "gen_ai.usage.input_tokens"
        ] == {"intValue": "180"}

    def test_session_root_carries_the_aliased_attribute(self) -> None:
        doc = otlp_http.encode(
            _projected_spans(), resource={}, aliases={"session.id": "langfuse.session.id"}
        )
        spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
        root = next(s for s in spans if s["name"] == "docket.session")
        keys = {a["key"] for a in root["attributes"]}
        assert {"session.id", "langfuse.session.id"} <= keys


# ── transport ───────────────────────────────────────────────────────────────


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
