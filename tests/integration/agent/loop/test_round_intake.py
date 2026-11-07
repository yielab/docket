"""A round takes in what the window holds (agent-loop requirement 115).

One response asking for more tool calls than the window can hold gets the first calls run and the
rest answered "not run", so the next request carries every result raw and fits without a
compaction that would summarize results the model never saw.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from tests.support.loop_harness import _final, unframed
from tests.support.trace import trace_events

from docket.agent import loop as _loop
from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec, assistant
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry

SUBJECT = "docket.agent.loop"

_CALLS = 20
_RESULT_CHARS = 1_200
_WINDOW = 4_000
_MAX_OUTPUT = 200
_DEFERRAL = "[docket] not run: this round's results already fill the context window"


class _Backend:
    """Replays scripted task replies (a callable is asked for its reply when its turn comes);
    estimates a request as its characters over four; counts the summarizer calls."""

    def __init__(
        self, replies: list[ChatResponse | Callable[[], ChatResponse]], *, window: int | None
    ) -> None:
        self.replies = list(replies)
        self.calls: list[list[ChatMessage]] = []
        self.context_window_tokens = window
        self.max_output_tokens = _MAX_OUTPUT
        self.summarizer_calls = 0

    def estimate_input_tokens(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> int:
        chars = sum(
            len(m.content)
            + 40
            + sum(len(c.id) + len(c.name) + len(c.arguments) for c in m.tool_calls)
            for m in messages
        )
        return chars // 4 + 16

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
        if len(messages) == 1 and "Turns, oldest first:" in messages[0].content:
            self.summarizer_calls += 1
            return _final("a summary")
        reply = self.replies.pop(0)
        return reply() if callable(reply) else reply


def _batch(numbers: range, *extra: ToolCall) -> ChatResponse:
    calls = [ToolCall(id=f"c{n}", name="blob", arguments=json.dumps({"n": n})) for n in numbers]
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[*calls, *extra]),
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
    )


def _registry(ran: list[int]) -> ToolRegistry:
    def _blob(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        ran.append(int(str(args["n"])))
        return ToolOutcome(ok=True, content=f"{args['n']} " + "r" * _RESULT_CHARS)

    def _close(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(ok=True, content="closed")

    registry = ToolRegistry()
    registry.register(
        _Tool(
            name="blob",
            description="A large result.",
            parameters={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
            handler=_blob,
            kind="read",
        )
    )
    registry.register(
        _Tool(
            name="close",
            description="Close the turn.",
            parameters={"type": "object", "properties": {}},
            handler=_close,
            kind="read",
            ends_turn=True,
        )
    )
    return registry


def _run(
    backend: _Backend, ran: list[int], ctx: ToolContext, session: str
) -> _loop.AgentLoopResult:
    return _loop.run_agent_turn(
        backend,
        _registry(ran),
        ctx,
        session,
        "read them all",
        config=_loop.LoopConfig(
            context_window_tokens=backend.context_window_tokens,
            max_tokens=backend.max_output_tokens,
        ),
    )


def _tool_messages(request: list[ChatMessage]) -> list[ChatMessage]:
    return [m for m in request if m.role == "tool"]


class TestARoundTakesInWhatTheWindowHolds:
    def test_the_calls_past_the_room_are_answered_not_run_and_the_next_request_fits(
        self, ctx: ToolContext
    ) -> None:
        ran: list[int] = []
        compactions_before_second_reply: list[int] = []

        def again() -> ChatResponse:
            compactions_before_second_reply.append(backend.summarizer_calls)
            return _batch(range(len(ran), len(ran) + 2))

        backend = _Backend([_batch(range(_CALLS)), again, _final("done")], window=_WINDOW)

        result = _run(backend, ran, ctx, "agent:intake:demo")

        assert result.ok, result.error
        # The request carrying the whole batch fit: nothing was summarized before it was sent.
        assert compactions_before_second_reply == [0]
        second = _tool_messages(backend.calls[1])
        assert len(second) == _CALLS
        kept = [m for m in second if not unframed(m.content).startswith(_DEFERRAL)]
        deferred = [m for m in second if unframed(m.content).startswith(_DEFERRAL)]
        assert 0 < len(kept) < _CALLS and len(kept) + len(deferred) == _CALLS
        assert [m.tool_call_id for m in kept] == [f"c{n}" for n in range(len(kept))]
        assert all(unframed(m.content).startswith(f"{i} rrr") for i, m in enumerate(kept))
        assert "call it again in your next response" in deferred[0].content
        # The first calls ran in order; the next response asked for two deferred ones again.
        assert ran[: len(kept)] == list(range(len(kept)))
        assert ran[len(kept) :] == [len(kept), len(kept) + 1]
        assert result.tool_calls_executed == len(kept) + 2

    def test_a_deferred_call_is_traced_as_deferred_and_never_a_denial(
        self, ctx: ToolContext
    ) -> None:
        ran: list[int] = []
        backend = _Backend([_batch(range(_CALLS)), _final("done")], window=_WINDOW)

        result = _run(backend, ran, ctx, "agent:intake-trace:demo")

        assert result.ok, result.error
        assert result.tool_calls_executed == len(ran) < _CALLS
        results = [e for e in trace_events("demo") if e["event_type"] == "tool_result"]
        deferred = [e["payload"] for e in results if e["payload"]["decision"] == "deferred"]
        assert len(deferred) == _CALLS - len(ran)
        for payload in deferred:
            assert payload["ok"] is False and payload["executed"] is False
            assert "denialKind" not in payload
        calls = [e for e in trace_events("demo") if e["event_type"] == "tool_call"]
        assert len(calls) == _CALLS

    def test_an_unknown_window_bounds_nothing(self, ctx: ToolContext) -> None:
        ran: list[int] = []
        backend = _Backend([_batch(range(_CALLS)), _final("done")], window=None)

        result = _run(backend, ran, ctx, "agent:intake-unknown:demo")

        assert result.ok, result.error
        assert ran == list(range(_CALLS))
        assert not any(m.content.startswith(_DEFERRAL) for m in _tool_messages(backend.calls[1]))

    def test_the_closing_tool_after_the_bound_still_runs(self, ctx: ToolContext) -> None:
        ran: list[int] = []
        close = ToolCall(id="close1", name="close", arguments="{}")
        backend = _Backend([_batch(range(_CALLS), close)], window=_WINDOW)

        result = _run(backend, ran, ctx, "agent:intake-close:demo")

        assert result.ok, result.error
        assert len(backend.calls) == 1
        assert len(ran) < _CALLS
        assert result.output.endswith("closed")
