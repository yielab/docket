"""A provider's context-overflow refusal of a task request is learned from and sent once more.

The fake backend under-counts: its estimate is a quarter of the characters while its refusals state
the count the provider would have measured, so the first fit says "fits" and the provider says no.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from tests.support.loop_harness import ScriptedBackend, _final, _tool_call_response

from docket.agent import loop as _loop
from docket.agent.ports import ChatMessage, ChatResponse, ToolSpec
from docket.agent.session import append_messages as append_session_messages
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.kernel.home import current_home

SUBJECT = "docket.agent.loop"

_WINDOW = 6_000
_RESERVE = 400
_ROOM = _WINDOW - _RESERVE


def _overflow(tokens: int | None) -> ChatResponse:
    """The refusal the adapter builds from a provider's context-overflow body."""
    return ChatResponse(
        ok=False,
        error="HTTP 400: request exceeds the available context size",
        failure_kind="nonzero_exit",
        context_overflow=True,
        overflow_input_tokens=tokens,
    )


class UnderCountingBackend(ScriptedBackend):
    """Estimates a quarter of the characters it is sent, over a window it publishes."""

    context_window_tokens = _WINDOW
    max_output_tokens = _RESERVE

    def estimate_input_tokens(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> int:
        return sum(len(m.content) for m in messages) // 4


def _config(**overrides: int) -> _loop.LoopConfig:
    return _loop.LoopConfig(context_window_tokens=_WINDOW, max_tokens=_RESERVE, **overrides)


def _task_fits(session_key: str, ctx: ToolContext) -> list[dict[str, object]]:
    tracefile = current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
    records = [json.loads(line) for line in tracefile.read_text().splitlines()]
    return [
        r["payload"]
        for r in records
        if r["event_type"] == "request_fit" and r["payload"]["purpose"] == "task"
    ]


def _llm_calls(session_key: str, ctx: ToolContext) -> int:
    tracefile = current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
    records = [json.loads(line) for line in tracefile.read_text().splitlines()]
    return sum(1 for r in records if r["event_type"] == "llm_call")


class TestOverflowIsLearnedAndRetried:
    def test_the_providers_count_rescales_the_estimate_and_the_request_is_sent_again(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:overflow-retry:demo"
        backend = UnderCountingBackend([_overflow(2_600), _final("done")])
        append_session_messages(session_key, [ChatMessage(role="user", content="x" * 4_000)])

        result = _loop.run_agent_turn(
            backend, registry, ctx, session_key, "carry on", config=_config()
        )

        assert result.ok, result.error
        assert result.output == "done"
        assert len(backend.calls) == 2
        assert backend.calls[0] == backend.calls[1]
        fits = _task_fits(session_key, ctx)
        assert [f["status"] for f in fits] == ["fits", "fits"]
        first, second = (int(str(f["estimatedInputTokens"])) for f in fits)
        assert second > first
        assert second == pytest.approx(2_600, abs=2)
        assert result.first_call_ratio == pytest.approx(2_600 / first, abs=0.01)

    def test_a_count_that_no_longer_fits_compacts_before_the_second_call(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:overflow-compact:demo"
        history = [ChatMessage(role="user", content=f"old-{n} " * 160) for n in range(20)]
        append_session_messages(session_key, history)
        backend = UnderCountingBackend([_overflow(8_000), _final("S" * 80), _final("done")])

        result = _loop.run_agent_turn(
            backend, registry, ctx, session_key, "carry on", config=_config()
        )

        assert result.ok, result.error
        assert result.output == "done"
        assert len(backend.calls) == 3
        assert "compacting durable turn history" in backend.calls[1][0].content
        assert backend.tool_specs[1] == []
        assert any(m.content.startswith("[compacted summary of ") for m in backend.calls[2])
        fits = _task_fits(session_key, ctx)
        assert fits[0]["status"] == "fits"
        assert "failed" in [f["status"] for f in fits[1:]]
        assert fits[-1]["status"] == "fits"

    def test_a_refusal_without_a_count_proves_the_request_room_was_exceeded(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:overflow-no-count:demo"
        history = [ChatMessage(role="user", content=f"old-{n} " * 160) for n in range(20)]
        append_session_messages(session_key, history)
        backend = UnderCountingBackend([_overflow(None), _final("S" * 80), _final("done")])

        result = _loop.run_agent_turn(
            backend, registry, ctx, session_key, "carry on", config=_config()
        )

        assert result.ok, result.error
        assert len(backend.calls) == 3
        fits = _task_fits(session_key, ctx)
        first = int(str(fits[0]["estimatedInputTokens"]))
        assert first <= _ROOM
        assert fits[1]["status"] == "failed"
        assert int(str(fits[1]["estimatedInputTokens"])) >= _ROOM + 1

    def test_the_retry_does_not_spend_a_round(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        backend = UnderCountingBackend([_overflow(2_600), _final("done")])
        append_session_messages("agent:overflow-round:demo", [ChatMessage("user", "x" * 4_000)])

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            "agent:overflow-round:demo",
            "carry on",
            config=_config(max_iterations=1),
        )

        assert result.ok, result.error
        assert len(backend.calls) == 2

    def test_a_refusal_later_in_the_turn_is_retried_after_its_tool_round(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        backend = UnderCountingBackend(
            [
                _tool_call_response("c1", "echo", '{"text": "hi"}'),
                _overflow(2_600),
                _final("done"),
            ]
        )
        append_session_messages("agent:overflow-late:demo", [ChatMessage("user", "x" * 4_000)])

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:overflow-late:demo", "carry on", config=_config()
        )

        assert result.ok, result.error
        assert len(backend.calls) == 3
        assert backend.calls[1] == backend.calls[2]


class TestSecondOverflowEndsTheTurn:
    def test_two_refusals_of_one_request_end_in_context_fit(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:overflow-twice:demo"
        backend = UnderCountingBackend([_overflow(2_600), _overflow(2_700), _final("unused")])
        append_session_messages(session_key, [ChatMessage(role="user", content="x" * 4_000)])

        result = _loop.run_agent_turn(
            backend, registry, ctx, session_key, "carry on", config=_config()
        )

        assert not result.ok
        assert result.stop_reason == "context_fit"
        assert result.failure_kind == "invalid_output"
        assert "2700" in result.error
        assert str(_WINDOW) in result.error
        assert len(backend.calls) == 2
        assert _llm_calls(session_key, ctx) == 2

    def test_a_second_refusal_that_states_no_count_says_so(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        backend = UnderCountingBackend([_overflow(2_600), _overflow(None)])
        append_session_messages("agent:overflow-nocount2:demo", [ChatMessage("user", "x" * 4_000)])

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:overflow-nocount2:demo", "go", config=_config()
        )

        assert result.stop_reason == "context_fit"
        assert "no count" in result.error
        assert str(_WINDOW) in result.error

    def test_the_allowance_is_per_request_not_per_turn(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        backend = UnderCountingBackend(
            [
                _overflow(2_600),
                _tool_call_response("c1", "echo", '{"text": "hi"}'),
                _overflow(2_700),
                _final("done"),
            ]
        )
        append_session_messages("agent:overflow-each:demo", [ChatMessage("user", "x" * 4_000)])

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:overflow-each:demo", "go", config=_config()
        )

        assert result.ok, result.error
        assert len(backend.calls) == 4


class TestOtherFailuresAreUnchanged:
    def test_a_failure_that_is_not_an_overflow_is_a_backend_error_after_one_call(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        refusal = ChatResponse(ok=False, error="HTTP 400: bad", failure_kind="nonzero_exit")
        backend = UnderCountingBackend([refusal, _final("unused")])

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:not-overflow:demo", "go", config=_config()
        )

        assert result.stop_reason == "backend_error"
        assert len(backend.calls) == 1

    def test_an_overflow_with_no_count_and_no_window_is_a_backend_error(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        backend = UnderCountingBackend([_overflow(None), _final("unused")])
        backend.context_window_tokens = None  # type: ignore[assignment]
        backend.max_output_tokens = None  # type: ignore[assignment]

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:overflow-open:demo", "go", config=_loop.LoopConfig()
        )

        assert result.stop_reason == "backend_error"
        assert len(backend.calls) == 1
