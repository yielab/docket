"""The hop budget chain: step beats role beats pod (time only) beats the machine default."""

from __future__ import annotations

import pytest

from docket.hops.domain.budget import Limit, resolve_hop_budget
from docket.kernel.errors import InvalidInput

SUBJECT = "docket.hops.domain.budget"

MACHINE = {"default_rounds": 60, "default_tool_calls": 40, "default_seconds": 300}


def test_a_step_value_beats_a_role_value() -> None:
    budget = resolve_hop_budget(step_rounds=5, role_rounds=9, **MACHINE)
    assert budget.rounds == Limit(5, "step")


def test_a_role_value_applies_when_the_step_declares_none() -> None:
    budget = resolve_hop_budget(role_rounds=9, role_tool_calls=7, **MACHINE)
    assert budget.rounds == Limit(9, "role")
    assert budget.tool_calls == Limit(7, "role")


def test_a_pod_time_applies_when_the_step_declares_none() -> None:
    budget = resolve_hop_budget(pod_seconds=600, **MACHINE)
    assert budget.seconds == Limit(600, "pod")


def test_a_step_time_beats_the_pod_time() -> None:
    budget = resolve_hop_budget(step_seconds=1200, pod_seconds=600, **MACHINE)
    assert budget.seconds == Limit(1200, "step")


def test_nothing_declared_gives_the_machine_values() -> None:
    budget = resolve_hop_budget(**MACHINE)
    assert budget.rounds == Limit(60, "default")
    assert budget.tool_calls == Limit(40, "default")
    assert budget.seconds == Limit(300, "default")


def test_each_bound_resolves_on_its_own_chain() -> None:
    budget = resolve_hop_budget(step_tool_calls=3, role_rounds=9, pod_seconds=600, **MACHINE)
    assert (budget.rounds.source, budget.tool_calls.source, budget.seconds.source) == (
        "role",
        "step",
        "pod",
    )


@pytest.mark.parametrize("bad", [0, -1])
def test_a_declared_value_that_is_not_positive_is_refused(bad: int) -> None:
    with pytest.raises(InvalidInput, match="positive"):
        resolve_hop_budget(step_rounds=bad, **MACHINE)
