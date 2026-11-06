"""A reply cut at the output cap is answered by one request for a shorter reply (agent-loop 116).

The cut reply is never run or kept (requirements 3-4); the same request goes again with a trailing,
request-only ask naming the cap. A second cut in a row ends the turn as before.
"""

from __future__ import annotations

from tests.support.loop_harness import ScriptedBackend, _final, _tool_call_response, _truncated

from docket.agent import loop as _loop
from docket.agent.ports import ChatMessage, TokenUsage, ToolCall
from docket.agent.session import load_session
from docket.agent.tools.registry import ToolContext, ToolRegistry

SUBJECT = "docket.agent.loop"

_ASK = "[docket] Your last reply was cut at the output limit of 50 tokens before it ended"
_POISON = ToolCall(id="cut", name="echo", arguments='{"text": "never run"}')


def _asks(request: list[ChatMessage]) -> bool:
    return request[-1].role == "user" and request[-1].content.startswith(_ASK)


def _turn(backend: ScriptedBackend, registry: ToolRegistry, ctx: ToolContext, key: str):
    return _loop.run_agent_turn(
        backend, registry, ctx, f"agent:{key}:default", "go",
        config=_loop.LoopConfig(max_tokens=50),
    )  # fmt: skip


def test_a_cut_reply_is_sent_again_with_the_ask_and_the_turn_goes_on(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    backend = ScriptedBackend(
        [
            _truncated("half a plan", tool_calls=[_POISON], usage=TokenUsage(10, 50)),
            _tool_call_response("c1", "echo", '{"text": "hi"}'),
            _final("done"),
        ]
    )
    result = _turn(backend, registry, ctx, "cut-once")
    assert (result.ok, result.stop_reason, result.output) == (True, "final_message", "done")
    assert result.tool_calls_executed == 1
    assert _asks(backend.calls[1]) and backend.calls[1][:-1] == backend.calls[0]
    assert not _asks(backend.calls[2])
    stored = load_session("agent:cut-once:default")
    assert [m.role for m in stored.messages] == ["user", "assistant", "tool", "assistant"]
    assert not any(m.content.startswith(_ASK) for m in stored.messages)
    assert stored.usage.output_tokens >= 50


def test_a_second_cut_in_a_row_ends_the_turn_truncated(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    backend = ScriptedBackend([_truncated("one"), _truncated("two", tool_calls=[_POISON])])
    result = _turn(backend, registry, ctx, "cut-twice")
    assert (result.ok, result.stop_reason, result.failure_kind) == (
        False,
        "truncated",
        "invalid_output",
    )
    assert len(backend.calls) == 2 and result.tool_calls_executed == 0


def test_a_complete_reply_clears_the_ask_so_a_later_cut_is_asked_about_again(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    backend = ScriptedBackend(
        [
            _truncated("one"),
            _tool_call_response("c1", "echo", '{"text": "hi"}'),
            _truncated("two"),
            _final("done"),
        ]
    )
    result = _turn(backend, registry, ctx, "cut-later")
    assert result.ok and len(backend.calls) == 4
    assert [_asks(request) for request in backend.calls] == [False, True, False, True]
