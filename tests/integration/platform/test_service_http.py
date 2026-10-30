"""`call_operation` against a real loopback HTTP server (`platform/service_http.py`).

Pins the call (URL, JSON in and out, status handling) and the perimeter (host set, redirects,
loopback refusal before any socket, header hygiene, size cap, credential redaction)."""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from docket.kernel.home import current_home, use_home
from docket.platform.service_http import ServiceRequest, call_operation

SUBJECT = "docket.platform.service_http"


class _Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *args: object) -> None:
        pass

    def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        type(self).seen.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": raw.decode(),
            }
        )
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "http://evil.example.test/pwned")
            self.end_headers()
        elif self.path.startswith("/missing"):
            self._reply(404, b"no such thing here", "text/plain")
        elif self.path.startswith("/big"):
            self._reply(200, b"z" * 5000, "text/plain")
        elif self.path.startswith("/echo-auth"):
            auth = self.headers.get("Authorization", "")
            self._reply(200, json.dumps({"you_sent": auth}).encode())
        elif self.path.startswith("/text"):
            self._reply(200, b"plain words", "text/plain")
        else:
            self._reply(200, b'{ "ok": true,  "n": [1, 2] }')

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle


@pytest.fixture
def server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    _Handler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _request(base: str, **kwargs: Any) -> ServiceRequest:
    kwargs.setdefault("method", "GET")
    kwargs.setdefault("hosts", ("127.0.0.1",))
    return ServiceRequest(base_url=base, **kwargs)


class TestTheCall:
    def test_get_with_a_query_returns_compact_json(self, server: tuple[str, list]) -> None:
        base, seen = server
        out = call_operation(_request(base, path="/items", query={"q": "a b", "full": True}))
        assert out.ok
        assert out.content == '{"ok":true,"n":[1,2]}'
        assert seen[0]["method"] == "GET"
        assert seen[0]["path"] == "/items?q=a+b&full=true"

    def test_post_sends_the_json_body_and_the_header(self, server: tuple[str, list]) -> None:
        base, seen = server
        out = call_operation(
            _request(
                base,
                method="POST",
                path="/items",
                body={"name": "x", "n": 2},
                headers={"X-Api-Version": "7"},
            )
        )
        assert out.ok
        assert json.loads(seen[0]["body"]) == {"name": "x", "n": 2}
        assert seen[0]["headers"]["content-type"] == "application/json"
        assert seen[0]["headers"]["x-api-version"] == "7"

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_every_other_method_is_sent(self, server: tuple[str, list], method: str) -> None:
        base, seen = server
        assert call_operation(_request(base, method=method, path="/items/1")).ok
        assert seen[0]["method"] == method

    def test_a_path_parameter_is_encoded_not_concatenated(self, server: tuple[str, list]) -> None:
        base, seen = server
        out = call_operation(
            _request(base, path="/items/{id}/info", path_params={"id": "../x?y=1#z"})
        )
        assert out.ok
        assert seen[0]["path"] == "/items/..%2Fx%3Fy%3D1%23z/info"

    @pytest.mark.parametrize("value", ["..", "."])
    def test_a_dot_segment_parameter_is_refused(self, server: tuple[str, list], value: str) -> None:
        base, seen = server
        out = call_operation(_request(base, path="/items/{id}", path_params={"id": value}))
        assert not out.ok
        assert out.refusal == "service_bad_request"
        assert seen == []

    def test_a_missing_parameter_is_refused(self, server: tuple[str, list]) -> None:
        base, seen = server
        out = call_operation(_request(base, path="/items/{id}"))
        assert out.refusal == "service_bad_request"
        assert seen == []

    def test_a_non_json_body_is_returned_as_text(self, server: tuple[str, list]) -> None:
        base, _ = server
        out = call_operation(_request(base, path="/text"))
        assert out.ok
        assert out.content == "plain words"

    def test_a_404_is_a_failed_outcome_naming_it(self, server: tuple[str, list]) -> None:
        base, _ = server
        out = call_operation(_request(base, path="/missing", query={"k": "v"}))
        assert not out.ok
        assert "404" in out.error
        assert "no such thing here" in out.error
        assert "k=v" not in out.error

    def test_an_unknown_method_is_refused(self, server: tuple[str, list]) -> None:
        base, seen = server
        out = call_operation(_request(base, method="TRACE"))
        assert not out.ok
        assert seen == []

    def test_an_unreachable_host_fails_without_raising(self) -> None:
        out = call_operation(_request("http://127.0.0.1:9", path="/x"))
        assert not out.ok
        assert "127.0.0.1" in out.error


class TestThePerimeter:
    def test_an_unlisted_loopback_host_is_refused_before_any_socket(
        self, server: tuple[str, list]
    ) -> None:
        base, seen = server
        out = call_operation(_request(base, path="/items", hosts=()))
        assert not out.ok
        assert out.refusal == "service_address_not_allowed"
        assert seen == []

    def test_a_redirect_to_another_host_is_refused(self, server: tuple[str, list]) -> None:
        base, seen = server
        out = call_operation(_request(base, path="/redirect"))
        assert not out.ok
        assert out.refusal == "service_host_not_allowed"
        assert "evil.example.test" in out.error
        assert len(seen) == 1

    def test_a_base_url_with_credentials_or_a_bad_scheme_is_refused(self) -> None:
        for base in ("http://user:pw@127.0.0.1:1", "ftp://127.0.0.1", "not a url"):
            out = call_operation(_request(base, path="/x"))
            assert out.refusal == "service_host_not_allowed", base

    @pytest.mark.parametrize(
        "headers",
        [
            {"X-Note": "a\nb"},
            {"X-Note": "a\r\nInjected: 1"},
            {"Bad Name": "v"},
            {"Host": "evil.example.test"},
        ],
    )
    def test_a_bad_header_is_refused_before_any_socket(
        self, server: tuple[str, list], headers: dict[str, str]
    ) -> None:
        base, seen = server
        out = call_operation(_request(base, path="/items", headers=headers))
        assert not out.ok
        assert out.refusal == "service_bad_request"
        assert seen == []

    def test_an_oversized_response_is_cut_and_says_so(self, server: tuple[str, list]) -> None:
        base, _ = server
        with use_home(dataclasses.replace(current_home(), fetch_max_response_bytes=100)):
            out = call_operation(_request(base, path="/big"))
        assert out.ok
        assert out.content.count("z") == 100
        assert "[truncated: response exceeded 100 bytes]" in out.content

    def test_an_echoed_credential_is_redacted(self, server: tuple[str, list]) -> None:
        base, _ = server
        out = call_operation(
            _request(base, path="/echo-auth", headers={"Authorization": "Bearer s3cr3t-tok"})
        )
        assert out.ok
        assert "s3cr3t-tok" not in out.content
        assert "[redacted]" in out.content

    def test_a_credential_in_an_error_is_redacted(self, server: tuple[str, list]) -> None:
        base, _ = server
        out = call_operation(
            _request(
                base, path="/missing", headers={"X-Api-Key": "k-12345"}, secrets=("such thing",)
            )
        )
        assert not out.ok
        assert "such thing" not in out.error
        assert "k-12345" not in out.error
