"""Scripted chat backend and response builders for the DocketDriver integration tests."""

from __future__ import annotations

import json
from collections.abc import Sequence

from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- see test_agent_loop.py
    for the identical pattern; redefined locally per this suite's convention
    of self-contained per-file test doubles rather than a shared fake."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.max_tokens_seen: list[int | None] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        self.max_tokens_seen.append(max_tokens)
        return self._responses.pop(0)


def _final_response(text: str, usage: TokenUsage | None = None) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=usage or TokenUsage(5, 5)
    )


def _read_call_response(path: str, usage: TokenUsage | None = None) -> ChatResponse:
    call = ToolCall(id="c1", name="read", arguments=json.dumps({"path": path}))
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=usage or TokenUsage(10, 5),
    )


def _never_called(model: str):  # pragma: no cover - only exercised on a real bug
    raise AssertionError(f"backend_factory should not have been called for model {model!r}")


def _probe_call_response() -> ChatResponse:
    call = ToolCall(id="c1", name="probe", arguments="{}")
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )
