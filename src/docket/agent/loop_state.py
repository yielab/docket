"""The turn-scoped state shared by the turn loop and its collaborators.

``TurnState`` holds what more than one collaborator reads or writes: the resolved per-turn
constants, the running usage, the iteration and tool-call counters, and the last response's
identity. State only one collaborator touches (the progress detector, the compaction failure
marker) lives on that collaborator instead.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from docket.agent.loop_types import AgentLoopResult, LoopConfig, StopReason
from docket.agent.ports import (
    BudgetStop,
    CapabilityGap,
    ChatBackend,
    FailureKind,
    TokenUsage,
    ToolSpec,
)
from docket.agent.tools.registry import ToolContext, ToolRegistry


@dataclass
class TurnState:
    """Turn-scoped state threaded through ``run_agent_turn``'s phases as attributes."""

    backend: ChatBackend
    ctx: ToolContext
    session_key: str
    cfg: LoopConfig
    clock: Callable[[], float]
    started: float
    project: str
    trace_key: str
    context_window: int | None
    output_reserve: int
    request_max_tokens: int | None
    call_max_tokens: int | None
    registry: ToolRegistry
    system_prompt: str
    tool_specs: list[ToolSpec]

    # The ratio this turn's first task call measured over its raw estimate, for the driver to
    # record against the model (agent-loop.spec.md requirement 46a).
    first_call_ratio: float | None = None
    trace_task_id: str = ""
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    tool_calls_executed: int = 0
    iteration: int = 0
    last_raw: dict[str, Any] = field(default_factory=dict)
    last_model: str = ""
    last_provider: str = ""
    summary_usage: TokenUsage = field(default_factory=TokenUsage)
    accounted_summary_usage: TokenUsage = field(default_factory=TokenUsage)
    # The budget bound the turn lands on (stop reason and its message) and whether the one
    # notice before it has been sent (agent-loop.spec.md requirements 51-54, 108).
    landing: StopReason | None = None
    landing_error: str = ""
    notice_sent: bool = False
    # Transport retries made so far over the turn, and the wait before one (requirement 110).
    request_retries: int = 0
    sleep: Callable[[float], None] = time.sleep

    def land(self, stop_reason: StopReason, error: str) -> None:
        """Select *stop_reason* as the bound the turn lands on; the first bound reached wins."""
        if self.landing is None:
            self.landing, self.landing_error = stop_reason, error

    def landed(self, *, output: str = "", error: str = "") -> AgentLoopResult:
        """The turn's result once its landing is over: the bound's stop, never a success. *output*
        is the landing's report, kept as the hop's summary."""
        assert self.landing is not None
        return self.done(
            ok=False,
            stop_reason=self.landing,
            output=output,
            error=error or self.landing_error,
        )

    def done(
        self,
        *,
        ok: bool,
        stop_reason: StopReason,
        output: str = "",
        error: str = "",
        failure_kind: FailureKind | None = None,
        retry_after_s: float | None = None,
        closing_args: dict[str, Any] | None = None,
        capability_gap: CapabilityGap | None = None,
    ) -> AgentLoopResult:
        """The turn's result. A failed stop on a budget bound (rounds, tool calls, wall clock,
        tokens) is always ``budget_exhausted`` with its ``budget_stop``, whatever the caller passed."""
        budget_stop = None if ok else self.budget_stop_for(stop_reason)
        if budget_stop is not None:
            failure_kind = "budget_exhausted"
        return AgentLoopResult(
            ok=ok,
            output=output,
            stop_reason=stop_reason,
            iterations=self.iteration,
            tool_calls_executed=self.tool_calls_executed,
            usage=self.total_usage,
            error=error,
            failure_kind=failure_kind,
            raw=self.last_raw,
            retry_after_s=retry_after_s,
            request_retries=self.request_retries,
            model=self.last_model,
            provider=self.last_provider,
            closing_args=closing_args,
            budget_stop=budget_stop,
            capability_gap=capability_gap,
            first_call_ratio=self.first_call_ratio,
        )

    def budget_stop_for(self, stop_reason: StopReason) -> BudgetStop | None:
        """Which bound a stop ran out of, with its limit, the figure used and the owner that set
        it; ``None`` for a stop that is not a budget stop (agent-loop.spec.md requirement 107)."""
        cfg = self.cfg
        if stop_reason == "max_iterations":
            used = min(self.iteration, cfg.max_iterations)
            return BudgetStop(
                "rounds", cfg.max_iterations, used, cfg.max_iterations_source or "default"
            )
        if stop_reason == "max_tool_calls":
            return BudgetStop(
                "toolCalls",
                cfg.max_tool_calls,
                self.tool_calls_executed,
                cfg.max_tool_calls_source or "default",
            )
        if stop_reason == "timeout":
            return BudgetStop(
                "time",
                int(cfg.wall_clock_timeout_s),
                int(self.clock() - self.started),
                cfg.wall_clock_source or "default",
            )
        if stop_reason == "token_budget":
            return BudgetStop(
                "tokens",
                cfg.token_budget,
                self.total_usage.counted_tokens,
                cfg.token_budget_source or "default",
            )
        return None

    def cancellation_requested(self) -> bool:
        return self.ctx.cancellation_check is not None and self.ctx.cancellation_check()

    def cancelled(self) -> AgentLoopResult:
        return self.done(
            ok=False,
            stop_reason="run_cancelled",
            error="run cancellation requested",
            failure_kind="run_cancelled",
        )
