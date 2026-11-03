"""The loop's served model and provider reach the driver port's TurnResult (docket_runtime.py)."""

from __future__ import annotations

from docket.agent import loop as _loop
from docket.agent.tools.registry import ToolContext
from docket.hops.application import driver_support as _dr
from docket.models import catalog as _catalog

SUBJECT = "docket.hops.application.driver_support"


def test_turn_result_carries_the_served_model_and_provider() -> None:
    """The loop's served model and provider are copied field for field onto the TurnResult."""
    result = _loop.AgentLoopResult(ok=True, output="done", model="served-model", provider="local")
    turn = _dr._turn_result_from(result)
    assert (turn.model, turn.provider) == ("served-model", "local")


class _Backend:
    context_window_tokens = 1_000_000
    max_output_tokens = None


def test_the_loop_config_carries_the_profiles_history_budget() -> None:
    """A hosted model on a 1M window gets 25,000 tokens of history; a local one keeps the role's."""
    ctx = ToolContext(agent_id="a", role="implementer", project="demo")
    hosted = _catalog.BUILTIN_PROFILES["hosted"]
    wide = _catalog.ModelProfile(
        **{**hosted.__dict__, "budgets": _catalog.ProfileBudgets(history_tokens=25_000)}
    )
    local = _catalog.BUILTIN_PROFILES["local"]

    assert _dr._loop_config(_Backend(), 60, 1000, wide, "", ctx).history_budget_tokens == 25_000
    assert _dr._loop_config(_Backend(), 60, 1000, local, "", ctx).history_budget_tokens == 8_000
