"""The loop's served model and provider reach the driver port's TurnResult (docket_runtime.py)."""

from __future__ import annotations

from docket.agent import loop as _loop
from docket.hops.application import driver_support as _dr

SUBJECT = "docket.hops.application.driver_support"


def test_turn_result_carries_the_served_model_and_provider() -> None:
    """The loop's served model and provider are copied field for field onto the TurnResult."""
    result = _loop.AgentLoopResult(ok=True, output="done", model="served-model", provider="local")
    turn = _dr._turn_result_from(result)
    assert (turn.model, turn.provider) == ("served-model", "local")
