"""``DocketDriver`` offers ``verdict`` only on a verdict-gated hop, and calling it ends the hop."""

from __future__ import annotations

import json
from collections.abc import Sequence

from tests.support.pods import write_meta_overrides as _write_meta

from docket.agent import ports as _rd
from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.hops.application.driver import DocketDriver

SUBJECT = "docket.hops.application.driver"
VALUES = json.dumps({"values": ["APPROVE", "REQUEST-CHANGES"], "caseSensitive": False})


class _Backend:
    def __init__(self, replies: list[ChatResponse]) -> None:
        self._replies = list(replies)
        self.tools_seen: list[list[ToolSpec]] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.tools_seen.append(list(tools))
        return self._replies.pop(0)


def _verdict_call(value: str, text: str = "") -> ChatResponse:
    call = ToolCall(id="v1", name="verdict", arguments=json.dumps({"value": value}))
    return ChatResponse(
        ok=True,
        message=assistant(text, tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(10, 5),
    )


def _text(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


def _run(backend: _Backend, env: dict[str, str] | None) -> _rd.TurnResult:
    _write_meta("rev-agent", role="reviewer")
    driver = DocketDriver(backend_factory=lambda model: backend)
    return driver.run_turn("rev-agent", "agent:rev-agent:default", "review it", 60, env)


def test_the_verdict_tool_is_offered_with_the_gates_enum() -> None:
    backend = _Backend([_text("APPROVE")])

    _run(backend, {_rd.DOCKET_VERDICT_VALUES: VALUES})

    specs = {s.name: s for s in backend.tools_seen[0]}
    assert specs["verdict"].parameters["properties"]["value"]["enum"] == [
        "APPROVE",
        "REQUEST-CHANGES",
    ]


def test_a_hop_without_a_verdict_gate_is_not_offered_the_tool() -> None:
    backend = _Backend([_text("done")])

    _run(backend, None)

    assert "verdict" not in {s.name for s in backend.tools_seen[0]}


def test_calling_the_tool_ends_the_hop_with_the_value_as_the_last_line() -> None:
    backend = _Backend([_verdict_call("request-changes", "The helper leaks a handle."), _text("x")])

    result = _run(backend, {_rd.DOCKET_VERDICT_VALUES: VALUES})

    assert result.ok is True
    assert result.output == "The helper leaks a handle.\nREQUEST-CHANGES"
    assert len(backend.tools_seen) == 1  # no request after the closing call
