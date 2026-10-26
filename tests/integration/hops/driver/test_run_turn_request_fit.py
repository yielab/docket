"""DocketDriver.run_turn: request-fit compaction around appends and suffix and prefix summaries."""

from __future__ import annotations

import json
from collections.abc import Sequence

from tests.support.driver_harness import (
    _final_response,
)
from tests.support.pods import write_meta_overrides as _write_meta

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
    def test_request_fit_rechecks_an_append_completed_during_the_fit_check(self) -> None:
        _write_meta("fit-refresh-agent")
        session_key = "agent:fit-refresh-agent:default"
        task_message = "CONCURRENT_REVISION " * 600
        original = "ORIGINAL_SUFFIX " * 600
        dispatches = 0
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=original)

        registry.register(
            Tool(
                name="lookup",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class PostReloadAppendBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.prospectives: list[tuple[str, int]] = []
                self.summary_prompts: list[str] = []
                self.task_transports = 0
                self.injected = False

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
                elif (
                    sum(
                        message.role == "user" and message.content == task_message
                        for message in messages
                    )
                    > 1
                ):
                    prospective = ("task", 1_100)
                elif any("SECOND_SUMMARY" in message.content for message in messages):
                    prospective = ("task", 700)
                elif any("FIRST_SUMMARY" in message.content for message in messages):
                    if not self.injected:
                        self.injected = True
                        _session.append_messages(
                            session_key,
                            [
                                ChatMessage(
                                    role="user",
                                    content=task_message,
                                    name="concurrent-copy",
                                )
                            ],
                        )
                    prospective = ("task", 700)
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
                    if self.task_transports == 1:
                        call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                        return ChatResponse(
                            ok=True,
                            message=assistant("", tool_calls=[call]),
                            finish_reason="tool_calls",
                            usage=TokenUsage(10, 5),
                        )
                    fresh = any("SECOND_SUMMARY" in message.content for message in messages)
                    return _final_response(
                        "fresh revision transported" if fresh else "stale revision transported",
                        TokenUsage(10, 5),
                    )
                prompt = messages[0].content
                self.summary_prompts.append(prompt)
                assert "compacting durable turn history" in prompt
                if "CONCURRENT_REVISION" in prompt:
                    assert "FIRST_SUMMARY" not in prompt
                    assert "ORIGINAL_SUFFIX" not in prompt
                    return _final_response("SECOND_SUMMARY " + "N" * 400, TokenUsage(10, 5))
                assert "ORIGINAL_SUFFIX" in prompt
                return _final_response("FIRST_SUMMARY " + "S" * 1_000, TokenUsage(10, 5))

        backend = PostReloadAppendBackend()
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role, project, launch=None: [],
        )

        result = driver.run_turn("fit-refresh-agent", session_key, task_message, 60)

        assert result.ok
        assert result.output == "fresh revision transported"
        assert backend.injected
        assert dispatches == 1
        assert [bool(tools) for tools in backend.tools_seen] == [True, False, False, True]
        assert backend.prospectives == [
            ("task", 200),
            ("task", 1_220),
            ("compaction", 700),
            ("task", 700),
            ("task", 1_100),
            ("compaction", 700),
            ("task", 700),
        ]
        assert len(backend.summary_prompts) == 2
        assert "FIRST_SUMMARY" not in backend.summary_prompts[1]
        assert "ORIGINAL_SUFFIX" not in backend.summary_prompts[1]

        final_task = backend.calls[-1]
        assert any("FIRST_SUMMARY" in message.content for message in final_task)
        assert any("SECOND_SUMMARY" in message.content for message in final_task)
        assert all("ORIGINAL_SUFFIX" not in message.content for message in final_task)
        final_tasks = [
            message
            for message in final_task
            if message.role == "user" and message.content == task_message
        ]
        assert len(final_tasks) == 1
        assert final_tasks[0].name == ""

        stored = load_session(session_key)
        assert stored.usage.input_tokens == 40
        assert stored.usage.output_tokens == 20
        assert stored.usage.turns == 4
        assert any("FIRST_SUMMARY" in message.content for message in stored.messages)
        assert any("SECOND_SUMMARY" in message.content for message in stored.messages)
        assert all("ORIGINAL_SUFFIX" not in message.content for message in stored.messages)
        stored_tasks = [
            message
            for message in stored.messages
            if message.role == "user" and message.content == task_message
        ]
        assert len(stored_tasks) == 1
        assert stored_tasks[0].name == ""
        assert not _session_units.find_orphaned_tool_messages(stored.messages)
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

        trace_path = current_home().traces_dir / "fit-refresh-agent" / f"{session_key}.jsonl"
        records = [json.loads(line) for line in trace_path.read_text().splitlines()]
        fit_payloads = [
            record["payload"] for record in records if record["event_type"] == "request_fit"
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
        assert "ORIGINAL_SUFFIX" not in trace_path.read_text()
        assert "CONCURRENT_REVISION" not in trace_path.read_text()

    def test_request_fit_may_compact_suffix_then_an_independent_prefix(self) -> None:
        _write_meta("two-segment-agent")
        session_key = "agent:two-segment-agent:default"
        prefix_drop = "PREFIX_DROP_SENTINEL " * 250
        prefix_anchor = "PREFIX_ANCHOR " * 250
        suffix = "SUFFIX_SENTINEL " * 500
        _session.append_messages(
            session_key,
            [
                ChatMessage(role="user", content=prefix_drop),
                ChatMessage(role="user", content=prefix_anchor),
            ],
        )
        dispatches = 0
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=suffix)

        registry.register(
            Tool(
                name="lookup",
                description="Return another large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class TwoSegmentBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.prospectives: list[tuple[str, int]] = []
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
                elif any("SUFFIX_SUMMARY" in message.content for message in messages) and any(
                    "PREFIX_DROP_SENTINEL" in message.content for message in messages
                ):
                    prospective = ("task", 1_100)
                elif any("PREFIX_SUMMARY" in message.content for message in messages):
                    prospective = ("task", 700)
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
                    if self.task_transports == 1:
                        call = ToolCall(id="lookup-1", name="lookup", arguments="{}")
                        return ChatResponse(
                            ok=True,
                            message=assistant("", tool_calls=[call]),
                            finish_reason="tool_calls",
                            usage=TokenUsage(10, 5),
                        )
                    return _final_response("done", TokenUsage(10, 5))
                prompt = messages[0].content
                assert "compacting durable turn history" in prompt
                if "SUFFIX_SENTINEL" in prompt:
                    return _final_response("SUFFIX_SUMMARY " + "S" * 1_500)
                assert "PREFIX_DROP_SENTINEL" in prompt
                return _final_response("PREFIX_SUMMARY " + "P" * 500)

        backend = TwoSegmentBackend()
        driver = DocketDriver(
            backend_factory=lambda model: backend,
            registry_factory=lambda: registry,
            mcp_loader=lambda registry, role, project, launch=None: [],
        )

        result = driver.run_turn("two-segment-agent", session_key, "inspect both segments", 60)

        assert result.ok
        assert result.output == "done"
        assert dispatches == 1
        assert [bool(tools) for tools in backend.tools_seen] == [True, False, False, True]
        assert backend.prospectives == [
            ("task", 200),
            ("task", 1_220),
            ("compaction", 700),
            ("task", 1_100),
            ("compaction", 700),
            ("task", 700),
        ]
        records = [
            json.loads(line)
            for line in (current_home().traces_dir / "two-segment-agent" / f"{session_key}.jsonl")
            .read_text()
            .splitlines()
        ]
        succeeded = [
            record
            for record in records
            if record["event_type"] == "session_compaction"
            and record["payload"]["status"] == "succeeded"
        ]
        assert len(succeeded) == 2
        stored = _session.load_messages(session_key)
        assert all("PREFIX_DROP_SENTINEL" not in message.content for message in stored)
        assert all("SUFFIX_SENTINEL" not in message.content for message in stored)
        assert any("PREFIX_ANCHOR" in message.content for message in stored)
        assert any("PREFIX_SUMMARY" in message.content for message in stored)
        assert any("SUFFIX_SUMMARY" in message.content for message in stored)
        assert not _session_units.find_orphaned_tool_messages(stored)
        assert not _session_units.find_unanswered_tool_calls(stored)
