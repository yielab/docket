from __future__ import annotations

import email.utils
import json
from collections.abc import Sequence
from datetime import UTC
from typing import Any

from docket.agent.llm import (
    ChatMessage,
    ChatResponse,
    Endpoint,
    Role,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from docket.agent.ports import FailureKind
from docket.kernel import clock as _clock

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


def _is_anthropic(model_id: str) -> bool:
    return model_id.rsplit("/", 1)[-1].lower().startswith("claude")


def _mark_cacheable(message: dict[str, Any]) -> None:
    """Turn a message's non-empty text content into one ephemeral cache-marked part."""
    content = message.get("content")
    if isinstance(content, str) and content:
        part = {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
        message["content"] = [part]


def build_payload(
    endpoint: Endpoint,
    messages: Sequence[ChatMessage],
    tools: Sequence[ToolSpec] = (),
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Build the request body. Split out from the POST so tests can assert on
    the exact wire shape without a socket."""
    encoded = [_encode_message(m) for m in messages]
    if _is_anthropic(endpoint.model_id) and encoded:
        if encoded[0]["role"] == "system":
            _mark_cacheable(encoded[0])
        _mark_cacheable(encoded[-1])
    payload: dict[str, Any] = {
        "model": endpoint.model_id,
        "messages": encoded,
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


_REQUEST_PART_BY_ROLE = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "toolResults",
}


def request_part_bytes(payload: dict[str, Any]) -> dict[str, int]:
    """Bytes of each part of an encoded request body; trace-store requirement 28."""
    sizes = dict.fromkeys(("system", "tools", "toolResults", "assistant", "user"), 0)
    for message in payload.get("messages", []):
        sizes[_REQUEST_PART_BY_ROLE[message["role"]]] += _utf8_len(message)
    for tool in payload.get("tools", []):
        sizes["tools"] += _utf8_len(tool)
    return sizes


def _utf8_len(part: Any) -> int:
    return len(json.dumps(part, ensure_ascii=False).encode("utf-8", errors="replace"))


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
    written = _as_int(details.get("cache_write_tokens")) if isinstance(details, dict) else 0
    return TokenUsage(
        input_tokens=_as_int(raw.get("prompt_tokens")),
        output_tokens=_as_int(raw.get("completion_tokens")),
        cached_tokens=cached,
        cache_write_tokens=written or _as_int(raw.get("cache_creation_input_tokens")),
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

    finish_reason = str(first.get("finish_reason") or "")
    choice_error = first.get("error")
    if finish_reason == "error" or (isinstance(choice_error, dict) and choice_error):
        detail = choice_error if isinstance(choice_error, dict) else {}
        reason = str(detail.get("message") or detail or "endpoint returned finish_reason=error")
        code = detail.get("code")
        failure_kind: FailureKind = "invalid_output"
        if isinstance(code, int) and not isinstance(code, bool):
            failure_kind = _classify_http_status(code)
        return ChatResponse(ok=False, raw=data, error=reason, failure_kind=failure_kind)

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
        finish_reason=finish_reason,
        usage=_decode_usage(data.get("usage")),
        raw=data,
    )


# ── transport ─────────────────────────────────────────────────────────────────


def _classify_http_status(status: int) -> FailureKind:
    """Map an HTTP status onto docket's retry vocabulary.

    ``nonzero_exit``/``daemon_error`` read oddly for HTTP; they are reused
    because ``hops/application/runner.py``'s ``_RETRYABLE_FAILURE_KINDS`` is keyed on
    the existing ``FailureKind`` literals, and inventing a synonym would mean
    either a parallel retry table or a rename across dozens of test modules
    for no behavioural gain. The daemon these names originally described is
    gone; renaming the vocabulary itself remains a separate, not-yet-scheduled
    cleanup.
    """
    return "daemon_error" if status in _RETRYABLE_STATUS else "nonzero_exit"


def _retry_after_seconds(headers: Any) -> float | None:
    """``Retry-After`` as seconds: integer form, or an HTTP-date as a delta from now clamped
    to zero. Absent or unparseable is ``None`` ("the endpoint named no wait", not zero)."""
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(int(value)))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - _clock.now()).total_seconds())
