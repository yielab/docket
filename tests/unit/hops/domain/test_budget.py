"""The hop's clock chain: the step's timeout beats the pod's, which beats the machine default."""

from __future__ import annotations

import pytest

from docket.hops.domain.budget import Limit, resolve_seconds
from docket.kernel.errors import InvalidInput

SUBJECT = "docket.hops.domain.budget"


def test_a_pod_time_applies_when_the_step_declares_none() -> None:
    assert resolve_seconds(step=None, pod=600, default=300) == Limit(600, "pod")


def test_a_step_time_beats_the_pod_time() -> None:
    assert resolve_seconds(step=1200, pod=600, default=300) == Limit(1200, "step")


def test_nothing_declared_gives_the_machine_value() -> None:
    assert resolve_seconds(step=None, pod=None, default=300) == Limit(300, "default")


@pytest.mark.parametrize("bad", [0, -1])
def test_a_declared_time_that_is_not_positive_is_refused(bad: int) -> None:
    with pytest.raises(InvalidInput, match="positive"):
        resolve_seconds(step=bad, pod=None, default=300)
