"""Live session compaction in the turn loop: usage accounting, failure handling and history feeding."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence

import pytest
from tests.support.loop_harness import (
    ScriptedBackend,
    _final,
    _tool_call_response,
    _truncated,
)

from docket.agent import loop as _loop
from docket.agent import ports as _ports
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
from docket.agent.session import append_messages as append_session_messages
from docket.agent.session import load_session
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.kernel.home import current_home
from docket.platform import read_json

SUBJECT = "docket.agent.loop"

# A window the history below does not fit, so the first task request is compacted: the oldest
# units are summarized, in rounds whose prompts stay inside window - reserve - 16.
_NARROW_WINDOW = _loop.LoopConfig(context_window_tokens=700, max_tokens=100)


def _append_history_that_does_not_fit(session_key: str) -> list[dict[str, object]]:
    """Eight user messages of about 105 tokens each; returns them as stored, for byte comparison."""
    append_session_messages(
        session_key,
        [ChatMessage(role="user", content=f"old-{n} " * 60) for n in range(8)],
    )
    return [message.model_dump(by_alias=True) for message in load_session(session_key).messages]


def _assert_history_untouched(
    session_key: str, original_messages: list[dict[str, object]], task: str
) -> None:
    """A failed summary left the earlier history as it was; only the task message was appended."""
    stored = load_session(session_key).messages
    assert [message.model_dump(by_alias=True) for message in stored[:-1]] == original_messages
    assert stored[-1].content == task
    assert not (_session._session_path(session_key, None).parent / "compactions").exists()


class TestLiveSessionCompaction:
    def test_unstable_preflight_revision_cap_reports_request_fit_evidence(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:request-fit-preflight-churn:demo"

        class PreflightChurnBackend:
            context_window_tokens = 1_000
            max_output_tokens = 200

            def __init__(self) -> None:
                self.estimate_calls = 0
                self.complete_calls = 0

            def estimate_input_tokens(
                self,
                messages: Sequence[ChatMessage],
                *,
                tools: Sequence[ToolSpec] = (),
                max_tokens: int | None = None,
                temperature: float | None = None,
            ) -> int:
                self.estimate_calls += 1
                append_session_messages(
                    session_key,
                    [
                        ChatMessage(
                            role="user",
                            content=f"concurrent revision {self.estimate_calls}",
                        )
                    ],
                )
                return 300

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
                self.complete_calls += 1
                raise AssertionError("an unstable preflight revision must not be transported")

        backend = PreflightChurnBackend()

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "inspect a continuously changing request",
            config=_loop.LoopConfig(
                context_window_tokens=backend.context_window_tokens,
                max_tokens=backend.max_output_tokens,
            ),
        )

        assert not result.ok
        assert result.stop_reason == "context_fit"
        assert result.failure_kind == "invalid_output"
        assert "input 300" in result.error
        assert "output reserve 200" in result.error
        assert "registered context window 1000" in result.error
        assert "attempt cap 2" in result.error
        assert backend.estimate_calls == 3
        assert backend.complete_calls == 0

    def test_a_history_whose_request_does_not_fit_is_compacted_before_the_task_call(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:demo-agent:demo"
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
                ChatMessage(role="user", content="recent context " * 100),
            ],
        )
        events: list[tuple[str, dict[str, object]]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            events.append((event_type, json.loads(payload)))
            return "written"

        real_tracer_except(trace_event=_trace)
        backend = ScriptedBackend(
            [
                _final("old decision preserved", TokenUsage(input_tokens=30, output_tokens=7)),
                _final("task done", TokenUsage(input_tokens=11, output_tokens=3)),
            ]
        )

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "new request",
            config=_loop.LoopConfig(context_window_tokens=600, max_tokens=60),
        )

        assert result.ok, result.error
        assert len(backend.calls) == 2
        assert len(backend.calls[0]) == 1
        assert backend.calls[0][0].role == "user"
        assert backend.tool_specs[0] == []
        assert backend.tool_specs[1]
        assert "old context" in backend.calls[0][0].content
        assert "middle context" in backend.calls[0][0].content
        assert "recent context" not in backend.calls[0][0].content
        assert any("old decision preserved" in m.content for m in backend.calls[1])
        assert any("recent context" in m.content for m in backend.calls[1])
        stored = load_session(session_key)
        stored_messages = _session.load_messages(session_key)
        assert not _session_units.find_orphaned_tool_messages(stored_messages)
        assert not _session_units.find_unanswered_tool_calls(stored_messages)
        assert result.usage == TokenUsage(input_tokens=41, output_tokens=10)
        assert stored.usage.input_tokens == 41
        assert stored.usage.output_tokens == 10
        assert not _session._session_path(f"{session_key}:compaction", None).exists()
        compaction_events = [payload for kind, payload in events if kind == "session_compaction"]
        assert len(compaction_events) == 1
        assert compaction_events[0]["status"] == "succeeded"
        assert (
            compaction_events[0]["afterMessageCount"] < compaction_events[0]["beforeMessageCount"]
        )
        assert "summary" not in compaction_events[0]
        assert compaction_events[0]["record"] == "compactions/1.json"
        assert compaction_events[0]["summarizedRange"] == [0, 4]
        assert re.fullmatch(r"[0-9a-f]{64}", str(compaction_events[0]["promptSha256"]))
        record = read_json(_session._session_path(session_key, None).parent / "compactions/1.json")
        assert record["promptSha256"] == compaction_events[0]["promptSha256"]
        assert record["range"] == [0, 4]
        assert [m["role"] for m in record["replaced"]] == ["user", "assistant", "tool", "user"]
        assert backend.calls[1][0].role == "user"
        assert backend.calls[1][0].content.startswith("[compacted summary of ")
        assert [m.content for m in backend.calls[1][-1:]] == ["new request"]

    def test_live_path_aggregates_usage_across_bounded_summary_rounds(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:hierarchical:demo"
        append_session_messages(
            session_key,
            [ChatMessage(role="user", content=f"old-{index} " * 90) for index in range(20)],
        )
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "session_compaction":
                events.append(json.loads(payload))
            return "written"

        class _Backend:
            def __init__(self) -> None:
                self.summary_prompts: list[str] = []

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
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    self.summary_prompts.append(messages[0].content)
                    return _final(
                        f"bounded summary {len(self.summary_prompts)}",
                        TokenUsage(input_tokens=10, output_tokens=2),
                    )
                return _final("task done", TokenUsage(input_tokens=5, output_tokens=1))

        real_tracer_except(trace_event=_trace)
        backend = _Backend()
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "new request",
            config=_loop.LoopConfig(context_window_tokens=1_000, max_tokens=50),
        )

        rounds = len(backend.summary_prompts)
        summary_input_bound = 1_000 - 50 - 16
        assert result.ok, result.error
        assert rounds > 1
        assert all(
            _ports.estimate_tokens(prompt) <= summary_input_bound
            for prompt in backend.summary_prompts
        )
        assert result.usage == TokenUsage(
            input_tokens=rounds * 10 + 5,
            output_tokens=rounds * 2 + 1,
        )
        stored = load_session(session_key)
        assert stored.usage.input_tokens == result.usage.input_tokens
        assert stored.usage.output_tokens == result.usage.output_tokens
        assert sum(int(event["summaryRounds"]) for event in events) == rounds
        assert all(
            event["maxSummaryPromptEstimatedTokens"] <= summary_input_bound for event in events
        )

    def test_successive_compaction_preflights_include_prior_summary_usage(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:summary-budget:demo"
        append_session_messages(
            session_key,
            [ChatMessage(role="user", content=f"old-{index} " * 30) for index in range(100)],
        )
        original_messages = [
            message.model_dump(by_alias=True) for message in load_session(session_key).messages
        ]

        class _Backend:
            context_window_tokens = 300
            max_output_tokens = 10

            def __init__(self) -> None:
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
                    return 10
                return 900

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
                assert not tools
                assert "compacting durable turn history" in messages[0].content
                self.summary_prompts.append(messages[0].content)
                return _final(
                    f"bounded summary {len(self.summary_prompts)}",
                    TokenUsage(input_tokens=480, output_tokens=20),
                )

        backend = _Backend()
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "task request that does not fit",
            config=_loop.LoopConfig(token_budget=1_000, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert result.usage.total_tokens == 1_000
        assert len(backend.summary_prompts) == 2
        stored = load_session(session_key)
        assert [
            message.model_dump(by_alias=True) for message in stored.messages[:-1]
        ] == original_messages
        assert stored.messages[-1].content == "task request that does not fit"
        assert stored.usage.input_tokens == 960
        assert stored.usage.output_tokens == 40
        tracefile = (
            current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        )
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        compaction_fits = [
            record
            for record in records
            if record["event_type"] == "request_fit"
            and record["payload"]["purpose"] == "compaction"
        ]
        assert len(compaction_fits) == 3
        assert records[-1]["event_type"] == "session_compaction"
        assert records[-1]["payload"]["status"] == "failed"

    def test_a_history_that_fits_makes_no_compaction_event(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        real_tracer_except: Callable[..., None],
    ) -> None:
        events: list[str] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            events.append(event_type)
            return "written"

        real_tracer_except(trace_event=_trace)
        session_key = "agent:demo-agent:demo"
        append_session_messages(
            session_key,
            [ChatMessage(role="user", content="earlier ask " * 20), assistant("earlier answer")],
        )
        backend = ScriptedBackend([_final("done")])
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "hello",
            config=_loop.LoopConfig(context_window_tokens=8_000, max_tokens=500),
        )

        assert result.ok
        assert len(backend.calls) == 1
        assert backend.tool_specs[0]
        assert "session_compaction" not in events
        assert not (_session._session_path(session_key, None).parent / "compactions").exists()

    def test_summary_failure_aborts_turn_and_preserves_history(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:demo-agent:demo"
        original_messages = _append_history_that_does_not_fit(session_key)
        events: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "session_compaction":
                events.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)
        backend = ScriptedBackend(
            [ChatResponse(ok=False, error="summary timed out", failure_kind="timeout")]
        )
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "task request",
            config=_NARROW_WINDOW,
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == "timeout"
        assert len(backend.calls) == 1
        _assert_history_untouched(session_key, original_messages, "task request")
        assert events[0]["status"] == "failed"

    def test_truncated_summary_is_never_accepted_with_budget_remaining(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:summary-truncated:demo"
        original_messages = _append_history_that_does_not_fit(session_key)
        backend = ScriptedBackend(
            [
                _truncated(
                    "partial summary must never become durable",
                    usage=TokenUsage(input_tokens=4, output_tokens=1),
                ),
                _final("task completion must not be called"),
            ]
        )

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "task request",
            config=_loop.LoopConfig(
                context_window_tokens=700, max_tokens=100, token_budget=100_000
            ),
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == "invalid_output"
        assert result.usage == TokenUsage(input_tokens=4, output_tokens=1)
        assert len(backend.calls) == 1
        _assert_history_untouched(session_key, original_messages, "task request")
        stored = load_session(session_key)
        assert stored.usage.input_tokens == 4
        assert stored.usage.output_tokens == 1

    @pytest.mark.parametrize(
        ("case", "expected_failure_kind"),
        [
            ("backend_timeout", "timeout"),
            ("truncated", "invalid_output"),
            ("empty", "invalid_output"),
            ("tool_call", "invalid_output"),
        ],
    )
    def test_invalid_summary_outcome_wins_over_measured_budget_overrun(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        case: str,
        expected_failure_kind: str,
    ) -> None:
        session_key = f"agent:summary-precedence-{case}:demo"
        original_messages = _append_history_that_does_not_fit(session_key)
        usage = TokenUsage(input_tokens=2_500, output_tokens=500)
        if case == "backend_timeout":
            response = ChatResponse(
                ok=False,
                error="token budget: upstream timeout",
                failure_kind="timeout",
                usage=usage,
            )
        elif case == "truncated":
            response = _truncated("partial summary must not persist", usage=usage)
        elif case == "empty":
            response = _final("   ", usage)
        else:
            response = _tool_call_response("summary-tool", "echo", '{"text": "no"}', usage)
        backend = ScriptedBackend([response])

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "task request",
            config=_loop.LoopConfig(context_window_tokens=700, max_tokens=100, token_budget=2_000),
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == expected_failure_kind
        assert result.usage == usage
        assert len(backend.calls) == 1
        _assert_history_untouched(session_key, original_messages, "task request")
        stored = load_session(session_key)
        assert stored.usage.input_tokens == 2_500
        assert stored.usage.output_tokens == 500
        assert stored.usage.turns == 1


class TestHistoryFeeding:
    def test_prior_session_history_is_loaded_and_sent_to_the_backend(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        # Seed a prior turn.
        _loop.run_agent_turn(
            ScriptedBackend([_final("first answer")]), registry, ctx, session_key, "first question"
        )

        backend = ScriptedBackend([_final("second answer")])
        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "second question")

        assert result.ok
        sent_contents = [m.content for m in backend.calls[0]]
        assert "first question" in sent_contents
        assert "first answer" in sent_contents
        assert "second question" in sent_contents


class TestHistoryCondensation:
    def test_old_results_become_notices_and_the_record_keeps_every_byte(
        self, ctx: ToolContext
    ) -> None:
        reg = ToolRegistry()
        reg.register(
            _Tool(
                name="read",
                description="Read a file.",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                handler=lambda args, c: ToolOutcome(
                    ok=True,
                    content="\n".join(f"{i}\t{args['path']} row" for i in range(60))
                    + "\n"
                    + "x" * (_session.HISTORY_FULL_RESULTS_CHARS // 2),
                ),
                kind="read",
            )
        )
        backend = ScriptedBackend(
            [_tool_call_response(f"c{n}", "read", f'{{"path":"f{n}.py"}}') for n in range(6)]
            + [_final("done")]
        )
        session_key = "agent:condense:default"

        result = _loop.run_agent_turn(backend, reg, ctx, session_key, "work")

        assert result.ok, result.error
        keep = _session.HISTORY_KEEP_FULL_RESULTS
        sent = [m for m in backend.calls[-1] if m.role == "tool"]
        assert len(sent) == 6
        assert sum(m.content.startswith("[read f") for m in sent) == 6 - keep
        assert all("row" in m.content and not m.content.startswith("[") for m in sent[-keep:])
        stored = [m for m in _session.load_messages(session_key) if m.role == "tool"]
        assert len(stored) == 6
        assert all(not m.content.startswith("[") for m in stored)

    def test_the_first_task_request_names_what_the_projection_condensed(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:projection:default"
        history: list[ChatMessage] = [ChatMessage(role="user", content="earlier ask")]
        for n in range(4):
            call = ToolCall(id=f"r{n}", name="read", arguments=f'{{"path":"f{n}.py"}}')
            history += [
                assistant("", tool_calls=[call]),
                ChatMessage(role="tool", content="x" * 1_600, tool_call_id=call.id, name="read"),
            ]
        history.append(assistant("read them all"))
        append_session_messages(session_key, history)
        llm_calls: list[dict[str, object]] = []

        def _trace(
            project: str,
            traced_session: str,
            role: str,
            event_type: str,
            payload: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            if event_type == "llm_call":
                llm_calls.append(json.loads(payload))
            return "written"

        real_tracer_except(trace_event=_trace)
        result = _loop.run_agent_turn(
            ScriptedBackend([_final("done")]), registry, ctx, session_key, "next ask"
        )

        assert result.ok, result.error
        assert llm_calls[0]["projection"] == {
            "condensedResults": 2,
            "keptWholeResults": 2,
            "budgetChars": _session.HISTORY_FULL_RESULTS_CHARS,
        }
