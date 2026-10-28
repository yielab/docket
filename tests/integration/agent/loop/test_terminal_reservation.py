"""The terminal response reservation: the last call always has room to answer."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from tests.support.loop_harness import (
    ScriptedBackend,
    _final,
    _tool_call_response,
    _truncated,
)

from docket.agent import loop as _loop
from docket.agent import session_units as _session_units
from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.agent.session import load_session
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.kernel.home import current_home

SUBJECT = "docket.agent.loop"


class TestTerminalResponseReservation:
    @staticmethod
    def _backend(
        first: ChatResponse,
        second: ChatResponse,
        *,
        normal_estimate: int = 25,
        finalization_estimate: int = 10,
    ) -> ScriptedBackend:
        class BudgetBackend(ScriptedBackend):
            context_window_tokens = 1_000
            max_output_tokens = 10

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                return normal_estimate if tools else finalization_estimate

        return BudgetBackend([first, second])

    def test_normal_continuation_keeps_tools_when_request_and_reserve_fit(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response("c1", "echo", '{"text": "validated"}', TokenUsage(input_tokens=10)),
            _final("complete", TokenUsage(input_tokens=5, output_tokens=5)),
        )

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            "agent:budget-normal:default",
            "finish the task",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert result.ok
        assert len(backend.calls) == 2
        assert all(backend.tool_specs), "ordinary completions must retain the narrowed tool set"

    def test_forces_one_explicit_tool_free_finalization_that_succeeds(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1",
                "echo",
                '{"text": "tests passed"}',
                TokenUsage(input_tokens=65, output_tokens=5),
            ),
            _final("implemented and validated", TokenUsage(input_tokens=8, output_tokens=2)),
            normal_estimate=65,
        )
        session_key = "agent:budget-finalize:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "repair the defect",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
            trace_project="budget-audit",
            trace_session_key="task-budget-finalize",
        )

        assert result.ok
        assert result.output == "implemented and validated"
        assert result.usage.total_tokens == 80
        assert len(backend.calls) == 2
        assert backend.tool_specs[0]
        assert backend.tool_specs[1] == []
        assert any(
            message.role == "user" and "terminal response" in message.content.lower()
            for message in backend.calls[1]
        )
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        tracefile = current_home().traces_dir / "budget-audit" / "task-budget-finalize.jsonl"
        warning = next(
            json.loads(line)["payload"]
            for line in tracefile.read_text().splitlines()
            if json.loads(line)["event_type"] == "budget_warning"
        )
        assert warning == {
            "action": "terminal_finalization",
            "status": "entered",
            "reason": "normal_request_exceeds_remaining_turn_budget",
            "tokenBudget": 100,
            "measuredTokensUsed": 70,
            "remainingMeasuredTokens": 30,
            "normalEstimatedInputTokens": 65,
            "finalizationEstimatedInputTokens": 10,
            "outputReserveTokens": 10,
            "normalProspectiveTokens": 75,
            "finalizationProspectiveTokens": 20,
            "estimate": True,
        }
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        task_fits = [
            record
            for record in records
            if record["event_type"] == "request_fit" and record["payload"]["purpose"] == "task"
        ]
        assert len(task_fits) == 3  # first normal, second normal, one finalization; no duplicate

    def test_finalization_request_keeps_the_prefix_and_trails_a_user_message(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1",
                "echo",
                '{"text": "tests passed"}',
                TokenUsage(input_tokens=65, output_tokens=5),
            ),
            _final("implemented and validated", TokenUsage(input_tokens=8, output_tokens=2)),
            normal_estimate=65,
        )

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            "agent:budget-prefix:default",
            "repair the defect",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert result.ok
        previous, finalization = backend.calls
        assert finalization[: len(previous)] == previous
        assert finalization[0] == previous[0]
        assert finalization[-1].role == "user"
        assert "terminal response" in finalization[-1].content.lower()
        assert not any("terminal response" in message.content.lower() for message in previous)

    def test_finalization_after_window_compaction_uses_exact_durable_summary(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        raw_unit = "CURRENT_TOOL_UNIT " * 600

        class WindowThenBudgetBackend:
            context_window_tokens = 100
            max_output_tokens = 10

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tool_specs: list[list[ToolSpec]] = []

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return 60
                if any(
                    message.role == "user" and "terminal response" in message.content.lower()
                    for message in messages
                ):
                    return 5
                if any(message.role == "tool" for message in messages):
                    return 150
                if any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    return 90
                return 45

            def complete(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
                timeout: int = 120,
            ) -> ChatResponse:
                self.calls.append(list(messages))
                self.tool_specs.append(list(tools))
                if tools:
                    call = ToolCall(
                        id="current-1",
                        name="echo",
                        arguments=json.dumps({"text": raw_unit}),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(input_tokens=45, output_tokens=5),
                    )
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return _final(
                        "DURABLE_CURRENT_UNIT_SUMMARY",
                        TokenUsage(input_tokens=60, output_tokens=10),
                    )
                assert any(
                    message.role == "user" and "terminal response" in message.content.lower()
                    for message in messages
                )
                return _final(
                    "done from durable history", TokenUsage(input_tokens=4, output_tokens=1)
                )

        backend = WindowThenBudgetBackend()
        session_key = "agent:budget-after-window-compaction:default"
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "finish after the diagnostic",
            config=_loop.LoopConfig(token_budget=210, max_tokens=10),
        )

        assert result.ok
        assert result.output == "done from durable history"
        assert result.usage.total_tokens == 125
        assert [bool(tools) for tools in backend.tool_specs] == [True, False, False]
        assert "compacting durable turn history" in backend.calls[1][0].content
        assert any(
            "DURABLE_CURRENT_UNIT_SUMMARY" in message.content for message in backend.calls[2]
        )
        assert all("CURRENT_TOOL_UNIT" not in message.content for message in backend.calls[2])
        stored = load_session(session_key)
        assert any("DURABLE_CURRENT_UNIT_SUMMARY" in message.content for message in stored.messages)
        assert all("CURRENT_TOOL_UNIT" not in message.content for message in stored.messages)
        assert not _session_units.find_orphaned_tool_messages(stored.messages)
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

    def test_irreducible_budget_fails_without_a_second_transport(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1", "echo", '{"text": "done"}', TokenUsage(input_tokens=75, output_tokens=5)
            ),
            _tool_call_response(
                "poison", "echo", '{"text": "must not run"}', TokenUsage(input_tokens=30)
            ),
            normal_estimate=75,
            finalization_estimate=15,
        )
        session_key = "agent:budget-irreducible:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "do the work",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert result.failure_kind == "invalid_output"
        assert "used 80" in result.error
        assert "input 15 + output reserve 10" in result.error
        assert "remaining 20" in result.error
        assert len(backend.calls) == 1
        assert [message.role for message in load_session(session_key).messages] == [
            "user",
            "assistant",
            "tool",
        ]

    def test_finalization_context_window_failure_remains_context_fit(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1", "echo", '{"text": "done"}', TokenUsage(input_tokens=65, output_tokens=5)
            ),
            _final("must not be reached"),
            finalization_estimate=95,
            normal_estimate=65,
        )
        backend.context_window_tokens = 100  # type: ignore[attr-defined]
        session_key = "agent:budget-final-context:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "do the work",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "context_fit"
        assert result.failure_kind == "invalid_output"
        assert "registered context window 100" in result.error
        assert len(backend.calls) == 1
        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        warning = next(
            json.loads(line)["payload"]
            for line in tracefile.read_text().splitlines()
            if json.loads(line)["event_type"] == "budget_warning"
        )
        assert warning["status"] == "refused"
        assert warning["reason"] == "finalization_context_fit_failed"

    def test_tool_call_during_finalization_is_refused_without_dispatch_or_persistence(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1", "echo", '{"text": "validated"}', TokenUsage(input_tokens=65, output_tokens=5)
            ),
            _tool_call_response(
                "c2",
                "echo",
                '{"text": "optional retry"}',
                TokenUsage(input_tokens=8, output_tokens=2),
            ),
            normal_estimate=65,
        )
        session_key = "agent:budget-tool-refused:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "finish",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert result.failure_kind == "invalid_output"
        assert result.tool_calls_executed == 1
        assert len(backend.calls) == 2
        assert backend.tool_specs[1] == []
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == ["user", "assistant", "tool"]
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

    def test_truncated_finalization_persists_only_measured_usage(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1", "echo", '{"text": "validated"}', TokenUsage(input_tokens=65, output_tokens=5)
            ),
            _truncated(
                "partial terminal response",
                tool_calls=[ToolCall(id="partial", name="echo", arguments="{")],
                usage=TokenUsage(input_tokens=8, output_tokens=2),
            ),
            normal_estimate=65,
        )
        session_key = "agent:budget-final-truncated:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "finish",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "truncated"
        assert result.tool_calls_executed == 1
        assert backend.tool_specs[1] == []
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == ["user", "assistant", "tool"]
        assert stored.usage.input_tokens == 73
        assert stored.usage.output_tokens == 7
        assert stored.usage.turns == 2
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

    def test_measured_post_response_overrun_refuses_tool_call_and_preserves_prior_history(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "overrun",
                "echo",
                '{"text": "must not execute"}',
                TokenUsage(input_tokens=95, output_tokens=15),
            ),
            _final("must not be reached"),
            normal_estimate=20,
        )
        session_key = "agent:budget-measured-overrun:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "run only if bounded",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert result.usage.total_tokens == 110
        assert result.tool_calls_executed == 0
        assert len(backend.calls) == 1
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == ["user"]
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

    @pytest.mark.parametrize("failure_kind", ["timeout", "daemon_error"])
    def test_finalization_timeout_or_backend_error_is_fail_closed(
        self, ctx: ToolContext, registry: ToolRegistry, failure_kind: str
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1", "echo", '{"text": "validated"}', TokenUsage(input_tokens=65, output_tokens=5)
            ),
            ChatResponse(ok=False, error="finalization cancelled", failure_kind=failure_kind),
            normal_estimate=65,
        )
        session_key = f"agent:budget-{failure_kind}:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "finish",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "backend_error"
        assert result.failure_kind == failure_kind
        assert backend.tool_specs[1] == []
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == ["user", "assistant", "tool"]
        assert not _session_units.find_unanswered_tool_calls(stored.messages)
