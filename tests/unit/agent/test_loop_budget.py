"""The turn's bounds (`agent/loop_budget.py`): reserve clamping, budget refusal, ceilings."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from docket.agent.loop_budget import MIN_OUTPUT_TOKENS, TurnBudget
from docket.agent.loop_state import TurnState
from docket.agent.loop_types import LoopConfig
from docket.agent.ports import TokenUsage

SUBJECT = "docket.agent.loop_budget"

MakeState = Callable[..., TurnState]


class TestReserveWithinBudget:
    """A known output cap is cut to the room the budget leaves; an unknown cap is left alone."""

    def test_a_known_cap_is_cut_to_the_remaining_room(self, make_turn_state: MakeState) -> None:
        budget = TurnBudget(make_turn_state(request_max_tokens=900, output_reserve=900))
        assert budget.reserve_within_budget(estimated_input=1_000, remaining=1_800) == 800

    def test_room_below_the_minimum_keeps_the_full_reserve(
        self, make_turn_state: MakeState
    ) -> None:
        budget = TurnBudget(make_turn_state(request_max_tokens=500, output_reserve=500))
        remaining = 1_000 + MIN_OUTPUT_TOKENS - 1
        assert budget.reserve_within_budget(1_000, remaining) == 500

    def test_an_unknown_cap_is_never_clamped(self, make_turn_state: MakeState) -> None:
        budget = TurnBudget(make_turn_state(request_max_tokens=None, output_reserve=500))
        assert budget.reserve_within_budget(1_000, 1_800) == 500


class TestProspectiveBudgetError:
    """The refusal names the budget and the arithmetic; success records the clamped cap."""

    def test_a_request_that_fits_clamps_the_call_cap(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(
            LoopConfig(token_budget=2_000), request_max_tokens=500, output_reserve=500
        )
        assert TurnBudget(state).prospective_budget_error(1_000, purpose="task") == ""
        assert state.call_max_tokens == 500

    def test_a_request_that_does_not_fit_is_refused_before_any_call(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(token_budget=1_000), output_reserve=500)
        error = TurnBudget(state).prospective_budget_error(900, purpose="task")
        assert error.startswith("token budget: cannot start task completion")
        assert "token_budget=1000" in error
        assert error.endswith("no backend call made")

    def test_pending_summary_usage_counts_against_the_budget(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(
            LoopConfig(token_budget=1_000),
            output_reserve=100,
            summary_usage=TokenUsage(input_tokens=500, output_tokens=300),
        )
        assert TurnBudget(state).effective_measured_tokens() == 800
        assert TurnBudget(state).prospective_budget_error(150, purpose="task")


class TestCalibrate:
    """Later estimates scale by measured/estimated, never below one."""

    def test_a_larger_measurement_scales_the_next_estimate(
        self, make_turn_state: MakeState
    ) -> None:
        budget = TurnBudget(make_turn_state())
        budget.pending_raw_estimate = 100
        budget.calibrate(250)
        assert budget.calibration == 2.5

    def test_a_smaller_measurement_never_shrinks_estimates(
        self, make_turn_state: MakeState
    ) -> None:
        budget = TurnBudget(make_turn_state())
        budget.pending_raw_estimate = 100
        budget.calibrate(40)
        assert budget.calibration == 1.0


class TestCheckIterationBounds:
    """Each ceiling ends the turn with its own stop reason, in a fixed order."""

    def test_the_iteration_ceiling_stops_the_turn(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(LoopConfig(max_iterations=1))
        budget = TurnBudget(state)
        timeout, stop = budget.check_iteration_bounds()
        assert stop is None and timeout > 0
        _timeout, stop = budget.check_iteration_bounds()
        assert stop is not None
        assert stop.stop_reason == "max_iterations"
        assert stop.error == "exceeded max_iterations=1"

    def test_the_wall_clock_ceiling_stops_the_turn(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(LoopConfig(wall_clock_timeout_s=10), clock=lambda: 11.0)
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is not None
        assert (stop.stop_reason, stop.failure_kind) == ("timeout", "timeout")

    def test_the_request_timeout_is_cut_to_the_remaining_wall_clock(
        self, make_turn_state: MakeState
    ) -> None:
        cfg = LoopConfig(wall_clock_timeout_s=100, request_timeout_s=60)
        state = make_turn_state(cfg, clock=lambda: 70.0)
        timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is None
        assert timeout == 30

    def test_spent_counted_tokens_stop_the_turn(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(
            LoopConfig(token_budget=100), total_usage=TokenUsage(input_tokens=101)
        )
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is not None
        assert stop.stop_reason == "token_budget"

    def test_the_tool_call_ceiling_stops_the_turn(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(LoopConfig(max_tool_calls=3), tool_calls_executed=3)
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is not None
        assert stop.stop_reason == "max_tool_calls"

    def test_cancellation_is_checked_before_the_iteration_counts(
        self, make_turn_state: MakeState
    ) -> None:
        base = make_turn_state()
        state = make_turn_state(ctx=dataclasses.replace(base.ctx, cancellation_check=lambda: True))
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is not None
        assert stop.stop_reason == "run_cancelled"
        assert state.iteration == 0
