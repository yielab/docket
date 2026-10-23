"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from docket.hops.application import record as _record
from docket.hops.application import runner as _runner
from docket.pipeline.application import executor as _executor
from docket.pipeline.domain import plan as _orch

SUBJECT = "docket.hops.application.record"


def _unit(step_id: str, **extra: Any) -> _orch.PlannedUnit:
    fields: dict[str, Any] = {
        "step_id": step_id,
        "role": "implementer",
        "agent": None,
        "archetype": None,
        "member_id": "demo-implementer",
        "gate": None,
        "retries": None,
        "timeout": None,
    }
    return _orch.PlannedUnit(**{**fields, **extra})


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
