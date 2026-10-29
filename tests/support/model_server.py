"""One loopback OpenAI-compatible fake model for every Python test.

``FakeModel`` serves ``GET /v1/models``, ``POST /v1/chat/completions`` and ``POST /v1/messages`` (the
Anthropic Messages shape, decoded into the same ``Request`` and encoded from the same replies; its
``usage`` is the one the test sets) on a free port. A script
routes replies by the role named in the system prompt (``script=``) or by request order
(``sequence=``). A reply runs out loudly: HTTP 400 naming the fake, never a silent repeat unless
``repeat_last`` asks for one. Reply builders: ``say call calls fail hang not_json truncated hold``.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

_ROLE_LINE = re.compile(r"the \*\*([^*]+)\*\* of the \*\*")
_HOLD_LIMIT_S = 30.0
_CONTEXT_FULL = "request exceeds the available context size"


@dataclass(frozen=True)
class Reply:
    """What the fake answers one request with; build it with the module's builders."""

    status: int = 200
    message: Mapping[str, Any] | None = None
    finish_reason: str = "stop"
    raw_body: str | None = None
    error_message: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    delay_s: float = 0.0
    gate: tuple[threading.Event, Reply] | None = None


@dataclass(frozen=True)
class Request:
    """One parsed request, as the fake received it. An Anthropic Messages body is read into the
    chat-completions shape (``body``); ``raw`` is the body as sent and ``headers`` its headers, names lower-cased."""

    body: Mapping[str, Any]
    role: str | None
    path: str = "/v1/chat/completions"
    headers: Mapping[str, str] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self.body.get("messages", []))

    @property
    def tools(self) -> list[str]:
        return [str(t.get("function", {}).get("name", "")) for t in self.body.get("tools", [])]

    @property
    def system_text(self) -> str:
        return next((_text(m) for m in self.messages if m.get("role") == "system"), "")

    @property
    def last_user_text(self) -> str:
        return next((_text(m) for m in reversed(self.messages) if m.get("role") == "user"), "")

    def tool_result(self, call_id: str) -> str | None:
        """The content of the tool message answering *call_id*, or ``None``."""
        for message in self.messages:
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id:
                return _text(message)
        return None


Step = Reply | Callable[[Request], Reply]


def _text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


def _chars(message: Mapping[str, Any]) -> int:
    calls = message.get("tool_calls") or []
    return len(_text(message)) + sum(len(c["function"]["arguments"]) for c in calls)


