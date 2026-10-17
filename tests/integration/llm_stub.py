"""A loopback OpenAI-compatible stub for integration tests: scripted chat-completion bodies,
one per POST, plus the ``llm_server`` fixture that starts and stops them."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


def _tool_call_response(
    name: str, arguments: dict[str, Any], call_id: str = "call-1"
) -> dict[str, Any]:
    return {
        "model": "local/qwen3-stub-served",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def _final_response(text: str) -> dict[str, Any]:
    return {
        "model": "local/qwen3-stub-served",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }


class _ScriptedLLMServer:
    """A loopback ``ThreadingHTTPServer`` replaying a fixed script of
    OpenAI-compatible chat-completion bodies, one per POST."""

    def __init__(
        self,
        responses: list[dict[str, Any]],
        on_request: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.requests: list[dict[str, Any]] = []
        responses_ref = self.responses = list(responses)
        requests_ref = self.requests

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                requests_ref.append(json.loads(body.decode("utf-8")))
                if on_request is not None:
                    on_request(requests_ref[-1])
                index = min(len(requests_ref) - 1, len(responses_ref) - 1)
                payload = json.dumps(responses_ref[index]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt: str, *args: object) -> None:  # pragma: no cover - silence
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/v1"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def llm_server() -> Iterator[Any]:
    servers: list[_ScriptedLLMServer] = []

    def _start(
        responses: list[dict[str, Any]],
        on_request: Callable[[dict[str, Any]], None] | None = None,
    ) -> _ScriptedLLMServer:
        server = _ScriptedLLMServer(responses, on_request)
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.stop()
