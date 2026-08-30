"""The turn loop (`core/agent_loop.py`).

docket owns the loop, so what matters most here is that there is exactly one
path to tool execution and that every stop condition is a deliberate,
reported exit -- never a silent hang or a runaway loop. Covers, in order of
how much each one matters:

* **Single execution path** -- `run_agent_turn` never calls a tool handler
  except through `core.tools.dispatch_tool`; an architectural guard walks
  the module's own source to prove it.
* **Truncation safety** -- a length-truncated response carrying tool calls
  never has them dispatched, and is never persisted to session history.
* **All four stop conditions** -- final message, max_iterations,
  max_tool_calls, wall-clock timeout, token budget -- each independently
  triggerable and each reporting the right `stop_reason`/`failure_kind`.
* **Durability** -- history is persisted per iteration, not only at the end;
  a "crash" after N iterations leaves exactly N iterations on disk.
* **Tracing** -- every dispatched tool call emits a `tool_call` and a
  `tool_result` trace event.

No test here sleeps for real or hits the network: `ChatBackend` is a small
scripted fake, and wall-clock timeout tests inject a fake `clock`.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core import session as _session
from docket.core.llm import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.core.session import append_messages as append_session_messages
from docket.core.session import load_session
from docket.core.tools import Tool as _Tool
from docket.core.tools import ToolContext, ToolRegistry
from docket.edges.adapters.toolbox import ToolOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LOOP_SRC = REPO_ROOT / "src" / "docket" / "core" / "agent_loop.py"


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", tmp_path / "sessions", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", tmp_path / "traces", raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("alpha\nbeta\n")
    return ws


@pytest.fixture
def registry() -> ToolRegistry:
    """A tiny registry with one harmless read-only tool -- enough to exercise
    dispatch without pulling in bash/exec classification noise."""
    reg = ToolRegistry()
    reg.register(
        _Tool(
            name="echo",
            description="Echo the given text back.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args, ctx: ToolOutcome(ok=True, content=str(args.get("text", ""))),
            kind="read",
        )
    )
    return reg


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-agent", role="implementer", project="demo", roots=(workspace,), timeout=10
    )


# ── a small scripted ChatBackend ─────────────────────────────────────────────


class ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s, one per `complete()` call.

    Records every call's messages so tests can assert on what was actually
    sent (e.g. that tool results were fed back). Raises `AssertionError` if
    asked for more responses than scripted -- a test bug, not something a
    real backend would ever need to signal this way.
    """

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.tool_specs: list[list[ToolSpec]] = []

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
        if not self._responses:
            raise AssertionError("ScriptedBackend ran out of scripted responses")
        return self._responses.pop(0)


class InfiniteToolBackend:
    """Always asks for one more tool call -- the "confused model" bait used
    to prove the iteration/tool-call caps actually stop the loop."""

    def __init__(self, tool_name: str = "echo") -> None:
        self.tool_name = tool_name
        self.call_count = 0

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.call_count += 1
        call = ToolCall(
            id=f"call_{self.call_count}", name=self.tool_name, arguments='{"text": "x"}'
        )
        return ChatResponse(
            ok=True,
            message=assistant("", tool_calls=[call]),
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )


def _final(content: str = "done", usage: TokenUsage | None = None) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(content),
        finish_reason="stop",
        usage=usage or TokenUsage(input_tokens=5, output_tokens=5),
    )


def _tool_call_response(
    call_id: str, name: str, arguments: str, usage: TokenUsage | None = None
) -> ChatResponse:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=usage or TokenUsage(input_tokens=10, output_tokens=5),
    )


def _truncated(
    content: str = "",
    tool_calls: Sequence[ToolCall] = (),
    usage: TokenUsage | None = None,
) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(content, tool_calls=tool_calls),
        finish_reason="length",
        usage=usage or TokenUsage(input_tokens=10, output_tokens=5),
    )


