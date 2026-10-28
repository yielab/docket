"""Live session compaction in the turn loop: usage accounting, failure handling and history feeding."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import pytest
from tests.support.loop_harness import (
    ScriptedBackend,
    _final,
    _SizedBackend,
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

SUBJECT = "docket.agent.loop"


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

    def test_over_budget_history_is_compacted_before_task_completion(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:demo-agent:demo"
        call = ToolCall(id="old_call", name="echo", arguments='{"text":"old"}')
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content="old context " * 100),
                assistant("", tool_calls=[call]),
                ChatMessage(
                    role="tool", content="old result", tool_call_id=call.id, name=call.name
                ),
                ChatMessage(role="user", content="recent context"),
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
            config=_loop.LoopConfig(history_budget_tokens=1),
        )

        assert result.ok
        assert len(backend.calls) == 2
        assert len(backend.calls[0]) == 1
        assert backend.calls[0][0].role == "user"
        assert backend.tool_specs[0] == []
        assert backend.tool_specs[1]
        assert "old context" in backend.calls[0][0].content
        assert any("old decision preserved" in m.content for m in backend.calls[1])
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

    def test_live_path_aggregates_usage_across_bounded_summary_rounds(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:hierarchical:demo"
        append_session_messages(
            session_key,
            [ChatMessage(role="user", content=f"old-{index} " * 30) for index in range(10)],
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
            config=_loop.LoopConfig(
                history_budget_tokens=80,
                summary_input_budget_tokens=180,
            ),
        )

        rounds = len(backend.summary_prompts)
        assert result.ok
        assert rounds > 1
        assert all(_ports.estimate_tokens(prompt) <= 180 for prompt in backend.summary_prompts)
        assert result.usage == TokenUsage(
            input_tokens=rounds * 10 + 5,
            output_tokens=rounds * 2 + 1,
        )
        stored = load_session(session_key)
        assert stored.usage.input_tokens == result.usage.input_tokens
        assert stored.usage.output_tokens == result.usage.output_tokens
        assert events[0]["summaryRounds"] == rounds
        assert events[0]["maxSummaryPromptEstimatedTokens"] <= 180

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
            context_window_tokens = 1_000
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
                return 10

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
                    TokenUsage(input_tokens=25, output_tokens=5),
                )

        backend = _Backend()
        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "must not be appended",
            config=_loop.LoopConfig(
                token_budget=70,
                max_tokens=10,
                history_budget_tokens=80,
                summary_input_budget_tokens=180,
            ),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert result.usage.total_tokens == 60
        assert len(backend.summary_prompts) == 2
        stored = load_session(session_key)
        assert [
            message.model_dump(by_alias=True) for message in stored.messages
        ] == original_messages
        assert stored.usage.input_tokens == 50
        assert stored.usage.output_tokens == 10
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

    def test_no_op_uses_one_backend_call_and_emits_bounded_trace(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
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
        backend = ScriptedBackend([_final("done")])
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo-agent:demo", "hello")

        assert result.ok
        assert len(backend.calls) == 1
        assert events == [
            {
                "status": "no_op",
                "beforeMessageCount": 0,
                "afterMessageCount": 0,
                "beforeEstimatedTokens": 0,
                "afterEstimatedTokens": 0,
                "groupsSummarized": 0,
                "summaryRounds": 0,
                "maxSummaryPromptEstimatedTokens": 0,
            }
        ]

    def test_summary_failure_aborts_turn_and_preserves_history_bytes(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        monkeypatch: pytest.MonkeyPatch,
        real_tracer_except: Callable[..., None],
    ) -> None:
        session_key = "agent:demo-agent:demo"
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content="old " * 200),
                ChatMessage(role="user", content="keep"),
            ],
        )
        path = _session._session_path(session_key, None)
        before = path.read_bytes()
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
            "must not be appended",
            config=_loop.LoopConfig(history_budget_tokens=1),
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == "timeout"
        assert len(backend.calls) == 1
        assert path.read_bytes() == before
        assert events[0]["status"] == "failed"

    def test_truncated_summary_is_never_accepted_with_budget_remaining(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        session_key = "agent:summary-truncated:demo"
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content="old " * 200),
                ChatMessage(role="user", content="keep verbatim"),
            ],
        )
        original_messages = [
            message.model_dump(by_alias=True) for message in load_session(session_key).messages
        ]
        backend = _SizedBackend(
            [
                _truncated(
                    "partial summary must never become durable",
                    usage=TokenUsage(input_tokens=4, output_tokens=1),
                ),
                _final("task completion must not be called"),
            ],
            estimate=5,
        )

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "must not be appended",
            config=_loop.LoopConfig(history_budget_tokens=1, token_budget=100, max_tokens=5),
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == "invalid_output"
        assert result.usage == TokenUsage(input_tokens=4, output_tokens=1)
        assert len(backend.calls) == 1
        stored = load_session(session_key)
        assert [
            message.model_dump(by_alias=True) for message in stored.messages
        ] == original_messages
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
        append_session_messages(
            session_key,
            [
                ChatMessage(role="user", content="old " * 200),
                ChatMessage(role="user", content="keep verbatim"),
            ],
        )
        original_messages = [
            message.model_dump(by_alias=True) for message in load_session(session_key).messages
        ]
        usage = TokenUsage(input_tokens=25, output_tokens=5)
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
        backend = _SizedBackend([response], estimate=5)

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "must not be appended",
            config=_loop.LoopConfig(history_budget_tokens=1, token_budget=20, max_tokens=5),
        )

        assert not result.ok
        assert result.stop_reason == "compaction_failed"
        assert result.failure_kind == expected_failure_kind
        assert result.usage == usage
        assert len(backend.calls) == 1
        stored = load_session(session_key)
        assert [
            message.model_dump(by_alias=True) for message in stored.messages
        ] == original_messages
        assert stored.usage.input_tokens == 25
        assert stored.usage.output_tokens == 5
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
