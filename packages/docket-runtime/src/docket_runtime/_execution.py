"""Bounded execution state for external runtime adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from docket_runtime._internal.docket.core.handoff import HandoffArtifact
from docket_runtime._internal.docket.core.llm import TokenUsage, ToolCall
from docket_runtime._internal.docket.core.tools import ToolContext, ToolResult
from docket_runtime._internal.docket.core.trace import trace_event

ExecutionStopReason = Literal["final_message", "token_budget", "max_tool_calls"]
Dispatch = Callable[[ToolCall, ToolContext], ToolResult]


@dataclass(frozen=True)
class ExecutionLimits:
    """Measured token and admitted tool-call limits for one execution."""

    token_budget: int
    max_tool_calls: int

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be positive")


@dataclass(frozen=True)
class ExecutionResult:
    """The single immutable terminal result of a governed execution."""

    ok: bool
    output: str
    stop_reason: ExecutionStopReason
    usage: TokenUsage
    tool_calls_executed: int
    handoff: HandoffArtifact
    error: str = ""


class GovernedExecution:
    """Bind reported responses to bounded, sequential tool dispatches."""

    def __init__(
        self,
        dispatch: Dispatch,
        context: ToolContext,
        limits: ExecutionLimits,
    ) -> None:
        self._dispatch = dispatch
        self._context = context
        self._limits = limits
        self._usage = TokenUsage()
        self._pending: list[ToolCall] = []
        self._tool_calls_executed = 0
        self._terminal: ExecutionResult | None = None

    def record_response(
        self, usage: TokenUsage, tool_calls: Sequence[ToolCall]
    ) -> ExecutionResult | None:
        """Accumulate measured usage and admit one complete ordered call batch."""
        self._require_active()
        if self._pending:
            raise RuntimeError("the prior response still has pending tool calls")
        if not isinstance(usage, TokenUsage):
            raise TypeError("usage must be endpoint-reported TokenUsage")

        calls = tuple(tool_calls)
        self._usage = TokenUsage(
            input_tokens=self._usage.input_tokens + usage.input_tokens,
            output_tokens=self._usage.output_tokens + usage.output_tokens,
            cached_tokens=self._usage.cached_tokens + usage.cached_tokens,
        )
        if self._usage.total_tokens > self._limits.token_budget:
            return self._stop("token_budget", "reported token budget exceeded")
        if self._tool_calls_executed + len(calls) > self._limits.max_tool_calls:
            return self._stop("max_tool_calls", "tool-call budget exceeded")

        self._pending.extend(calls)
        return None

    def dispatch(self, call: ToolCall) -> ToolResult:
        """Dispatch the next exact admitted call through the runtime facade."""
        self._require_active()
        if not self._pending:
            raise RuntimeError("no tool call is pending")
        if call != self._pending[0]:
            raise RuntimeError("tool calls must be dispatched in admitted order")

        trace_event(
            self._context.project,
            self._context.session_key,
            self._context.role,
            "tool_call",
            json.dumps({"tool": call.name, "callId": call.id, "arguments": call.arguments}),
        )
        result = self._dispatch(call, self._context)
        self._pending.pop(0)
        if result.denial_kind != "run_cancelled":
            self._tool_calls_executed += 1
        payload = {
            "tool": call.name,
            "callId": call.id,
            "decision": result.decision,
            "ok": result.ok,
            "executed": result.executed,
        }
        if result.denial_kind is not None:
            payload["denialKind"] = result.denial_kind
        trace_event(
            self._context.project,
            self._context.session_key,
            self._context.role,
            "tool_result",
            json.dumps(payload),
        )
        return result

    def finish(self, summary: str) -> ExecutionResult:
        """Finish successfully once all admitted calls have been dispatched."""
        self._require_active()
        if self._pending:
            raise RuntimeError("cannot finish while tool calls remain pending")
        self._terminal = ExecutionResult(
            ok=True,
            output=summary,
            stop_reason="final_message",
            usage=self._usage,
            tool_calls_executed=self._tool_calls_executed,
            handoff=HandoffArtifact(summary=summary),
        )
        return self._terminal

    def _require_active(self) -> None:
        if self._terminal is not None:
            raise RuntimeError("execution is already terminal")

    def _stop(self, reason: ExecutionStopReason, error: str) -> ExecutionResult:
        self._terminal = ExecutionResult(
            ok=False,
            output="",
            stop_reason=reason,
            usage=self._usage,
            tool_calls_executed=self._tool_calls_executed,
            handoff=HandoffArtifact(summary=""),
            error=error,
        )
        return self._terminal
