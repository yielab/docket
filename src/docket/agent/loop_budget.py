"""The turn's bounds: per-iteration ceilings and the measured-token budget.

``TurnBudget`` owns the request-fit preflight, the calibration of estimates against measured
usage, and the checks that end a turn (cancellation, ``max_iterations``, ``timeout``,
``token_budget``, ``max_tool_calls``). Every bound is a stop condition, not a throughput knob.
"""

from __future__ import annotations

import math

from docket.agent.loop_request import _estimate_input_tokens, _message_tokens, _usage_delta
from docket.agent.loop_state import TurnState
from docket.agent.loop_trace import _trace_budget_notice, _trace_request_fit
from docket.agent.loop_types import AgentLoopResult, StopReason, limit_origin
from docket.agent.ports import ChatBackend, ChatMessage, ChatResponse, ToolSpec, user

_TOKEN_BUDGET_ERROR_PREFIX = "token budget:"
# The fewest output tokens a budget-clamped request may keep (agent-loop requirement 46).
MIN_OUTPUT_TOKENS = 256
# The request timeout of a landing past the rounds or wall-clock limit (requirement 51).
LANDING_TIMEOUT_S = 60
_NOTICE = (
    "[docket] This step's budget is running out: {left}. Do not start new reads or searches; "
    "finish from what you have, run the checks, leave the tree consistent; when it ends you "
    "will be asked for a report."
)
_NOTICE_UNITS = {"rounds": "rounds", "toolCalls": "tool calls", "tokens": "tokens", "time": "s"}


def budget_notice(state: TurnState) -> str:
    """The line telling the model a bound has a quarter or less left (requirement 108), traced and
    returned the first time any of the four is there; ``""`` after that and while none is. The
    round in flight is the one the request starts, so the rounds left include it."""
    if state.notice_sent:
        return ""
    cfg = state.cfg
    remaining_time = cfg.wall_clock_timeout_s - (state.clock() - state.started)
    figures = (
        ("rounds", cfg.max_iterations - state.iteration + 1, cfg.max_iterations),
        ("toolCalls", cfg.max_tool_calls - state.tool_calls_executed, cfg.max_tool_calls),
        ("tokens", cfg.token_budget - state.total_usage.counted_tokens, cfg.token_budget),
        ("time", int(remaining_time), int(cfg.wall_clock_timeout_s)),
    )
    low = [(b, max(0, left), limit) for b, left, limit in figures if left * 4 <= limit]
    if not low:
        return ""
    state.notice_sent = True
    _trace_budget_notice(
        state.project,
        state.trace_key,
        state.ctx.role,
        [{"bound": b, "left": left, "limit": limit} for b, left, limit in low],
        task_id=state.trace_task_id,
    )
    left = ", ".join(f"{n} of {limit} {_NOTICE_UNITS[b]} left" for b, n, limit in low)
    return _NOTICE.format(left=left)


def _observed_estimate_ratio(backend: ChatBackend) -> float | None:
    """The ratio the backend's model measured on its last turn, or ``None`` when it reports none."""
    ratio = getattr(backend, "estimate_ratio", None)
    return float(ratio) if isinstance(ratio, int | float) and ratio > 0 else None