def _from_anthropic(body: Mapping[str, Any]) -> dict[str, Any]:
    """An Anthropic Messages body in the chat-completions shape the scripts read."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": str(b.get("text", ""))} for b in body.get("system") or []
    ]
    for message in body.get("messages", []):
        blocks = message["content"]
        blocks = [{"type": "text", "text": blocks}] if isinstance(blocks, str) else blocks
        text = "".join(str(b.get("text", "")) for b in blocks if b["type"] == "text")
        if message["role"] == "assistant":
            uses = [b for b in blocks if b["type"] == "tool_use"]
            entry: dict[str, Any] = {"role": "assistant", "content": text}
            if uses:
                entry["tool_calls"] = [_wire_call(b["name"], b["input"], b["id"]) for b in uses]
            messages.append(entry)
            continue
        for block in blocks:
            if block["type"] == "tool_result":
                content = block.get("content", "")
                messages.append(
                    {"role": "tool", "tool_call_id": block["tool_use_id"], "content": content}
                )
        if text:
            messages.append({"role": "user", "content": text})
    out: dict[str, Any] = {"model": body.get("model"), "messages": messages}
    if body.get("tools"):
        out["tools"] = [{"function": {"name": t["name"]}} for t in body["tools"]]
    return out


_STOP_REASON = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens"}


def _to_anthropic(model: str, reply: Reply, usage: Mapping[str, int]) -> dict[str, Any]:
    """A reply in the Anthropic Messages shape."""
    message = reply.message or {}
    blocks: list[dict[str, Any]] = []
    if message.get("content"):
        blocks.append({"type": "text", "text": message["content"]})
    for entry in message.get("tool_calls") or []:
        function = entry["function"]
        blocks.append(
            {
                "type": "tool_use",
                "id": entry["id"],
                "name": function["name"],
                "input": json.loads(function["arguments"]),
            }
        )
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": blocks,
        "stop_reason": _STOP_REASON.get(reply.finish_reason, reply.finish_reason),
        "stop_sequence": None,
        "usage": dict(usage),
    }


def _wire_call(tool: str, arguments: Mapping[str, Any], call_id: str) -> dict[str, Any]:
    function = {"name": tool, "arguments": json.dumps(dict(arguments))}
    return {"id": call_id, "type": "function", "function": function}


def say(text: str) -> Reply:
    """A final message."""
    return Reply(message={"role": "assistant", "content": text})


def call(tool: str, call_id: str | None = None, **arguments: Any) -> Reply:
    """One tool call; *arguments* become the JSON arguments string."""
    entry = _wire_call(tool, arguments, call_id or "call-1")
    return Reply(
        message={"role": "assistant", "content": "", "tool_calls": [entry]},
        finish_reason="tool_calls",
    )


def calls(
    entries: Sequence[tuple[str, Mapping[str, Any]] | tuple[str, Mapping[str, Any], str]],
) -> Reply:
    """Several tool calls in one reply: ``(tool, arguments)`` or ``(tool, arguments, call_id)``."""
    wire = [
        _wire_call(e[0], e[1], e[2] if len(e) == 3 else f"call-{i}")
        for i, e in enumerate(entries, 1)
    ]
    return Reply(
        message={"role": "assistant", "content": "", "tool_calls": wire},
        finish_reason="tool_calls",
    )


def fail(status: int, message: str = "", retry_after: int | None = None) -> Reply:
    """An HTTP error, with a ``Retry-After`` header when *retry_after* is given."""
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return Reply(
        status=status, error_message=message or f"fake model: status {status}", headers=headers
    )


def hang(seconds: float) -> Reply:
    """A final message that arrives only after *seconds*, to trip a client timeout."""
    return Reply(message={"role": "assistant", "content": "late"}, delay_s=seconds)


def not_json() -> Reply:
    """A 200 response whose body is not JSON."""
    return Reply(raw_body="<html>not a chat completion</html>")


def truncated(text: str = "") -> Reply:
    """A message cut short by the output cap (``finish_reason: length``)."""
    return Reply(message={"role": "assistant", "content": text}, finish_reason="length")


def hold(event: threading.Event, then: Reply) -> Reply:
    """Block until the test sets *event*, then answer with *then*."""
    return Reply(gate=(event, then))


class FakeModel:
    """A loopback fake model. Use as a context manager or call ``start`` and ``stop``."""

    def __init__(
        self,
        script: Mapping[str, Sequence[Step]] | None = None,
        *,
        sequence: Sequence[Step] | None = None,
        repeat_last: bool = False,
        context_window_chars: int | None = None,
        models: Sequence[str] = ("e2e-model",),
        usage: Mapping[str, int] | None = None,
    ) -> None:
        if script is not None and sequence is not None:
            raise ValueError("give a role script or an ordinal sequence, not both")
        self._script = {role: list(steps) for role, steps in (script or {}).items()}
        self._sequence = list(sequence) if sequence is not None else None
        self._repeat_last = repeat_last
        self._context_window_chars = context_window_chars
        self._models = tuple(models)
        self._usage = usage
        self._lock = threading.Lock()
        self._used: dict[str, int] = {}
        self._closing = threading.Event()
        self.requests: list[Request] = []
        self.models_calls = 0
        self._server: ThreadingHTTPServer | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> FakeModel:
        owner = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner._handle_get(self)

            def do_POST(self) -> None:
                owner._handle_post(self)

            def log_message(self, fmt: str, *args: object) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        self._server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._closing.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> FakeModel:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    @property
    def base_url(self) -> str:
        assert self._server is not None, "FakeModel is not started"
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def by_role(self, role: str) -> list[Request]:
        with self._lock:
            return [r for r in self.requests if r.role == role]

    # ── serving ──────────────────────────────────────────────────────────────

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        if handler.path.split("?")[0] != "/v1/models":
            return self._send(handler, 404, {"error": {"message": "fake model: no such path"}})
        with self._lock:
            self.models_calls += 1
        rows = [{"id": m, "object": "model"} for m in self._models]
        self._send(handler, 200, {"object": "list", "data": rows})

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length", 0))
        raw = handler.rfile.read(length)
        path = handler.path.split("?")[0]
        if path not in ("/v1/chat/completions", "/v1/messages"):
            return self._send(handler, 404, {"error": {"message": "fake model: no such path"}})
        sent = json.loads(raw.decode("utf-8"))
        anthropic = path == "/v1/messages"
        body = _from_anthropic(sent) if anthropic else sent
        role = self._role_of(body)
        request = Request(
            body=body,
            role=role,
            path=path,
            headers={k.lower(): v for k, v in handler.headers.items()},
            raw=sent,
        )
        total = sum(_chars(m) for m in request.messages)
        over = self._context_window_chars is not None and total > self._context_window_chars
        with self._lock:
            self.requests.append(request)
            step, why = (None, "") if over else self._pick(request)
        if over:
            return self._send(handler, 400, self._error_body(anthropic, _CONTEXT_FULL))
        if step is None:
            return self._send(handler, 400, self._error_body(anthropic, f"fake model: {why}"))
        reply = step(request) if callable(step) else step
        self._answer(handler, reply, total, anthropic)

    @staticmethod
    def _error_body(anthropic: bool, message: str) -> dict[str, Any]:
        if anthropic:
            return {"type": "error", "error": {"type": "api_error", "message": message}}
        return {"error": {"message": message}}

    @staticmethod
    def _role_of(body: Mapping[str, Any]) -> str | None:
        for message in body.get("messages", []):
            if message.get("role") == "system":
                found = _ROLE_LINE.search(_text(message))
                return found.group(1) if found else None
        return None

    def _pick(self, request: Request) -> tuple[Step | None, str]:
        if self._sequence is not None:
            key, steps = "", self._sequence
        elif request.role is None:
            return None, "no role line in the system prompt and no ordinal sequence"
        else:
            key, steps = request.role, self._script.get(request.role, [])
        index = self._used.get(key, 0)
        self._used[key] = index + 1
        if index < len(steps):
            return steps[index], ""
        if self._repeat_last and steps:
            return steps[-1], ""
        return None, f"no step left for {key or 'the sequence'} (request {index + 1})"

    def _answer(
        self,
        handler: BaseHTTPRequestHandler,
        reply: Reply,
        prompt_chars: int,
        anthropic: bool = False,
    ) -> None:
        if reply.gate is not None:
            event, then = reply.gate
            event.wait(_HOLD_LIMIT_S)
            return self._answer(handler, then, prompt_chars, anthropic)
        if reply.delay_s and self._closing.wait(reply.delay_s):
            return
        if reply.raw_body is not None:
            return self._send_raw(handler, reply.status, reply.raw_body.encode(), reply.headers)
        if reply.message is None:
            error = self._error_body(anthropic, reply.error_message)
            return self._send(handler, reply.status, error, reply.headers)
        completion = max(1, _chars(reply.message) // 4)
        if anthropic:
            usage = self._usage or {"input_tokens": prompt_chars // 4, "output_tokens": completion}
            body = _to_anthropic(self._models[0], reply, usage)
            return self._send(handler, reply.status, body, reply.headers)
        payload = {
            "model": self._models[0],
            "choices": [{"message": dict(reply.message), "finish_reason": reply.finish_reason}],
            "usage": {"prompt_tokens": prompt_chars // 4, "completion_tokens": completion},
        }
        self._send(handler, reply.status, payload, reply.headers)

    def _send(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        payload: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._send_raw(handler, status, json.dumps(payload).encode(), headers or {})

    @staticmethod
    def _send_raw(
        handler: BaseHTTPRequestHandler, status: int, data: bytes, headers: Mapping[str, str]
    ) -> None:
        try:
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(data)))
            for name, value in headers.items():
                handler.send_header(name, value)
            handler.end_headers()
            handler.wfile.write(data)
        except OSError:
            return None


@pytest.fixture()
def fake_model() -> Iterator[Callable[..., FakeModel]]:
    """A factory for started ``FakeModel`` servers; every one stops at teardown."""
    started: list[FakeModel] = []

    def _start(*args: Any, **kwargs: Any) -> FakeModel:
        model = FakeModel(*args, **kwargs).start()
        started.append(model)
        return model

    yield _start
    for model in started:
        model.stop()


def write_file(path: str, content: str) -> Reply:
    """A ``write`` tool call, the step most scripted implementers make."""
    return call("write", path=path, content=content)


def only_if(marker: str, then: Reply) -> Callable[[Request], Reply]:
    """A step that answers *then* only when the request carries *marker*, else fails loudly."""

    def step(request: Request) -> Reply:
        if marker in request.last_user_text:
            return then
        return fail(400, f"fake model: the request does not carry {marker!r}")

    return step


def register_lab_provider(server: FakeModel, **fields: Any) -> None:
    """A catalog row named `lab` over *server*, with one model `m`; *fields* are further document
    keys (`local`, a profile and its overrides)."""
    from docket.models import catalog

    catalog.save_provider(
        catalog.ProviderSpec.model_validate(
            {
                "name": "lab",
                "baseUrl": server.base_url,
                "auth": {"type": "none"},
                "models": [{"id": "m", "contextWindow": 32768}],
                **fields,
            }
        )
    )
