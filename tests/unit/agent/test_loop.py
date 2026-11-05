"""Phase functions extracted from `run_agent_turn` (`agent/loop.py`).

Each function here is pure and module-level, unlike the loop's stateful
nested closures, so it is exercised directly instead of only end to end.
The full turn is still `tests/integration/test_agent_loop.py`'s job.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.support import llm as _support_llm
from tests.support.loop_harness import ScriptedBackend, _echo_rounds, _final

from docket.agent import loop as _loop
from docket.agent.ports import (
    BudgetStop,
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    assistant,
)
from docket.agent.session import load_session
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry, ToolResult
from docket.kernel.home import current_home, use_home

ctx = _support_llm.ctx

SUBJECT = "docket.agent.loop"


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    """A registry with one read tool and one write tool, enough to prove narrowing."""
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
    reg.register(
        _Tool(
            name="write",
            description="Write a file.",
            parameters={"type": "object", "properties": {}},
            handler=lambda args, ctx: ToolOutcome(ok=True, content=""),
            kind="write",
        )
    )
    return reg


class _FakeBoundsBackend:
    """Reports fixed window/output attributes; `complete` is never called here."""

    def __init__(self, context_window_tokens: object, max_output_tokens: object) -> None:
        self.context_window_tokens = context_window_tokens
        self.max_output_tokens = max_output_tokens

    def complete(self, *args: object, **kwargs: object) -> ChatResponse:
        raise AssertionError("this fake only exercises attribute resolution")


# ── _resolve_context_bounds ──────────────────────────────────────────────────


class TestResolveContextBounds:
    """Config wins; a backend value only fills a gap the config leaves unset."""

    def test_config_values_win_over_the_backend(self) -> None:
        """An explicit LoopConfig bound is never overridden by the backend."""
        backend = _FakeBoundsBackend(context_window_tokens=999, max_output_tokens=999)
        cfg = _loop.LoopConfig(context_window_tokens=1_000, max_tokens=200)
        window, reserve, max_tokens = _loop._resolve_context_bounds(backend, cfg)
        assert (window, reserve, max_tokens) == (1_000, 200, 200)

    def test_backend_fills_an_unset_config_value(self) -> None:
        """An unset LoopConfig bound is filled from the backend's own report."""
        backend = _FakeBoundsBackend(context_window_tokens=1_000, max_output_tokens=200)
        cfg = _loop.LoopConfig()
        window, reserve, max_tokens = _loop._resolve_context_bounds(backend, cfg)
        assert (window, reserve, max_tokens) == (1_000, 200, 200)

    def test_non_positive_or_missing_backend_values_are_ignored(self) -> None:
        """A non-positive or absent backend value never fills the gap; the reserve defaults."""
        backend = _FakeBoundsBackend(context_window_tokens=0, max_output_tokens=-5)
        cfg = _loop.LoopConfig()
        window, reserve, max_tokens = _loop._resolve_context_bounds(backend, cfg)
        assert (window, reserve, max_tokens) == (
            None,
            current_home().default_max_output_tokens,
            None,
        )

    def test_an_unbounded_backend_reserves_the_default_without_sending_a_limit(self) -> None:
        """No registered output bound means a positive reserve and no request max_tokens."""
        backend = _FakeBoundsBackend(context_window_tokens=8_000, max_output_tokens=None)
        _window, reserve, max_tokens = _loop._resolve_context_bounds(backend, _loop.LoopConfig())
        assert reserve == current_home().default_max_output_tokens > 0
        assert max_tokens is None


# ── _resolve_trace_coordinates ───────────────────────────────────────────────


class TestResolveTraceCoordinates:
    """Explicit overrides win, then `ctx`, then the durable session key."""

    def test_explicit_overrides_win(self, ctx: ToolContext) -> None:
        """An explicit trace project/key is never replaced by a fallback."""
        project, trace_key = _loop._resolve_trace_coordinates(
            ctx, "agent:demo:default", "explicit-project", "explicit-key"
        )
        assert (project, trace_key) == ("explicit-project", "explicit-key")

    def test_falls_back_to_ctx_project_then_session_key(self, ctx: ToolContext) -> None:
        """With no override, project comes from ctx and trace_key from session_key."""
        project, trace_key = _loop._resolve_trace_coordinates(ctx, "agent:demo:default", None, None)
        assert (project, trace_key) == (ctx.project, "agent:demo:default")

    def test_falls_back_to_agent_id_when_ctx_project_is_unset(self, tmp_path: Path) -> None:
        """With no ctx.project either, the agent id is the last fallback."""
        bare_ctx = ToolContext(agent_id="bare-agent", roots=(tmp_path,), timeout=10)
        project, _ = _loop._resolve_trace_coordinates(bare_ctx, "agent:bare:default", None, None)
        assert project == "bare-agent"