# ── live session compaction ──────────────────────────────────────────────────


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
        assert not _session.find_orphaned_tool_messages(stored)
        assert not _session.find_unanswered_tool_calls(stored)
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
        assert not _session.find_orphaned_tool_messages(stored.messages)
        assert not _session.find_unanswered_tool_calls(stored.messages)

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

        real_compact_session = _loop.compact_session
        injected = False
        ranged_calls: list[tuple[int, int]] = []

        def _append_after_ranged_write(*args: Any, **kwargs: Any) -> _session.CompactionResult:
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

        monkeypatch.setattr(_loop, "compact_session", _append_after_ranged_write, raising=True)
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
        assert not _session.find_orphaned_tool_messages(stored.messages)
        assert not _session.find_unanswered_tool_calls(stored.messages)

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

        real_compact_session = _loop.compact_session
        ranged_calls: list[tuple[int, int]] = []

        def _append_after_every_ranged_write(
            *args: Any, **kwargs: Any
        ) -> _session.CompactionResult:
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
            _loop,
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
        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        fits = [
            json.loads(line)
            for line in tracefile.read_text().splitlines()
            if json.loads(line)["event_type"] == "request_fit"
        ]
        assert len(fits) == 10
        assert fits[-1]["payload"]["purpose"] == "task"
        assert fits[-1]["payload"]["status"] == "failed"

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
        self, registry: ToolRegistry, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
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

        monkeypatch.setattr(_loop, "trace_event", _trace, raising=True)
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
        assert not _session.find_orphaned_tool_messages(stored_messages)
        assert not _session.find_unanswered_tool_calls(stored_messages)
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
        self, registry: ToolRegistry, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
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
                timeout: int = 120,
            ) -> ChatResponse:
                if len(messages) == 1 and "compacting durable turn history" in messages[0].content:
                    self.summary_prompts.append(messages[0].content)
                    return _final(
                        f"bounded summary {len(self.summary_prompts)}",
                        TokenUsage(input_tokens=10, output_tokens=2),
                    )
                return _final("task done", TokenUsage(input_tokens=5, output_tokens=1))

        monkeypatch.setattr(_loop, "trace_event", _trace, raising=True)
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
        assert all(
            _session._context.estimate_tokens(prompt) <= 180 for prompt in backend.summary_prompts
        )
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
        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
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
        self, registry: ToolRegistry, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
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

        monkeypatch.setattr(_loop, "trace_event", _trace, raising=True)
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
        self, registry: ToolRegistry, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
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

        monkeypatch.setattr(_loop, "trace_event", _trace, raising=True)
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
            "must not be appended",
            config=_loop.LoopConfig(history_budget_tokens=1, token_budget=100),
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
        backend = ScriptedBackend([response])

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "must not be appended",
            config=_loop.LoopConfig(history_budget_tokens=1, token_budget=20),
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


# ── architectural guard: dispatch_tool is the only execution path ───────────


