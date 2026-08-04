"""OpenAI-compatible chat-completions adapter.

The one shipped implementation of ``core/llm.py``'s ``ChatBackend`` port, and
the **only** module in docket that knows what a chat-completions request or
response looks like on the wire. Everything above it — the turn loop, the tool
dispatcher, the gates — speaks ``ChatMessage``/``ToolCall``/``ChatResponse``.

**Zero new dependencies, on purpose.** The protocol is an HTTP POST with a JSON
body; stdlib ``urllib`` covers it. Pulling in a vendor SDK to do that would
re-introduce exactly the coupling docket deliberately avoids, and the standing
ban on hand-rolled *per-vendor* clients is not in tension with this: there is
one client here for one open protocol, not one per provider. llama.cpp, vLLM,
LM Studio, OpenAI, Groq, Together and OpenRouter all speak it.

**What this module refuses to do:** decide anything. It does not retry (that
policy lives in ``core/dispatch.py``, keyed on ``FailureKind``), does not
inspect tool calls (that is the gate's job), and does not raise for endpoint
failures — every ordinary failure comes back as ``ChatResponse(ok=False, ...)``
so the caller stays in control of what happens next.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from docket.core.llm import (
    ChatMessage,
    ChatResponse,
    Endpoint,
    Role,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from docket.core.runtime_driver import FailureKind

# Endpoints that return one of these are worth trying again: an overloaded or
# briefly-unreachable server is not an answer. Everything else in the 4xx range
# is a real rejection (bad request, bad credential, unknown model) and retrying
# it just spends the same money twice for the same error.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

_VALID_ROLES: frozenset[str] = frozenset({"system", "user", "assistant", "tool"})


# ── wire encoding ─────────────────────────────────────────────────────────────


def _encode_message(msg: ChatMessage) -> dict[str, Any]:
    """Translate one docket ``ChatMessage`` into a wire message object."""
    out: dict[str, Any] = {"role": msg.role}
    if msg.role == "tool":
        # `content` must be present even when empty: a tool message with no
        # content field is rejected outright by strict endpoints, and a tool
        # that legitimately produced no output is a normal occurrence.
        out["content"] = msg.content
        out["tool_call_id"] = msg.tool_call_id
        if msg.name:
            out["name"] = msg.name
        return out

    if msg.tool_calls:
        # An assistant message that requests tool calls may carry no prose at
        # all. `content: null` (not "") is the shape every endpoint accepts
        # when replaying such a message back as history.
        out["content"] = msg.content or None
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in msg.tool_calls
        ]
        return out

    out["content"] = msg.content
    return out


def _encode_tool(spec: ToolSpec) -> dict[str, Any]:
    """Translate one ``ToolSpec`` into a wire tool definition."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            # An empty schema still has to be a valid object schema, or models
            # that validate it before calling will silently never call the tool.
            "parameters": spec.parameters or {"type": "object", "properties": {}},
        },
    }


