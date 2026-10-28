"""Scripted chat backends, fixtures and response builders for the agent-loop integration tests."""

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
from docket.kernel.home import current_home


class ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s; records each call's messages for assertions
    and raises `AssertionError` (a test-bug signal) if asked for more responses than scripted."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.tool_specs: list[list[ToolSpec]] = []

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
        self.tool_specs.append(list(tools))
        if not self._responses:
            raise AssertionError("ScriptedBackend ran out of scripted responses")
        return self._responses.pop(0)


def _final(content: str = "done", usage: TokenUsage | None = None) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(content),
        finish_reason="stop",
        usage=usage or TokenUsage(input_tokens=5, output_tokens=5),
    )


def _tool_call_response(
    call_id: str, name: str, arguments: str, usage: TokenUsage | None = None
) -> ChatResponse:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=usage or TokenUsage(input_tokens=10, output_tokens=5),
    )


def _truncated(
    content: str = "",
    tool_calls: Sequence[ToolCall] = (),
    usage: TokenUsage | None = None,
) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(content, tool_calls=tool_calls),
        finish_reason="length",
        usage=usage or TokenUsage(input_tokens=10, output_tokens=5),
    )


def _write_gate_policy(policy_id: str, pattern: str, action: str) -> None:
    """Install one minimal `pre_tool_call` policy for a single RED scenario --
    a hand-written stand-in for the shipped templates, scoped to exactly the
    tool name this test drives rather than a real destructive-command list."""
    current_home().policies_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "kind": "policy",
        "name": policy_id,
        "description": "test-only policy",
        "appliesTo": ["*"],
        "on": "toolCall",
        "when": {"matches": pattern},
        "then": action,
        "message": "test gate",
    }
    (current_home().policies_dir / f"{policy_id}.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


class _SizedBackend(ScriptedBackend):
    """A scripted backend with registered bounds and a fixed input estimate."""

    def __init__(
        self,
        responses: Sequence[ChatResponse],
        *,
        estimate: int,
        window: int | None = None,
        max_output: int | None = None,
    ) -> None:
        super().__init__(responses)
        self._estimate = estimate
        self.context_window_tokens = window
        self.max_output_tokens = max_output

    def estimate_input_tokens(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> int:
        return self._estimate
