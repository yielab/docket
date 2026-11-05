"""The request-fit reduction frees headroom beyond the overflow (agent-loop requirement 47), so a
turn that keeps adding tool results is not compacted again by every round, and a headroom the
summarizer cannot carry falls back to the range that covers the overflow alone."""

from __future__ import annotations

import json
from collections.abc import Sequence

from tests.support.loop_harness import (
    SUMMARIZER_FIXED_TOKENS,
    ScriptedBackend,
    _final,
    _tool_call_response,
)

from docket.agent import loop as _loop
from docket.agent import session as _session
from docket.agent.ports import ChatMessage, ChatResponse, ToolCall, ToolSpec, assistant
from docket.agent.session import append_messages as append_session_messages
from docket.agent.tools.registry import ToolContext, ToolRegistry

SUBJECT = "docket.agent.loop"

_ROUNDS = 24
_RESULT_CHARS = 1_200
_SUMMARY_CHARS = 400


class _ByteEstimateBackend(ScriptedBackend):
    """Answers a summarizer prompt with a fixed summary and each task call with the next echo
    round; counts the summarizer calls. Its estimate is the request's characters over four."""

    context_window_tokens = 3_000
    max_output_tokens = 200

    def __init__(self) -> None:
        super().__init__([])
        self.summarizer_calls = 0
        self.task_calls = 0

    def estimate_input_tokens(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> int:
        return sum(len(m.content) + 40 for m in messages) // 4 + 16

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
            return _final("s" * _SUMMARY_CHARS)
        self.task_calls += 1
        if self.task_calls > _ROUNDS:
            return _final("done")
        text = json.dumps({"text": f"{self.task_calls} " + "r" * _RESULT_CHARS})
        return _tool_call_response(f"c{self.task_calls}", "echo", text)


class TestAReductionLeavesRoomForTheNextRounds:
    def test_a_turn_that_keeps_adding_results_is_not_compacted_by_every_round(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:headroom:demo"
        backend = _ByteEstimateBackend()

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "go on reading",
            config=_loop.LoopConfig(
                context_window_tokens=backend.context_window_tokens,
                max_tokens=backend.max_output_tokens,
                max_iterations=_ROUNDS + 4,
            ),
        )

        assert result.ok, result.error
        assert backend.task_calls == _ROUNDS + 1
        assert backend.summarizer_calls >= 1
        # Each compaction frees the overflow and a quarter of the room, so several rounds of
        # results fit before the next one; a reduction that freed only the overflow was repeated
        # by nearly every round.
        assert backend.summarizer_calls <= _ROUNDS // 4


class TestARangeWithHeadroomTheSummarizerCannotCarry:
    def test_the_range_that_covers_the_overflow_alone_is_summarized_instead(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:headroom-refused:demo"
        call = ToolCall(id="old_call", name="echo", arguments='{"text":"old"}')
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content="old context " * 25),
                assistant("", tool_calls=[call]),
                ChatMessage(
                    role="tool", content="old result", tool_call_id=call.id, name=call.name
                ),
                ChatMessage(role="user", content="middle context " * 40),
                ChatMessage(role="user", content="recent context " * 250),
            ],
        )
        # The headroom reaches the large last message, which no summarizer prompt carries: that
        # range is refused after its first round, and the range that covers the overflow runs.
        backend = ScriptedBackend([_final("discarded"), _final("kept summary"), _final("done")])

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "new request",
            config=_loop.LoopConfig(
                context_window_tokens=600 + SUMMARIZER_FIXED_TOKENS, max_tokens=60
            ),
        )

        assert result.ok, result.error
        stored = _session.load_messages(session_key)
        summaries = [m.content for m in stored if m.content.startswith("[compacted summary of ")]
        assert len(summaries) == 1
        assert "kept summary" in summaries[0] and "discarded" not in summaries[0]
        assert any("recent context" in m.content for m in stored)
