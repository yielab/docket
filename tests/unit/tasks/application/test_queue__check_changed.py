"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

from typing import Any

import pytest

from docket.hops.gates import pre_hop as _pre_hop
from docket.pipeline.application import executor as _executor_c
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.queue"


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


def test_every_command_a_task_runs_as_a_check_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_queue, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_pre_hop, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_executor_c, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_fleet, "meta_get", lambda *a, **k: "make verify")
    steps = (
        _unit("build", gate=_gates.MechanicalGate(command="bash scripts/check.sh")),
        _orch.PlannedGroup(
            step_id="par",
            children=(
                _unit("a", gate=_gates.ExternalGate(command="./verify.sh")),
                _unit("b", run="node lint.js"),
                _unit("c", gate=_gates.VerdictGate(pattern="x", passValues=["x"])),
            ),
        ),
    )
    task = {"gate": {"command": "python gate.py"}}

    assert _pre_hop._checked_commands("demo", task, steps) == [
        "make verify",
        "bash scripts/check.sh",
        "./verify.sh",
        "node lint.js",
        "python gate.py",
    ]
