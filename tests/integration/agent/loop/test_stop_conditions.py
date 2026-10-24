"""The turn loop's stop conditions: every bound is a deliberate, reported exit."""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.support.loop_harness import (
    ScriptedBackend,
    _final,
    _SizedBackend,
    _tool_call_response,
    _truncated,
    _write_gate_policy,
)

from docket.agent import loop as _loop
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
from docket.governance import approval as _approval
from docket.kernel.home import current_home

SUBJECT = "docket.agent.loop"


REPO_ROOT = Path(__file__).resolve().parents[4]


AGENT_LOOP_SRCS = sorted((REPO_ROOT / "src" / "docket" / "agent").glob("loop*.py"))


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


def _request_fits(ctx: ToolContext, session_key: str) -> list[dict[str, Any]]:
    tracefile = current_home().traces_dir / (ctx.project or ctx.agent_id) / f"{session_key}.jsonl"
    records = [json.loads(line) for line in tracefile.read_text().splitlines()]
    return [r["payload"] for r in records if r["event_type"] == "request_fit"]


class TestSingleExecutionPath:
    """Non-negotiable: a tool call bypassing `dispatch_tool` bypasses every guardrail the gate
    builds. Verified by walking agent_loop.py's own source, not by observing today's behaviour;
    confirmed red when a hand-patched direct-dispatch path replaced the real call."""

    def test_never_imports_toolbox_or_calls_a_handler_directly(self) -> None:
        tree = ast.parse("\n".join(src.read_text(encoding="utf-8") for src in AGENT_LOOP_SRCS))

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
        # The loop is split across agent/loop*.py; the single call site is counted over all of them.
        tree = ast.parse("\n".join(src.read_text(encoding="utf-8") for src in AGENT_LOOP_SRCS))

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "docket.agent.tools.registry":
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


