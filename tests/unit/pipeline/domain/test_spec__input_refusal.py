"""``input_refusal``: the message for a pipeline that asks a person, given a task level that cannot."""

from __future__ import annotations

import pytest
from tests.support.roles import ROLE_NAMES

from docket.pipeline.domain.spec import input_refusal, load_pipeline

SUBJECT = "docket.pipeline.domain.spec"

ASKS = """\
name: asks
steps:
  - plan: lead
  - ask:
      input:
        from: plan
  - confirm:
      input:
        from: plan
  - implement: implementer
"""

PLAIN = "name: plain\nsteps:\n  - plan: lead\n  - implement: implementer\n"


def _spec(text: str):  # type: ignore[no-untyped-def]
    loaded = load_pipeline(text, roles=ROLE_NAMES)
    assert loaded.spec is not None, loaded.errors
    return loaded.spec


@pytest.mark.parametrize("level", ["L4", "L5"])
def test_every_input_step_is_named_with_the_level_and_the_two_ways_out(level: str) -> None:
    message = input_refusal(_spec(ASKS), level)

    assert message is not None
    assert "'ask'" in message and "'confirm'" in message and level in message
    assert "L3" in message and "input step" in message


def test_a_pipeline_that_asks_nobody_is_not_refused() -> None:
    assert input_refusal(_spec(PLAIN), "L5") is None
