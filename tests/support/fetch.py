"""A loopback HTTP server and a closed-by-default home for the `fetch` tool tests."""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from docket.kernel.home import Home, current_home, use_home


@pytest.fixture(autouse=True)
def hermetic(tmp_path: Path) -> Iterator[None]:
    """Isolate every docket-owned store this module touches and default the
    fetch allowlist closed so each test opts a host in explicitly."""
    with (
        use_home(Home(tmp_path)),
        use_home(
            dataclasses.replace(current_home(), tool_approval_timeout=0, fetch_allowed_domains=())
        ),
    ):
        yield


class FetchHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet the test output
        pass

    def _reply(self, status: int, body: bytes = b"", content_type: str = "text/plain") -> None:
        self.send_response(status)
        if body:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # BaseHTTPRequestHandler's own naming convention
        if self.path == "/ok":
            self._reply(200, b"hello world")
        elif self.path == "/big":
            # 'z' deliberately, not 'x' -- so counting filler bytes in the
            # truncated result can't be confused by an incidental 'x' in the
            # "HTTP 200 text/plain" header or the "truncated" message.
            self._reply(200, b"z" * 5000)
        elif self.path == "/slow":
            time.sleep(2)
            self._reply(200, b"too late")
        elif self.path == "/drip":
            # Headers, then one byte every 0.4s: each read returns before a socket timeout.
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            try:
                for _ in range(10):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.4)
            except OSError:
                pass
        elif self.path == "/missing":
            self._reply(404, b"not found")
        elif self.path == "/redirect-allowed":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/redirect-blocked":
            self.send_response(302)
            self.send_header("Location", "http://evil.example.test/pwned")
            self.end_headers()
        else:
            self._reply(404, b"unknown path")


@pytest.fixture
def fetch_server() -> Iterator[str]:
    """A real local HTTP server; yields its base URL (``http://127.0.0.1:<port>``)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FetchHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = srv.server_address[0], srv.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@contextmanager
def allow(server_url: str) -> Iterator[None]:
    host = server_url.split("//", 1)[1].split(":")[0]
    with use_home(dataclasses.replace(current_home(), fetch_allowed_domains=(host,))):
        yield
