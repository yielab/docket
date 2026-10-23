"""The turn-scoped state shared by the turn loop and its collaborators.

``TurnState`` holds what more than one collaborator reads or writes: the resolved per-turn
constants, the running usage, the iteration and tool-call counters, and the last response's
identity. State only one collaborator touches (the progress detector, the compaction failure
marker) lives on that collaborator instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from docket.agent.llm import ChatBackend, TokenUsage, ToolSpec
from docket.agent.loop_types import AgentLoopResult, LoopConfig, StopReason
from docket.agent.ports import FailureKind
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

    trace_task_id: str = ""
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    tool_calls_executed: int = 0
    iteration: int = 0
    last_raw: dict[str, Any] = field(default_factory=dict)
    last_model: str = ""
    last_provider: str = ""
    summary_usage: TokenUsage = field(default_factory=TokenUsage)
    accounted_summary_usage: TokenUsage = field(default_factory=TokenUsage)

    def done(
        self,
        *,
        ok: bool,
        stop_reason: StopReason,
        output: str = "",
        error: str = "",
        failure_kind: FailureKind | None = None,
        retry_after_s: float | None = None,
    ) -> AgentLoopResult:
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
            model=self.last_model,
            provider=self.last_provider,
        )

    def cancellation_requested(self) -> bool:
        return self.ctx.cancellation_check is not None and self.ctx.cancellation_check()

    def cancelled(self) -> AgentLoopResult:
        return self.done(
            ok=False,
            stop_reason="run_cancelled",
            error="run cancellation requested",
            failure_kind="run_cancelled",
        )
