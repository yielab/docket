"""A loopback HTTP service that records what it was sent: the oracle for a declared service."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every GET and POST with a small JSON body and records method, path, lowercased
    headers and body in ``seen``."""

    seen: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *args: object) -> None:
        pass

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        type(self).seen.append(
            {"method": self.command, "path": self.path, "headers": headers, "body": raw.decode()}
        )
        payload = json.dumps(
            {"id": 7, "name": "Ana", "echo": self.headers.get("Authorization")}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _handle


@contextmanager
def recording_service() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Serve on a free loopback port; yields the base URL and the list of requests seen."""
    RecordingHandler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", RecordingHandler.seen
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