def build_payload(
    endpoint: Endpoint,
    messages: Sequence[ChatMessage],
    tools: Sequence[ToolSpec] = (),
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Build the request body. Split out from the POST so tests can assert on
    the exact wire shape without a socket."""
    payload: dict[str, Any] = {
        "model": endpoint.model_id,
        "messages": [_encode_message(m) for m in messages],
        "stream": False,
    }
    if tools:
        payload["tools"] = [_encode_tool(t) for t in tools]
        payload["tool_choice"] = "auto"
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if temperature is not None:
        payload["temperature"] = float(temperature)
    return payload


# ── wire decoding ─────────────────────────────────────────────────────────────


def _decode_tool_calls(raw: Any) -> list[ToolCall]:
    """Pull tool calls out of a wire assistant message.

    Tolerant by design about *shape* (missing ids, absent arguments) and strict
    about nothing — because rejecting a malformed call here would hide it from
    the gate. A call with an empty name survives this function and is refused
    downstream, where the refusal gets an audit entry.
    """
    if not isinstance(raw, list):
        return []
    calls: list[ToolCall] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        fn = entry.get("function")
        fn = fn if isinstance(fn, dict) else {}
        # Some servers omit `id` for single-call replies; the loop needs a
        # stable handle to address the result back, so synthesise a positional
        # one rather than dropping the call.
        call_id = str(entry.get("id") or f"call_{idx}")
        arguments = fn.get("arguments")
        if isinstance(arguments, dict):
            # A few OpenAI-compatible servers (llama.cpp among them, depending
            # on the grammar in use) emit already-decoded arguments instead of
            # the spec's JSON *string*. Re-encode so `ToolCall.arguments` keeps
            # its documented contract of being the raw JSON text.
            arguments = json.dumps(arguments)
        calls.append(
            ToolCall(
                id=call_id,
                name=str(fn.get("name") or ""),
                arguments=str(arguments if arguments is not None else "{}"),
            )
        )
    return calls


def _decode_usage(raw: Any) -> TokenUsage:
    """Read real token counts off the response, defaulting to zeros."""
    if not isinstance(raw, dict):
        return TokenUsage()

    def _as_int(value: Any) -> int:
        return int(value) if isinstance(value, int | float) else 0

    details = raw.get("prompt_tokens_details")
    cached = _as_int(details.get("cached_tokens")) if isinstance(details, dict) else 0
    return TokenUsage(
        input_tokens=_as_int(raw.get("prompt_tokens")),
        output_tokens=_as_int(raw.get("completion_tokens")),
        cached_tokens=cached,
    )


def decode_response(data: dict[str, Any]) -> ChatResponse:
    """Translate a decoded response body into a ``ChatResponse``.

    Separate from the transport so the tricky part — the many shapes real
    servers emit — is unit-testable without a network.
    """
    # An endpoint may answer 200 with an error object instead of choices.
    err = data.get("error")
    if isinstance(err, dict) and err:
        reason = str(err.get("message") or err)
        return ChatResponse(ok=False, raw=data, error=reason, failure_kind="invalid_output")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ChatResponse(
            ok=False,
            raw=data,
            error="response contained no choices",
            failure_kind="invalid_output",
        )
    first = choices[0]
    if not isinstance(first, dict):
        return ChatResponse(
            ok=False, raw=data, error="malformed choice entry", failure_kind="invalid_output"
        )

    wire_msg = first.get("message")
    wire_msg = wire_msg if isinstance(wire_msg, dict) else {}
    content = wire_msg.get("content")
    role_raw = str(wire_msg.get("role") or "assistant")
    role: Role = role_raw if role_raw in _VALID_ROLES else "assistant"  # type: ignore[assignment]

    message = ChatMessage(
        role=role,
        content=str(content) if isinstance(content, str) else "",
        tool_calls=_decode_tool_calls(wire_msg.get("tool_calls")),
    )
    return ChatResponse(
        ok=True,
        message=message,
        finish_reason=str(first.get("finish_reason") or ""),
        usage=_decode_usage(data.get("usage")),
        raw=data,
    )


# ── transport ─────────────────────────────────────────────────────────────────


def _classify_http_status(status: int) -> FailureKind:
    """Map an HTTP status onto docket's retry vocabulary.

    ``nonzero_exit``/``daemon_error`` read oddly for HTTP; they are reused
    because ``core/dispatch.py``'s ``_RETRYABLE_FAILURE_KINDS`` is keyed on
    the existing ``FailureKind`` literals, and inventing a synonym would mean
    either a parallel retry table or a rename across dozens of test modules
    for no behavioural gain. The daemon these names originally described is
    gone; renaming the vocabulary itself remains a separate, not-yet-scheduled
    cleanup.
    """
    return "daemon_error" if status in _RETRYABLE_STATUS else "nonzero_exit"


class OpenAIChatClient:
    """``ChatBackend`` over an OpenAI-compatible ``/v1/chat/completions``.

    Stateless apart from its ``Endpoint`` — safe to construct per call or hold
    for the life of a loop.
    """

    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint

    @property
    def url(self) -> str:
        return f"{self.endpoint.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.endpoint.api_key:
            headers["Authorization"] = f"Bearer {self.endpoint.api_key}"
        return headers

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        """Send one exchange. Never raises for an endpoint or transport failure."""
        if not self.endpoint.base_url:
            return ChatResponse(
                ok=False,
                error="no endpoint configured for this model",
                failure_kind="daemon_error",
            )
        payload = build_payload(self.endpoint, messages, tools, max_tokens, temperature)
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            self.url, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as ex:
            # The body of an error response is where the useful message lives
            # (an unknown model, a bad key, a context-length overflow); reading
            # it can itself fail on a truncated response, hence the guard.
            try:
                detail = ex.read().decode("utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            return ChatResponse(
                ok=False,
                error=f"HTTP {ex.code} from {self.url}: {detail[:500] or ex.reason}",
                failure_kind=_classify_http_status(ex.code),
            )
        except TimeoutError:
            return ChatResponse(
                ok=False,
                error=f"timed out after {timeout}s calling {self.url}",
                failure_kind="timeout",
            )
        except urllib.error.URLError as ex:
            # urlopen wraps a socket timeout in URLError on some platforms, so
            # the check above is not sufficient on its own.
            if isinstance(ex.reason, TimeoutError):
                return ChatResponse(
                    ok=False,
                    error=f"timed out after {timeout}s calling {self.url}",
                    failure_kind="timeout",
                )
            return ChatResponse(
                ok=False,
                error=f"cannot reach {self.url}: {ex.reason}",
                failure_kind="daemon_error",
            )
        except OSError as ex:
            return ChatResponse(
                ok=False, error=f"cannot reach {self.url}: {ex}", failure_kind="daemon_error"
            )

        try:
            data = json.loads(raw_body) if raw_body.strip() else {}
        except json.JSONDecodeError as ex:
            return ChatResponse(
                ok=False,
                error=f"endpoint returned non-JSON ({ex}): {raw_body[:200]}",
                failure_kind="invalid_output",
            )
        if not isinstance(data, dict):
            return ChatResponse(
                ok=False,
                error=f"endpoint returned a {type(data).__name__}, expected an object",
                failure_kind="invalid_output",
            )
        return decode_response(data)


# ── endpoint resolution ───────────────────────────────────────────────────────


def resolve_endpoint(model: str) -> Endpoint | None:
    """Resolve a ``provider/model-id`` string to a callable endpoint.

    Precedence, highest first:

    1. ``DOCKET_LLM_BASE_URL`` / ``DOCKET_LLM_API_KEY`` — a process-wide
       override that points every model at one endpoint. Exists for local
       development and for tests that want a stub server without touching
       stored config.
    2. The stored provider block for ``<provider>``.

    The API key falls back through ``DOCKET_LLM_API_KEY``, then the provider
    block's own key, then ``<PROVIDER>_API_KEY`` from the environment. Returns
    ``None`` when no base URL can be found, so callers report an actionable
    "no endpoint configured" rather than posting into the void.

    The stored-config lookup reads docket's own fleet registry
    (``core/fleet.py``'s ``get_local_provider``) directly -- there is no
    daemon config file left to have ever pointed at.
    """
    provider, _, model_id = model.partition("/")
    if not model_id:
        provider, model_id = "", model

    env_base = os.environ.get("DOCKET_LLM_BASE_URL", "").strip()
    env_key = os.environ.get("DOCKET_LLM_API_KEY", "").strip()

    stored: dict[str, Any] = {}
    if provider and not env_base:
        from docket.core import fleet as _fleet

        stored = _fleet.get_local_provider(provider) or {}

    base_url = env_base or str(stored.get("baseUrl") or "").strip()
    if not base_url:
        return None

    api_key = env_key or str(stored.get("apiKey") or "").strip()
    if not api_key and provider:
        api_key = os.environ.get(f"{provider.upper().replace('-', '_')}_API_KEY", "").strip()
    # Local servers conventionally require *some* bearer token but ignore its
    # value; "local" is what docket already writes into the provider block.
    if api_key == "local":
        api_key = ""

    return Endpoint(base_url=base_url, model_id=model_id, api_key=api_key, provider=provider)


def client_for(model: str) -> OpenAIChatClient | None:
    """Build a client for ``provider/model-id``, or ``None`` if unresolvable."""
    endpoint = resolve_endpoint(model)
    return OpenAIChatClient(endpoint) if endpoint else None
