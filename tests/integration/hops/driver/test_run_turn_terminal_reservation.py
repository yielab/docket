"""DocketDriver.run_turn: the terminal response reservation against the budget."""

from __future__ import annotations

import json
from collections.abc import Sequence

from tests.support.driver_harness import (
    _final_response,
    _ScriptedBackend,
)
from tests.support.pods import write_meta_2 as _write_meta

from docket.agent import session as _session
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
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home

SUBJECT = "docket.hops.application.driver"


class TestRunTurn:
    def test_default_driver_reserves_a_tool_free_terminal_response_inside_budget(self) -> None:
        ws = _write_meta("budget-agent")
        (ws / "module.py").write_text("VALUE = 'broken'\n")

        class BudgetBackend:
            context_window_tokens = 100_000
            max_output_tokens = 4_000

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                return 44_000 if tools else 1_000

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
                self.tools_seen.append(list(tools))
                call_number = len(self.calls)
                if call_number == 1:
                    call = ToolCall(
                        id="edit-1",
                        name="edit",
                        arguments=json.dumps(
                            {
                                "path": "module.py",
                                "old_string": "broken",
                                "new_string": "fixed",
                            }
                        ),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(44_000, 1_000),
                    )
                if call_number == 2:
                    call = ToolCall(
                        id="validate-1",
                        name="read",
                        arguments=json.dumps({"path": "module.py"}),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(44_000, 1_000),
                    )
                if tools:
                    call = ToolCall(
                        id="optional-1",
                        name="read",
                        arguments=json.dumps({"path": "module.py"}),
                    )
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(9_500, 600),
                    )
                return _final_response(
                    "fixed and validated without another optional tool round",
                    TokenUsage(900, 100),
                )

        backend = BudgetBackend()
        driver = DocketDriver(backend_factory=lambda model: backend)
        session_key = "agent:budget-agent:default"

        result = driver.run_turn(
            "budget-agent", session_key, "repair module.py and validate it", 60
        )

        assert result.ok
        assert result.output == "fixed and validated without another optional tool round"
        assert (ws / "module.py").read_text() == "VALUE = 'fixed'\n"
        assert len(backend.calls) == 3
        assert backend.tools_seen[0] and backend.tools_seen[1]
        assert backend.tools_seen[2] == []
        assert any(
            message.role == "system" and "terminal response" in message.content.lower()
            for message in backend.calls[2]
        )
        record = load_session(session_key)
        assert record.usage.input_tokens + record.usage.output_tokens == 91_000
        assert [message.role for message in record.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
        ]

    def test_terminal_reservation_precedes_request_fit_compaction(self) -> None:
        _write_meta("window-budget-agent")
        registry = ToolRegistry()
        raw_result = "CURRENT_TOOL_UNIT " * 1_000

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            return ToolOutcome(True, content=raw_result)

        registry.register(
            Tool(
                name="lookup",
                description="Return the current diagnostic.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class WindowBudgetBackend:
            context_window_tokens = 100_000
            max_output_tokens = 10_000

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return 5_000
                if any(
                    message.role == "system" and "terminal response" in message.content.lower()
                    for message in messages
                ):
                    return 5_000
                if any(message.role == "tool" for message in messages) or any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    return 150_000
                return 20_000

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
                self.tools_seen.append(list(tools))
                if tools:
                    call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(65_000, 5_000),
                    )
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return _final_response("bounded summary", TokenUsage(4_000, 1_000))
                assert any(
                    message.role == "system" and "terminal response" in message.content.lower()
                    for message in messages
                )
                return _final_response("truthful terminal response", TokenUsage(4_000, 1_000))

        backend = WindowBudgetBackend()
        session_key = "agent:window-budget-agent:default"
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role, project, launch=None: [],
        )

        result = driver.run_turn(
            "window-budget-agent", session_key, "inspect and report truthfully", 60
        )

        assert result.ok
        assert result.output == "truthful terminal response"
        assert len(backend.calls) == 2
        assert [bool(tools) for tools in backend.tools_seen] == [True, False]
        assert not any(
            len(call) == 1 and "compacting durable turn history" in call[0].content
            for call in backend.calls
        )
        assert any(
            message.role == "tool" and "CURRENT_TOOL_UNIT" in message.content
            for message in backend.calls[1]
        )
        record = load_session(session_key)
        assert record.usage.input_tokens + record.usage.output_tokens == 75_000
        assert not any(
            message.content.startswith("[compacted summary of ") for message in record.messages
        )
        assert any("CURRENT_TOOL_UNIT" in message.content for message in record.messages)
        trace_path = current_home().traces_dir / "window-budget-agent" / f"{session_key}.jsonl"
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        warnings = [record for record in records if record["event_type"] == "budget_warning"]
        assert len(warnings) == 1
        assert warnings[0]["payload"]["action"] == "terminal_finalization"
        assert warnings[0]["payload"]["status"] == "entered"

    def test_irreducible_registered_window_fails_before_transport(self) -> None:
        _write_meta("tiny-window-agent")
        backend = _ScriptedBackend([_final_response("must not be called")])
        backend.context_window_tokens = 1  # type: ignore[attr-defined]
        backend.max_output_tokens = 1  # type: ignore[attr-defined]
        driver = DocketDriver(backend_factory=lambda model: backend)

        result = driver.run_turn(
            "tiny-window-agent", "agent:tiny-window-agent:default", "keep this exact", 60
        )

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert "registered context window 1" in result.error
        assert backend.calls == []

    def test_request_fit_does_not_recompact_the_same_current_turn_segment(self) -> None:
        _write_meta("fit-agent")
        sentinel = "ORIGINAL_SENTINEL " * 500
        dispatches = 0
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=sentinel)

        registry.register(
            Tool(
                name="lookup",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class RecompactionBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.prospectives: list[tuple[str, int]] = []
                self.summary_lengths = iter((1_500, 1_000, 600, 300))
                self.task_transports = 0

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    prospective = ("compaction", 700)
                elif any(message.role == "tool" for message in messages):
                    prospective = ("task", 1_220)
                elif any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    prospective = ("task", 890)
                else:
                    prospective = ("task", 200)
                self.prospectives.append(prospective)
                return prospective[1]

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
                self.tools_seen.append(list(tools))
                if tools:
                    self.task_transports += 1
                    if self.task_transports > 1:
                        raise AssertionError("oversized task request must not reach the backend")
                    call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                    return ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    )
                assert "compacting durable turn history" in messages[0].content
                return _final_response("S" * next(self.summary_lengths), TokenUsage(10, 5))

        backend = RecompactionBackend()
        session_key = "agent:fit-agent:default"
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role, project, launch=None: [],
        )

        result = driver.run_turn("fit-agent", session_key, "inspect the diagnostic", 60)

        assert not result.ok
        assert result.failure_kind == "invalid_output"
        assert "estimated request 1090" in result.error
        assert "input 890" in result.error
        assert "output reserve 200" in result.error
        assert "registered context window 1000" in result.error
        assert "irreducible" in result.error
        assert dispatches == 1
        assert len(backend.calls) == 2
        assert [bool(tools) for tools in backend.tools_seen] == [True, False]
        assert backend.prospectives == [
            ("task", 200),
            ("task", 1_220),
            ("compaction", 700),
            ("task", 890),
        ]

        trace_path = current_home().traces_dir / "fit-agent" / f"{session_key}.jsonl"
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        fit_payloads = [
            record["payload"] for record in records if record["event_type"] == "request_fit"
        ]
        assert [
            (payload["purpose"], payload["status"], payload["estimatedInputTokens"])
            for payload in fit_payloads
        ] == [
            ("task", "fits", 200),
            ("task", "failed", 1_220),
            ("compaction", "fits", 700),
            ("task", "failed", 890),
        ]
        expected_fit_keys = {
            "purpose",
            "status",
            "estimatedInputTokens",
            "outputReserveTokens",
            "contextWindowTokens",
            "estimate",
        }
        assert all(set(payload) == expected_fit_keys for payload in fit_payloads)
        assert all(payload["outputReserveTokens"] == 200 for payload in fit_payloads)
        assert all(payload["contextWindowTokens"] == 1_000 for payload in fit_payloads)
        assert all(payload["estimate"] is True for payload in fit_payloads)
        succeeded = [
            record
            for record in records
            if record["event_type"] == "session_compaction"
            and record["payload"]["status"] == "succeeded"
        ]
        assert len(succeeded) == 1
        assert "ORIGINAL_SENTINEL" not in trace_path.read_text()

        stored = _session.load_messages(session_key)
        assert any("S" * 100 in message.content for message in stored)
        assert all("ORIGINAL_SENTINEL" not in message.content for message in stored)
        assert any(message.content == "inspect the diagnostic" for message in stored)
        assert not _session_units.find_orphaned_tool_messages(stored)
        assert not _session_units.find_unanswered_tool_calls(stored)
