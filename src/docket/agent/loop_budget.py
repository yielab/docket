"""The turn's bounds: per-iteration ceilings and the measured-token budget.

``TurnBudget`` owns the request-fit preflight, the calibration of estimates against measured
usage, and the checks that end a turn (cancellation, ``max_iterations``, ``timeout``,
``token_budget``, ``max_tool_calls``). Every bound is a stop condition, not a throughput knob.
"""

from __future__ import annotations

import math

from docket.agent.loop_request import _estimate_input_tokens, _usage_delta
from docket.agent.loop_state import TurnState
from docket.agent.loop_trace import _trace_request_fit
from docket.agent.loop_types import AgentLoopResult
from docket.agent.ports import ChatMessage, ToolSpec

_TOKEN_BUDGET_ERROR_PREFIX = "token budget:"
# The fewest output tokens a budget-clamped request may keep (agent-loop requirement 46).
MIN_OUTPUT_TOKENS = 256


class TurnBudget:
    """Fit preflight, token-budget accounting and the per-iteration ceilings."""

    def __init__(self, state: TurnState) -> None:
        self.state = state
        self.calibration = 1.0
        self.pending_raw_estimate = 0

    def preflight_request(
        self,
        request_messages: list[ChatMessage],
        request_tools: list[ToolSpec],
        *,
        purpose: str,
    ) -> tuple[int, str]:
        raw_estimate = _estimate_input_tokens(
            self.state.backend,
            request_messages,
            request_tools,
            self.state.request_max_tokens,
            self.state.cfg.temperature,
        )
        self.pending_raw_estimate = raw_estimate
        estimated_input = math.ceil(raw_estimate * self.calibration)
        if self.state.context_window is None:
            _trace_request_fit(
                self.state.project,
                self.state.trace_key,
                self.state.ctx.role,
                purpose=purpose,
                status="unknown_window",
                estimated_input_tokens=estimated_input,
                output_reserve_tokens=self.state.output_reserve,
                context_window_tokens=None,
                task_id=self.state.trace_task_id,
            )
            return estimated_input, ""
        if self.state.output_reserve <= 0:
            error = (
                "context fit: selected endpoint has registered context window "
                f"{self.state.context_window} but no positive maximum-output reserve"
            )
        elif estimated_input + self.state.output_reserve > self.state.context_window:
            error = (
                "context fit: estimated request "
                f"{estimated_input + self.state.output_reserve} tokens (input {estimated_input} + "
                f"output reserve {self.state.output_reserve}) exceeds registered context window "
                f"{self.state.context_window}"
            )
        else:
            error = ""
        _trace_request_fit(
            self.state.project,
            self.state.trace_key,
            self.state.ctx.role,
            purpose=purpose,
            status="failed" if error else "fits",
            estimated_input_tokens=estimated_input,
            output_reserve_tokens=self.state.output_reserve,
            context_window_tokens=self.state.context_window,
            task_id=self.state.trace_task_id,
        )
        return estimated_input, error

    def effective_measured_tokens(self) -> int:
        pending = _usage_delta(self.state.summary_usage, self.state.accounted_summary_usage)
        return self.state.total_usage.counted_tokens + pending.counted_tokens

    def calibrate(self, measured_input: int) -> None:
        """Scale later estimates by ``max(1, measured / estimated)`` of the latest call."""
        if measured_input > 0 and self.pending_raw_estimate > 0:
            self.calibration = max(1.0, measured_input / self.pending_raw_estimate)

    def reserve_within_budget(self, estimated_input: int, remaining: int) -> int:
        """A known cap cut to what the budget leaves after the input (requirement 46); the
        default reserve of an unknown cap is left alone."""
        room = remaining - estimated_input
        if self.state.request_max_tokens is None or room < MIN_OUTPUT_TOKENS:
            return self.state.output_reserve
        return min(self.state.output_reserve, room)

    def prospective_budget_error(self, estimated_input: int, *, purpose: str) -> str:
        measured_tokens = self.effective_measured_tokens()
        remaining = self.state.cfg.token_budget - measured_tokens
        reserve = self.reserve_within_budget(estimated_input, remaining)
        prospective = estimated_input + reserve
        if prospective <= remaining:
            if self.state.request_max_tokens is not None:
                self.state.call_max_tokens = reserve
            return ""
        return (
            f"{_TOKEN_BUDGET_ERROR_PREFIX} cannot start {purpose} completion within "
            f"token_budget={self.state.cfg.token_budget} (used {measured_tokens}, estimated input "
            f"{estimated_input} + output reserve {reserve}, remaining "
            f"{max(0, remaining)}); no backend call made"
        )

    # A non-None second element means stop now; otherwise the first element is
    # this iteration's request timeout.
    def check_iteration_bounds(self) -> tuple[int, AgentLoopResult | None]:
        """Cancellation plus the four per-iteration ceilings, in bound-check order."""
        if self.state.cancellation_requested():
            return 0, self.state.cancelled()
        self.state.iteration += 1
        if self.state.iteration > self.state.cfg.max_iterations:
            return 0, self.state.done(
                ok=False,
                stop_reason="max_iterations",
                error=f"exceeded max_iterations={self.state.cfg.max_iterations}",
                failure_kind="invalid_output",
            )
        elapsed = self.state.clock() - self.state.started
        if elapsed > self.state.cfg.wall_clock_timeout_s:
            return 0, self.state.done(
                ok=False,
                stop_reason="timeout",
                error=f"exceeded wall_clock_timeout_s={self.state.cfg.wall_clock_timeout_s}",
                failure_kind="timeout",
            )
        if self.state.total_usage.counted_tokens > self.state.cfg.token_budget:
            return 0, self.state.done(
                ok=False,
                stop_reason="token_budget",
                error=(
                    f"exceeded token_budget={self.state.cfg.token_budget} "
                    f"(used {self.state.total_usage.counted_tokens})"
                ),
                failure_kind="invalid_output",
            )
        if self.state.tool_calls_executed >= self.state.cfg.max_tool_calls:
            return 0, self.state.done(
                ok=False,
                stop_reason="max_tool_calls",
                error=f"exceeded max_tool_calls={self.state.cfg.max_tool_calls}",
                failure_kind="invalid_output",
            )
        remaining = max(1, int(self.state.cfg.wall_clock_timeout_s - elapsed))
        return min(self.state.cfg.request_timeout_s, remaining), None
