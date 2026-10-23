"""Turn-loop compaction (`agent/loop_compaction.py`): the tool-free summariser's refusals and
the request-fit helpers around the incoming task message."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from docket.agent.llm import ChatMessage, ChatResponse, ToolCall, assistant, system, user
from docket.agent.loop_budget import TurnBudget
from docket.agent.loop_compaction import TurnCompaction
from docket.agent.loop_state import TurnState
from docket.agent.loop_types import LoopConfig
from docket.agent.session import append_messages, load_messages

SUBJECT = "docket.agent.loop_compaction"

MakeState = Callable[..., TurnState]


class _OneReply:
    """Answers the summariser's single exchange with a fixed response."""

    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(self, messages: list[ChatMessage], **kwargs: Any) -> ChatResponse:
        self.calls.append({"messages": messages, **kwargs})
        return self.response


def _compaction(state: TurnState) -> TurnCompaction:
    return TurnCompaction(state, TurnBudget(state))


def _summarize(compaction: TurnCompaction, key: str = "agent:demo-agent:demo:compaction"):
    return compaction.summarize_without_reentry("demo-agent", key, "summarise", 30)


class TestSummarizeWithoutReentry:
    """One tool-free exchange; every rejection records why compaction stopped the turn."""

    def test_a_summary_key_equal_to_the_target_session_is_refused(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state()
        compaction = _compaction(state)
        result = _summarize(compaction, key=state.session_key)
        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert compaction.compaction_failure_stop_reason == "compaction_failed"

    def test_an_exhausted_wall_clock_is_refused_before_any_call(
        self, make_turn_state: MakeState
    ) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("summary")))
        state = make_turn_state(
            LoopConfig(wall_clock_timeout_s=10), backend=backend, clock=lambda: 11.0
        )
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.failure_kind == "timeout"
        assert backend.calls == []
        assert compaction.compaction_failure_stop_reason == "compaction_failed"

    def test_a_good_summary_is_returned_and_its_usage_is_kept_apart(
        self, make_turn_state: MakeState
    ) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("the summary")))
        state = make_turn_state(backend=backend)
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.ok
        assert result.output == "the summary"
        assert backend.calls[0]["tools"] == ()
        assert compaction.compaction_failure_stop_reason is None
        assert state.total_usage.total_tokens == 0

    def test_a_tool_requesting_summary_is_rejected(self, make_turn_state: MakeState) -> None:
        reply = assistant("x", [ToolCall(id="c", name="echo")])
        state = make_turn_state(backend=_OneReply(ChatResponse(ok=True, message=reply)))
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert not result.ok
        assert "requested tools" in result.error
        assert compaction.compaction_failure_stop_reason == "compaction_failed"

    def test_an_empty_summary_is_rejected(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(backend=_OneReply(ChatResponse(ok=True, message=assistant("   "))))
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert "empty summary" in result.error

    def test_a_truncated_summary_is_rejected(self, make_turn_state: MakeState) -> None:
        response = ChatResponse(ok=True, message=assistant("cut"), finish_reason="length")
        state = make_turn_state(backend=_OneReply(response))
        result = _summarize(_compaction(state))
        assert "truncated" in result.error

    def test_a_cancelled_run_never_calls_the_backend(self, make_turn_state: MakeState) -> None:
        backend = _OneReply(ChatResponse(ok=True, message=assistant("summary")))
        base = make_turn_state()
        state = make_turn_state(
            backend=backend, ctx=dataclasses.replace(base.ctx, cancellation_check=lambda: True)
        )
        compaction = _compaction(state)
        result = _summarize(compaction)
        assert result.failure_kind == "run_cancelled"
        assert backend.calls == []
        assert compaction.compaction_failure_stop_reason == "run_cancelled"


class TestRequestFitHelpers:
    """The durable position of the task message and the request built around it."""

    def test_messages_for_durable_prepends_the_system_prompt(
        self, make_turn_state: MakeState
    ) -> None:
        compaction = _compaction(make_turn_state(system_prompt="you are an agent"))
        messages = compaction.messages_for_durable([user("hello")])
        assert [m.role for m in messages] == ["system", "user"]
        assert messages[0] == system("you are an agent")

    def test_messages_for_durable_omits_an_empty_system_prompt(
        self, make_turn_state: MakeState
    ) -> None:
        compaction = _compaction(make_turn_state(system_prompt=""))
        assert [m.role for m in compaction.messages_for_durable([user("hello")])] == ["user"]

    def test_seed_task_message_records_its_durable_position(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state()
        append_messages(state.session_key, [user("earlier"), assistant("reply")])
        compaction = _compaction(state)
        compaction.seed_task_message("the task")
        assert compaction.task_message_index == 2
        assert load_messages(state.session_key)[2] == compaction.incoming == user("the task")

    def test_convergence_error_names_the_window_or_says_unknown(
        self, make_turn_state: MakeState
    ) -> None:
        known = _compaction(make_turn_state(context_window=1_000, output_reserve=100))
        error = known.context_fit_convergence_error("no luck", 400)
        assert "estimated request 500 tokens (input 400 + output reserve 100)" in error
        assert error.endswith("registered context window 1000: no luck")
        unknown = _compaction(make_turn_state(context_window=None))
        assert "registered context window unknown" in unknown.context_fit_convergence_error("x", 1)
