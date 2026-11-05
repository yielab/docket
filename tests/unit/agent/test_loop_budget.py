"""The turn's bounds (`agent/loop_budget.py`): reserve clamping, budget refusal, ceilings."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from docket.agent.loop_budget import (
    LANDING_TIMEOUT_S,
    MIN_OUTPUT_TOKENS,
    TurnBudget,
    budget_notice,
)
from docket.agent.loop_state import TurnState
from docket.agent.loop_types import AgentLoopResult, LoopConfig
from docket.agent.ports import BudgetStop, ChatResponse, TokenUsage

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
    """Rounds, wall clock, tool calls and spent tokens select the landing; cancellation stops."""

    def test_the_iteration_ceiling_selects_the_landing(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(LoopConfig(max_iterations=1))
        budget = TurnBudget(state)
        timeout, stop = budget.check_iteration_bounds()
        assert stop is None and timeout > 0 and state.landing is None
        timeout, stop = budget.check_iteration_bounds()
        assert stop is None and timeout == min(state.cfg.request_timeout_s, LANDING_TIMEOUT_S)
        assert (state.landing, state.landing_error) == (
            "max_iterations",
            "exceeded max_iterations=1",
        )

    def test_a_known_source_names_the_owner_and_the_key_that_raises_the_limit(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(max_iterations=1, max_iterations_source="default"))
        budget = TurnBudget(state)
        budget.check_iteration_bounds()
        budget.check_iteration_bounds()
        assert state.landing_error == (
            "exceeded max_iterations=1 (source: default; raise AGENT_LOOP_MAX_ITERATIONS)"
        )

    def test_a_wall_clock_from_the_step_names_timeout(self, make_turn_state: MakeState) -> None:
        cfg = LoopConfig(wall_clock_timeout_s=10, wall_clock_source="step")
        state = make_turn_state(cfg, clock=lambda: 11.0)
        TurnBudget(state).check_iteration_bounds()
        assert "(source: step; raise timeout)" in state.landing_error

    def test_a_wall_clock_from_the_pod_names_turn_timeout(self, make_turn_state: MakeState) -> None:
        cfg = LoopConfig(wall_clock_timeout_s=10, wall_clock_source="pod")
        state = make_turn_state(cfg, clock=lambda: 11.0)
        TurnBudget(state).check_iteration_bounds()
        assert "(source: pod; raise turnTimeoutS)" in state.landing_error

    def test_a_default_source_names_the_machine_variable(self, make_turn_state: MakeState) -> None:
        cfg = LoopConfig(max_tool_calls=3, max_tool_calls_source="default")
        state = make_turn_state(cfg, tool_calls_executed=3)
        TurnBudget(state).check_iteration_bounds()
        assert "(source: default; raise AGENT_LOOP_MAX_TOOL_CALLS)" in state.landing_error

    def test_the_wall_clock_ceiling_selects_the_landing_with_a_grace_timeout(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(wall_clock_timeout_s=10), clock=lambda: 11.0)
        timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is None and state.landing == "timeout"
        assert timeout == min(state.cfg.request_timeout_s, LANDING_TIMEOUT_S)

    def test_the_request_timeout_is_cut_to_the_remaining_wall_clock(
        self, make_turn_state: MakeState
    ) -> None:
        cfg = LoopConfig(wall_clock_timeout_s=100, request_timeout_s=60)
        state = make_turn_state(cfg, clock=lambda: 70.0)
        timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is None
        assert timeout == 30

    def test_spent_counted_tokens_select_the_landing(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(
            LoopConfig(token_budget=100), total_usage=TokenUsage(input_tokens=101)
        )
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is None
        assert state.landing == "token_budget"
        assert "token_budget=100" in state.landing_error

    def test_the_tool_call_ceiling_selects_the_landing(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(LoopConfig(max_tool_calls=3), tool_calls_executed=3)
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is None and state.landing == "max_tool_calls"

    def test_the_first_bound_in_check_order_is_the_landing(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(
            LoopConfig(max_iterations=0, max_tool_calls=3), tool_calls_executed=3
        )
        TurnBudget(state).check_iteration_bounds()
        assert state.landing == "max_iterations"

    def test_cancellation_is_checked_before_the_iteration_counts(
        self, make_turn_state: MakeState
    ) -> None:
        base = make_turn_state()
        state = make_turn_state(ctx=dataclasses.replace(base.ctx, cancellation_check=lambda: True))
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is not None
        assert stop.stop_reason == "run_cancelled"
        assert state.iteration == 0


class TestARunOutBoundIsABudgetStop:
    """Rounds, tool calls, wall clock and tokens end the turn as `budget_exhausted` and say how much."""

    def _stop(self, state: TurnState) -> AgentLoopResult:
        budget = TurnBudget(state)
        stop = None
        for _ in range(state.cfg.max_iterations + 1):
            _timeout, stop = budget.check_iteration_bounds()
            if stop is not None:
                return stop
            if state.landing is not None:
                return state.landed()
        raise AssertionError("no bound fired")

    @pytest.mark.parametrize(
        ("bound", "cfg", "state_kwargs", "clock", "expected"),
        [
            (
                "rounds",
                LoopConfig(max_iterations=2, max_iterations_source="default"),
                {},
                0.0,
                BudgetStop("rounds", 2, 2, "default"),
            ),
            (
                "toolCalls",
                LoopConfig(max_tool_calls=3, max_tool_calls_source="default"),
                {"tool_calls_executed": 3},
                0.0,
                BudgetStop("toolCalls", 3, 3, "default"),
            ),
            (
                "time",
                LoopConfig(wall_clock_timeout_s=10, wall_clock_source="pod"),
                {},
                11.0,
                BudgetStop("time", 10, 11, "pod"),
            ),
            (
                "tokens",
                LoopConfig(token_budget=100),
                {"total_usage": TokenUsage(input_tokens=101)},
                0.0,
                BudgetStop("tokens", 100, 101, "default"),
            ),
        ],
    )
    def test_each_bound_returns_the_kind_and_the_figures(
        self,
        make_turn_state: MakeState,
        bound: str,
        cfg: LoopConfig,
        state_kwargs: dict[str, object],
        clock: float,
        expected: BudgetStop,
    ) -> None:
        state = make_turn_state(cfg, clock=lambda: clock, **state_kwargs)
        stop = self._stop(state)
        assert (stop.ok, stop.failure_kind, stop.budget_stop) == (
            False,
            "budget_exhausted",
            expected,
        )
        assert expected.bound == bound

    def test_a_cancelled_turn_carries_no_budget_stop(self, make_turn_state: MakeState) -> None:
        base = make_turn_state()
        state = make_turn_state(ctx=dataclasses.replace(base.ctx, cancellation_check=lambda: True))
        _timeout, stop = TurnBudget(state).check_iteration_bounds()
        assert stop is not None
        assert (stop.failure_kind, stop.budget_stop) == ("run_cancelled", None)


class TestBudgetNotice:
    """The notice names each bound at a quarter or less, once per turn."""

    def test_nothing_is_said_while_every_bound_has_more_than_a_quarter(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(max_iterations=8, max_tool_calls=8), iteration=6)
        assert budget_notice(state) == ""
        assert not state.notice_sent

    @pytest.mark.parametrize(
        ("cfg", "state_kwargs", "clock", "figure"),
        [
            (
                LoopConfig(max_tool_calls=8),
                {"tool_calls_executed": 6},
                0.0,
                "2 of 8 tool calls left",
            ),
            (
                LoopConfig(token_budget=1_000),
                {"total_usage": TokenUsage(input_tokens=760)},
                0.0,
                "240 of 1000 tokens left",
            ),
            (LoopConfig(wall_clock_timeout_s=100), {}, 80.0, "20 of 100 s left"),
        ],
    )
    def test_each_bound_at_a_quarter_is_named_with_what_is_left(
        self,
        make_turn_state: MakeState,
        cfg: LoopConfig,
        state_kwargs: dict[str, object],
        clock: float,
        figure: str,
    ) -> None:
        state = make_turn_state(cfg, clock=lambda: clock, **state_kwargs)
        notice = budget_notice(state)
        assert notice.startswith("[docket] This step's budget is running out: ")
        assert figure in notice
        assert state.notice_sent

    def test_the_notice_tells_the_model_to_stop_reading_and_finish(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(max_iterations=4), iteration=4)
        assert "do not start new reads or searches; finish from what you have" in (
            budget_notice(state).lower()
        )

    def test_the_rounds_left_count_the_round_the_request_starts(
        self, make_turn_state: MakeState
    ) -> None:
        """Round 7 of 8 is in flight: rounds 7 and 8 are left, six are done."""
        assert budget_notice(make_turn_state(LoopConfig(max_iterations=8), iteration=6)) == ""
        notice = budget_notice(make_turn_state(LoopConfig(max_iterations=8), iteration=7))
        assert "2 of 8 rounds left" in notice

    def test_it_is_said_once(self, make_turn_state: MakeState) -> None:
        state = make_turn_state(LoopConfig(max_iterations=4), iteration=4)
        assert budget_notice(state) != ""
        assert budget_notice(state) == ""


class TestARequestThatTimedOutOnTheClock:
    """A stall on a timeout the wall clock set is a time budget stop; on the request limit it is not."""

    _TIMED_OUT = ChatResponse(ok=False, error="timed out", failure_kind="timeout")

    def test_the_clock_left_as_the_timeout_ends_the_turn_on_time(
        self, make_turn_state: MakeState
    ) -> None:
        cfg = LoopConfig(wall_clock_timeout_s=10, request_timeout_s=120, wall_clock_source="step")
        state = make_turn_state(cfg, clock=lambda: 7.0)
        budget = TurnBudget(state)
        timeout, _stop = budget.check_iteration_bounds()
        assert timeout == 3 and budget.clock_cut(timeout)
        stop = budget.clock_cut_stop(self._TIMED_OUT, timeout)
        assert stop is not None
        assert (stop.ok, stop.stop_reason, stop.failure_kind) == (
            False,
            "timeout",
            "budget_exhausted",
        )
        assert stop.budget_stop == BudgetStop("time", 10, 7, "step")

    def test_the_request_limit_as_the_timeout_is_a_transport_timeout(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(wall_clock_timeout_s=10, request_timeout_s=2))
        budget = TurnBudget(state)
        timeout, _stop = budget.check_iteration_bounds()
        assert timeout == 2 and not budget.clock_cut(timeout)
        assert budget.clock_cut_stop(self._TIMED_OUT, timeout) is None

    def test_a_failure_that_is_not_a_timeout_is_not_the_clock(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(wall_clock_timeout_s=10), clock=lambda: 7.0)
        budget = TurnBudget(state)
        timeout, _stop = budget.check_iteration_bounds()
        refused = ChatResponse(ok=False, error="503", failure_kind="daemon_error")
        assert budget.clock_cut_stop(refused, timeout) is None

    def test_a_landing_past_the_clock_keeps_its_own_outcome(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(wall_clock_timeout_s=10), clock=lambda: 11.0)
        budget = TurnBudget(state)
        timeout, _stop = budget.check_iteration_bounds()
        assert state.landing == "timeout" and not budget.clock_cut(timeout)
