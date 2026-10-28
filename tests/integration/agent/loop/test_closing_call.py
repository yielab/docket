"""``tool_choice: forced-on-close`` makes a reply that asks for no tool one closing call."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from docket.agent import loop as _loop
from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.agent.session import load_messages
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry

SUBJECT = "docket.agent.loop"
SESSION = "agent:demo:default"
FORCED = _loop.LoopConfig(tool_choice="forced-on-close", closing_tool="close", temperature=0.5)


@dataclass
class _Seen:
    messages: list[ChatMessage]
    tool_choice: str | None
    top_p: float | None
    temperature: float | None


@dataclass
class _Backend:
    replies: list[tuple[str, list[ToolCall]]]
    seen: list[_Seen] = field(default_factory=list)

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
        self.seen.append(_Seen(list(messages), tool_choice, top_p, temperature))
        text, calls = self.replies.pop(0)
        return ChatResponse(
            ok=True,
            message=assistant(text, tool_calls=calls),
            finish_reason="tool_calls" if calls else "stop",
            usage=TokenUsage(10, 5),
        )


def _registry(*, offered: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    if offered:
        registry.register(
            _Tool(
                name="close",
                description="Close.",
                parameters={"type": "object", "properties": {"value": {"type": "string"}}},
                handler=lambda args, ctx: ToolOutcome(True, content="DONE"),
                kind="read",
                ends_turn=True,
            )
        )
    return registry


def _close() -> ToolCall:
    return ToolCall(id="c1", name="close", arguments="{}")


def _run(
    backend: _Backend, ctx: ToolContext, config: _loop.LoopConfig = FORCED, **kwargs: bool
) -> _loop.AgentLoopResult:
    return _loop.run_agent_turn(backend, _registry(**kwargs), ctx, SESSION, "go", config=config)


def test_a_reply_with_no_tool_call_is_followed_by_one_forced_closing_call(ctx: ToolContext) -> None:
    backend = _Backend([("It is fine.", []), ("", [_close()])])

    result = _run(backend, ctx)

    first, closing = backend.seen
    assert first.tool_choice is None and closing.tool_choice == "close"
    assert [m.role for m in closing.messages[-2:]] == ["assistant", "user"]
    assert closing.messages[-2].content == "It is fine."
    assert "`close`" in closing.messages[-1].content
    assert result.ok is True and result.output == "It is fine.\nDONE"


def test_the_first_reply_is_not_persisted_on_its_own(ctx: ToolContext) -> None:
    _run(_Backend([("It is fine.", []), ("", [_close()])]), ctx)

    roles = [m.role for m in load_messages(SESSION)]
    assert roles == ["user", "assistant", "tool"]
    assert load_messages(SESSION)[1].content == "It is fine."


def test_a_model_that_calls_the_closing_tool_itself_is_not_asked_twice(ctx: ToolContext) -> None:
    backend = _Backend([("why", [_close()])])

    result = _run(backend, ctx)

    assert len(backend.seen) == 1 and backend.seen[0].tool_choice is None
    assert result.output == "why\nDONE"


def test_a_closing_call_that_still_names_no_tool_ends_the_turn(ctx: ToolContext) -> None:
    backend = _Backend([("first", []), ("second", [])])

    result = _run(backend, ctx)

    assert len(backend.seen) == 2
    assert result.ok is True and result.output == "first\nsecond"


def test_auto_never_forces_a_call(ctx: ToolContext) -> None:
    backend = _Backend([("just text", [])])

    result = _run(backend, ctx, _loop.LoopConfig(closing_tool="close"))

    assert len(backend.seen) == 1 and backend.seen[0].tool_choice is None
    assert result.output == "just text"


def test_a_closing_tool_the_turn_does_not_offer_is_never_forced(ctx: ToolContext) -> None:
    backend = _Backend([("just text", [])])

    result = _run(backend, ctx, offered=False)

    assert len(backend.seen) == 1 and backend.seen[0].tool_choice is None
    assert result.output == "just text"


def test_sampling_reaches_every_call(ctx: ToolContext) -> None:
    config = _loop.LoopConfig(
        tool_choice="forced-on-close", closing_tool="close", temperature=0.7, top_p=0.8
    )
    backend = _Backend([("text", []), ("", [_close()])])

    _run(backend, ctx, config)

    assert [(s.temperature, s.top_p) for s in backend.seen] == [(0.7, 0.8), (0.7, 0.8)]
