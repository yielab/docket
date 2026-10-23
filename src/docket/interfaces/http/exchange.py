"""One HTTP exchange as the route handlers see it: how a response is written, a body is read.

Every route handler takes an ``HttpExchange`` and answers through it, so a JSON error is built in
exactly one place and a request body is read, capped and parsed in exactly one place. The two
methods ``_submit_sweep`` and ``_render_health`` reach state the server process owns (the sweep
pool and its stop flag); ``server._DocketHandler`` implements them, so no route module imports
the server."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from docket.teams import provisioning as _prov

# Cap on a POST request body this server will read -- above it, `_read_body`
# sends 413 without touching `rfile`, so a caller cannot pin a handler thread
# by promising (and trickling) an unbounded body.
MAX_POST_BODY_BYTES = 1024 * 1024


class HttpExchange(BaseHTTPRequestHandler):
    """The request/response surface shared by every route. ``serve_token`` (a `run_serve`
    subclass attribute) empty means "disallow all auth" -- never an accidental unauthenticated
    pass-through."""

    serve_token: str = ""
    dispatch_on: bool = False
    # Bounds every blocking socket read (request line, headers, body) so a
    # client that opens a connection and never finishes sending cannot pin a
    # handler thread forever.
    timeout = 30

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _submit_sweep(self, project: str) -> bool:
        """Start a dispatch sweep of *project*; the server's pool answers this."""
        raise NotImplementedError

    def _render_health(self) -> str:
        """The ``/health`` body; the server's stop flag and sweep pool answer this."""
        raise NotImplementedError

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._send(json.dumps(payload).encode(), "application/json", status)

    def _send_json_error(self, msg: str, status: int = 400) -> None:
        body = json.dumps({"ok": False, "error": msg}).encode()
        self._send(body, "application/json", status)

    def _read_body(self) -> bytes | None:
        """Read a POST body up to `MAX_POST_BODY_BYTES`, sending `413` and
        returning `None` without touching `rfile` above the cap."""
        # An absent/zero Content-Length reads as `b"{}"`, matching every
        # caller's existing no-body behavior.
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length > MAX_POST_BODY_BYTES:
            self._send_json_error("Request body too large", 413)
            return None
        if length <= 0:
            return b"{}"
        return self.rfile.read(length)

    def _read_json_object(
        self, *, not_object: str = "Request body must be a JSON object", blank: bool = False
    ) -> dict[str, Any] | None:
        """Read the body as a JSON object, or answer `400` and return `None`; *not_object* words
        the non-object error and *blank* reads an empty body as ``{}``."""
        raw = self._read_body()
        if raw is None:
            return None
        try:
            body: Any = json.loads((raw or b"{}") if blank else raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return None
        if not isinstance(body, dict):
            self._send_json_error(not_object, 400)
            return None
        return body

    def _reject_bad_project_id(self, project: str) -> bool:
        """Send a `400` and return `True` if *project* fails `validate_project_id` --
        every project-path-segment handler but `post_pod` (whose `400` comes
        from `provision_pod`'s own boundary check) calls this right after auth."""
        try:
            _prov.validate_project_id(project)
        except _prov.ProjectIdError as exc:
            self._send_json_error(str(exc), 400)
            return True
        return False
