"""Live session compaction in the turn loop: request fit, summary rounds and revision caps."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from tests.support.loop_harness import (
    ScriptedBackend,
    _final,
    _tool_call_response,
)

from docket.agent import loop as _loop
from docket.agent import loop_compaction as _loop_compaction
from docket.agent import session as _session
from docket.agent import session_compaction as _session_compaction
from docket.agent import session_units as _session_units
from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.agent.session import append_messages as append_session_messages
from docket.agent.session import load_session
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.kernel.home import current_home

SUBJECT = "docket.agent.loop"


class TestLiveSessionCompaction:
    def test_same_turn_request_growth_compacts_and_reloads_before_transport(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        class FitAwareBackend(ScriptedBackend):
            context_window_tokens = 1_000
            max_output_tokens = 200

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return 700
                if any(message.role == "tool" for message in messages):
                    return 900
                if any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    return 300
                return 200

        large_result = "result " * 400
        large_registry = ToolRegistry()
        large_registry.register(
            _Tool(
                name="large",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=lambda args, tool_ctx: ToolOutcome(ok=True, content=large_result),
                kind="read",
            )
        )
        backend = FitAwareBackend(
            [
                _tool_call_response("large-1", "large", "{}"),
                _final("diagnostic result retained"),
                _final("task complete"),
            ]
        )
        session_key = "agent:request-fit:demo"

        result = _loop.run_agent_turn(
            backend,
            large_registry,
            ctx,
            session_key,
            "inspect the diagnostic",
            config=_loop.LoopConfig(
                context_window_tokens=backend.context_window_tokens,
                max_tokens=backend.max_output_tokens,
            ),
        )

        assert result.ok
        assert result.output == "task complete"
        assert len(backend.calls) == 3
        assert "compacting durable turn history" in backend.calls[1][0].content
        assert backend.tool_specs[1] == []
        assert not any(large_result in message.content for message in backend.calls[2])
        stored = _session.load_messages(session_key)
        assert not _session_units.find_orphaned_tool_messages(stored)
        assert not _session_units.find_unanswered_tool_calls(stored)
        assert any(message.content == "inspect the diagnostic" for message in stored)
        assert any(message.content.startswith("[compacted summary of ") for message in stored)

    def test_irreducible_request_fails_locally_before_backend_call(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        class NeverFitsBackend(ScriptedBackend):
            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                return 900

        backend = NeverFitsBackend([_final("must not be used")])

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            "agent:irreducible:demo",
            "current task must remain exact",
            config=_loop.LoopConfig(context_window_tokens=1_000, max_tokens=200),
        )

        assert not result.ok
        assert result.stop_reason == "context_fit"
        assert result.failure_kind == "invalid_output"
        assert "estimated" in result.error
        assert "1000" in result.error
        assert backend.calls == []
        assert [
            message.content for message in _session.load_messages("agent:irreducible:demo")
        ] == ["current task must remain exact"]

    def test_request_fit_summary_timeout_aborts_before_trying_the_prefix(
        self, ctx: ToolContext
    ) -> None:
        session_key = "agent:request-fit-timeout:demo"
        prefix_drop = "old prefix drop " * 300
        prefix_keep = "old prefix keep " * 300
        suffix = "current suffix " * 600
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content=prefix_drop),
                ChatMessage(role="user", content=prefix_keep),
            ],
        )
        registry = ToolRegistry()
        dispatches = 0

        def _lookup(args: dict[str, object], tool_ctx: ToolContext) -> ToolOutcome:
            nonlocal dispatches
            dispatches += 1
            return ToolOutcome(True, content=suffix)

        registry.register(
            _Tool(
                name="lookup",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class TimeoutBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.summary_prompts: list[str] = []

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return 700
                if any(message.role == "tool" for message in messages):
                    return 1_220
                return 200

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
                        usage=TokenUsage(input_tokens=10, output_tokens=5),
                    )
                self.summary_prompts.append(messages[0].content)
                return ChatResponse(
                    ok=False,
                    error="request-fit summary timed out",
                    failure_kind="timeout",
                    usage=TokenUsage(input_tokens=12, output_tokens=8),
                )

        backend = TimeoutBackend()
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "inspect the current diagnostic",
            config=_loop.LoopConfig(
                context_window_tokens=backend.context_window_tokens,
                max_tokens=backend.max_output_tokens,
            ),
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == "timeout"
        assert result.error == "request-fit summary timed out"
        assert result.usage == TokenUsage(input_tokens=22, output_tokens=13)
        assert dispatches == 1
        assert len(backend.calls) == 2
        assert [bool(tools) for tools in backend.tools_seen] == [True, False]
        assert len(backend.summary_prompts) == 1
        stored = load_session(session_key)
        assert stored.usage.input_tokens == 22
        assert stored.usage.output_tokens == 13
        assert any("current suffix" in message.content for message in stored.messages)
        assert not _session_units.find_orphaned_tool_messages(stored.messages)
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

    def test_concurrent_suffix_append_is_a_new_request_fit_revision(
        self, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_key = "agent:request-fit-concurrent-revision:demo"
        suffix = "ORIGINAL_SUFFIX " * 600
        concurrent = "CONCURRENT_REVISION " * 600
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], tool_ctx: ToolContext) -> ToolOutcome:
            return ToolOutcome(True, content=suffix)

        registry.register(
            _Tool(
                name="lookup",
                description="Return a large diagnostic result.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class ConcurrentRevisionBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
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
                    return 700
                if any(message.role == "tool" for message in messages):
                    return 1_220
                if any("CONCURRENT_REVISION" in message.content for message in messages):
                    return 1_100
                if any("SECOND_SUMMARY" in message.content for message in messages):
                    return 700
                return 200

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
                    return _final("done after the new revision", TokenUsage(10, 5))
                prompt = messages[0].content
                assert "compacting durable turn history" in prompt
                if "CONCURRENT_REVISION" in prompt:
                    assert "FIRST_SUMMARY" not in prompt
                    assert "ORIGINAL_SUFFIX" not in prompt
                    return _final("SECOND_SUMMARY " + "N" * 400)
                assert "ORIGINAL_SUFFIX" in prompt
                return _final("FIRST_SUMMARY " + "S" * 1_000)

        real_compact_session = _loop_compaction.compact_session
        injected = False
        ranged_calls: list[tuple[int, int]] = []

        def _append_after_ranged_write(
            *args: Any, **kwargs: Any
        ) -> _session_compaction.CompactionResult:
            nonlocal injected
            result = real_compact_session(*args, **kwargs)
            compact_range = kwargs.get("compact_range")
            if isinstance(compact_range, tuple):
                ranged_calls.append(compact_range)
            if compact_range is not None and result.compacted and not injected:
                injected = True
                append_session_messages(
                    session_key,
                    [ChatMessage(role="user", content=concurrent)],
                )
            return result

        monkeypatch.setattr(
            _loop_compaction, "compact_session", _append_after_ranged_write, raising=True
        )
        backend = ConcurrentRevisionBackend()

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "inspect concurrent history",
            config=_loop.LoopConfig(
                context_window_tokens=backend.context_window_tokens,
                max_tokens=backend.max_output_tokens,
            ),
        )

        assert result.ok
        assert result.output == "done after the new revision"
        assert injected
        assert ranged_calls == [(1, 3), (2, 3)]
        assert [bool(tools) for tools in backend.tools_seen] == [True, False, False, True]
        stored = load_session(session_key)
        assert all("ORIGINAL_SUFFIX" not in message.content for message in stored.messages)
        assert all("CONCURRENT_REVISION" not in message.content for message in stored.messages)
        assert any("FIRST_SUMMARY" in message.content for message in stored.messages)
        assert any("SECOND_SUMMARY" in message.content for message in stored.messages)
        assert any(message.content == "inspect concurrent history" for message in stored.messages)
        assert not _session_units.find_orphaned_tool_messages(stored.messages)
        assert not _session_units.find_unanswered_tool_calls(stored.messages)

    def test_fixed_revision_cap_rechecks_the_last_accepted_summary(
        self, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session_key = "agent:request-fit-continuous-appends:demo"
        registry = ToolRegistry()

        def _lookup(args: dict[str, object], tool_ctx: ToolContext) -> ToolOutcome:
            return ToolOutcome(True, content="INITIAL_SUFFIX " * 600)

        registry.register(
            _Tool(
                name="lookup",
                description="Return a large initial diagnostic.",
                parameters={"type": "object", "properties": {}},
                handler=_lookup,
                kind="read",
            )
        )

        class ContinuousAppendBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.calls: list[list[ChatMessage]] = []
                self.tools_seen: list[list[ToolSpec]] = []
                self.summary_calls = 0

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    return 700
                if any(message.role == "tool" for message in messages):
                    return 1_220
                if any("CONCURRENT_APPEND" in message.content for message in messages):
                    return 1_100
                return 200

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
                        usage=TokenUsage(10, 5),
                    )
                self.summary_calls += 1
                return _final(
                    f"SUMMARY_{self.summary_calls} " + "S" * 200,
                    TokenUsage(10, 5),
                )

        real_compact_session = _loop_compaction.compact_session
        ranged_calls: list[tuple[int, int]] = []

        def _append_after_every_ranged_write(
            *args: Any, **kwargs: Any
        ) -> _session_compaction.CompactionResult:
            result = real_compact_session(*args, **kwargs)
            compact_range = kwargs.get("compact_range")
            if isinstance(compact_range, tuple) and result.compacted:
                ranged_calls.append(compact_range)
                append_session_messages(
                    session_key,
                    [
                        ChatMessage(
                            role="user",
                            content=f"CONCURRENT_APPEND_{len(ranged_calls)} " * 500,
                        )
                    ],
                )
            return result

        monkeypatch.setattr(
            _loop_compaction,
            "compact_session",
            _append_after_every_ranged_write,
            raising=True,
        )
        backend = ContinuousAppendBackend()

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "inspect a changing stream",
            config=_loop.LoopConfig(
                context_window_tokens=backend.context_window_tokens,
                max_tokens=backend.max_output_tokens,
            ),
        )

        assert not result.ok
        assert result.stop_reason == "context_fit"
        assert "request-fit compaction did not converge" in result.error
        assert backend.summary_calls == 4
        assert len(ranged_calls) == 4
        assert [bool(tools) for tools in backend.tools_seen] == [True, False, False, False, False]
        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        fits = [
            json.loads(line)
            for line in tracefile.read_text().splitlines()
            if json.loads(line)["event_type"] == "request_fit"
        ]
        assert len(fits) == 10
        assert fits[-1]["payload"]["purpose"] == "task"
        assert fits[-1]["payload"]["status"] == "failed"