# ── _resolve_role_registry_and_prompt ────────────────────────────────────────


class TestResolveRoleRegistryAndPrompt:
    """Narrows the registry by role, then composes today's system prompt."""

    def test_narrows_the_registry_to_the_role_and_returns_matching_specs(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """A role's denied_tools drops that tool from the returned specs."""
        reviewer_ctx = ToolContext(
            agent_id=ctx.agent_id, role="reviewer", project=ctx.project, roots=ctx.roots, timeout=10
        )
        narrowed, _composition, specs = _loop._resolve_role_registry_and_prompt(
            registry, reviewer_ctx, _loop.LoopConfig()
        )
        names = {spec.name for spec in specs}
        assert "write" not in names
        assert "echo" in names
        assert specs == narrowed.specs()

    def test_a_role_with_no_denials_keeps_every_tool(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """implementer denies nothing, so both registered tools survive."""
        _narrowed, _composition, specs = _loop._resolve_role_registry_and_prompt(
            registry, ctx, _loop.LoopConfig()
        )
        assert {spec.name for spec in specs} == {"echo", "write"}

    def test_prompt_is_empty_for_an_unprovisioned_agent(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """No workspace/identity files means a fail-open empty prompt, not an error."""
        _narrowed, composition, _specs = _loop._resolve_role_registry_and_prompt(
            registry, ctx, _loop.LoopConfig()
        )
        assert composition.text == ""
        assert composition.sections == ()


class TestApprovalParkedError:
    """``approval_parked_error`` owns the wire format the way
    ``approval_unavailable_error`` owns its own -- one function, one format."""

    def test_renders_every_field_in_the_shared_key_value_shape(self) -> None:
        result = ToolResult(
            ok=False,
            tool="bash",
            call_id="call-1",
            decision="deny",
            denial_kind="approval_parked",
            reason="require_approval",
            policy_id="test-ask-echo",
            approval_token="apr-abc123",
        )
        rendered = _loop.approval_parked_error(result)
        assert rendered == (
            "approval_parked: tool='bash' call_id='call-1' policy_id='test-ask-echo' "
            "reason='require_approval' approval_token='apr-abc123'"
        )


def test_the_loop_bounds_default_to_the_current_home(tmp_path: Path) -> None:
    """The defaults are read when a LoopConfig is built, not when the module is imported."""
    tuned = dataclasses.replace(
        current_home(),
        agent_loop_max_iterations=7,
        agent_loop_max_tool_calls=8,
        agent_loop_max_consecutive_tool_denials=9,
        agent_loop_no_progress_rounds=10,
        agent_loop_wall_clock_timeout_s=11.5,
        agent_loop_token_budget=12,
        agent_loop_request_timeout_s=13,
    )
    with use_home(tuned):
        config = _loop.LoopConfig()
    assert (
        config.max_iterations,
        config.max_tool_calls,
        config.max_consecutive_tool_denials,
        config.no_progress_rounds,
        config.wall_clock_timeout_s,
        config.token_budget,
        config.request_timeout_s,
    ) == (7, 8, 9, 10, 11.5, 12, 13)
    assert _loop.LoopConfig().max_iterations == current_home().agent_loop_max_iterations


# ── the landing and the notice ───────────────────────────────────────────────


class _TimedBackend(ScriptedBackend):
    """A scripted backend that advances a fake clock per call and records each request timeout."""

    def __init__(self, responses: list[ChatResponse], clock: list[float], step: float) -> None:
        super().__init__(responses)
        self.clock, self.step = clock, step
        self.timeouts: list[int] = []

    def complete(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        self.timeouts.append(kwargs["timeout"])
        self.clock[0] += self.step
        return super().complete(messages, **kwargs)


def _stored(session_key: str) -> list[ChatMessage]:
    return load_session(session_key).messages


class TestTheLanding:
    """A bound that would stop the turn makes one tool-free report request instead."""

    def test_the_round_bound_lands_with_a_report_that_is_never_a_success(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """Three rounds, then one tool-free request that names the rounds; its text is the output."""
        backend = ScriptedBackend([*_echo_rounds(3), _final("done: A; left: B; checks not run")])
        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:land-rounds:default", "go",
            config=_loop.LoopConfig(max_iterations=3, max_tool_calls=100),
        )  # fmt: skip
        assert len(backend.calls) == 4
        assert backend.tool_specs[3] == []
        assert backend.calls[3][-1].role == "user" and "rounds" in backend.calls[3][-1].content
        assert (result.ok, result.stop_reason, result.failure_kind) == (
            False,
            "max_iterations",
            "budget_exhausted",
        )
        assert result.output == "done: A; left: B; checks not run"
        assert result.budget_stop == BudgetStop("rounds", 3, 3, "default")
        stored = _stored("agent:land-rounds:default")
        assert stored[-1].role == "assistant" and stored[-1].content == result.output
        assert not any("rounds" in m.content and m.role == "user" for m in stored[1:])

    def test_a_refused_batch_lands_without_persisting_the_batch(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """A batch over the call cap is refused whole; the next request is the tool-free landing."""
        over = ChatResponse(
            ok=True,
            message=assistant(
                "",
                tool_calls=[ToolCall(id=f"b{n}", name="echo", arguments='{"text":"x"}') for n in range(3)],
            ),
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )  # fmt: skip
        backend = ScriptedBackend([_echo_rounds(1)[0], over, _final("kept one call")])
        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:land-calls:default", "go",
            config=_loop.LoopConfig(max_tool_calls=2),
        )  # fmt: skip
        assert backend.tool_specs[2] == [] and "tool calls" in backend.calls[2][-1].content
        assert (result.ok, result.stop_reason, result.output) == (
            False,
            "max_tool_calls",
            "kept one call",
        )
        assert result.tool_calls_executed == 1
        roles = [m.role for m in _stored("agent:land-calls:default")]
        assert roles == ["user", "assistant", "tool", "assistant"]

    def test_the_spent_clock_lands_with_a_grace_request_of_its_own_timeout(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """When the wall clock has run out, the landing is a tool-free request capped at 60 s."""
        clock = [0.0]
        backend = _TimedBackend([*_echo_rounds(2), _final("out of time")], clock, 60.0)
        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:land-time:default", "go",
            config=_loop.LoopConfig(wall_clock_timeout_s=100, request_timeout_s=300),
            clock=lambda: clock[0],
        )  # fmt: skip
        assert backend.tool_specs[2] == [] and "time" in backend.calls[2][-1].content
        assert backend.timeouts[2] == 60
        assert (result.ok, result.stop_reason, result.output) == (False, "timeout", "out of time")
        assert result.budget_stop is not None and result.budget_stop.bound == "time"

    def test_a_landing_that_asks_for_a_tool_is_a_hard_stop(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """Tools in the landing answer are never dispatched or persisted; the bound stays the reason."""
        backend = ScriptedBackend(_echo_rounds(3))
        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:land-tools:default", "go",
            config=_loop.LoopConfig(max_iterations=2),
        )  # fmt: skip
        assert (result.ok, result.stop_reason, result.failure_kind) == (
            False,
            "max_iterations",
            "budget_exhausted",
        )
        assert result.tool_calls_executed == 2 and len(backend.calls) == 3


class TestTheNotice:
    """The first time a bound has a quarter or less left is traced once."""

    def test_it_is_traced_once_as_a_budget_warning_notice(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """The trace holds one budget_warning with action notice and the figures, no content."""
        backend = ScriptedBackend([*_echo_rounds(8), _final("report")])
        _loop.run_agent_turn(
            backend, registry, ctx, "agent:notice-trace:default", "go",
            config=_loop.LoopConfig(max_iterations=8, max_tool_calls=100),
            trace_project="notice-audit", trace_session_key="notice-trace",
        )  # fmt: skip
        trace = current_home().traces_dir / "notice-audit" / "notice-trace.jsonl"
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        notices = [
            e["payload"]
            for e in events
            if e["event_type"] == "budget_warning" and e["payload"].get("action") == "notice"
        ]
        assert len(notices) == 1
        assert notices[0]["bounds"] == [{"bound": "rounds", "left": 2, "limit": 8}]


# ── transport retries ────────────────────────────────────────────────────────


def _failed(
    kind: str, error: str = "endpoint stalled", retry_after_s: float | None = None
) -> ChatResponse:
    return ChatResponse(
        ok=False,
        error=error,
        failure_kind=kind,  # type: ignore[arg-type]
        retry_after_s=retry_after_s,
    )


def _retry_events(project: str, key: str) -> list[dict[str, Any]]:
    trace = current_home().traces_dir / project / f"{key}.jsonl"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    return [e["payload"] for e in events if e["event_type"] == "request_retry"]


class TestTransportRetries:
    """A transient failure resends the same request inside the turn, up to the config's count."""

    def _turn(
        self,
        backend: ScriptedBackend,
        registry: ToolRegistry,
        ctx: ToolContext,
        key: str,
        sleeps: list[float],
        **cfg: Any,
    ) -> _loop.AgentLoopResult:
        return _loop.run_agent_turn(
            backend, registry, ctx, f"agent:{key}:default", "go",
            config=_loop.LoopConfig(**cfg), sleep=sleeps.append,
            trace_project="retry-audit", trace_session_key=key,
        )  # fmt: skip

    def test_a_timeout_then_an_answer_finishes_the_turn_with_one_retry(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """The failed request leaves nothing in the session and the same messages are sent again."""
        backend = ScriptedBackend([_failed("timeout"), _final("all done")])
        sleeps: list[float] = []
        result = self._turn(backend, registry, ctx, "retry-ok", sleeps, request_retries=2)
        assert (result.ok, result.output, result.request_retries) == (True, "all done", 1)
        assert backend.calls[0] == backend.calls[1] and len(backend.calls) == 2
        assert [m.role for m in _stored("agent:retry-ok:default")] == ["user", "assistant"]
        assert sleeps == [2.0]
        retries = _retry_events("retry-audit", "retry-ok")
        assert retries == [
            {
                "attempt": 1,
                "retries": 2,
                "failureKind": "timeout",
                "error": "endpoint stalled",
                "retryAfterS": None,
            }
        ]

    def test_retries_that_run_out_end_the_turn_with_the_failure_after_a_linear_backoff(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """Three requests, two waits of 2 s and 4 s, then the backend_error stop keeps the kind."""
        backend = ScriptedBackend([_failed("timeout")] * 3)
        sleeps: list[float] = []
        result = self._turn(backend, registry, ctx, "retry-out", sleeps, request_retries=2)
        assert len(backend.calls) == 3 and sleeps == [2.0, 4.0]
        assert (result.ok, result.failure_kind, result.stop_reason) == (
            False,
            "timeout",
            "backend_error",
        )
        assert result.request_retries == 2

    def test_an_endpoint_retry_after_sets_the_wait_when_it_is_longer(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """A daemon_error naming Retry-After 5 sleeps 5 s, and the event says so."""
        backend = ScriptedBackend([_failed("daemon_error", retry_after_s=5.0), _final()])
        sleeps: list[float] = []
        result = self._turn(backend, registry, ctx, "retry-after", sleeps, request_retries=1)
        assert result.ok and sleeps == [5.0]
        assert _retry_events("retry-audit", "retry-after")[0]["retryAfterS"] == 5.0

    def test_a_response_that_arrived_is_never_retried(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """invalid_output is an answer: one request, no wait, no retry event."""
        backend = ScriptedBackend([_failed("invalid_output"), _final()])
        sleeps: list[float] = []
        result = self._turn(backend, registry, ctx, "retry-none", sleeps, request_retries=2)
        assert (result.ok, result.failure_kind, result.request_retries) == (
            False,
            "invalid_output",
            0,
        )
        assert len(backend.calls) == 1 and sleeps == []

    def test_a_turn_with_no_retry_count_sends_each_request_once(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """The config default is zero: a caller that sets nothing keeps the old single try."""
        backend = ScriptedBackend([_failed("daemon_error"), _final()])
        sleeps: list[float] = []
        result = self._turn(backend, registry, ctx, "retry-default", sleeps)
        assert (result.ok, result.failure_kind) == (False, "daemon_error")
        assert len(backend.calls) == 1 and sleeps == []

    def test_a_retry_whose_wait_does_not_fit_in_the_clock_left_is_not_made(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """With 3 s of clock, the 2 s wait fits and the 4 s one does not."""
        backend = ScriptedBackend([_failed("daemon_error")] * 3)
        sleeps: list[float] = []
        result = self._turn(
            backend, registry, ctx, "retry-fit", sleeps, request_retries=2, wall_clock_timeout_s=3
        )
        assert len(backend.calls) == 2 and sleeps == [2.0]
        assert (result.failure_kind, result.request_retries) == ("daemon_error", 1)

    def test_a_request_that_timed_out_on_the_clock_left_ends_the_turn_and_is_not_retried(
        self, registry: ToolRegistry, ctx: ToolContext
    ) -> None:
        """Cut to the 3 s left, the stall is the wall clock: a time budget stop, never a retry."""
        clock = [7.0]
        backend = ScriptedBackend([_failed("timeout"), _final()])
        sleeps: list[float] = []
        result = _loop.run_agent_turn(
            backend, registry, ctx, "agent:retry-clock:default", "go",
            config=_loop.LoopConfig(wall_clock_timeout_s=10, request_retries=2),
            clock=lambda: clock[0], sleep=sleeps.append,
        )  # fmt: skip
        assert len(backend.calls) == 1 and sleeps == []
        assert (result.ok, result.stop_reason, result.failure_kind) == (
            False,
            "timeout",
            "budget_exhausted",
        )
        assert result.budget_stop is not None and result.budget_stop.bound == "time"