class TestSingleExecutionPath:
    """Non-negotiable: a tool call that bypasses dispatch_tool bypasses every
    guardrail the tool-call gate builds. Verified by walking agent_loop.py's
    own source, not just by observing today's behaviour.

    Proven RED before being trusted. Planted and reverted by hand while
    writing this test (not committed):
    temporarily replaced the `dispatch_tool(call, ctx, registry)` call with
    `tool = registry.get(call.name); tool.handler(call.parsed_arguments(), ctx)`
    -- a direct second path around the gate. This test went red (the
    forbidden `toolbox` import check and the "exactly one dispatch_tool call"
    count both fail against source that reaches for `.handler` directly),
    confirming it actually inspects behaviour that matters rather than always
    passing. Restored before committing.
    """

    def test_never_imports_toolbox_or_calls_a_handler_directly(self) -> None:
        tree = ast.parse(AGENT_LOOP_SRC.read_text(encoding="utf-8"))

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        assert not any("toolbox" in m for m in imported_modules), (
            f"agent_loop.py must not import the toolbox handlers directly: {imported_modules}"
        )

        handler_attr_accesses = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "handler"
        ]
        assert handler_attr_accesses == [], "agent_loop.py must never touch Tool.handler directly"

    def test_dispatch_tool_is_imported_and_is_the_only_call_of_its_name(self) -> None:
        tree = ast.parse(AGENT_LOOP_SRC.read_text(encoding="utf-8"))

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "docket.core.tools":
                imported_names.update(alias.asname or alias.name for alias in node.names)
        assert "dispatch_tool" in imported_names

        call_sites = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dispatch_tool"
        ]
        assert len(call_sites) == 1, "expected exactly one dispatch_tool(...) call site"

    def test_every_tool_call_actually_goes_through_dispatch_tool(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """Behavioural companion to the AST checks: a real turn's tool call
        produces a real dispatch_tool decision (recorded on the ToolResult
        fed back to the model), not a bypassed handler invocation."""
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.ok
        assert result.tool_calls_executed == 1
        # The tool result fed back to the model on the second call must be the
        # handler's real output ("hi"), proving dispatch_tool's execute step
        # ran (not a stubbed/skipped path).
        second_call_messages = backend.calls[1]
        tool_msg = next(m for m in second_call_messages if m.role == "tool")
        assert tool_msg.content == "hi"


# ── truncation safety ────────────────────────────────────────────────────────


class TestTruncatedResponses:
    """A truncated response must not have its tool calls executed (the card's
    requirement #3) -- the most dangerous failure mode this loop exists to
    prevent, since partial arguments are exactly what a gate cannot evaluate.
    """

    def test_truncated_with_tool_calls_never_dispatches_them(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        poison_call = ToolCall(id="c1", name="echo", arguments='{"text": "should not run"}')
        backend = ScriptedBackend([_truncated(tool_calls=[poison_call])])

        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")

        assert result.ok is False
        assert result.stop_reason == "truncated"
        assert result.failure_kind == "invalid_output"
        assert result.tool_calls_executed == 0

    def test_truncated_response_is_not_persisted_to_session(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        poison_call = ToolCall(id="c1", name="echo", arguments='{"text": "nope"}')
        backend = ScriptedBackend([_truncated(content="cut off mid-sen", tool_calls=[poison_call])])

        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        record = load_session(session_key)
        # Only the incoming user message should be durable -- the truncated
        # assistant reply (and its unexecuted tool call) must never land here.
        assert len(record.messages) == 1
        assert record.messages[0].role == "user"
        assert record.usage.input_tokens == 10
        assert record.usage.output_tokens == 5
        assert record.usage.turns == 1

    def test_truncated_with_no_tool_calls_is_still_reported_as_truncated(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """Truncation is checked uniformly, before ever looking at tool_calls
        -- a plain truncated reply is just as much "not a real answer" as one
        carrying a partial tool call."""
        backend = ScriptedBackend([_truncated(content="ran out of ro")])
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.stop_reason == "truncated"
        assert result.ok is False


# ── stop conditions ───────────────────────────────────────────────────────────


class TestStopConditions:
    def test_final_message_with_no_tool_calls_succeeds(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = ScriptedBackend([_final("all done")])
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.ok is True
        assert result.stop_reason == "final_message"
        assert result.output == "all done"
        assert result.failure_kind is None
        assert result.iterations == 1

    def test_max_iterations_stops_a_model_that_never_finishes(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()
        config = _loop.LoopConfig(max_iterations=3, max_tool_calls=1000)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "max_iterations"
        assert result.failure_kind == "invalid_output"
        # Exactly 3 calls were made -- not 4, not unbounded. This is the
        # numeric assertion that makes the guard meaningful: a config change
        # that silently allowed one extra iteration would fail this.
        assert backend.call_count == 3

    def test_max_tool_calls_stops_before_dispatching_an_over_budget_batch(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()
        config = _loop.LoopConfig(max_iterations=1000, max_tool_calls=2)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "max_tool_calls"
        assert result.tool_calls_executed == 2

    def test_max_tool_calls_never_dispatches_a_partial_batch(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """A single response requesting more tool calls than remain in budget
        is rejected wholesale -- never partially dispatched, which would leave
        an orphaned tool_calls entry in session history."""
        calls = [ToolCall(id=f"c{i}", name="echo", arguments='{"text": "x"}') for i in range(5)]
        backend = ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=calls),
                    finish_reason="tool_calls",
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                )
            ]
        )
        config = _loop.LoopConfig(max_tool_calls=3)
        session_key = "agent:demo:default"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go", config=config)

        assert result.ok is False
        assert result.stop_reason == "max_tool_calls"
        assert result.tool_calls_executed == 0
        record = load_session(session_key)
        assert len(record.messages) == 1  # only the user turn; nothing orphaned

    def test_allowed_executed_call_resets_consecutive_tool_denials(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        private_sentinel = "PRIVATE_ARGUMENT_SENTINEL"
        denied = lambda call_id: _tool_call_response(  # noqa: E731
            call_id,
            f"missing-{private_sentinel}",
            "{}",
        )
        backend = ScriptedBackend(
            [
                denied("deny-1"),
                _tool_call_response("allow-1", "echo", '{"text": "recovered"}'),
                denied("deny-2"),
                denied("deny-3"),
                denied("deny-4"),
                _final("must not be requested"),
            ]
        )
        session_key = "agent:demo:denial-reset"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.ok is False
        assert result.stop_reason == "tool_denials"
        assert result.failure_kind == "invalid_output"
        assert len(backend.calls) == 5
        assert result.tool_calls_executed == 5
        assert "count=3" in result.error
        assert "invalid_call,invalid_call,invalid_call" in result.error
        assert private_sentinel not in result.error
        record = load_session(session_key)
        assert [message.role for message in record.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
            "tool",
            "assistant",
            "tool",
        ]
        assert record.usage.input_tokens + record.usage.output_tokens == 75

    def test_tool_denial_limit_persists_the_whole_returned_batch(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        calls = [
            ToolCall(id=f"deny-{index}", name="missing", arguments="{}") for index in range(1, 4)
        ]
        backend = ScriptedBackend(
            [
                ChatResponse(
                    ok=True,
                    message=assistant("", tool_calls=calls),
                    finish_reason="tool_calls",
                    usage=TokenUsage(30, 6),
                ),
                _final("must not be requested"),
            ]
        )
        session_key = "agent:demo:denial-batch"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.stop_reason == "tool_denials"
        assert len(backend.calls) == 1
        assert result.tool_calls_executed == 3
        record = load_session(session_key)
        assert [message.role for message in record.messages] == [
            "user",
            "assistant",
            "tool",
            "tool",
            "tool",
        ]
        assert record.usage.input_tokens + record.usage.output_tokens == 36

    def test_wall_clock_timeout_stops_without_real_sleep(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()
        config = _loop.LoopConfig(
            max_iterations=1000, max_tool_calls=1000, wall_clock_timeout_s=5.0
        )
        # A fake clock: 0, 1, 2, 3, ... seconds per call -- crosses the 5s
        # budget on the 6th check without any real time passing.
        ticks = iter(range(0, 100))

        def fake_clock() -> float:
            return float(next(ticks))

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config, clock=fake_clock
        )

        assert result.ok is False
        assert result.stop_reason == "timeout"
        assert result.failure_kind == "timeout"

    def test_token_budget_stops_a_turn_that_keeps_spending(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = InfiniteToolBackend()  # 15 tokens (10 in + 5 out) per iteration
        config = _loop.LoopConfig(max_iterations=1000, max_tool_calls=1000, token_budget=40)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "token_budget"
        assert result.failure_kind == "invalid_output"
        assert result.usage.total_tokens > 40
        assert backend.call_count == 3  # no invented prospective reserve when max_tokens is unknown

    def test_backend_error_is_reported_with_its_own_failure_kind(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = ScriptedBackend(
            [ChatResponse(ok=False, error="endpoint unreachable", failure_kind="daemon_error")]
        )
        result = _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go")
        assert result.ok is False
        assert result.stop_reason == "backend_error"
        assert result.failure_kind == "daemon_error"
        assert result.error == "endpoint unreachable"


# ── cumulative-budget terminal response reservation ─────────────────────────


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
            message.role == "system" and "terminal response" in message.content.lower()
            for message in backend.calls[1]
        )
        stored = load_session(session_key)
        assert [message.role for message in stored.messages] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        tracefile = _cfg.TRACES_DIR / "budget-audit" / "task-budget-finalize.jsonl"
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
            "normalEstimatedInputTokens": 25,
            "finalizationEstimatedInputTokens": 10,
            "outputReserveTokens": 10,
            "normalProspectiveTokens": 35,
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
                    message.role == "system" and "terminal response" in message.content.lower()
                    for message in messages
                ):
                    return 5
                if any(message.role == "tool" for message in messages):
                    return 150
                if any(
                    message.content.startswith("[compacted summary of ") for message in messages
                ):
                    return 90
                return 20

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
                    message.role == "system" and "terminal response" in message.content.lower()
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
        assert not _session.find_orphaned_tool_messages(stored.messages)
        assert not _session.find_unanswered_tool_calls(stored.messages)

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
        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
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
        assert not _session.find_unanswered_tool_calls(stored.messages)

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
        assert not _session.find_unanswered_tool_calls(stored.messages)

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
        assert not _session.find_unanswered_tool_calls(stored.messages)

    @pytest.mark.parametrize("failure_kind", ["timeout", "daemon_error"])
    def test_finalization_timeout_or_backend_error_is_fail_closed(
        self, ctx: ToolContext, registry: ToolRegistry, failure_kind: str
    ) -> None:
        backend = self._backend(
            _tool_call_response(
                "c1", "echo", '{"text": "validated"}', TokenUsage(input_tokens=65, output_tokens=5)
            ),
            ChatResponse(ok=False, error="finalization cancelled", failure_kind=failure_kind),
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
        assert not _session.find_unanswered_tool_calls(stored.messages)


# ── durability: persisted per iteration ──────────────────────────────────────


class TestDurability:
    def test_incoming_message_is_persisted_before_any_model_call(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend([_final("ok")])
        _loop.run_agent_turn(backend, registry, ctx, session_key, "please help")
        # Even inspecting mid-flight isn't possible from outside, but the
        # post-condition proves the user turn was written via append_messages
        # (not assembled only in memory and flushed once at the very end):
        # combined with test_max_tool_calls_never_dispatches_a_partial_batch
        # above (which stops immediately after the same one append), the
        # user message is confirmed present independent of how the turn ends.
        record = load_session(session_key)
        assert record.messages[0].role == "user"
        assert record.messages[0].content == "please help"

    def test_a_crash_after_n_iterations_loses_at_most_the_next_one(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """Simulates a crash: the backend raises on the 3rd call, standing in
        for a process death mid-loop. Iterations 1-2 (each a real tool round
        trip) must already be durable."""
        session_key = "agent:demo:default"

        class CrashingBackend:
            def __init__(self) -> None:
                self.n = 0

            def complete(
                self, messages, *, tools=(), max_tokens=None, temperature=None, timeout=120
            ):
                self.n += 1
                if self.n == 3:
                    raise RuntimeError("simulated crash")
                return _tool_call_response(f"c{self.n}", "echo", f'{{"text": "turn{self.n}"}}')

        backend = CrashingBackend()
        with pytest.raises(RuntimeError):
            _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        record = load_session(session_key)
        # user turn + 2 completed (assistant, tool) pairs = 5 messages.
        roles = [m.role for m in record.messages]
        assert roles == ["user", "assistant", "tool", "assistant", "tool"]


# ── tracing ───────────────────────────────────────────────────────────────────


class TestTracing:
    def test_trace_coordinate_can_differ_from_durable_history_coordinate(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        history_key = "agent:demo-agent:demo:task:t1:step:implementer"
        trace_key = "agent:demo:t1"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )

        _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            history_key,
            "go",
            trace_session_key=trace_key,
        )

        assert [m.role for m in _session.load_messages(history_key)] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        assert _session.load_messages(trace_key) == []
        assert not (_cfg.TRACES_DIR / "demo" / f"{history_key}.jsonl").exists()
        tracefile = _cfg.TRACES_DIR / "demo" / f"{trace_key}.jsonl"
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        assert all(record["session_id"] == trace_key for record in records)
        assert {record["event_type"] for record in records} >= {
            "session_compaction",
            "tool_call",
            "tool_result",
        }

    def test_every_dispatched_tool_call_emits_call_and_result_trace_events(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        assert tracefile.exists()
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        event_types = [r["event_type"] for r in records]
        assert [kind for kind in event_types if kind in {"tool_call", "tool_result"}] == [
            "tool_call",
            "tool_result",
        ]
        tool_records = [
            record for record in records if record["event_type"] in {"tool_call", "tool_result"}
        ]
        assert tool_records[0]["payload"]["tool"] == "echo"
        assert tool_records[1]["payload"]["decision"] == "allow"
        assert tool_records[1]["payload"]["executed"] is True

    def test_no_tool_calls_means_no_trace_events(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:demo:default"
        backend = ScriptedBackend([_final("no tools needed")])
        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        assert not [
            record for record in records if record["event_type"] in {"tool_call", "tool_result"}
        ]

    def test_request_fit_trace_is_registered_and_contains_only_estimates(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        session_key = "agent:fit-trace:default"
        backend = ScriptedBackend([_final("done")])

        _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
        records = [json.loads(line) for line in tracefile.read_text().splitlines()]
        fit = next(record["payload"] for record in records if record["event_type"] == "request_fit")
        assert fit["status"] == "unknown_window"
        assert fit["purpose"] == "task"
        assert fit["estimate"] is True
        assert "messages" not in fit and "prompt" not in fit and "usage" not in fit

    def test_trace_project_falls_back_to_agent_id_when_project_unset(
        self, workspace: Path, registry: ToolRegistry
    ) -> None:
        bare_ctx = ToolContext(agent_id="bare-agent", roots=(workspace,), timeout=10)
        session_key = "agent:bare:default"
        backend = ScriptedBackend(
            [_tool_call_response("c1", "echo", '{"text": "hi"}'), _final("ok")]
        )
        _loop.run_agent_turn(backend, registry, bare_ctx, session_key, "go")

        tracefile = _cfg.TRACES_DIR / "bare-agent" / f"{session_key}.jsonl"
        assert tracefile.exists()


# ── multi-turn history feeding ───────────────────────────────────────────────


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
