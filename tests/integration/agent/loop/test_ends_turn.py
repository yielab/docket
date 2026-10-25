"""A tool declared ``ends_turn`` closes the turn when its call succeeds.

Drives the real ``run_agent_turn`` with a scripted chat port: no further backend call follows,
the output is the message text then the tool's result, and a failed call keeps the turn going.
"""

from __future__ import annotations

from collections.abc import Sequence

from docket.agent import loop as _loop
from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.agent.session import load_messages
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry

SUBJECT = "docket.agent.loop"
SESSION = "agent:demo:default"


class _Backend:
    def __init__(self, replies: list[tuple[str, list[ToolCall]]]) -> None:
        self._replies = list(replies)
        self.requests = 0

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.requests += 1
        text, calls = self._replies.pop(0)
        return ChatResponse(
            ok=True,
            message=assistant(text, tool_calls=calls),
            finish_reason="tool_calls" if calls else "stop",
            usage=TokenUsage(10, 5),
        )


def _closing_registry() -> ToolRegistry:
    def _close(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        value = str(args.get("value", ""))
        if value != "DONE":
            return ToolOutcome(False, error="value must be DONE")
        return ToolOutcome(True, content=value)

    registry = ToolRegistry()
    registry.register(
        _Tool(
            name="close",
            description="Close.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            handler=_close,
            kind="read",
            ends_turn=True,
        )
    )
    return registry


def _close_call(value: str, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name="close", arguments=f'{{"value": "{value}"}}')


def _run(backend: _Backend, ctx: ToolContext) -> _loop.AgentLoopResult:
    return _loop.run_agent_turn(backend, _closing_registry(), ctx, SESSION, "go")


def test_the_turn_ends_with_the_message_text_then_the_result(ctx: ToolContext) -> None:
    backend = _Backend([("Reasons above.", [_close_call("DONE")])])

    result = _run(backend, ctx)

    assert result.ok is True and result.failure_kind is None
    assert result.stop_reason == "final_message"
    assert result.output == "Reasons above.\nDONE"
    assert backend.requests == 1  # no request follows the closing call


def test_a_call_with_no_message_text_outputs_just_the_result(ctx: ToolContext) -> None:
    result = _run(_Backend([("", [_close_call("DONE")])]), ctx)

    assert result.ok is True
    assert result.output == "DONE"


def test_the_round_is_persisted_whole_before_the_turn_ends(ctx: ToolContext) -> None:
    _run(_Backend([("why", [_close_call("DONE")])]), ctx)

    roles = [m.role for m in load_messages(SESSION)]
    assert roles[-2:] == ["assistant", "tool"]


def test_a_failed_call_does_not_end_the_turn(ctx: ToolContext) -> None:
    backend = _Backend([("", [_close_call("WRONG", "c1")]), ("", [_close_call("DONE", "c2")])])

    result = _run(backend, ctx)

    assert result.ok is True and result.output == "DONE"
    assert backend.requests == 2


def test_a_turn_that_never_calls_it_ends_on_the_final_message_as_before(ctx: ToolContext) -> None:
    backend = _Backend([("just text", [])])

    result = _run(backend, ctx)

    assert result.output == "just text" and backend.requests == 1
