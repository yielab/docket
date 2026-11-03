"""The turn state (`agent/loop_state.py`): the result a stop builds."""

from __future__ import annotations

from collections.abc import Callable

from docket.agent.loop_state import TurnState
from docket.agent.ports import CapabilityGap

SUBJECT = "docket.agent.loop_state"

MakeState = Callable[..., TurnState]


class TestDone:
    """`done` builds the turn's result from the state and the stop it is given."""

    def test_a_capability_gap_travels_on_the_result(self, make_turn_state: MakeState) -> None:
        gap = CapabilityGap("fetch", "fetch", "run `docket pod set fetchDomains <host>`")
        result = make_turn_state().done(
            ok=False,
            stop_reason="capability_missing",
            error="needs fetch",
            failure_kind="capability_missing",
            capability_gap=gap,
        )

        assert result.capability_gap == gap
        assert result.failure_kind == "capability_missing"

    def test_a_stop_without_a_gap_carries_none(self, make_turn_state: MakeState) -> None:
        result = make_turn_state().done(ok=True, stop_reason="final_message", output="done")

        assert result.capability_gap is None