class TestTruncatedResponses:
    """A truncated response must never have its tool calls executed -- the most dangerous
    failure mode this loop guards against, since partial arguments are exactly what a gate
    cannot evaluate."""

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
            max_iterations=1000,
            max_tool_calls=1000,
            wall_clock_timeout_s=5.0,
            no_progress_rounds=0,
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
        backend.max_output_tokens = 1  # type: ignore[attr-defined]
        backend.estimate_input_tokens = lambda messages, **kwargs: 10  # type: ignore[attr-defined]
        config = _loop.LoopConfig(max_iterations=1000, max_tool_calls=1000, token_budget=44)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is False
        assert result.stop_reason == "token_budget"
        assert result.failure_kind == "invalid_output"
        assert result.usage.total_tokens > 44
        assert (
            backend.call_count == 3
        )  # the prospective estimate was tiny; the measured guard fires

    def test_a_known_output_cap_above_the_budget_is_cut_to_what_the_budget_leaves(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """An observed 128k cap never refuses a 10k-budget hop; the request sends what is left."""
        backend = ScriptedBackend([_final()])
        backend.max_output_tokens = 128_000  # type: ignore[attr-defined]
        backend.estimate_input_tokens = lambda messages, **kwargs: 10  # type: ignore[attr-defined]
        sent: list[int | None] = []
        scripted_complete = backend.complete

        def complete(messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
            sent.append(kwargs.get("max_tokens"))
            return scripted_complete(messages, **kwargs)

        backend.complete = complete  # type: ignore[method-assign]
        config = _loop.LoopConfig(token_budget=10_000)

        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:demo:default", "go", config=config
        )

        assert result.ok is True, result.error
        assert sent == [10_000 - 10]

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


class TestApprovalUnavailable:
    def test_refuse_mode_stops_the_turn_immediately_with_a_typed_result(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """A call gated to `ask` under `approval_mode="refuse"` ends the turn
        on its own -- not folded into the consecutive-denial count -- with no
        second backend request and a session unit carrying the refusal."""
        _write_gate_policy("test-ask-echo", r"\becho\b", "require_approval")
        ctx.approval_mode = "refuse"
        backend = ScriptedBackend(
            [
                _tool_call_response("call-1", "echo", '{"text": "hello"}'),
                _final("must not be requested"),
            ]
        )
        session_key = "agent:demo:approval-unavailable"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.ok is False
        assert result.stop_reason == "approval_unavailable"
        assert result.failure_kind == "invalid_output"
        assert len(backend.calls) == 1  # no second request was made
        assert "echo" in result.error
        assert "call-1" in result.error
        assert "test-ask-echo" in result.error
        record = load_session(session_key)
        assert [message.role for message in record.messages] == ["user", "assistant", "tool"]
        assert "REFUSED [approval_unavailable]" in record.messages[-1].content

    # The specificity proof: only approval_unavailable is immediately terminal
    # under refuse mode. gate_denied and invalid_call stay recoverable and
    # bounded only by max_consecutive_tool_denials, exactly as under "wait" --
    # lowering that limit instead would also make these terminal, which is
    # the shortcut this test rules out.
    def test_refuse_mode_still_bounds_gate_denied_and_invalid_call_by_the_existing_limit(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """gate_denied/invalid_call remain recoverable under refuse mode."""
        _write_gate_policy("test-block-echo", r"blocked-arg", "block")
        ctx.approval_mode = "refuse"
        backend = ScriptedBackend(
            [
                _tool_call_response("bad-1", "missing-tool", "{}"),
                _tool_call_response("deny-1", "echo", '{"text": "blocked-arg"}'),
                _tool_call_response("bad-2", "missing-tool", "{}"),
                _final("must not be requested"),
            ]
        )
        session_key = "agent:demo:refuse-specificity"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.stop_reason == "tool_denials"
        assert result.failure_kind == "invalid_output"
        assert len(backend.calls) == 3  # stopped at the denial limit, the final() was never sent
        assert "invalid_call" in result.error
        assert "gate_denied" in result.error


class TestApprovalParked:
    def test_park_mode_stops_the_turn_immediately_with_a_typed_result(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        """A call gated to `ask` under `approval_mode="park"` ends the turn on its
        own, recording the call rather than waiting on it or refusing it outright."""
        _write_gate_policy("test-ask-echo", r"\becho\b", "require_approval")
        ctx.approval_mode = "park"
        backend = ScriptedBackend(
            [
                _tool_call_response("call-1", "echo", '{"text": "hello"}'),
                _final("must not be requested"),
            ]
        )
        session_key = "agent:demo:approval-parked"

        result = _loop.run_agent_turn(backend, registry, ctx, session_key, "go")

        assert result.ok is False
        assert result.stop_reason == "approval_parked"
        assert result.failure_kind == "invalid_output"
        assert len(backend.calls) == 1  # no second request was made
        assert "echo" in result.error
        assert "call-1" in result.error
        assert "test-ask-echo" in result.error
        assert "approval_token=" in result.error
        pending = _approval.list_pending()
        assert len(pending) == 1
        record = load_session(session_key)
        assert [message.role for message in record.messages] == ["user", "assistant", "tool"]
        assert "REFUSED [approval_parked]" in record.messages[-1].content


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


class TestCountedTokenBudget:
    def test_cache_reads_do_not_count_against_the_budget(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        cached = TokenUsage(input_tokens=12_000, cached_tokens=10_000, output_tokens=50)
        backend = _SizedBackend(
            [
                _tool_call_response("c1", "echo", '{"text": "a"}', cached),
                _tool_call_response("c2", "echo", '{"text": "b"}', cached),
                _tool_call_response("c3", "echo", '{"text": "c"}', cached),
                _final("done", cached),
            ],
            estimate=12_000,
        )

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            "agent:counted-cache:default",
            "work",
            config=_loop.LoopConfig(token_budget=30_000),
        )

        assert result.ok, result.error
        assert len(backend.calls) == 4
        assert result.usage.counted_tokens == 4 * 2_050

    def test_a_final_reply_that_crosses_the_budget_is_kept(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = _SizedBackend(
            [
                _tool_call_response("c1", "echo", '{"text": "a"}', TokenUsage(10, 5)),
                _final("the answer", TokenUsage(input_tokens=200, output_tokens=50)),
            ],
            estimate=20,
            max_output=10,
        )
        session_key = "agent:counted-final:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "work",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert result.ok, result.error
        assert result.stop_reason == "final_message"
        assert result.output == "the answer"
        assert result.usage.counted_tokens > 100
        assert load_session(session_key).messages[-1].content == "the answer"

    def test_a_tool_calling_reply_that_crosses_the_budget_is_still_refused(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = _SizedBackend(
            [
                _tool_call_response("c1", "echo", '{"text": "a"}', TokenUsage(10, 5)),
                _tool_call_response("c2", "echo", '{"text": "b"}', TokenUsage(200, 50)),
            ],
            estimate=20,
            max_output=10,
        )
        session_key = "agent:counted-tools:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "work",
            config=_loop.LoopConfig(token_budget=100, max_tokens=10),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert [m.role for m in load_session(session_key).messages] == ["user", "assistant", "tool"]

    def test_a_backend_without_an_output_bound_reserves_the_default(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = _SizedBackend([_final()], estimate=50, window=100_000)
        session_key = "agent:counted-reserve:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "work",
            config=_loop.LoopConfig(token_budget=current_home().default_max_output_tokens - 1),
        )

        assert not result.ok
        assert result.stop_reason == "token_budget"
        assert "no backend call made" in result.error
        assert not backend.calls
        fits = _request_fits(ctx, session_key)
        assert fits
        assert {fit["outputReserveTokens"] for fit in fits} == {
            current_home().default_max_output_tokens
        }

    def test_the_estimate_is_scaled_by_the_first_measured_call(
        self, ctx: ToolContext, registry: ToolRegistry
    ) -> None:
        backend = _SizedBackend(
            [
                _tool_call_response("c1", "echo", '{"text": "a"}', TokenUsage(400, 5)),
                _tool_call_response("c2", "echo", '{"text": "b"}', TokenUsage(40, 5)),
                _final("done", TokenUsage(40, 5)),
            ],
            estimate=100,
            window=100_000,
            max_output=10,
        )
        session_key = "agent:counted-calibration:default"

        result = _loop.run_agent_turn(
            backend,
            registry,
            ctx,
            session_key,
            "work",
            config=_loop.LoopConfig(max_tokens=10),
        )

        assert result.ok, result.error
        task_fits = [fit["estimatedInputTokens"] for fit in _request_fits(ctx, session_key)]
        assert task_fits == [100, 400, 100]
