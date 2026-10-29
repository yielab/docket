"""The Anthropic Messages wire: ``POST {baseUrl}/messages``.

The second dialect behind ``openai_http.py``'s one client. This module only encodes a request and
decodes a reply (the table is requirement 10 of ``specs/functional/model-profiles.spec.md``); the
transport, headers, timeouts and error handling stay in the client. It invents no value: a missing
``max_tokens`` is a failed call, not a default.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    Endpoint,
    TokenUsage,
    ToolCall,
    ToolSpec,
)
from docket.models.adapters.openai_wire import _utf8_len

_EPHEMERAL = {"type": "ephemeral"}

_FINISH_REASON = {
    "tool_use": "tool_calls",
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
}


# ── wire encoding ─────────────────────────────────────────────────────────────


def _tool_input(arguments: str) -> dict[str, Any]:
    """The parsed ``arguments`` object; a string that is not a JSON object is an empty input."""
    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _encode_blocks(msg: ChatMessage) -> tuple[str, list[dict[str, Any]]]:
    """The wire role and content blocks of one docket message (``system`` excluded)."""
    if msg.role == "tool":
        return "user", [
            {"type": "tool_result", "tool_use_id": msg.tool_call_id, "content": msg.content}
        ]
    blocks: list[dict[str, Any]] = []
    if msg.content:
        blocks.append(_text_block(msg.content))
    if msg.role == "assistant":
        blocks.extend(
            {"type": "tool_use", "id": c.id, "name": c.name, "input": _tool_input(c.arguments)}
            for c in msg.tool_calls
        )
        return "assistant", blocks
    return "user", blocks


def _encode_messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Alternating-role wire messages: consecutive same-role messages share one, so the results of
    one assistant turn and the nudge that follows travel in a single ``user`` message."""
    encoded: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            continue
        role, blocks = _encode_blocks(msg)
        if not blocks:
            continue
        if encoded and encoded[-1]["role"] == role:
            encoded[-1]["content"].extend(blocks)
        else:
            encoded.append({"role": role, "content": blocks})
    return encoded


def _encode_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters or {"type": "object", "properties": {}},
    }


def request_problem(endpoint: Endpoint, max_tokens: int | None) -> str | None:
    """Why this request cannot be sent, or ``None``. The endpoint requires ``max_tokens``; with
    neither the request's value nor the endpoint's declared or observed cap, docket does not guess."""
    if max_tokens is not None or endpoint.max_output_tokens is not None:
        return None
    provider = endpoint.provider or "<provider>"
    return (
        f"no output cap is known for {endpoint.model_id}, and the Messages API requires "
        f"max_tokens; declare one with: docket setup provider add {provider} "
        f"--model {endpoint.model_id} --max-tokens N"
    )


def build_payload(
    endpoint: Endpoint,
    messages: Sequence[ChatMessage],
    tools: Sequence[ToolSpec] = (),
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    tool_choice: str | None = None,
) -> dict[str, Any]:
    """Build the request body. ``max_tokens`` is the request's value, else the endpoint's cap, and
    is left out when neither is known (``request_problem`` refuses to send that). ``temperature``
    and ``top_p`` are sent only when given."""
    system = [_text_block(m.content) for m in messages if m.role == "system" and m.content]
    encoded = _encode_messages(messages)
    if system:
        system[-1]["cache_control"] = dict(_EPHEMERAL)
    if encoded:
        encoded[-1]["content"][-1]["cache_control"] = dict(_EPHEMERAL)
    payload: dict[str, Any] = {"model": endpoint.model_id, "messages": encoded}
    if system:
        payload["system"] = system
    if tools:
        payload["tools"] = [_encode_tool(t) for t in tools]
        if tool_choice:
            payload["tool_choice"] = {"type": "tool", "name": tool_choice}
    cap = max_tokens if max_tokens is not None else endpoint.max_output_tokens
    if cap is not None:
        payload["max_tokens"] = int(cap)
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if top_p is not None:
        payload["top_p"] = float(top_p)
    return payload


def request_part_bytes(payload: dict[str, Any]) -> dict[str, int]:
    """Bytes of each part of an encoded request body; trace-store requirement 28. ``tool_result``
    blocks count as ``toolResults``, the other blocks by their message's role."""
    sizes = dict.fromkeys(("system", "tools", "toolResults", "assistant", "user"), 0)
    sizes["system"] = sum(_utf8_len(b) for b in payload.get("system", []))
    sizes["tools"] = sum(_utf8_len(t) for t in payload.get("tools", []))
    for message in payload.get("messages", []):
        for block in message["content"]:
            part = "toolResults" if block["type"] == "tool_result" else message["role"]
            sizes[part] += _utf8_len(block)
    return sizes


# ── wire decoding ─────────────────────────────────────────────────────────────


def _as_int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _decode_usage(raw: Any) -> TokenUsage:
    """Real token counts off the response. Anthropic's ``input_tokens`` excludes the cache, so the
    input is the sum of the three fields and the cache counts are subsets of it."""
    if not isinstance(raw, dict):
        return TokenUsage()
    read = _as_int(raw.get("cache_read_input_tokens"))
    written = _as_int(raw.get("cache_creation_input_tokens"))
    return TokenUsage(
        input_tokens=_as_int(raw.get("input_tokens")) + read + written,
        output_tokens=_as_int(raw.get("output_tokens")),
        cached_tokens=read,
        cache_write_tokens=written,
    )


def decode_response(data: dict[str, Any]) -> ChatResponse:
    """Translate a decoded reply body into a ``ChatResponse``."""
    if data.get("type") == "error" or isinstance(data.get("error"), dict):
        err = data.get("error")
        detail = err if isinstance(err, dict) else {}
        reason = str(detail.get("message") or err or "endpoint returned an error")
        return ChatResponse(ok=False, raw=data, error=reason, failure_kind="invalid_output")
    content = data.get("content")
    if not isinstance(content, list):
        return ChatResponse(
            ok=False, raw=data, error="response contained no content", failure_kind="invalid_output"
        )
    texts: list[str] = []
    calls: list[ToolCall] = []
    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            raw_input = block.get("input")
            calls.append(
                ToolCall(
                    id=str(block.get("id") or f"call_{idx}"),
                    name=str(block.get("name") or ""),
                    arguments=json.dumps(
                        raw_input if isinstance(raw_input, dict) else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
    stop = str(data.get("stop_reason") or "")
    return ChatResponse(
        ok=True,
        message=ChatMessage(role="assistant", content="".join(texts), tool_calls=calls),
        finish_reason=_FINISH_REASON.get(stop, stop),
        usage=_decode_usage(data.get("usage")),
        raw=data,
    )