class TurnBudget:
    """Fit preflight, token-budget accounting and the per-iteration ceilings."""

    def __init__(self, state: TurnState) -> None:
        self.state = state
        # Seeded by the model's observed ratio (agent-loop.spec.md requirement 46a), never under 1.
        self.calibration = max(1.0, _observed_estimate_ratio(state.backend) or 1.0)
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

    def request_room(self) -> int:
        """The most input a request may estimate to: the window less the output reserve."""
        assert self.state.context_window is not None
        return self.state.context_window - self.state.output_reserve

    def intake_room(self) -> int | None:
        """What one round's reply and tool results may add to the next request: the request room
        less the estimate of the task request just sent (the raw estimate its preflight made, scaled
        by the calibration the call has since measured). ``None`` when the window is unknown."""
        if self.state.context_window is None:
            return None
        return self.request_room() - math.ceil(self.pending_raw_estimate * self.calibration)

    def message_cost(self, message: ChatMessage) -> int:
        """What the fit preflight counts for *message* in a request, calibration included."""
        return math.ceil(_message_tokens([message]) * self.calibration)

    def prompt_cost(self, text: str) -> int:
        """What the fit preflight would estimate for a one-message, tool-free request carrying
        *text*, calibration included. The summarizer's prompt is bounded by it, so the request
        that carries the prompt is never refused for a size the bound let through."""
        raw = _estimate_input_tokens(
            self.state.backend,
            [user(text)],
            [],
            self.state.request_max_tokens,
            self.state.cfg.temperature,
        )
        return math.ceil(raw * self.calibration)

    def effective_measured_tokens(self) -> int:
        pending = _usage_delta(self.state.summary_usage, self.state.accounted_summary_usage)
        return self.state.total_usage.counted_tokens + pending.counted_tokens

    def calibrate(self, measured_input: int) -> None:
        """Scale later estimates by ``max(1, measured / estimated)`` of the latest call; the first
        call's unscaled ratio is kept for the driver to record."""
        if measured_input > 0 and self.pending_raw_estimate > 0:
            ratio = measured_input / self.pending_raw_estimate
            if self.state.first_call_ratio is None:
                self.state.first_call_ratio = ratio
            self.calibration = max(1.0, ratio)

    def learn_from_overflow(self, overflow_input_tokens: int | None) -> bool:
        """Scale later estimates by the provider's count over the latest raw estimate, else the
        request room plus one over it, never lowering the scale; ``False`` when that teaches nothing."""
        # The count also seeds first_call_ratio; with no count and no window nothing is proven.
        raw = self.pending_raw_estimate
        if raw <= 0:
            return False
        if overflow_input_tokens is not None and overflow_input_tokens > 0:
            ratio = overflow_input_tokens / raw
            if self.state.first_call_ratio is None:
                self.state.first_call_ratio = ratio
        elif self.state.context_window is not None:
            ratio = (self.request_room() + 1) / raw
        else:
            return False
        self.calibration = max(self.calibration, ratio)
        return True

    def repeated_overflow_error(self, overflow_input_tokens: int | None) -> str:
        """The error of a request the provider refused for its size a second time."""
        window = self.state.context_window
        count = (
            f"its prompt was {overflow_input_tokens} tokens"
            if overflow_input_tokens
            else "it stated no count"
        )
        return (
            "context fit: the provider refused the request again after the estimate was "
            f"recalibrated from its first refusal; {count}, against a registered context window "
            f"of {window if window is not None else 'unknown'}"
        )

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
    # this iteration's request timeout and a bound reached is on ``state.landing``.
    def check_iteration_bounds(self) -> tuple[int, AgentLoopResult | None]:
        """Cancellation, then the four per-iteration ceilings, in bound-check order. A bound
        that would stop the turn selects the landing (requirement 51) instead."""
        if self.state.cancellation_requested():
            return 0, self.state.cancelled()
        self.state.iteration += 1
        if self.state.landing is None:
            stop = self.select_landing()
            if stop is not None:
                return 0, stop
        return self.request_timeout(), None

    def select_landing(self) -> AgentLoopResult | None:
        """Select the first bound reached as the landing, spent tokens included."""
        cfg = self.state.cfg
        if self.state.iteration > cfg.max_iterations:
            self.state.land(
                "max_iterations",
                f"exceeded max_iterations={cfg.max_iterations}"
                + limit_origin("rounds", cfg.max_iterations_source),
            )
        elif self.state.clock() - self.state.started > cfg.wall_clock_timeout_s:
            self.state.land(
                "timeout",
                f"exceeded wall_clock_timeout_s={cfg.wall_clock_timeout_s}"
                + limit_origin("time", cfg.wall_clock_source),
            )
        elif self.state.total_usage.counted_tokens > cfg.token_budget:
            self.state.land(
                "token_budget",
                f"exceeded token_budget={cfg.token_budget} "
                f"(used {self.state.total_usage.counted_tokens})",
            )
        elif self.state.tool_calls_executed >= cfg.max_tool_calls:
            self.state.land(
                "max_tool_calls",
                f"exceeded max_tool_calls={cfg.max_tool_calls}"
                + limit_origin("toolCalls", cfg.max_tool_calls_source),
            )
        return None

    def request_timeout(self) -> int:
        """This request's timeout: the smaller of ``request_timeout_s`` and the wall clock left, or
        the grace of a landing past it. ``clock_cut`` says which of the two set it."""
        cfg = self.state.cfg
        remaining = int(cfg.wall_clock_timeout_s - (self.state.clock() - self.state.started))
        past: tuple[StopReason | None, ...] = ("max_iterations", "timeout")
        if self.state.landing in past or (self.state.landing and remaining < 1):
            return min(cfg.request_timeout_s, LANDING_TIMEOUT_S)
        return min(cfg.request_timeout_s, max(1, remaining))

    def clock_cut(self, timeout: int) -> bool:
        """Whether *timeout* is the wall clock left rather than ``request_timeout_s``: it is the
        smaller of the two and no landing is under way (requirement 109). A tie is the request's."""
        return self.state.landing is None and timeout < self.state.cfg.request_timeout_s

    def timed_out_on_clock(self, response: ChatResponse, timeout: int) -> bool:
        """Whether *response* is the timeout of a request that was cut to the clock left."""
        return response.failure_kind == "timeout" and self.clock_cut(timeout)

    def clock_cut_stop(self, response: ChatResponse, timeout: int) -> AgentLoopResult | None:
        """The turn's end when *response* timed out on the clock left: the wall clock is spent, so
        ``timeout`` as a budget stop (requirement 109), never retried and never followed by a
        landing; ``None`` for any other failure."""
        if not self.timed_out_on_clock(response, timeout):
            return None
        cfg = self.state.cfg
        return self.state.done(
            ok=False,
            stop_reason="timeout",
            error=(
                f"exceeded wall_clock_timeout_s={cfg.wall_clock_timeout_s}"
                + limit_origin("time", cfg.wall_clock_source)
                + f"; a request cut to the {timeout} s left timed out"
            ),
        )
