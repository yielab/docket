"""What a test needs to be an A2A client of ``docket start``: JSON-RPC calls, a push listener.

``A2AClient`` speaks to ``POST /a2a`` through the e2e ``Service`` (so the Bearer token is the real
one); ``PushListener`` is the local HTTP endpoint a push notification config points at. The
``normalize`` function turns a recorded exchange into the form the fixtures hold: ids and times
replaced by placeholders, so two runs of the same scenario compare equal.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tests.support.e2e import Service, World

EXTENSION = "https://docket.dev/schemas/operator-v1.1/question.schema.json"
CONSULT = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}
_TIME_KEYS = frozenset({"timestamp", "expiresAt", "askedAt"})


class A2AClient:
    """JSON-RPC 2.0 calls to ``POST /a2a`` of a running service."""

    def __init__(self, service: Service) -> None:
        self.service = service
        self._ids = iter(range(1, 10_000))

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """The request object ``rpc`` would send."""
        return {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": dict(params)}

    def send(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """POST *request*; the JSON-RPC response (HTTP status 200 is part of the contract)."""
        status, response = self.service.post("/a2a", dict(request))
        assert status == 200, response
        assert isinstance(response, dict)
        return response

    def rpc(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        return self.send(self.request(method, params))

    def result(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """The ``result`` of a call that must have succeeded."""
        response = self.rpc(method, params)
        assert "error" not in response, response
        return dict(response["result"])

    def send_text(self, text: str, message_id: str, **extra: Any) -> dict[str, Any]:
        """``message/send`` creating a task from *text*; the ``Task``."""
        message = {"kind": "message", "role": "user", "messageId": message_id}
        message["parts"] = [{"kind": "text", "text": text}]
        return self.result("message/send", {"message": message, **extra})

    def answer(self, task_id: str, message_id: str, action: str, **content: Any) -> dict[str, Any]:
        """The raw response of a ``message/send`` that answers *task_id* with a result data part."""
        data: dict[str, Any] = {"action": action}
        if content:
            data["content"] = content
        message = {"kind": "message", "role": "user", "messageId": message_id, "taskId": task_id}
        message["parts"] = [{"kind": "data", "data": data}]
        return self.rpc("message/send", {"message": message})

    def get(self, task_id: str) -> dict[str, Any]:
        return self.result("tasks/get", {"id": task_id})

    def state(self, task_id: str) -> str:
        return str(self.get(task_id)["status"]["state"])

    def wait_state(self, w: World, task_id: str, state: str, timeout: float = 30) -> dict[str, Any]:
        """Poll ``tasks/get`` until the task reads *state*; the ``Task``."""
        w.wait_for(lambda: self.state(task_id) == state, timeout, f"the task to read {state}")
        return self.get(task_id)


def agent_card(service: Service, token: str | None) -> tuple[int, Any]:
    """``(status, JSON)`` of ``GET /.well-known/agent.json``, with *token* as Bearer when given."""
    request = urllib.request.Request(service.url + "/.well-known/agent.json")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class PushListener:
    """A loopback HTTP endpoint that records every POST it receives."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.received.append({"headers": dict(self.headers), "body": body})
                self.send_response(204)
                self.end_headers()

            def log_message(self, fmt: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/hook"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def kinds(self) -> list[tuple[str, str]]:
        """``(event type, task id)`` of every notification so far, in arrival order."""
        return [(r["body"]["type"], r["body"]["data"].get("taskId", "")) for r in self.received]


@contextmanager
def push_listener() -> Iterator[PushListener]:
    listener = PushListener()
    listener._thread.start()
    try:
        yield listener
    finally:
        listener._server.shutdown()
        listener._server.server_close()


def normalize(value: Any, names: Mapping[str, str]) -> Any:
    """*value* with every string in *names* replaced by its placeholder and every time by
    ``<time>``."""
    if isinstance(value, dict):
        return {k: "<time>" if k in _TIME_KEYS else normalize(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v, names) for v in value]
    if isinstance(value, str):
        out = value
        for real, placeholder in names.items():
            out = out.replace(real, placeholder)
        return out
    return value
