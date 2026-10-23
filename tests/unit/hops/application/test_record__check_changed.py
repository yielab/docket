"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from tests.support.pods import unit as _unit

from docket.hops.application import record as _record
from docket.hops.application import runner as _runner
from docket.pipeline.application import executor as _executor
from docket.pipeline.domain import plan as _orch

SUBJECT = "docket.hops.application.record"


def test_a_group_keeps_the_failure_kind_of_the_child_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(ctx: Any, child: Any, **_k: Any) -> _record._UnitOutcome:
        if child.step_id == "b":
            return _record._UnitOutcome(kind="failed", reason="spent", failure_kind="budget")
        return _record._UnitOutcome(kind="advance")

    monkeypatch.setattr(_runner, "_execute_unit", fake)
    monkeypatch.setattr(_executor, "_execute_unit", fake)
    group = _orch.PlannedGroup(step_id="par", children=(_unit("a"), _unit("b")))

    outcome = _executor._run_group_node(SimpleNamespace(), group, [], 0)

    assert (outcome.kind, outcome.reason, outcome.failure_kind) == ("failed", "spent", "budget")
