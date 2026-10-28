"""Helpers shared by the pod-dispatch integration tests."""

from __future__ import annotations

from typing import Any

from docket.agent.ports import ChatMessage, ChatResponse


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- see test_docket_driver.py
    for the identical pattern; redefined locally per this suite's convention
    of self-contained per-file test doubles rather than a shared fake."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)
